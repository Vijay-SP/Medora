"""
Medpark Meeting Intelligence System - Transcript Domain Models
Defines transcript segments, speaker attribution, language detection, and audio timestamps.

Speaker attribution is a four-state machine enforced by Pydantic invariants (anonymous -> suggested ->
confirmed/corrected). `speaker` is ALWAYS the anonymous cluster label ("Speaker N") so the LLM prompt and
every persisted consumer keep seeing anonymous text; a person's name lives only in `confirmed_display_name`
and is exposed through `display_speaker`, which prints it only when the segment carries enough speech.
A name gets there in one of two ways (`attribution_basis`): a reviewer confirming an enrolled voiceprint
match (speaker_id = Person.id) or a reviewer assigning a label / attendee name with no Person record
(state "corrected", speaker_id None). Both are human decisions; neither is ever inferred.
"""

from datetime import datetime
import re
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, computed_field, field_validator, model_validator
import uuid

from app.models.meeting import _normalize_datetime

ANONYMOUS_SPEAKER_PATTERN = re.compile(r"^Speaker \d+$")
DEFAULT_ANONYMOUS_SPEAKER = "Speaker 1"

AttributionState = Literal["anonymous", "suggested", "confirmed", "corrected"]
MatchBand = Literal["strong", "moderate", "weak", "no_match"]
# What a confirmed/corrected name rests on: an enrolled voiceprint (speaker_id points at the Person) or a
# reviewer-typed / attendee-picked label with no Person record behind it (speaker_id stays None).
AttributionBasis = Literal["voiceprint", "reviewer_label"]

# Language identification provenance for a segment (code-switching ASR, see docs/ASR_CODE_SWITCHING.md).
# "legacy" = persisted before per-window LID existed (the language was stamped by a single whole-file pass).
LanguageSource = Literal["acoustic", "text", "rescored", "manual", "legacy"]
# The three languages the restricted LID may choose between; a segment's `language` may additionally be
# "mixed" (see language_spans) or "und" (undetermined), and stored data may hold other whisper codes.
SpanLanguage = Literal["ro", "ru", "en"]
UNDETERMINED_LANGUAGE = "und"
MIXED_LANGUAGE = "mixed"


def is_anonymous_speaker_label(label: Any) -> bool:
    """True for the only speaker labels a transcript may carry: 'Speaker N'."""
    return isinstance(label, str) and ANONYMOUS_SPEAKER_PATTERN.match(label) is not None


class LanguageSpan(BaseModel):
    """A contiguous run of one language inside a segment, in absolute audio seconds (only set for 'mixed')."""
    start: float
    end: float
    language: SpanLanguage


class Correction(BaseModel):
    """A lexicon substitution the ASR post-processor applied; `was` is the original decoder output."""
    was: str
    now: str
    score: float = Field(..., description="Match score of the lexicon rule that fired (not a probability)")


class SpeakerSuggestion(BaseModel):
    """Voiceprint match proposed to the reviewer; never rendered into a document."""
    person_id: str
    person_name: str
    score: float = Field(..., description="Cosine similarity of the cluster centroid to the voiceprint (not a probability)")
    margin: float = Field(..., description="Top-1 minus top-2 score across enrolled voiceprints")
    band: MatchBand
    space_id: str = Field(..., description="Embedding space the score was computed in")


class TranscriptSegment(BaseModel):
    """A bounded utterance with exact audio timestamps and speaker mapping."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    start: float = Field(..., description="Start timestamp in seconds from audio beginning")
    end: float = Field(..., description="End timestamp in seconds")
    speaker: str = Field(default=DEFAULT_ANONYMOUS_SPEAKER, description="Anonymous speaker label, always 'Speaker N'")
    speaker_id: Optional[str] = Field(None, description="Confirmed Person.id; set only when state is confirmed/corrected")
    suggested_identity: Optional[str] = Field(None, description="Mirror of suggestion.person_name pending reviewer confirmation")

    raw_text: str = Field(..., description="Verbatim raw ASR output preserving original language")
    corrected_text: Optional[str] = Field(None, description="Human reviewer correction if amended")

    language: str = Field(default="ro", description="Detected language code (ro, ru, en, mixed or und)")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Model decoding confidence")

    # Per-window language identification (all defaulted so persisted transcripts keep loading).
    language_confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Restricted LID probability of `language`")
    language_source: LanguageSource = Field(default="legacy", description="Which LID stage decided `language`")
    language_spans: list[LanguageSpan] = Field(default_factory=list, description="Per-language runs when language is 'mixed'")
    corrections: list[Correction] = Field(
        default_factory=list,
        description="Lexicon corrections already applied to raw_text; the decoder output is recoverable from `was`"
    )
    window_index: Optional[int] = Field(None, description="Index of the VAD decode window that produced the segment")
    asr_avg_logprob: Optional[float] = Field(None, description="faster-whisper avg_logprob of the source segment")
    asr_compression_ratio: Optional[float] = Field(None, description="faster-whisper compression_ratio of the source segment")
    asr_no_speech_prob: Optional[float] = Field(None, description="faster-whisper no_speech_prob of the source segment")

    is_flagged: bool = Field(default=False, description="Flagged for uncertainty, drug names, or numbers")
    flag_reason: Optional[str] = Field(None, description="Explanation for human reviewer check")

    # Speaker attribution (all defaulted so persisted transcripts keep loading)
    cluster_id: Optional[str] = Field(None, description="Diarization cluster, e.g. 'SPEAKER_01'")
    attribution_state: AttributionState = "anonymous"
    confirmed_display_name: Optional[str] = Field(None, description="Snapshot of the person's name at confirmation time")
    confirmed_by: Optional[str] = Field(None, description="Reviewer, e.g. 'Dr. Elena Ceban (Director Medical)'")
    confirmed_at: Optional[datetime] = None
    confirmed_for_revision: Optional[int] = Field(None, description="Meeting revision the confirmation was made against")
    suggestion: Optional[SpeakerSuggestion] = None
    attribution_basis: AttributionBasis = Field(
        default="voiceprint",
        description="'reviewer_label' when the corrected name is a reviewer-assigned label without a Person record"
    )
    speech_seconds: Optional[float] = Field(None, description="VAD speech inside the segment, set by the diarizer")
    printable_name: bool = Field(
        default=False,
        description="True only when confirmed/corrected AND speech_seconds >= SPEAKER_MIN_PRINTABLE_SPEECH_S"
    )
    # Pre-attribution transcripts stored free-text speaker names / attendee ids; kept for audit, never rendered.
    legacy_speaker_id: Optional[str] = None
    legacy_speaker_label: Optional[str] = None

    @field_validator("confirmed_at", mode="before")
    @classmethod
    def validate_confirmed_at(cls, v: Any) -> Any:
        return _normalize_datetime(v)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_attribution(cls, data: Any) -> Any:
        """
        Migrates segments persisted before the attribution states existed (idempotent).

        A pre-attribution `speaker_id` was an Attendee id, not a confirmed Person id, and a free-text
        `speaker` was an unverified name: both move to the legacy_* audit fields so nothing unconfirmed
        can ever print as a person.
        """
        if not isinstance(data, dict) or "attribution_state" in data:
            return data
        data = dict(data)
        if data.get("speaker_id"):
            data["legacy_speaker_id"] = data["speaker_id"]
        data["speaker_id"] = None
        speaker = data.get("speaker", DEFAULT_ANONYMOUS_SPEAKER)
        if not is_anonymous_speaker_label(speaker):
            data["legacy_speaker_label"] = speaker if isinstance(speaker, str) else str(speaker)
            data["speaker"] = DEFAULT_ANONYMOUS_SPEAKER
        data["attribution_state"] = "anonymous"
        return data

    @model_validator(mode="after")
    def enforce_attribution_invariants(self) -> "TranscriptSegment":
        """An unconfirmed name is unrepresentable: every state pins exactly which identity fields may be set."""
        if not is_anonymous_speaker_label(self.speaker):
            raise ValueError(f"speaker must be an anonymous label matching 'Speaker N', got {self.speaker!r}")
        state = self.attribution_state
        if state in ("confirmed", "corrected"):
            if not self.confirmed_display_name:
                raise ValueError(f"attribution_state={state!r} requires confirmed_display_name")
            if self.attribution_basis == "reviewer_label":
                # A reviewer label is always a correction and never points at an enrolled Person
                if state != "corrected" or self.speaker_id is not None:
                    raise ValueError("attribution_basis='reviewer_label' requires attribution_state='corrected' and no speaker_id")
            elif not self.speaker_id:
                raise ValueError(f"attribution_state={state!r} requires speaker_id (or a reviewer label as attribution_basis)")
        else:
            if self.speaker_id is not None or self.confirmed_display_name is not None or self.confirmed_by is not None:
                raise ValueError(
                    f"attribution_state={state!r} forbids speaker_id, confirmed_display_name and confirmed_by"
                )
            if state == "suggested" and self.suggestion is None:
                raise ValueError("attribution_state='suggested' requires a suggestion")
            if self.printable_name:
                raise ValueError(f"printable_name is only allowed for confirmed/corrected segments, not {state!r}")
        return self

    @computed_field
    @property
    def display_text(self) -> str:
        """Returns the reviewer-corrected text if present, otherwise raw ASR text."""
        return self.corrected_text if self.corrected_text is not None else self.raw_text

    @computed_field
    @property
    def display_speaker(self) -> str:
        """The only accessor renderers may use: the confirmed name when printable, else the anonymous label."""
        if self.printable_name and self.confirmed_display_name:
            return self.confirmed_display_name
        return self.speaker


class Transcript(BaseModel):
    """Complete collection of transcript segments for a meeting."""
    meeting_id: str
    segments: list[TranscriptSegment] = Field(default_factory=list)
    languages_detected: list[str] = Field(default_factory=lambda: ["ro"])
    total_words: int = 0
    duration_seconds: float = 0.0

    def compute_stats(self) -> None:
        """
        Computes total words, languages, and duration from segments.

        languages_detected lists real languages only: "und" is dropped and "mixed" is expanded into the
        languages of its spans (a mixed segment without spans contributes nothing). Sorted; falls back to
        ["ro"] only when no segment carries a determinable language.
        """
        all_words = 0
        langs: set[str] = set()
        max_end = 0.0
        for seg in self.segments:
            all_words += len(seg.display_text.split())
            if seg.language == MIXED_LANGUAGE:
                langs.update(span.language for span in seg.language_spans)
            elif seg.language and seg.language != UNDETERMINED_LANGUAGE:
                langs.add(seg.language)
            if seg.end > max_end:
                max_end = seg.end
        self.total_words = all_words
        self.languages_detected = sorted(langs) if langs else ["ro"]
        self.duration_seconds = max_end

    def to_indexed_lines(self) -> tuple[list[str], list[str]]:
        """
        Renders the compact indexed transcript consumed by the LLM extraction prompts.

        Each line is "{i} {spk}: {text}" when the speaker changes from the previous line and
        "{i} {text}" otherwise, with speaker labels shortened ("Speaker 1" -> "S1"). The integer
        index is the ONLY citation key the LLM ever sees; the second value maps each index back to
        the segment id so cited evidence can be copied verbatim from the source segment.
        """
        lines: list[str] = []
        segment_ids: list[str] = []
        previous_speaker: Optional[str] = None
        for i, s in enumerate(self.segments):
            spk = s.speaker.replace("Speaker ", "S")
            if s.speaker != previous_speaker:
                lines.append(f"{i} {spk}: {s.display_text}")
            else:
                lines.append(f"{i} {s.display_text}")
            segment_ids.append(s.id)
            previous_speaker = s.speaker
        return lines, segment_ids

    def to_full_text(self, use_display_names: bool = False) -> str:
        """
        Generates formatted transcript with speaker labels and timestamps.

        Anonymous labels by default (the LLM and every stored consumer). Only the UI/PDF appendix passes
        use_display_names=True, which substitutes display_speaker: a confirmed name where the segment is
        printable, the anonymous label everywhere else.
        """
        lines = []
        for s in self.segments:
            m_start, s_start = divmod(int(s.start), 60)
            m_end, s_end = divmod(int(s.end), 60)
            time_str = f"[{m_start:02d}:{s_start:02d} - {m_end:02d}:{s_end:02d}]"
            label = s.display_speaker if use_display_names else s.speaker
            lines.append(f"{time_str} {label}: {s.display_text}")
        return "\n".join(lines)
