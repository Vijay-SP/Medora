"""
Medpark Meeting Intelligence System - Abstract ASR Interface
Enables pluggable speech-to-text engines (faster-whisper, sherpa, whisper.cpp) with zero code churn.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any
from app.models.transcript import TranscriptSegment


class BaseASREngine(ABC):
    """Abstract specification for offline Speech-to-Text inference."""

    @abstractmethod
    def transcribe(
        self,
        audio_path: Path,
        initial_prompt: str | None = None,
        language: str | None = None,
        *,
        context: Any | None = None
    ) -> list[TranscriptSegment]:
        """
        Transcribes the given 16kHz mono WAV file into a sequence of timestamped segments.

        :param audio_path: Path to normalized audio file.
        :param initial_prompt: Accepted for compatibility and IGNORED by the faster-whisper engine: prompt
            conditioning hallucinated the glossary as speech (docs/ASR_CODE_SWITCHING.md); engines use short
            per-language hotwords instead.
        :param language: Fixed language code ("ro", "ru", "en") forced on every decode window, or None for
            per-window language identification restricted to settings.WHISPER_LANGUAGES.
        :return: List of TranscriptSegment objects with absolute start/end seconds and text. Beyond the
            historical fields, engines fill: language (ro | ru | en | mixed | und), language_confidence,
            language_source (acoustic | text | rescored), language_spans (per-language runs when "mixed"),
            corrections (lexicon edits already applied to raw_text; the decoder output is `was`),
            window_index (decode window that produced the segment) and the raw decoder metrics
            asr_avg_logprob / asr_compression_ratio / asr_no_speech_prob. Segments that fail the garbage
            filter are kept and flagged with flag_reason "low_confidence_asr", never dropped.
        """
        pass
