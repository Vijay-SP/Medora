"""
Medpark Meeting Intelligence System - Transcript Domain Models
Defines transcript segments, speaker attribution, language detection, and audio timestamps.
"""

from typing import Optional
from pydantic import BaseModel, Field, computed_field
import uuid


class TranscriptSegment(BaseModel):
    """A bounded utterance with exact audio timestamps and speaker mapping."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    start: float = Field(..., description="Start timestamp in seconds from audio beginning")
    end: float = Field(..., description="End timestamp in seconds")
    speaker: str = Field(default="Speaker 1", description="Assigned speaker label, e.g., 'Speaker 1'")
    speaker_id: Optional[str] = Field(None, description="Linked Attendee ID if confirmed")
    suggested_identity: Optional[str] = Field(None, description="Suggested attendee name pending reviewer confirmation")
    
    raw_text: str = Field(..., description="Verbatim raw ASR output preserving original language")
    corrected_text: Optional[str] = Field(None, description="Human reviewer correction if amended")
    
    language: str = Field(default="ro", description="Detected language code (ro, ru, en, or mixed)")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Model decoding confidence")
    
    is_flagged: bool = Field(default=False, description="Flagged for uncertainty, drug names, or numbers")
    flag_reason: Optional[str] = Field(None, description="Explanation for human reviewer check")

    @computed_field
    @property
    def display_text(self) -> str:
        """Returns the reviewer-corrected text if present, otherwise raw ASR text."""
        return self.corrected_text if self.corrected_text is not None else self.raw_text


class Transcript(BaseModel):
    """Complete collection of transcript segments for a meeting."""
    meeting_id: str
    segments: list[TranscriptSegment] = Field(default_factory=list)
    languages_detected: list[str] = Field(default_factory=lambda: ["ro"])
    total_words: int = 0
    duration_seconds: float = 0.0

    def compute_stats(self) -> None:
        """Computes total words, languages, and duration from segments."""
        all_words = 0
        langs = set()
        max_end = 0.0
        for seg in self.segments:
            all_words += len(seg.display_text.split())
            if seg.language:
                langs.add(seg.language)
            if seg.end > max_end:
                max_end = seg.end
        self.total_words = all_words
        self.languages_detected = sorted(list(langs)) if langs else ["ro"]
        self.duration_seconds = max_end

    def to_full_text(self) -> str:
        """Generates formatted transcript with speaker labels and timestamps."""
        lines = []
        for s in self.segments:
            m_start, s_start = divmod(int(s.start), 60)
            m_end, s_end = divmod(int(s.end), 60)
            time_str = f"[{m_start:02d}:{s_start:02d} - {m_end:02d}:{s_end:02d}]"
            lines.append(f"{time_str} {s.speaker}: {s.display_text}")
        return "\n".join(lines)
