"""
Medpark Meeting Intelligence System - Pure ONNX Silero VAD
Provides get_speech_timestamps and VadOptions without requiring faster-whisper or torch.
Falls back to faster_whisper.vad if installed, otherwise uses onnxruntime with silero_vad.onnx.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np

from app.core.config import settings
from app.core.logging import logger

VAD_MODEL_PATH = Path(settings.MODELS_DIR) / "vad" / "silero_vad.onnx"


@dataclass
class VadOptions:
    """Silero VAD segmentation options (compatible with faster_whisper.vad.VadOptions)."""
    threshold: float = 0.5
    neg_threshold: float = 0.35
    min_speech_duration_ms: int = 250
    max_speech_duration_s: float = 20.0
    min_silence_duration_ms: int = 400
    speech_pad_ms: int = 200


_ONNX_SESSION: Any = None


def _get_onnx_session() -> Any:
    global _ONNX_SESSION
    if _ONNX_SESSION is None:
        import onnxruntime as ort

        model_path = VAD_MODEL_PATH
        if not model_path.is_file():
            # Check fallback in repo root data/models/vad
            alt_path = Path(__file__).resolve().parents[4] / "data" / "models" / "vad" / "silero_vad.onnx"
            if alt_path.is_file():
                model_path = alt_path
            else:
                raise FileNotFoundError(f"Silero VAD ONNX model not found at {model_path}")
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        _ONNX_SESSION = ort.InferenceSession(str(model_path), opts, providers=["CPUExecutionProvider"])
        logger.info(f"Loaded Silero VAD ONNX model from {model_path}")
    return _ONNX_SESSION


def get_speech_timestamps(
    audio: np.ndarray,
    vad_options: Optional[VadOptions] = None,
    sampling_rate: int = 16000,
) -> list[dict[str, int]]:
    """
    Detect speech regions in 16 kHz mono audio using Silero VAD.
    Returns list of dicts with {"start": sample_index, "end": sample_index}.
    """
    # 1. Try faster_whisper if installed
    try:
        from faster_whisper.vad import VadOptions as FWVadOptions, get_speech_timestamps as fw_get_speech_timestamps
        opts = vad_options or VadOptions()
        fw_opts = FWVadOptions(
            threshold=opts.threshold,
            neg_threshold=opts.neg_threshold,
            min_speech_duration_ms=opts.min_speech_duration_ms,
            max_speech_duration_s=opts.max_speech_duration_s,
            min_silence_duration_ms=opts.min_silence_duration_ms,
            speech_pad_ms=opts.speech_pad_ms,
        )
        return fw_get_speech_timestamps(audio, fw_opts, sampling_rate=sampling_rate)
    except (ImportError, Exception):
        pass

    # 2. Pure ONNX fallback
    opts = vad_options or VadOptions()
    session = _get_onnx_session()

    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if len(audio) == 0:
        return []

    window_size_samples = 512 if sampling_rate == 16000 else 256
    min_speech_samples = int(sampling_rate * opts.min_speech_duration_ms / 1000)
    speech_pad_samples = int(sampling_rate * opts.speech_pad_ms / 1000)
    min_silence_samples = int(sampling_rate * opts.min_silence_duration_ms / 1000)
    max_speech_samples = (
        int(sampling_rate * opts.max_speech_duration_s)
        if opts.max_speech_duration_s and np.isfinite(opts.max_speech_duration_s)
        else float("inf")
    )

    state = np.zeros((2, 1, 128), dtype=np.float32)
    sr_arr = np.array(sampling_rate, dtype=np.int64)

    triggered = False
    speeches: list[dict[str, int]] = []
    current_speech: dict[str, int] = {}
    temp_end = 0

    for i in range(0, len(audio), window_size_samples):
        chunk = audio[i : i + window_size_samples]
        if len(chunk) < window_size_samples:
            chunk = np.pad(chunk, (0, window_size_samples - len(chunk)))

        ort_inputs = {
            "input": chunk.reshape(1, -1),
            "state": state,
            "sr": sr_arr,
        }
        out, state = session.run(None, ort_inputs)
        speech_prob = float(out[0][0])

        current_sample = i
        if speech_prob >= opts.threshold:
            if temp_end != 0:
                temp_end = 0
            if not triggered:
                triggered = True
                current_speech["start"] = current_sample
            continue

        if triggered and speech_prob < opts.neg_threshold:
            if temp_end == 0:
                temp_end = current_sample
            if current_sample - temp_end >= min_silence_samples:
                current_speech["end"] = temp_end
                if current_speech["end"] - current_speech["start"] >= min_speech_samples:
                    speeches.append(current_speech)
                current_speech = {}
                triggered = False
                temp_end = 0

    if triggered and "start" in current_speech:
        current_speech["end"] = len(audio)
        if current_speech["end"] - current_speech["start"] >= min_speech_samples:
            speeches.append(current_speech)

    # Apply padding and split on max_speech_samples
    padded_speeches: list[dict[str, int]] = []
    for s in speeches:
        start = max(0, s["start"] - speech_pad_samples)
        end = min(len(audio), s["end"] + speech_pad_samples)
        duration = end - start
        if duration > max_speech_samples:
            # Cut into sub-regions <= max_speech_samples
            step = int(max_speech_samples)
            for sub_start in range(start, end, step):
                sub_end = min(end, sub_start + step)
                if sub_end - sub_start >= min_speech_samples:
                    padded_speeches.append({"start": sub_start, "end": sub_end})
        else:
            padded_speeches.append({"start": start, "end": end})

    return padded_speeches
