"""
Medpark Meeting Intelligence System - Abstract ASR Interface
Enables pluggable speech-to-text engines (faster-whisper, sherpa, whisper.cpp) with zero code churn.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from app.models.transcript import TranscriptSegment


class BaseASREngine(ABC):
    """Abstract specification for offline Speech-to-Text inference."""

    @abstractmethod
    def transcribe(
        self,
        audio_path: Path,
        initial_prompt: str | None = None,
        language: str | None = None
    ) -> list[TranscriptSegment]:
        """
        Transcribes the given 16kHz mono WAV file into a sequence of timestamped segments.
        
        :param audio_path: Path to normalized audio file.
        :param initial_prompt: Contextual conditioning prompt (glossary + code-switch tokens).
        :param language: Fixed language code or None for dynamic auto-detection per chunk.
        :return: List of TranscriptSegment objects with exact start/end seconds and text.
        """
        pass
