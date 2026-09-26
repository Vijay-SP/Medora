"""
Medpark Meeting Intelligence System - Kaldi-compatible log-mel filterbank (pure numpy)

Front-end for the WeSpeaker CAM++ speaker embedder (data/models/speaker/campplus). The model was trained
on features produced by torchaudio.compliance.kaldi.fbank(window_type="hamming") followed by per-utterance
cepstral mean normalisation, and it is ONLY meaningful when fed features computed the same way. Any other
mel front-end (librosa/Slaney mel, faster-whisper's Whisper mel, HTK mel) yields plausible-looking vectors
that cluster badly and never raises an exception, so this module reproduces the Kaldi semantics exactly:

  * the waveform is scaled to int16 range (x 32768) before anything else. torchaudio.load(normalize=False)
    hands WeSpeaker raw int16 samples; soundfile gives floats in [-1, 1]. Skipping the scale shifts every
    log-mel value by ln(32768^2) ~ 20.8, which CMN cancels for bins above the epsilon floor; the floor,
    however, then clips the quietest bins (pauses, silence, the upper bins of soft frames) that the scaled
    signal keeps well above it, so after CMN the two feature sets differ in exactly those regions and the
    embedding drifts from what the model was trained on. Loud, clean speech is barely affected (measured:
    a continuous 0.5-amplitude tone differs by < 1e-4 per bin after CMN, the same tone followed by 0.5 s of
    silence by up to 14), which is why the bug is silent; the scale is applied inside this function and not
    left to the caller.
  * snip_edges=True framing: num_frames = 1 + (num_samples - window_length) // window_shift.
  * per frame: dither (0 at inference), remove DC offset (subtract the frame mean), pre-emphasis
    x[n] - 0.97 * x[n-1] with x[-1] = x[0] (replicate padding), symmetric Hamming window, zero-pad to
    n_fft = next power of two >= window length (512 for 400 samples).
  * power spectrum |rfft|^2 over n_fft/2 + 1 bins.
  * Kaldi mel filterbank: num_mel_bins triangles between low_freq (20 Hz) and high_freq (0 -> Nyquist) on the
    Kaldi mel scale 1127 * ln(1 + f / 700), the mel span split into num_mel_bins + 1 equal steps, filter i
    spanning [mel_i, mel_{i+2}] and peaking at mel_{i+1}, weights linear in mel, no area normalisation.
    Kaldi computes the weights for the first n_fft/2 bins and appends a zero column for the Nyquist bin.
  * log(max(energy, eps)) with eps = float32 machine epsilon (torch.finfo(float32).eps = 1.1920929e-07),
    which is what torchaudio uses; no energy channel.
  * optional CMN: subtract the mean over time, per bin (WeSpeaker's extractor always applies it).

Reference: torchaudio.compliance.kaldi.fbank / get_mel_banks (torchaudio >= 0.9), Kaldi feat/mel-computations.cc.
"""

from __future__ import annotations

import math

import numpy as np

MILLISECONDS_TO_SECONDS = 0.001
# torchaudio: _get_epsilon(device, dtype) -> torch.finfo(dtype).eps for float32 features
EPSILON = float(np.finfo(np.float32).eps)
INT16_SCALE = 32768.0

_MEL_BANK_CACHE: dict[tuple, np.ndarray] = {}
_WINDOW_CACHE: dict[tuple[str, int], np.ndarray] = {}


def mel_scale(freq_hz):
    """Kaldi mel scale (NOT the Slaney/librosa scale)."""
    return 1127.0 * np.log(1.0 + np.asarray(freq_hz, dtype=np.float64) / 700.0)


def inverse_mel_scale(mel):
    return 700.0 * (np.exp(np.asarray(mel, dtype=np.float64) / 1127.0) - 1.0)


def next_power_of_two(n: int) -> int:
    """Smallest power of two >= n (torchaudio _next_power_of_2)."""
    return 1 if n < 1 else 1 << (n - 1).bit_length()


def window_properties(sample_rate: int, frame_length_ms: float, frame_shift_ms: float) -> tuple[int, int, int]:
    """(window_size, window_shift, padded_window_size) exactly as torchaudio derives them (int truncation)."""
    window_shift = int(sample_rate * frame_shift_ms * MILLISECONDS_TO_SECONDS)
    window_size = int(sample_rate * frame_length_ms * MILLISECONDS_TO_SECONDS)
    padded = next_power_of_two(window_size)
    if window_size < 2 or window_shift < 1:
        raise ValueError(f"invalid frame configuration: window_size={window_size}, window_shift={window_shift}")
    return window_size, window_shift, padded


def num_frames_snip_edges(num_samples: int, window_size: int, window_shift: int) -> int:
    """Kaldi frame count with snip_edges=True; 0 when the signal is shorter than one window."""
    if num_samples < window_size:
        return 0
    return 1 + (num_samples - window_size) // window_shift


def feature_window(window: str, window_size: int) -> np.ndarray:
    key = (window, window_size)
    cached = _WINDOW_CACHE.get(key)
    if cached is not None:
        return cached
    n = np.arange(window_size, dtype=np.float64)
    if window == "hamming":
        # torch.hamming_window(periodic=False, alpha=0.54, beta=0.46) == np.hamming (symmetric)
        w = 0.54 - 0.46 * np.cos(2.0 * math.pi * n / (window_size - 1))
    elif window == "hanning":
        w = 0.5 - 0.5 * np.cos(2.0 * math.pi * n / (window_size - 1))
    elif window == "povey":
        w = (0.5 - 0.5 * np.cos(2.0 * math.pi * n / (window_size - 1))) ** 0.85
    elif window == "rectangular":
        w = np.ones(window_size, dtype=np.float64)
    else:
        raise ValueError(f"unsupported window type: {window!r}")
    w = w.astype(np.float32)
    _WINDOW_CACHE[key] = w
    return w


def mel_filterbank(
    num_mel_bins: int,
    padded_window_size: int,
    sample_rate: int,
    low_freq: float = 20.0,
    high_freq: float = 0.0,
) -> np.ndarray:
    """
    Kaldi/torchaudio get_mel_banks with the trailing zero column appended, shape
    (num_mel_bins, padded_window_size // 2 + 1) so it multiplies an rfft power spectrum directly.
    """
    key = (num_mel_bins, padded_window_size, sample_rate, float(low_freq), float(high_freq))
    cached = _MEL_BANK_CACHE.get(key)
    if cached is not None:
        return cached

    num_fft_bins = padded_window_size // 2
    nyquist = 0.5 * sample_rate
    if high_freq <= 0.0:
        high_freq = high_freq + nyquist
    if not (0.0 <= low_freq < high_freq <= nyquist):
        raise ValueError(f"bad frequency range: low_freq={low_freq}, high_freq={high_freq}, nyquist={nyquist}")

    fft_bin_width = sample_rate / padded_window_size
    mel_low = mel_scale(low_freq)
    mel_high = mel_scale(high_freq)
    mel_delta = (mel_high - mel_low) / (num_mel_bins + 1)

    bins = np.arange(num_mel_bins, dtype=np.float64)[:, None]
    left_mel = mel_low + bins * mel_delta
    center_mel = mel_low + (bins + 1.0) * mel_delta
    right_mel = mel_low + (bins + 2.0) * mel_delta

    mel = mel_scale(fft_bin_width * np.arange(num_fft_bins, dtype=np.float64))[None, :]
    up_slope = (mel - left_mel) / (center_mel - left_mel)
    down_slope = (right_mel - mel) / (right_mel - center_mel)
    banks = np.maximum(0.0, np.minimum(up_slope, down_slope))

    # Kaldi computes num_fft_bins = padded // 2 weights and pads a zero for the Nyquist bin
    banks = np.concatenate([banks, np.zeros((num_mel_bins, 1))], axis=1).astype(np.float32)
    _MEL_BANK_CACHE[key] = banks
    return banks


def mel_center_frequencies(num_mel_bins: int, sample_rate: int, low_freq: float = 20.0, high_freq: float = 0.0) -> np.ndarray:
    """Centre frequency in Hz of each triangular filter (useful for tests and diagnostics)."""
    nyquist = 0.5 * sample_rate
    if high_freq <= 0.0:
        high_freq = high_freq + nyquist
    mel_low = mel_scale(low_freq)
    mel_high = mel_scale(high_freq)
    mel_delta = (mel_high - mel_low) / (num_mel_bins + 1)
    return inverse_mel_scale(mel_low + (np.arange(num_mel_bins) + 1.0) * mel_delta)


def frame_signal(waveform: np.ndarray, window_size: int, window_shift: int) -> np.ndarray:
    """(num_frames, window_size) strided view with snip_edges=True; copies so later in-place ops are safe."""
    m = num_frames_snip_edges(len(waveform), window_size, window_shift)
    if m == 0:
        return np.zeros((0, window_size), dtype=waveform.dtype)
    idx = np.arange(window_size)[None, :] + window_shift * np.arange(m)[:, None]
    return waveform[idx]


def kaldi_fbank(
    waveform: np.ndarray,
    sample_rate: int = 16000,
    num_mel_bins: int = 80,
    frame_length_ms: float = 25.0,
    frame_shift_ms: float = 10.0,
    dither: float = 0.0,
    preemphasis: float = 0.97,
    remove_dc_offset: bool = True,
    low_freq: float = 20.0,
    high_freq: float = 0.0,
    snip_edges: bool = True,
    window: str = "hamming",
    cmn: bool = True,
    scale_to_int16: bool = True,
) -> np.ndarray:
    """
    Kaldi-style log-mel filterbank, semantics of torchaudio.compliance.kaldi.fbank (+ optional CMN).

    Args:
        waveform: 1-D float array with samples in [-1, 1] (as returned by soundfile). Stereo input is
            averaged to mono. IMPORTANT: the signal is multiplied by 32768 internally (scale_to_int16=True)
            because WeSpeaker feeds int16-valued floats to fbank; pass scale_to_int16=False only if the
            array already holds int16-range values.
        sample_rate: must be the rate the model expects (16000 for CAM++); no resampling is done here.
        num_mel_bins: 80 for CAM++ (config.yaml fbank_args.num_mel_bins).
        frame_length_ms / frame_shift_ms: 25 / 10 (config.yaml fbank_args).
        dither: 0.0 at inference (config.yaml's 1.0 is a training-time augmentation). Non-zero dither uses a
            private Generator so it never touches global numpy state; it is deterministic (seed 0).
        preemphasis: 0.97, applied after DC removal with replicate padding.
        remove_dc_offset: subtract the per-frame mean.
        low_freq / high_freq: 20 Hz / 0 (= Nyquist).
        snip_edges: only True is supported (Kaldi/torchaudio default and what WeSpeaker uses).
        window: "hamming" (WeSpeaker passes window_type="hamming"; torchaudio's own default is "povey").
        cmn: subtract the per-bin mean over time (WeSpeaker extractor does this before the network).

    Returns:
        float32 array of shape (num_frames, num_mel_bins); (0, num_mel_bins) if the input is shorter than one
        frame (25 ms).
    """
    if not snip_edges:
        raise NotImplementedError("only snip_edges=True is implemented (Kaldi/WeSpeaker inference setting)")

    x = np.asarray(waveform)
    if x.ndim == 2:
        x = x.mean(axis=1)
    elif x.ndim != 1:
        raise ValueError(f"waveform must be 1-D (or 2-D channels-last), got shape {x.shape}")
    x = x.astype(np.float32, copy=False)
    if scale_to_int16:
        x = x * np.float32(INT16_SCALE)

    window_size, window_shift, padded_window_size = window_properties(sample_rate, frame_length_ms, frame_shift_ms)
    frames = frame_signal(x, window_size, window_shift).astype(np.float32)
    if frames.shape[0] == 0:
        return np.zeros((0, num_mel_bins), dtype=np.float32)

    if dither != 0.0:
        rng = np.random.default_rng(0)
        frames = frames + rng.standard_normal(frames.shape, dtype=np.float32) * np.float32(dither)

    if remove_dc_offset:
        frames = frames - frames.mean(axis=1, keepdims=True)

    if preemphasis != 0.0:
        # replicate-pad on the left: x[-1] := x[0]
        prev = np.concatenate([frames[:, :1], frames[:, :-1]], axis=1)
        frames = frames - np.float32(preemphasis) * prev

    frames = frames * feature_window(window, window_size)[None, :]

    spectrum = np.fft.rfft(frames, n=padded_window_size, axis=1)
    power = (spectrum.real ** 2 + spectrum.imag ** 2).astype(np.float32)

    banks = mel_filterbank(num_mel_bins, padded_window_size, sample_rate, low_freq, high_freq)
    mel_energies = power @ banks.T
    feats = np.log(np.maximum(mel_energies, np.float32(EPSILON))).astype(np.float32)

    if cmn:
        feats = feats - feats.mean(axis=0, keepdims=True)
    return feats


def sliding_windows(
    waveform: np.ndarray,
    sample_rate: int = 16000,
    win_s: float = 1.5,
    hop_s: float = 0.75,
) -> list[tuple[float, float, np.ndarray]]:
    """
    Fixed-length analysis windows over a waveform: [(start_s, end_s, samples), ...].

    Windows are win_s long with hop_s stride. A final partial window is emitted only if it is at least
    half of win_s (shorter tails carry too little speech for a stable embedding); a signal shorter than
    win_s yields a single window covering all of it.
    """
    x = np.asarray(waveform)
    if x.ndim == 2:
        x = x.mean(axis=1)
    n = len(x)
    win = int(round(win_s * sample_rate))
    hop = int(round(hop_s * sample_rate))
    if win <= 0 or hop <= 0:
        raise ValueError("win_s and hop_s must be positive")
    if n == 0:
        return []
    if n <= win:
        return [(0.0, n / sample_rate, x)]

    out: list[tuple[float, float, np.ndarray]] = []
    start = 0
    while start + win <= n:
        out.append((start / sample_rate, (start + win) / sample_rate, x[start:start + win]))
        start += hop
    tail = n - start
    if tail >= win // 2 and start < n:
        out.append((start / sample_rate, n / sample_rate, x[start:n]))
    return out
