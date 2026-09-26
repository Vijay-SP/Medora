"""Pluggable ASR subsystem supporting faster-whisper, local whisper.cpp (Metal), and remote LAN ASR."""

from __future__ import annotations

from app.core.config import settings
from app.services.asr.base import BaseASREngine


def get_asr_engine() -> BaseASREngine:
    """Return the configured ASR engine without loading unneeded hardware runtimes."""
    provider = settings.ASR_PROVIDER
    if provider == "whisper_cpp":
        from app.services.asr.whisper_cpp_engine import WhisperCppEngine

        return WhisperCppEngine(
            binary_path=settings.WHISPER_CPP_BINARY,
            model_path=settings.WHISPER_CPP_MODEL,
            vad_model_path=settings.WHISPER_CPP_VAD_MODEL,
            threads=settings.WHISPER_CPP_THREADS,
            use_gpu=settings.WHISPER_CPP_USE_GPU,
            timeout_s=settings.WHISPER_CPP_TIMEOUT_S,
        )
    elif provider == "remote":
        from app.services.asr.remote_engine import RemoteASREngine

        return RemoteASREngine(
            base_url=settings.REMOTE_ASR_BASE_URL,
            api_key=settings.REMOTE_ASR_API_KEY,
            timeout_s=settings.REMOTE_ASR_TIMEOUT_S,
            poll_interval_s=settings.REMOTE_ASR_POLL_INTERVAL_S,
        )
    else:  # "faster_whisper"
        from app.services.asr.whisper_engine import whisper_engine

        return whisper_engine


__all__ = ["BaseASREngine", "get_asr_engine"]
