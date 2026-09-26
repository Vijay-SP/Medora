"""
Medpark Meeting Intelligence System - Evidence Grounding & Deadline Validator
Verifies that all extracted claims map to verbatim audio timestamps, resolves temporal expressions and
grounds the speaker labels the LLM attributes in its prose to the labels of the cited lines.
"""

from datetime import datetime, timedelta
from difflib import SequenceMatcher, get_close_matches
import re
import unicodedata
from typing import Any, Optional
from app.core.logging import logger
from app.models.meeting import Attendee, Meeting
from app.models.transcript import Transcript, TranscriptSegment
from app.models.extraction import MinutesOfMeeting, EvidenceQuote, RiskOrQuestionItem
from app.services.extraction.attribution_render import SPEAKER_RE, sub_labels


# Bare first-person / group pronouns the LLM sometimes reports as "owner_mention": verbatim but useless
BARE_PRONOUNS = {"i", "me", "eu", "io", "я", "мне", "мы", "noi", "we"}
ANONYMOUS_SPEAKER_PATTERN = re.compile(r"^S(\d+)$")
OWNER_TOKEN_MIN_LENGTH = 4
OWNER_TOKEN_SIMILARITY = 0.85

# Capitalised tokens that are never fabricated names: institution, departments, titles, calendar words
_PROSE_WHITELIST_RAW = [
    "Medpark", "ATI", "RMN", "CT", "EKG", "ECG", "UPU", "ICU", "MRI", "ER",
    "Dr", "Doctor", "Doctorul", "Doctorului", "Doamna", "Domnul", "Prof", "Профессор", "Доктор",
    # Fixed vocabulary of the engine's and validator's own audit notes and owner labels (belt-and-braces:
    # llm_engine audits before appending them, but minutes edited via PUT /minutes may carry them too)
    "NOTĂ", "AUDIT", "LLM", "NEVERIFICAT", "AUDIO", "Verificați", "Speaker", "Unassigned",
    # Weekdays RO / RU / EN
    "Luni", "Marți", "Miercuri", "Joi", "Vineri", "Sâmbătă", "Duminică",
    "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье",
    "Понедельника", "Вторника", "Среды", "Четверга", "Пятницы", "Субботы", "Воскресенья",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    # Months RO / RU / EN
    "Ianuarie", "Februarie", "Martie", "Aprilie", "Mai", "Iunie", "Iulie", "August", "Septembrie", "Octombrie", "Noiembrie", "Decembrie",
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
    "Января", "Февраля", "Марта", "Апреля", "Мая", "Июня", "Июля", "Августа", "Сентября", "Октября", "Ноября", "Декабря",
    "January", "February", "March", "April", "May", "June", "July", "September", "October", "November", "December",
]
_WORD_PATTERN = re.compile(r"[^\W\d_]+")
_SENTENCE_END_CHARS = ".!?:;\n\"'«»()[]-–—"
# A period after one of these is an abbreviation, not a sentence end ("Dr. Vasilescu")
_TITLE_ABBREVIATIONS = {"dr", "prof", "conf", "dna", "dl", "ing", "mr", "mrs", "ms", "st", "д-р", "проф"}
_ABBREVIATION_BEFORE_PERIOD = re.compile(r"([^\W\d_]+)\.$")
# A capitalised word right after a person title is a person's name ("doctorul Popescu", "Dr. Ion Popescu",
# "доктор Попеску"), whether or not the transcript contains it
_PERSON_TITLE_RE = re.compile(
    r"(?<![^\W\d_])(?:[Dd]r|[Dd]octor(?:ul|ului|ii|ilor|ița|iței)?|[Dd]oamn(?:a|ei)|[Dd]omn(?:ul|ului|ii|ilor)|[Dd]na|[Dd]l"
    r"|[Pp]rof(?:esor(?:ul|ului|ii|ilor)?)?|[Cc]oleg(?:ul|ului|a|ei|ii|ilor)?|[Дд]-р|[Дд]октор(?:а|у|ом)?|[Пп]рофессор(?:а|у|ом)?"
    r"|[Кк]оллег(?:а|и|е|у)|[Гг]осподин(?:а|у)?|[Гг]оспож(?:а|и|е|у)|Mr|Mrs|Ms)\.?\s+([^\W\d_][\w\-]*(?:\s+[^\W\d_][\w\-]*){0,2})"
)
PERSON_TOKEN_MIN_LENGTH = 3


def normalise_text(text: Optional[str]) -> str:
    """NFKD, strip diacritics/combining marks, casefold, collapse whitespace."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped.casefold()).strip()


PROSE_WHITELIST = {normalise_text(w) for w in _PROSE_WHITELIST_RAW}


def _name_tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[^\w]+", normalise_text(name)) if t]


def resolve_owner(
    owner_mention: Optional[str],
    owner_speaker: Optional[str],
    cited_segments: list[TranscriptSegment],
    attendees: list[Attendee],
) -> tuple[str, str]:
    """
    Resolves an action owner to (owner, owner_source) without ever inventing a person name:
    a verbatim mention must literally occur in the cited segments (fabrication guard), is then
    fuzzy-matched against the attendee roster, otherwise kept as spoken for human confirmation;
    failing that, the anonymous speaker label is used, else "Unassigned".
    """
    # 1. Normalise and discard bare pronouns / fragments
    mention = normalise_text(owner_mention)
    if not mention or mention in BARE_PRONOUNS or len(mention) < 3:
        mention = ""

    # 2. Enforcement point: the mention must be a substring of what was actually said in the cited lines
    if mention:
        cited_text = normalise_text(" ".join(seg.display_text for seg in cited_segments))
        if mention not in cited_text:
            logger.warning(f"owner mention fabricated: '{owner_mention}' not found in cited segments; discarded")
            mention = ""

    # 3. Roster fuzzy match on tokens of useful length
    if mention:
        mention_tokens = [t for t in mention.split() if len(t) >= OWNER_TOKEN_MIN_LENGTH]
        for attendee in attendees:
            attendee_tokens = [t for t in _name_tokens(attendee.name) if len(t) >= OWNER_TOKEN_MIN_LENGTH]
            for m_tok in mention_tokens:
                for a_tok in attendee_tokens:
                    if SequenceMatcher(None, m_tok, a_tok).ratio() >= OWNER_TOKEN_SIMILARITY:
                        return attendee.name, "roster"
        # 4. Non-roster name as spoken: the caller flags minutes.needs_name_review
        return owner_mention.strip(), "mention"

    # 5. Anonymous speaker label (never a person name)
    speaker = (owner_speaker or "").strip()
    match = ANONYMOUS_SPEAKER_PATTERN.match(speaker)
    if match:
        return f"Speaker {match.group(1)}", "speaker"
    if speaker:
        # Diarization may already have replaced the label with a confirmed identity; accept it only when
        # that exact label spoke one of the cited lines.
        for seg in cited_segments:
            if normalise_text(seg.speaker.replace("Speaker ", "S")) == normalise_text(speaker):
                return seg.speaker, "speaker"

    # 6. Nothing verifiable
    return "Unassigned", "unassigned"


def _label_of(segment: TranscriptSegment) -> Optional[str]:
    """'Speaker 3' -> 'S3'; None for anything that is not an anonymous cluster label."""
    match = SPEAKER_RE.fullmatch(segment.speaker)
    return f"S{int(match.group(1))}" if match else None


def _dominant_label(segments: list[TranscriptSegment]) -> Optional[str]:
    """The label with the most speech across `segments` (ties: first seen); None when no labels."""
    seconds: dict[str, float] = {}
    for seg in segments:
        label = _label_of(seg)
        if label is None:
            continue
        spoken = seg.speech_seconds if seg.speech_seconds is not None else max(0.0, seg.end - seg.start)
        seconds[label] = seconds.get(label, 0.0) + spoken
    if not seconds:
        return None
    return max(seconds, key=lambda k: seconds[k])


def _normalise_label(raw: Any) -> Optional[str]:
    """Accepts 'S3', 's3', 'Speaker 3' (defensive: the prompt asks for 'S3'); None for anything else."""
    if not isinstance(raw, str):
        return None
    token = raw.strip()
    match = re.fullmatch(r"[Ss](\d{1,2})", token) or SPEAKER_RE.fullmatch(token)
    return f"S{int(match.group(1))}" if match else None


def ground_labels_in_text(text: Optional[str], allowed: set[str], fallback: Optional[str]) -> tuple[Optional[str], bool]:
    """
    Replaces every speaker-label token outside `allowed` with `fallback`; returns (text, repaired). With no
    fallback (nothing cited) the text is left as it is: an item without evidence never becomes official.
    Clinical S<n> notation ("L5-S1", "zgomotele S1 și S2", "galop S3") is not a label and is never rewritten.
    """
    if not text:
        return text, False
    repaired = False

    def _sub(match: re.Match) -> str:
        nonlocal repaired
        label = f"S{int(match.group(1))}"
        if label in allowed or fallback is None:
            return match.group(0)
        repaired = True
        return fallback

    return sub_labels(text, _sub), repaired


def ground_speaker_labels(
    text: Optional[str],
    speakers: Optional[list],
    cited_segments: list[TranscriptSegment],
) -> tuple[Optional[str], list[str], bool]:
    """
    Fabrication guard for speaker labels: the allowed set is exactly the labels of the cited segments.
    Any other S<digits> token in `text` or entry in `speakers` is replaced by the cited label with the
    most speech (a label the model never saw cannot stand in the minutes). Returns
    (text, speakers, repaired); speakers come back normalised, de-duplicated and capped at 3.
    """
    allowed = {label for label in (_label_of(seg) for seg in cited_segments) if label is not None}
    fallback = _dominant_label(cited_segments)

    text, repaired = ground_labels_in_text(text, allowed, fallback)

    grounded: list[str] = []
    for raw in speakers or []:
        label = _normalise_label(raw)
        if label is None or label not in allowed:
            repaired = True
            label = fallback
        if label is not None and label not in grounded:
            grounded.append(label)
    return text, grounded[:3], repaired


def _is_sentence_initial(before: str) -> bool:
    before = before.rstrip()
    if not before:
        return True
    if before[-1] != ".":
        return before[-1] in _SENTENCE_END_CHARS
    abbreviation = _ABBREVIATION_BEFORE_PERIOD.search(before)
    return not (abbreviation and normalise_text(abbreviation.group(1)) in _TITLE_ABBREVIATIONS)


def _capitalised_runs(text: str) -> list[tuple[list[str], bool]]:
    """Runs of consecutive capitalised words separated by spaces only, with a sentence-initial flag."""
    runs: list[tuple[list[str], bool]] = []
    current: list[str] = []
    current_initial = False
    last_end = -1
    for match in _WORD_PATTERN.finditer(text):
        token = match.group(0)
        gap = text[last_end:match.start()] if last_end >= 0 else ""
        capitalised = len(token) >= 2 and token[0].isupper()
        contiguous = current and gap.strip() == "" and last_end >= 0
        if capitalised and contiguous:
            current.append(token)
        else:
            if current:
                runs.append((current, current_initial))
            current = []
            if capitalised:
                current = [token]
                current_initial = _is_sentence_initial(text[:match.start()])
        last_end = match.end()
    if current:
        runs.append((current, current_initial))
    return runs


def _titled_names(text: str) -> list[str]:
    """Capitalised word runs that follow a person title ("doctorul Popescu" -> "Popescu")."""
    names: list[str] = []
    for match in _PERSON_TITLE_RE.finditer(text or ""):
        words: list[str] = []
        for word in match.group(1).split():
            if not word[0].isupper() or normalise_text(word) in PROSE_WHITELIST:
                break
            words.append(word)
        if words:
            names.append(" ".join(words))
    return names


def _matches_person_token(norm: str, person_tokens: set[str]) -> bool:
    """Exact, inflected ("Popescului") or near-identical match against a known person-name token."""
    if norm in person_tokens:
        return True
    for token in person_tokens:
        if len(token) >= OWNER_TOKEN_MIN_LENGTH and len(norm) >= OWNER_TOKEN_MIN_LENGTH and (norm.startswith(token) or token.startswith(norm)):
            return True
        if SequenceMatcher(None, norm, token).ratio() >= OWNER_TOKEN_SIMILARITY:
            return True
    return False


def audit_free_prose(minutes: MinutesOfMeeting, transcript: Transcript, meeting: Meeting) -> list[str]:
    """
    Returns capitalised token-runs from the free-prose fields that are neither in the transcript,
    nor in the attendee names, nor whitelisted: candidates for fabricated proper nouns that a human
    must confirm. Sentence-initial single words are treated as ordinary sentence starts.
    """
    transcript_norm = normalise_text(" ".join(seg.display_text for seg in transcript.segments))
    transcript_words = set(transcript_norm.split())
    attendee_words: set[str] = set()
    for attendee in meeting.attendees:
        attendee_words.update(_name_tokens(attendee.name))

    fields: list[str] = [minutes.summary_ro or "", minutes.summary_ru or "", minutes.summary_en or ""]
    fields.extend(minutes.agenda_topics)
    for dec in minutes.decisions:
        fields.extend([dec.topic, dec.decision])
    for act in minutes.action_items:
        fields.append(act.task)
    for risk in minutes.risks_and_questions:
        fields.append(risk.description)

    def _known(token: str) -> bool:
        norm = normalise_text(token)
        if norm in PROSE_WHITELIST or norm in attendee_words or norm in transcript_words:
            return True
        # Tolerate inflection/transliteration drift (vancomicină / vancomycin)
        return bool(get_close_matches(norm, transcript_words, n=1, cutoff=OWNER_TOKEN_SIMILARITY))

    suspects: list[str] = []
    seen: set[str] = set()
    for field in fields:
        for tokens, sentence_initial in _capitalised_runs(field):
            run_text = " ".join(tokens)
            if normalise_text(run_text) in transcript_norm:
                continue
            candidates = tokens[1:] if sentence_initial else tokens
            if not candidates:
                continue
            if all(_known(t) for t in candidates):
                continue
            key = normalise_text(run_text)
            if key not in seen:
                seen.add(key)
                suspects.append(run_text)
    return suspects


def audit_person_names(minutes: MinutesOfMeeting, transcript: Transcript, meeting: Meeting) -> list[str]:
    """
    Label-styled minutes (speaker_label_style "labels") name people ONLY through S<n> tokens, so any person
    name in their prose is a violation even when the transcript contains it (audit_free_prose accepts
    transcript words): a capitalised name after a person title ("doctorul Popescu", "Dr. Ion Popescu",
    "доктору Попеску"), or a token of an attendee name or of a name the transcript uses after a title.
    Returns the names found; the render layer would otherwise print them inline as if confirmed.
    Impersonal minutes return [] (their prose predates the label contract).
    """
    if minutes.speaker_label_style != "labels":
        return []
    person_tokens: set[str] = set()
    for attendee in meeting.attendees:
        person_tokens.update(_name_tokens(attendee.name))
    for seg in transcript.segments:
        for name in _titled_names(seg.display_text):
            person_tokens.update(_name_tokens(name))
    person_tokens = {t for t in person_tokens if len(t) >= PERSON_TOKEN_MIN_LENGTH and t not in PROSE_WHITELIST}

    fields: list[str] = [minutes.summary_ro or "", minutes.summary_ru or "", minutes.summary_en or ""]
    fields.extend(minutes.agenda_topics)
    for dec in minutes.decisions:
        fields.extend([dec.topic, dec.decision])
    for act in minutes.action_items:
        fields.append(act.task)
    for risk in minutes.risks_and_questions:
        fields.append(risk.description)

    found: list[str] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        key = normalise_text(name)
        if key and not any(key in known or known in key for known in seen):
            seen.add(key)
            found.append(name)

    for field in fields:
        for name in _titled_names(field):
            _add(name)
        for tokens, _sentence_initial in _capitalised_runs(field):
            hits = [t for t in tokens if _matches_person_token(normalise_text(t), person_tokens)]
            if hits:
                _add(" ".join(hits))
    return found


class EvidenceValidator:
    """Ensures 100% factual grounding by verifying citations against transcript utterances."""

    def validate_and_enrich(
        self,
        minutes: MinutesOfMeeting,
        transcript: Transcript,
        meeting: Meeting,
        trusted_evidence: bool = False,
    ) -> MinutesOfMeeting:
        """
        Validates evidence quotes against actual transcript text and calculates ISO dates for deadlines.
        Moves any claim lacking verified audio grounding out of official decisions into review questions.

        trusted_evidence=True is the LLM path: quotes were copied from the cited segment by the engine,
        so a citation is valid iff its segment id exists. Free-text quote matching remains for the
        heuristic/degraded path and for minutes edited by a reviewer via PUT /minutes.
        """
        segment_map = {seg.id: seg for seg in transcript.segments}
        verified_decisions = []
        verified_actions = []

        # 1. Validate Decision Grounding
        for dec in minutes.decisions:
            valid_evidence = []
            for ev in dec.evidence:
                if self._evidence_is_valid(ev, transcript, segment_map, trusted_evidence):
                    valid_evidence.append(ev)

            if valid_evidence:
                dec.evidence = valid_evidence
                verified_decisions.append(dec)
            else:
                # Reject unsupported claims from official decisions; flag for human review
                logger.warning(f"Decision '{dec.topic}' rejected: No valid audio evidence found. Moving to review questions.")
                minutes.risks_and_questions.append(
                    RiskOrQuestionItem(
                        item_type="unresolved_question",
                        description=f"[NEVERIFICAT AUDIO] {dec.topic}: {dec.decision} (Lipsă dovadă audio sincronizată)",
                        severity="high"
                    )
                )

        # 2. Validate Action Item Grounding and Resolve Deadlines
        for act in minutes.action_items:
            valid_evidence = []
            for ev in act.evidence:
                if self._evidence_is_valid(ev, transcript, segment_map, trusted_evidence):
                    valid_evidence.append(ev)

            if valid_evidence:
                act.evidence = valid_evidence
                # Resolve relative dates (e.g., "până vineri", "до конца недели")
                if act.deadline_phrase and not act.deadline_date:
                    act.deadline_date = self.resolve_relative_deadline(act.deadline_phrase, meeting.scheduled_at)
                verified_actions.append(act)
            else:
                logger.warning(f"Action '{act.task}' rejected: No valid audio evidence found. Moving to review questions.")
                minutes.risks_and_questions.append(
                    RiskOrQuestionItem(
                        item_type="unresolved_question",
                        description=f"[NEVERIFICAT AUDIO] Sarcină propusă: {act.task} (Responsabil prezumat: {act.owner})",
                        severity="medium"
                    )
                )

        minutes.decisions = verified_decisions
        minutes.action_items = verified_actions

        logger.info(f"Evidence validation: {len(minutes.decisions)} decisions and {len(minutes.action_items)} actions verified with audio grounding.")
        return minutes

    def _evidence_is_valid(
        self,
        evidence: EvidenceQuote,
        transcript: Transcript,
        segment_map: dict,
        trusted_evidence: bool,
    ) -> bool:
        """Trusted (engine-copied) evidence only needs an existing segment; anything else must reproduce the spoken text."""
        if trusted_evidence:
            seg = segment_map.get(evidence.segment_id)
            if seg is None:
                return False
            # Re-copy the audio coordinates so a stale quote can never outlive its segment
            evidence.start = seg.start
            evidence.end = seg.end
            evidence.speaker = seg.speaker
            evidence.quote = seg.display_text
            return True
        return self._verify_quote_exists(evidence, transcript, segment_map)

    def _verify_quote_exists(
        self,
        evidence: EvidenceQuote,
        transcript: Transcript,
        segment_map: dict
    ) -> bool:
        """
        Validates evidence citation strictly against cited segment ID and timestamps.
        Prevents hallucinated claims by requiring physical quote presence in cited segment.
        """
        quote = evidence.quote.strip()
        if not quote or len(quote) < 3:
            return False

        quote_clean = re.sub(r"[^\w\s]", "", quote.lower())

        # 1. Primary check: Cited segment exists and contains the quote
        seg_id = evidence.segment_id
        if seg_id in segment_map:
            target_seg = segment_map[seg_id]
            seg_text = target_seg.display_text.lower()
            seg_clean = re.sub(r"[^\w\s]", "", seg_text)

            # Timestamp bounds must overlap the cited segment for ANY match against it
            timestamps_aligned = evidence.start <= target_seg.end + 1.0 and evidence.end >= target_seg.start - 1.0
            if timestamps_aligned:
                # Check if quote or significant substring is inside cited segment
                if quote.lower() in seg_text or quote_clean in seg_clean:
                    return True

                # Tolerate only minor ASR/punctuation drift inside the cited segment:
                # the citation must still reproduce nearly every word of that utterance
                quote_words = set(quote_clean.split())
                seg_words = set(seg_clean.split())
                if len(quote_words) > 0 and len(quote_words & seg_words) / len(quote_words) >= 0.9:
                    return True

        # 2. Secondary check across all segments (must match an actual spoken segment)
        for seg in transcript.segments:
            seg_clean = re.sub(r"[^\w\s]", "", seg.display_text.lower())
            if quote_clean in seg_clean and len(quote_clean) > 8:
                evidence.segment_id = seg.id
                evidence.start = seg.start
                evidence.end = seg.end
                evidence.speaker = seg.speaker
                return True

        return False

    def resolve_relative_deadline(self, phrase: str, meeting_time: datetime) -> Optional[str]:
        """
        Calculates an ISO YYYY-MM-DD deadline from Romanian/Russian/English phrases.
        Tests longer phrases first (e.g. 'poimâine' before 'mâine') to prevent false matches.
        """
        p = phrase.lower()
        base_date = meeting_time.date()

        # Check 'poimâine' / 'послезавтра' FIRST before 'mâine' / 'завтра'
        if "poimâine" in p or "poimiine" in p or "послезавтра" in p or "day after tomorrow" in p:
            return (base_date + timedelta(days=2)).isoformat()

        if "mâine" in p or "miine" in p or "завтра" in p or "tomorrow" in p:
            return (base_date + timedelta(days=1)).isoformat()

        # Tested BEFORE day names: 'sfârșitul lunii' contains 'luni' (Monday) and would
        # otherwise resolve to next Monday
        if "sfârșitul lunii" in p or "sfarsitul lunii" in p or "конец месяца" in p or "end of month" in p:
            # Approximate end of current month
            next_month = base_date.replace(day=28) + timedelta(days=4)
            end_of_month = next_month - timedelta(days=next_month.day)
            return end_of_month.isoformat()

        # Days of week in Romanian / Russian (Russian genitive forms follow 'до ...')
        day_mapping = {
            "luni": 0, "понедельник": 0, "понедельника": 0, "monday": 0,
            "marți": 1, "marti": 1, "вторник": 1, "вторника": 1, "tuesday": 1,
            "miercuri": 2, "среда": 2, "среды": 2, "wednesday": 2,
            "joi": 3, "четверг": 3, "четверга": 3, "thursday": 3,
            "vineri": 4, "пятница": 4, "пятницы": 4, "friday": 4,
            "sâmbătă": 5, "sambata": 5, "суббота": 5, "субботы": 5, "saturday": 5,
            "duminică": 6, "duminica": 6, "воскресенье": 6, "воскресенья": 6, "sunday": 6,
        }

        # Word-boundary matching prevents substring traps ('luni' in 'lunii', 'marti' in 'martie')
        for day_name, target_weekday in day_mapping.items():
            if re.search(rf"\b{re.escape(day_name)}\b", p):
                days_ahead = target_weekday - base_date.weekday()
                if days_ahead <= 0:  # Target day already happened this week
                    days_ahead += 7
                return (base_date + timedelta(days=days_ahead)).isoformat()

        # Tested AFTER day names: 'luni săptămâna viitoare' must resolve to Monday, not to
        # the meeting weekday shifted by 7 days
        if "săptămâna viitoare" in p or "saptamana viitoare" in p or "следующая неделя" in p or "next week" in p:
            return (base_date + timedelta(days=7)).isoformat()

        return None


evidence_validator = EvidenceValidator()
