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


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        test_audio_normalization_and_vad(Path(td))
    print("Audio processing and VAD tests passed successfully!")
