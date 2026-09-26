"""
Medpark Meeting Intelligence System - Attribution Render Layer
Substitutes the anonymous speaker labels stored in the minutes ("S3" / "Speaker 3") with a display name
at READ time, and only where a reviewer confirmed or corrected the cluster and the segment is printable.

The stored MinutesOfMeeting never contains a person name in its label-styled prose: the LLM writes
"S3 a propus ...", the repository keeps "S3 a propus ...", and this module renders "Dr. Ion Popescu a
propus ..." (or "Vorbitorul 3 a propus ..." while the cluster is still anonymous) for the API, the
PDF/DOCX generator and the e-mail body. Nothing here mutates the stored object.

"S1".."S4" are also clinical notation in a hospital (sacral levels "L5-S1", nerve roots "radiculopatie S1",
heart sounds "zgomotele S1 și S2", "galop S3", stages "stadiul S2"). A token is therefore a speaker label only
when it stands alone (LABEL_RE) AND no clinical cue word governs it (is_speaker_label). The same predicate is
used by the renderer, by the extraction-time grounding (validator) and by the translation guard, so clinical
text is never rewritten, re-attributed or mistaken for a label change.
"""

import re
from typing import Callable, Iterator, Optional

from app.core.logging import logger
from app.models.extraction import EvidenceQuote, MinutesOfMeeting
from app.models.transcript import Transcript, TranscriptSegment

# "S<n>" standing on its own: not inside a word ("IS3", "S3a", "S123"), not part of a range or code
# ("L5-S1", "C7/S1", "S1-S2", "S1/S2", "S1–S2") and not a decimal ("S1.5", "S2,5").
LABEL_RE = re.compile(r"(?<![\w\-/.–])S(\d{1,2})(?![\w\-/–]|[.,]\d)")
SPEAKER_RE = re.compile(r"\bSpeaker (\d{1,2})\b")
# Both forms in ONE pass, so a substituted display name is never scanned again within a render
_TOKEN_RE = re.compile(r"(?<![\w\-/.–])(?:(Speaker )|S)(\d{1,2})(?![\w\-/–]|[.,]\d)")

ANON = {"ro": "Vorbitorul {n}", "en": "Speaker {n}", "ru": "Участник {n}"}

_CLUSTER_LABEL_RE = re.compile(r"^Speaker (\d+)$")
_NAMED_STATES = ("confirmed", "corrected")

# Words that make an adjacent S<n> clinical notation rather than a speaker (RO / EN / RU, casefolded)
_CLINICAL_CUE_RE = re.compile(
    r"^(?:zgomot\w*|galop\w*|gallops?|suflu\w*|murmurs?|sounds?|tonu\w*|tones?|radicul\w*|rădăcin\w*|radacin\w*|roots?"
    r"|nerv\w*|dermatom\w*|vertebr\w*|sacr[au]\w*|lomb\w*|lumba\w*|disc|discul|discului|disk|herni\w*|stadi\w*|stages?"
    r"|nivel\w*|levels?|segment\w*|тон\w*|галоп\w*|шум\w*|кореш\w*|нерв\w*|дерматом\w*|позвон\w*|крестц\w*|диск\w*"
    r"|грыж\w*|стади\w*|уровн\w*|сегмент\w*|радикул\w*)$"
)
# Modifiers that may sit between the cue and the token ("zgomotele cardiace S1", "tonuri cardiace S1")
_CLINICAL_MODIFIER_RE = re.compile(r"^(?:cardia\w*|heart|сердечн\w*|de|of|al|ale|patologic\w*|normal\w*|anormal\w*)$")
_SPINAL_CODE_RE = re.compile(r"^[CTLS]\d{1,2}$")
_BARE_LABEL_RE = re.compile(r"^S\d{1,2}$")
_LIST_CONJUNCTIONS = {"și", "si", "sau", "and", "or", "и", "или", "respectiv"}
_CLAUSE_BREAK_RE = re.compile(r"[.;:!?()\[\]\n]")
_CONTEXT_TOKEN_RE = re.compile(r"[^\W_]+|,")
_FOLLOWING_WORD_RE = re.compile(r"\s+([^\W\d_]+)")


def _is_cue(word: str) -> bool:
    return bool(_CLINICAL_CUE_RE.match(word.casefold()))


def _clinical_context(text: str, start: int, end: int) -> bool:
    """True when the token at text[start:end] is governed by a clinical cue word (before it, or right after it)."""
    following = _FOLLOWING_WORD_RE.match(text, end)
    if following and _is_cue(following.group(1)):
        return True
    clause = _CLAUSE_BREAK_RE.split(text[max(0, start - 120):start])[-1]
    tokens = list(reversed(_CONTEXT_TOKEN_RE.findall(clause)))
    words_seen = 0
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == ",":
            # A comma is transparent only inside a list of tokens ("zgomotele S1, S2 și S3")
            if i + 1 < len(tokens) and _BARE_LABEL_RE.match(tokens[i + 1]):
                i += 1
                continue
            return False
        if _BARE_LABEL_RE.match(token) or token.casefold() in _LIST_CONJUNCTIONS:
            i += 1
            continue
        if _is_cue(token) or _SPINAL_CODE_RE.match(token):
            return True
        words_seen += 1
        if words_seen >= 2 or not _CLINICAL_MODIFIER_RE.match(token.casefold()):
            return False
        i += 1
    return False


def is_speaker_label(text: str, match: re.Match) -> bool:
    """A LABEL_RE / token match is a speaker label unless a clinical cue governs it ("Speaker n" always is)."""
    if match.group(0).startswith("Speaker "):
        return True
    return not _clinical_context(text, match.start(), match.end())


def iter_label_matches(text: Optional[str]) -> Iterator[re.Match]:
    """The S<n> matches in `text` that are speaker labels (clinical notation excluded)."""
    if not text:
        return
    for match in LABEL_RE.finditer(text):
        if is_speaker_label(text, match):
            yield match


def labels_in(text: Optional[str]) -> set[str]:
    """Normalised speaker labels ("S3") present in `text`."""
    return {f"S{int(m.group(1))}" for m in iter_label_matches(text)}


def sub_labels(text: str, repl: Callable[[re.Match], str]) -> str:
    """LABEL_RE.sub restricted to speaker labels: clinical S<n> notation is always left as written."""
    return LABEL_RE.sub(lambda m: repl(m) if is_speaker_label(text, m) else m.group(0), text)


def _anonymous(n: str, locale: str) -> str:
    return ANON.get(locale, ANON["en"]).format(n=int(n))


def _carries_token(name: str) -> bool:
    return bool(LABEL_RE.search(name) or SPEAKER_RE.search(name))


def build_label_map(transcript: Transcript, locale: str) -> dict[str, str]:
    """
    Maps every label form of every cluster in the transcript ("S1" and "Speaker 1") to what it may
    print as in `locale`: the reviewer-confirmed name when the cluster has at least one segment that is
    confirmed/corrected AND printable (>= SPEAKER_MIN_PRINTABLE_SPEECH_S of speech), else the anonymous
    localized form. Suggestions never qualify: only a human decision makes a name printable.

    A name that itself contains a label token ("Echipa S2", "Speaker 2 (asistenta)") would re-attribute
    the text on the next render (a PUT round-trip renders stored text again), so it prints anonymously.
    """
    names: dict[str, str] = {}
    numbers: list[str] = []
    for seg in transcript.segments:
        match = _CLUSTER_LABEL_RE.match(seg.speaker)
        if not match:
            continue
        n = match.group(1)
        if n not in names:
            names[n] = ""
            numbers.append(n)
        if (
            not names[n]
            and seg.attribution_state in _NAMED_STATES
            and seg.printable_name
            and seg.confirmed_display_name
        ):
            candidate = seg.confirmed_display_name.strip()
            if _carries_token(candidate):
                logger.warning(f"Display name of {seg.speaker} contains a speaker token; the cluster renders anonymously")
                continue
            names[n] = candidate

    label_map: dict[str, str] = {}
    for n in numbers:
        display = names[n] or _anonymous(n, locale)
        label_map[f"S{int(n)}"] = display
        label_map[f"Speaker {int(n)}"] = display
    return label_map


def render_text(text: Optional[str], label_map: dict[str, str], locale: str) -> Optional[str]:
    """
    Replaces both token forms with the mapped display text in a single pass. Only tokens of clusters the
    transcript knows are substituted; anything else ("S30", a clinical "L5-S1", "zgomotele S1 și S2") is
    left exactly as written, so no unmapped token can surface a name or corrupt clinical content.
    Idempotent: anonymous forms and admissible names contain no label token. None-safe.
    """
    if not text:
        return text

    def _sub(match: re.Match) -> str:
        key = f"Speaker {int(match.group(2))}" if match.group(1) else f"S{int(match.group(2))}"
        if key not in label_map or not is_speaker_label(text, match):
            return match.group(0)
        return label_map[key]

    return _TOKEN_RE.sub(_sub, text)


def _render_list(items: Optional[list[str]], label_map: dict[str, str], locale: str) -> Optional[list[str]]:
    if items is None:
        return None
    return [render_text(t, label_map, locale) or "" for t in items]


def _render_evidence(evidence: list[EvidenceQuote], segments: dict[str, TranscriptSegment]) -> None:
    """An evidence quote IS one segment: it prints that segment's display_speaker (a name only when printable)."""
    for ev in evidence:
        seg = segments.get(ev.segment_id)
        if seg is not None:
            ev.speaker = seg.display_speaker


def _render_owner(owner: str, evidence: list[EvidenceQuote], segments: dict[str, TranscriptSegment]) -> str:
    """
    A speaker-derived owner ("Speaker 2") prints a name only when EVERY evidence segment of the action is a
    turn of that cluster and printable under the same name; a sub-floor turn, a turn of another cluster or
    a segment missing from the transcript keeps it anonymous, exactly as speakers.py decides for the stored
    owner. An owner that already is a name is left as stored.
    """
    if not evidence or not SPEAKER_RE.fullmatch(owner or ""):
        return owner
    turns = [segments.get(ev.segment_id) for ev in evidence]
    if any(seg is None or seg.speaker != owner for seg in turns):
        return owner
    shown = {seg.display_speaker for seg in turns}
    if len(shown) == 1:
        name = shown.pop()
        if name != owner:
            return name
    return owner


def render_minutes(minutes: MinutesOfMeeting, transcript: Transcript) -> MinutesOfMeeting:
    """
    Returns a DEEP COPY of the minutes with labels rendered: Romanian fields with the "ro" forms, *_ru
    with "ru", *_en with "en". EvidenceQuote.speaker and speaker-derived ActionItem.owner are resolved
    PER SEGMENT (the printable floor applies to the cited turns), never through the cluster map.

    Minutes with speaker_label_style "impersonal" (heuristic and pre-label extractions) keep their prose
    byte-identical: any "S1"/"Speaker 2" in it was written as content, not as an attribution token.
    The stored object is never touched.
    """
    rendered = minutes.model_copy(deep=True)
    segments = {seg.id: seg for seg in transcript.segments}

    for item in (*rendered.decisions, *rendered.action_items, *rendered.risks_and_questions):
        _render_evidence(item.evidence, segments)
    for act in rendered.action_items:
        if act.owner_source in ("speaker", "confirmed_speaker"):
            act.owner = _render_owner(act.owner, act.evidence, segments)

    if rendered.speaker_label_style != "labels":
        return rendered

    maps = {locale: build_label_map(transcript, locale) for locale in ("ro", "ru", "en")}
    ro, ru, en = maps["ro"], maps["ru"], maps["en"]

    rendered.summary_ro = render_text(rendered.summary_ro, ro, "ro") or ""
    rendered.summary_ru = render_text(rendered.summary_ru, ru, "ru")
    rendered.summary_en = render_text(rendered.summary_en, en, "en")
    rendered.agenda_topics = _render_list(rendered.agenda_topics, ro, "ro") or []
    rendered.agenda_topics_ru = _render_list(rendered.agenda_topics_ru, ru, "ru")
    rendered.agenda_topics_en = _render_list(rendered.agenda_topics_en, en, "en")

    for dec in rendered.decisions:
        dec.topic = render_text(dec.topic, ro, "ro") or ""
        dec.decision = render_text(dec.decision, ro, "ro") or ""
        dec.topic_ru = render_text(dec.topic_ru, ru, "ru")
        dec.decision_ru = render_text(dec.decision_ru, ru, "ru")
        dec.topic_en = render_text(dec.topic_en, en, "en")
        dec.decision_en = render_text(dec.decision_en, en, "en")

    for act in rendered.action_items:
        act.task = render_text(act.task, ro, "ro") or ""
        act.task_ru = render_text(act.task_ru, ru, "ru")
        act.task_en = render_text(act.task_en, en, "en")
        act.deadline_phrase = render_text(act.deadline_phrase, ro, "ro")
        act.deadline_phrase_ru = render_text(act.deadline_phrase_ru, ru, "ru")
        act.deadline_phrase_en = render_text(act.deadline_phrase_en, en, "en")

    for risk in rendered.risks_and_questions:
        risk.description = render_text(risk.description, ro, "ro") or ""
        risk.description_ru = render_text(risk.description_ru, ru, "ru")
        risk.description_en = render_text(risk.description_en, en, "en")

    return rendered
