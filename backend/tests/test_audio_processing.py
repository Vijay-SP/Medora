"""
Tests for audio normalization and VAD pause segmentation.
"""

from pathlib import Path
import numpy as np
import soundfile as sf
from app.services.audio.preprocessor import audio_preprocessor
from app.services.audio.vad import vad_detector


def test_audio_normalization_and_vad(tmp_path: Path):
    # 1. Synthesize 5 seconds of test audio with a speech burst and silence
    sr = 44100  # Non-standard rate to test resampling
    duration = 5.0
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    
    # 0s - 2s: tone (speech simulation)
    # 2s - 3s: silence
    # 3s - 5s: tone (speech simulation)
    tone1 = 0.5 * np.sin(2 * np.pi * 440 * t)
    silence_mask = (t >= 2.0) & (t < 3.0)
    audio_signal = tone1.copy()
    audio_signal[silence_mask] = 0.0

    raw_audio_path = tmp_path / "synthetic_raw.wav"
    sf.write(str(raw_audio_path), audio_signal, sr)

    # 2. Test Normalization to 16kHz Mono
    normalized_path = tmp_path / "normalized_16k.wav"
    out_path, norm_duration = audio_preprocessor.normalize(raw_audio_path, normalized_path)

    assert out_path.exists()
    assert abs(norm_duration - 5.0) < 0.2

    info = sf.info(str(out_path))
    assert info.samplerate == 16000
    assert info.channels == 1

    # 3. Test VAD Detection
    segments = vad_detector.detect_segments(out_path)
    assert len(segments) >= 1
    assert segments[0].duration_sec > 0.5


def test_vad_bounds_uninterrupted_speech(tmp_path: Path):
    """A speech run without any qualifying pause must still be split into bounded chunks."""
    sr = 16000
    duration = 40.0  # Well above max_chunk_duration, with no silence at all
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    continuous_signal = 0.5 * np.sin(2 * np.pi * 300 * t)

    audio_path = tmp_path / "continuous_speech.wav"
    sf.write(str(audio_path), continuous_signal, sr)

    segments = vad_detector.detect_segments(audio_path)
    max_chunk = vad_detector.max_chunk_duration

    assert len(segments) > 1
    # No chunk may exceed the configured budget (float tolerance only)
    assert all(seg.duration_sec <= max_chunk + 1e-6 for seg in segments)
    assert all(seg.duration_sec > 0.0 for seg in segments)
    # The split must tile the original run contiguously, without dropping or overlapping audio
    for previous, following in zip(segments, segments[1:]):
        assert abs(following.start_sec - previous.end_sec) < 1e-6
    assert (segments[-1].end_sec - segments[0].start_sec) > duration - 1.0


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        test_audio_normalization_and_vad(Path(td))
    with tempfile.TemporaryDirectory() as td:
        test_vad_bounds_uninterrupted_speech(Path(td))
    print("Audio processing and VAD tests passed successfully!")
