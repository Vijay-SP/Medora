"""
Offline unit tests for the Kaldi fbank front-end and the speaker embedder wrapper.

    PYTHONPATH=backend .venv\\Scripts\\python.exe backend\\tests\\test_speaker_embedder.py

Runs under pytest if it is installed, and as a plain script otherwise (every test_* function is executed in
order; a skipped test prints SKIP). Model-dependent tests are skipped when the ONNX file is absent.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.diarization.fbank import (  # noqa: E402
    EPSILON,
    kaldi_fbank,
    mel_center_frequencies,
    mel_filterbank,
    mel_scale,
    next_power_of_two,
    num_frames_snip_edges,
    sliding_windows,
    window_properties,
)

SR = 16000


class _Skip(Exception):
    pass


def _skip(reason: str):
    try:
        import pytest

        pytest.skip(reason)
    except ImportError:
        raise _Skip(reason)


def _model_path() -> Path:
    from app.services.diarization.embedder import SpeakerEmbedder

    return SpeakerEmbedder().model_path


def _tone(freq_hz: float, seconds: float = 1.0, amp: float = 0.5) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * math.pi * freq_hz * t)).astype(np.float32)


# ---------------------------------------------------------------- framing / shape math
def test_window_properties_match_kaldi_defaults():
    assert window_properties(SR, 25.0, 10.0) == (400, 160, 512)
    assert next_power_of_two(400) == 512
    assert next_power_of_two(512) == 512
    assert next_power_of_two(513) == 1024


def test_frame_count_snip_edges():
    assert num_frames_snip_edges(400, 400, 160) == 1
    assert num_frames_snip_edges(399, 400, 160) == 0
    assert num_frames_snip_edges(SR, 400, 160) == 1 + (SR - 400) // 160  # 98 for 1 s
    x = np.zeros(SR * 2 + 37, dtype=np.float32)
    f = kaldi_fbank(x, SR)
    assert f.shape == (1 + (len(x) - 400) // 160, 80)
    assert f.dtype == np.float32
    assert kaldi_fbank(np.zeros(100, dtype=np.float32), SR).shape == (0, 80)


def test_silence_hits_epsilon_floor_without_cmn():
    f = kaldi_fbank(np.zeros(SR, dtype=np.float32), SR, cmn=False)
    assert np.allclose(f, math.log(EPSILON), atol=1e-5)


# ---------------------------------------------------------------- DC removal / scaling
def test_dc_offset_is_removed():
    tone = _tone(440.0)
    with_dc = tone + 0.3
    a = kaldi_fbank(tone, SR, cmn=False)
    b = kaldi_fbank(with_dc, SR, cmn=False)
    assert np.allclose(a, b, atol=1e-3), "a constant offset must not change the features"
    c = kaldi_fbank(with_dc, SR, cmn=False, remove_dc_offset=False)
    assert not np.allclose(a, c, atol=1e-3), "without DC removal the offset leaks into the low bins"


def test_int16_scaling_is_applied_once():
    tone = _tone(1000.0)
    scaled = kaldi_fbank(tone, SR, cmn=False)
    manual = kaldi_fbank(tone * 32768.0, SR, cmn=False, scale_to_int16=False)
    assert np.allclose(scaled, manual, atol=1e-4)
    unscaled = kaldi_fbank(tone, SR, cmn=False, scale_to_int16=False)
    # the log of a 32768^2 power ratio: every bin above the floor shifts by ~20.79
    peak_bin = int(scaled.mean(axis=0).argmax())
    assert abs((scaled[:, peak_bin] - unscaled[:, peak_bin]).mean() - 2 * math.log(32768.0)) < 1e-2


# ---------------------------------------------------------------- mel filterbank
def test_mel_scale_is_kaldi_not_slaney():
    assert abs(mel_scale(1000.0) - 1127.0 * math.log(1 + 1000.0 / 700.0)) < 1e-9
    assert abs(mel_scale(1000.0) - 1000.0) < 0.1  # HTK/Kaldi property: 1000 Hz ~ 1000 mel
    # Slaney (librosa default) is linear below 1 kHz: mel(500) = 3 * 500 / 200 = 7.5. Kaldi gives ~607.
    assert abs(mel_scale(500.0) - 7.5) > 500.0


def test_mel_filterbank_shape_and_edges():
    banks = mel_filterbank(80, 512, SR, 20.0, 0.0)
    assert banks.shape == (80, 257)
    assert banks.dtype == np.float32
    assert np.all(banks >= 0.0) and np.all(banks <= 1.0)
    assert np.all(banks[:, -1] == 0.0), "Kaldi pads the Nyquist bin with a zero column"
    assert np.all(banks.sum(axis=1) > 0.0)
    # triangles are contiguous: every filter starts after the previous one starts
    first_nonzero = [int(np.argmax(row > 0)) for row in banks]
    assert first_nonzero == sorted(first_nonzero)
    # no area normalisation: upper filters are wider and sum to more
    assert banks[-1].sum() > banks[0].sum()


def test_pure_tone_lands_in_expected_mel_bin():
    # Exact bins measured on 2026-09-26 with this filterbank geometry (80 bins, 20 Hz - 8 kHz, n_fft 512):
    # a one-bin slack would also accept a mel scale that is slightly off, which is precisely the silent failure
    # this front-end exists to prevent, so the peak must land on the nearest centre with no tolerance.
    centers = mel_center_frequencies(80, SR)
    for hz, expected in ((300.0, 10), (1000.0, 27), (3000.0, 52), (6000.0, 72)):
        assert int(np.abs(centers - hz).argmin()) == expected, f"mel centre nearest {hz} Hz moved from bin {expected}"
        f = kaldi_fbank(_tone(hz), SR, cmn=False)
        got = int(f.mean(axis=0).argmax())
        assert got == expected, f"{hz} Hz landed in bin {got}, expected {expected}"


# ---------------------------------------------------------------- CMN / windows
def test_cmn_yields_zero_column_means():
    rng = np.random.default_rng(3)
    x = (rng.standard_normal(SR * 2) * 0.1).astype(np.float32)
    f = kaldi_fbank(x, SR, cmn=True)
    assert np.abs(f.mean(axis=0)).max() < 1e-4
    g = kaldi_fbank(x, SR, cmn=False)
    assert np.abs(g.mean(axis=0)).max() > 1.0
    assert np.allclose(f, g - g.mean(axis=0, keepdims=True), atol=1e-5)


def test_dither_zero_is_deterministic():
    x = (np.random.default_rng(5).standard_normal(SR) * 0.1).astype(np.float32)
    assert np.array_equal(kaldi_fbank(x, SR), kaldi_fbank(x, SR))


def test_sliding_windows_geometry():
    x = np.zeros(int(SR * 4.1), dtype=np.float32)
    w = sliding_windows(x, SR, win_s=1.5, hop_s=0.75)
    starts = [round(s, 3) for s, _, _ in w]
    assert starts == [0.0, 0.75, 1.5, 2.25, 3.0]
    assert all(len(c) == 24000 for _, _, c in w[:-1])
    assert abs(w[-1][1] - 4.1) < 1e-6 and len(w[-1][2]) == int(SR * 4.1) - 48000
    short = sliding_windows(np.zeros(8000, dtype=np.float32), SR)
    assert len(short) == 1 and short[0][:2] == (0.0, 0.5) and len(short[0][2]) == 8000
    assert sliding_windows(np.zeros(0, dtype=np.float32), SR) == []


# ---------------------------------------------------------------- deterministic clustering (no model needed)
def test_agglomerative_cosine_is_deterministic_and_threshold_bound():
    from app.services.diarization.clustering import agglomerative_cosine, cosine_distance_matrix

    rng = np.random.default_rng(11)
    base_a = rng.standard_normal(16)
    base_b = -base_a + rng.standard_normal(16) * 0.05
    rows = [base_a + rng.standard_normal(16) * 0.15 for _ in range(6)] + [base_b + rng.standard_normal(16) * 0.15 for _ in range(5)]
    x = np.stack(rows).astype(np.float32)
    labels = agglomerative_cosine(x, 0.45)
    assert labels.tolist() == [0] * 6 + [1] * 5, "two well-separated groups, numbered by first appearance"
    assert np.array_equal(labels, agglomerative_cosine(x, 0.45)), "same input, same labels"
    assert agglomerative_cosine(x, 2.0).max() == 0, "a loose threshold merges everything"
    assert agglomerative_cosine(x, 0.0).max() == len(x) - 1, "a zero threshold merges nothing"
    assert agglomerative_cosine(np.zeros((0, 16), np.float32), 0.45).shape == (0,)
    assert agglomerative_cosine(x[:1], 0.45).tolist() == [0]
    d = cosine_distance_matrix(x)
    assert np.allclose(d, d.T) and np.allclose(np.diag(d), 0.0)


def test_two_means_split_and_mixed_cluster_diagnostics():
    from app.services.diarization.clustering import diagnose_clusters, two_means_split

    rng = np.random.default_rng(12)
    a = rng.standard_normal(16)
    b = rng.standard_normal(16)
    b -= a * (a @ b) / (a @ a)  # orthogonal to a: centroid cosine ~ 0
    pure = np.stack([a + rng.standard_normal(16) * 0.1 for _ in range(6)])
    mixed = np.stack([a + rng.standard_normal(16) * 0.1 for _ in range(3)] + [b + rng.standard_normal(16) * 0.1 for _ in range(3)])
    assignment, split_cos = two_means_split(mixed)
    assert assignment.tolist() == [0, 0, 0, 1, 1, 1]
    assert split_cos < 0.55
    _, pure_cos = two_means_split(pure)
    assert pure_cos > 0.55
    labels = np.array([0] * 6 + [1] * 6)
    durations = np.ones(12)
    regions = np.arange(12)
    diag = diagnose_clusters(np.vstack([pure, mixed]), labels, durations, regions)
    assert diag[0].mixed_suspect is False and diag[0].short_suspect is False
    assert diag[1].mixed_suspect is True and any("two voices" in r for r in diag[1].reasons)
    short = diagnose_clusters(pure[:2], np.array([0, 0]), np.ones(2), np.array([0, 0]))
    assert short[0].short_suspect is True and short[0].region_count == 1


# ---------------------------------------------------------------- windowing at segment edges (no model needed)
def test_regions_are_cut_at_segment_edges_so_no_window_blends_two_turns():
    from app.services.diarization.speaker_engine import cluster_label, cut_windows, intersect_regions_with_segments

    # Silero merged three fast turns (300 ms gaps, below its min-silence) into one 12 s region; the region's
    # 0.5 s tail and the second region were never transcribed
    regions = [(1.0, 13.0), (20.0, 21.0)]
    spans = [(1.0, 5.0), (5.3, 9.0), (9.3, 12.5)]
    pieces, outside = intersect_regions_with_segments(regions, spans)
    assert pieces == spans, "one piece per turn, bounded by the segment edges"
    assert abs(outside - (0.3 + 0.3 + 0.5 + 1.0)) < 1e-9, "inter-turn gaps and untranscribed speech are left out"
    windows = cut_windows(pieces, 8.0)
    assert [w[0] for w in windows] == [0, 1, 2], "each piece is its own evidence region"
    for _, start, end in windows:
        assert sum(1 for s, e in spans if s <= start and end <= e) == 1, "a window lies inside exactly one segment"
    # a long turn is still cut into <= max_seconds parts, all inside its segment
    long_pieces, _ = intersect_regions_with_segments([(0.0, 20.0)], [(0.0, 20.0)])
    long_windows = cut_windows(long_pieces, 8.0)
    assert len(long_windows) == 3 and all(w[2] - w[1] <= 8.0 + 1e-9 for w in long_windows)
    # overlapping ASR segments never double-count speech
    overlapped, _ = intersect_regions_with_segments([(0.0, 10.0)], [(0.0, 6.0), (5.0, 10.0)])
    assert overlapped == [(0.0, 5.0), (5.0, 6.0), (6.0, 10.0)]
    assert all(b[0] >= a[1] for a, b in zip(overlapped, overlapped[1:])), "pieces are chronological and non-overlapping"
    # without segments the VAD regions are used as they are
    assert intersect_regions_with_segments(regions, []) == (regions, 0.0)
    assert cluster_label("SPEAKER_02") == "Speaker 2" and cluster_label("SPEAKER_10") == "Speaker 10"
    assert cluster_label(None) is None and cluster_label("Speaker 2") is None


def test_int16_waveform_is_not_scaled_twice():
    from app.services.diarization.embedder import SpeakerEmbedder

    # tone followed by silence: the silent frames sit on the epsilon floor, where a wrong scale is visible after CMN
    signal = np.concatenate([_tone(440.0), np.zeros(SR // 2, dtype=np.float32)])
    as_int16 = (signal * 32767.0).astype(np.int16)
    as_float = as_int16.astype(np.float32) / 32768.0
    # PCM16 input must be brought to [-1, 1] before the x32768 inside kaldi_fbank: identical features either way
    assert np.array_equal(SpeakerEmbedder.features(as_int16), SpeakerEmbedder.features(as_float))
    # ...whereas feeding the raw int16 values as floats (the double-scale bug) gives different features
    assert np.abs(SpeakerEmbedder.features(as_int16) - SpeakerEmbedder.features(as_int16.astype(np.float32))).max() > 1.0


# ---------------------------------------------------------------- embedder (model-dependent)
def test_embedder_unavailable_does_not_raise_at_construction():
    from app.services.diarization.embedder import SpeakerEmbedder

    e = SpeakerEmbedder(model_path=Path("does/not/exist.onnx"))
    assert e.available is False
    assert e.load_error is not None


def test_cosine_helper():
    from app.services.diarization.embedder import cosine

    assert abs(cosine(np.array([1.0, 0.0]), np.array([1.0, 0.0])) - 1.0) < 1e-9
    assert abs(cosine(np.array([1.0, 0.0]), np.array([0.0, 1.0]))) < 1e-9
    assert cosine(np.zeros(3), np.ones(3)) == 0.0


def test_embedder_shapes_and_batch_consistency():
    if not _model_path().is_file():
        _skip(f"ONNX model absent: {_model_path()}")
    from app.services.diarization.embedder import SpeakerEmbedder, cosine

    e = SpeakerEmbedder(threads=2)
    assert e.available and e.dim == 512
    rng = np.random.default_rng(7)
    a = (rng.standard_normal(SR * 2) * 0.1).astype(np.float32)
    b = (rng.standard_normal(SR * 2) * 0.1).astype(np.float32)
    c = (rng.standard_normal(SR) * 0.1).astype(np.float32)
    ea = e.embed(a)
    assert ea.shape == (512,) and abs(np.linalg.norm(ea) - 1.0) < 1e-4
    batch = e.embed_batch([a, b, c])
    assert batch.shape == (3, 512)
    assert cosine(batch[0], ea) > 0.9999, "batched result must equal the single-item result"
    assert cosine(batch[1], e.embed(b)) > 0.9999
    assert cosine(batch[2], e.embed(c)) > 0.9999
    try:
        e.embed(np.zeros(1000, dtype=np.float32))
        assert False, "too-short audio must raise"
    except ValueError:
        pass
    try:
        e.embed(a, sample_rate=8000)
        assert False, "non-16k audio must raise"
    except ValueError:
        pass


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except _Skip as s:
            print(f"SKIP {name}: {s}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
