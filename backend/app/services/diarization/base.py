"""
Medpark Meeting Intelligence System - Abstract Diarization Interface
Enables speaker turn segmentation and identity attribution across meeting participants.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
from app.models.meeting import Attendee
from app.models.person import Person
from app.models.transcript import TranscriptSegment


class BaseDiarizationEngine(ABC):
    """Abstract interface for offline speaker diarization and participant mapping."""

    @abstractmethod
    def assign_speakers(
        self,
        audio_path: Path,
        segments: list[TranscriptSegment],
        attendees: list[Attendee] | None = None,
        meeting_id: Optional[str] = None,
        people: Optional[list[Person]] = None,
    ) -> list[TranscriptSegment]:
        """
        Assigns anonymous speaker labels ('Speaker N') to each transcript segment.

        meeting_id lets the engine cache per-segment embeddings for later re-scoring; people are the enrolled
        voiceprint owners a cluster may be SUGGESTED to match. Neither kwarg is required by older callers, and
        no implementation may put a confirmed name on a segment: that is a reviewer's decision.
        """
        pass
