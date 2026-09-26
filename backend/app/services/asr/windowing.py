"""
Medpark Meeting Intelligence System - ASR Decode Windows
Cuts a recording into short, silence-aligned decode windows so language identification and decoding
happen per utterance group instead of once per file.

Why windows (docs/ASR_CODE_SWITCHING.md): Whisper's encoder always consumes 30 s, and faster-whisper's
whole-file pass detects ONE language from the first 30 s and stamps it on every segment. Moldovan
clinical meetings switch language between sentences, so each ~12 s window gets its own restricted LID
and a forced-language decode. Windows are hard cuts at VAD silences with no overlap: overlap would
cost a full encoder pass per window and cross-language seam de-duplication is unreliable.
"""

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

SAMPLE_RATE = 16000

try:
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    VAD_OPTIONS = VadOptions(
        threshold=0.5,
        neg_threshold=0.35,
        min_speech_duration_ms=250,
        max_speech_duration_s=20.0,
        min_silence_duration_ms=400,
        speech_pad_ms=200,
    )
except ImportError:
    VadOptions = None
    get_speech_timestamps = None
    VAD_OPTIONS = None

# A silence this long between two VAD regions closes the current window even below the target length:
# a window is decoded as one contiguous slice, so long internal silences only feed the hallucination
# path and waste encoder input.
DEFAULT_MAX_GAP_S = 3.0


@dataclass
class DecodeWindow:
    """A contiguous audio slice [start, end) in seconds, built from one or more VAD speech regions."""
    index: int
    start: float
    end: float
    speech_regions: list[tuple[float, float]] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def speech_seconds(self) -> float:
        return sum(e - s for s, e in self.speech_regions)

    def slice(self, audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
        return audio[int(round(self.start * sample_rate)): int(round(self.end * sample_rate))]


def speech_regions(audio: np.ndarray, sample_rate: int = SAMPLE_RATE, vad_options: VadOptions | None = None) -> list[tuple[float, float]]:
    """Silero VAD speech regions as (start_s, end_s), clipped to the audio length."""
    if audio.size == 0:
        return []
    if get_speech_timestamps is None:
        raise RuntimeError("faster_whisper is not installed. Use whisper_cpp or remote ASR provider.")
    opts = vad_options or VAD_OPTIONS
    chunks = get_speech_timestamps(audio, opts, sampling_rate=sample_rate)
    total = audio.shape[0] / sample_rate
    regions = []
    for chunk in chunks:
        start = max(0.0, chunk["start"] / sample_rate)
        end = min(total, chunk["end"] / sample_rate)
        if end > start:
            regions.append((round(start, 3), round(end, 3)))
    return regions


def _split_long_region(start: float, end: float, hard_cap_s: float) -> list[tuple[float, float]]:
    """A region longer than the hard cap has no silence to cut at; cut it into equal pieces under the cap."""
    length = end - start
    if length <= hard_cap_s:
        return [(start, end)]
    pieces = int(np.ceil(length / hard_cap_s))
    step = length / pieces
    return [(round(start + i * step, 3), round(start + (i + 1) * step, 3)) for i in range(pieces)]


def pack_windows(
    regions: Sequence[tuple[float, float]],
    *,
    min_s: float = 1.5,
    target_s: float = 12.0,
    max_s: float = 20.0,
    hard_cap_s: float = 28.0,
    max_gap_s: float = DEFAULT_MAX_GAP_S,
) -> list[DecodeWindow]:
    """
    Packs consecutive VAD speech regions into decode windows.

    Rules (all durations are the window SPAN, first region start to last region end):
      - regions are appended while the span stays <= target_s and the silence gap before the region
        is <= max_gap_s; a region that would push the span past target_s starts a new window unless the
        current window is still shorter than min_s, in which case the span may grow up to max_s;
      - no window ever exceeds hard_cap_s (a lone region longer than that is cut into equal pieces);
      - a finished window shorter than min_s is merged into the previous window when the merged span
        fits under hard_cap_s (the encoder sees 30 s anyway; a 1 s window carries no LID signal).
    Regions must be sorted and non-overlapping. Returns windows with contiguous 0-based indexes.
    """
    if not (0 < min_s <= target_s <= max_s <= hard_cap_s):
        raise ValueError("window sizes must satisfy 0 < min_s <= target_s <= max_s <= hard_cap_s")

    pieces: list[tuple[float, float]] = []
    for start, end in regions:
        if end <= start:
            continue
        pieces.extend(_split_long_region(float(start), float(end), hard_cap_s))

    windows: list[DecodeWindow] = []
    current: list[tuple[float, float]] = []

    def close() -> None:
        if current:
            windows.append(DecodeWindow(index=len(windows), start=current[0][0], end=current[-1][1], speech_regions=list(current)))
            current.clear()

    for start, end in pieces:
        if not current:
            current.append((start, end))
            continue
        span_now = current[-1][1] - current[0][0]
        span_if_added = end - current[0][0]
        gap = start - current[-1][1]
        fits_target = span_if_added <= target_s
        # A window still below the minimum may stretch to max_s rather than stay unusable.
        fits_stretch = span_now < min_s and span_if_added <= max_s
        if gap <= max_gap_s and (fits_target or fits_stretch) and span_if_added <= hard_cap_s:
            current.append((start, end))
        else:
            close()
            current.append((start, end))
    close()

    # Merge windows shorter than min_s into their predecessor when the merged span fits.
    merged: list[DecodeWindow] = []
    for window in windows:
        if merged and window.duration < min_s and (window.end - merged[-1].start) <= hard_cap_s:
            previous = merged[-1]
            previous.end = window.end
            previous.speech_regions.extend(window.speech_regions)
        else:
            merged.append(window)
    for i, window in enumerate(merged):
        window.index = i
    return merged
