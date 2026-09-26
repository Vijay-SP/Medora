"""
Medpark Meeting Intelligence System - Voice Activity Detection & Chunking
Segments continuous meeting audio along speech pauses to isolate code-switching utterances.
"""

from dataclasses import dataclass
import math
from pathlib import Path
import numpy as np
import soundfile as sf
from app.core.logging import logger


@dataclass
class SpeechSegment:
    start_sec: float
    end_sec: float
    duration_sec: float


class VoiceActivityDetector:
    """
    Lightweight, robust VAD that segments audio on pauses to ensure Whisper
    receives coherent utterance chunks rather than cross-language 30s blocks.
    """

    def __init__(
        self,
        min_silence_duration: float = 0.45,   # Minimum silence to trigger split (seconds)
        min_speech_duration: float = 1.0,     # Discard clicks/short noise (<1s)
        max_chunk_duration: float = 12.0,     # Max chunk length before forced split (seconds)
        energy_threshold_ratio: float = 0.04  # Threshold relative to RMS peak
    ):
        self.min_silence_duration = min_silence_duration
        self.min_speech_duration = min_speech_duration
        self.max_chunk_duration = max_chunk_duration
        self.energy_threshold_ratio = energy_threshold_ratio

    def _split_long_segment(self, segment: SpeechSegment) -> list[SpeechSegment]:
        """
        Divides an uninterrupted speech run longer than max_chunk_duration into equal bounded
        sub-chunks. Merging alone cannot bound a chunk: a speaker talking without a qualifying
        pause produces a single raw segment of arbitrary length.
        """
        if segment.duration_sec <= self.max_chunk_duration:
            return [segment]

        parts = math.ceil(segment.duration_sec / self.max_chunk_duration)
        part_duration = segment.duration_sec / parts

        chunks: list[SpeechSegment] = []
        for idx in range(parts):
            chunk_start = segment.start_sec + (idx * part_duration)
            chunk_end = segment.end_sec if idx == parts - 1 else chunk_start + part_duration
            chunks.append(SpeechSegment(chunk_start, chunk_end, chunk_end - chunk_start))
        return chunks

    def detect_segments(self, wav_path: Path) -> list[SpeechSegment]:
        """
        Analyzes 16kHz mono WAV and returns timestamp boundaries of active speech.
        """
        data, sample_rate = sf.read(str(wav_path))
        if data.ndim > 1:
            data = data.mean(axis=1)

        total_duration = len(data) / sample_rate
        if total_duration < 1.0:
            return [SpeechSegment(0.0, total_duration, total_duration)]

        # 30ms frame window, 10ms hop
        frame_len = int(0.030 * sample_rate)
        hop_len = int(0.010 * sample_rate)
        
        # Calculate short-time RMS energy
        num_frames = max(1, (len(data) - frame_len) // hop_len)
        frames = np.lib.stride_tricks.as_strided(
            data,
            shape=(num_frames, frame_len),
            strides=(data.strides[0] * hop_len, data.strides[0])
        )
        rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-9)
        peak_rms = np.max(rms)
        threshold = max(0.005, peak_rms * self.energy_threshold_ratio)

        is_speech = rms > threshold

        # Group contiguous speech frames into candidate segments
        raw_segments: list[SpeechSegment] = []
        in_speech = False
        start_idx = 0

        for idx, active in enumerate(is_speech):
            if active and not in_speech:
                in_speech = True
                start_idx = idx
            elif not active and in_speech:
                in_speech = False
                seg_start = (start_idx * hop_len) / sample_rate
                seg_end = ((idx * hop_len) + frame_len) / sample_rate
                if (seg_end - seg_start) >= self.min_speech_duration:
                    raw_segments.append(SpeechSegment(seg_start, seg_end, seg_end - seg_start))

        if in_speech:
            seg_start = (start_idx * hop_len) / sample_rate
            seg_end = total_duration
            if (seg_end - seg_start) >= self.min_speech_duration:
                raw_segments.append(SpeechSegment(seg_start, seg_end, seg_end - seg_start))

        # Merge segments separated by silences shorter than min_silence_duration, then split any
        # run still exceeding max_chunk_duration to keep Whisper chunks bounded
        refined: list[SpeechSegment] = []
        if not raw_segments:
            # Fallback: divide into 10s uniform blocks if entire file is below energy threshold
            block_size = 10.0
            cur = 0.0
            while cur < total_duration:
                end_cur = min(cur + block_size, total_duration)
                refined.append(SpeechSegment(cur, end_cur, end_cur - cur))
                cur = end_cur
            return refined

        current = raw_segments[0]
        for next_seg in raw_segments[1:]:
            silence_gap = next_seg.start_sec - current.end_sec
            combined_len = next_seg.end_sec - current.start_sec

            if silence_gap < self.min_silence_duration and combined_len <= self.max_chunk_duration:
                # Merge into current segment
                current = SpeechSegment(current.start_sec, next_seg.end_sec, combined_len)
            else:
                refined.append(current)
                current = next_seg
        refined.append(current)

        # Enforce the chunk budget on the merged result: any run still longer than
        # max_chunk_duration is force-split so Whisper never receives an unbounded window.
        bounded: list[SpeechSegment] = []
        for segment in refined:
            bounded.extend(self._split_long_segment(segment))

        logger.info(f"VAD partitioned {total_duration:.2f}s audio into {len(bounded)} bounded speech segments.")
        return bounded


vad_detector = VoiceActivityDetector()
