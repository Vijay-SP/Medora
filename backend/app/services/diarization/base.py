"""
Medpark Meeting Intelligence System - Abstract Diarization Interface
Enables speaker turn segmentation and identity attribution across meeting participants.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from app.models.meeting import Attendee
from app.models.transcript import TranscriptSegment


class BaseDiarizationEngine(ABC):
    """Abstract interface for offline speaker diarization and participant mapping."""

    @abstractmethod
    def assign_speakers(
        self,
        audio_path: Path,
        segments: list[TranscriptSegment],
        attendees: list[Attendee] | None = None
    ) -> list[TranscriptSegment]:
        """
        Assigns speaker labels (e.g. 'Speaker 1', 'Dr. Ceban') to each transcript segment.
        """
        pass
