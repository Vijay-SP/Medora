"""
Proves the WeSpeaker CAM++ speaker embedder is wired correctly end to end (ONNX file, onnxruntime session,
Kaldi fbank front-end) and reports CPU timings. Exit 0 only when the separation gate PASSES.

    PYTHONPATH=backend .venv\\Scripts\\python.exe scripts\\verify_speaker_embedder.py

Steps:
  1. Load data/models/speaker/campplus/voxceleb_CAM++_LM.onnx and print real input/output names and shapes.
  2. Synthesise 8 different sentences with each of the two offline Windows SAPI voices (Microsoft David
     Desktop, Microsoft Zira Desktop) through a PowerShell/System.Speech subprocess at 16 kHz mono PCM16.
  3. Embed each file over its full length; report same-speaker cosine (mean/min over 2 x C(8,2) = 56 pairs)
     and cross-speaker cosine (mean/max over 64 pairs). PASS iff same_min - cross_max >= MARGIN (0.15).
     A wrong mel front-end (Slaney, HTK, un-scaled waveform, no CMN) does not raise; it shows up here as a
     collapsed margin, which is the whole point of the gate.
  4. Channel test: one file band-limited to 8 kHz (decimate to 8 kHz after a 3.4 kHz low-pass, then linear
     up-sample back) and compared with its own clean embedding.
  5. Timings: fbank ms per 60 s of audio; embed ms per 1.5 s and per 8 s window (median of 10 after warm-up).

CAUTION: TTS voices are unrealistically clean and consistent. Passing proves the model and front-end are
correct, not far-field / meeting-room accuracy.

    PYTHONPATH=backend .venv\\Scripts\\python.exe scripts\\verify_speaker_embedder.py --real [PATH]

--real reproduces the clustering statistics quoted in data/models/speaker/campplus/MODEL_CARD.md on a real
normalized 16 kHz recording (default: the longest data/uploads/*/normalized_16k.wav): Silero VAD, windows of at
most SPEAKER_WINDOW_MAX_S, one CPU embedding batch, then average-linkage clustering at several cosine-distance
thresholds with within-cluster / cross-centroid cosine and the mixed/short-suspect diagnostics. Read-only: no
store, upload or voiceprint directory is written, and nothing runs on the GPU.
"""

from __future__ import annotations

import itertools
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

MARGIN = 0.15
VOICES = ["Microsoft David Desktop", "Microsoft Zira Desktop"]
SENTENCES = [
    "The patient was admitted with acute chest pain this morning.",
    "Please schedule the follow up appointment for next Tuesday.",
    "Blood pressure remained stable throughout the night shift.",
    "The cardiology team reviewed the echocardiogram results today.",
    "We need to update the medication list before discharge.",
    "The laboratory reported elevated potassium levels at noon.",
    "Nursing staff will monitor the wound dressing every four hours.",
    "The surgical consult recommended conservative management for now.",
]


def synthesize(out_dir: Path) -> dict[str, list[Path]]:
    """Render SENTENCES with each SAPI voice to 16 kHz mono PCM16 WAV files via System.Speech."""
    spec = [
        {"voice": v, "index": i, "text": s, "path": str(out_dir / f"{v.split()[1].lower()}_{i}.wav")}
        for v in VOICES
        for i, s in enumerate(SENTENCES)
    ]
    spec_path = out_dir / "tts_spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    ps = r"""
Add-Type -AssemblyName System.Speech
$items = Get-Content -Raw -Encoding UTF8 $args[0] | ConvertFrom-Json
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
foreach ($it in $items) {
  $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
  $s.SelectVoice($it.voice)
  $s.Rate = 0
  $s.SetOutputToWaveFile($it.path, $fmt)
  $s.Speak($it.text)
  $s.Dispose()
}
"Installed voices: " + ((New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }) -join ", "
"""
    script_path = out_dir / "tts.ps1"
    script_path.write_text(ps, encoding="utf-8")
    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script_path), str(spec_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"TTS synthesis failed:\n{proc.stdout}\n{proc.stderr}")
    print(proc.stdout.strip())
    files: dict[str, list[Path]] = {v: [] for v in VOICES}
    for it in spec:
        p = Path(it["path"])
        if not p.is_file() or p.stat().st_size < 1000:
            raise RuntimeError(f"TTS produced no audio for {p}")
        files[it["voice"]].append(p)
    return files


def band_limit_8k(x: np.ndarray, sr: int = 16000, cutoff_hz: float = 3400.0) -> np.ndarray:
    """Telephone-ish channel: FFT low-pass at cutoff, decimate to 8 kHz, linear-interpolate back to sr."""
    spec = np.fft.rfft(x.astype(np.float64))
    freqs = np.fft.rfftfreq(len(x), 1.0 / sr)
    spec[freqs > cutoff_hz] = 0.0
    lp = np.fft.irfft(spec, n=len(x))
    down = lp[::2]
    t_down = np.arange(len(down)) * 2
    t_full = np.arange(len(x))
    return np.interp(t_full, t_down, down).astype(np.float32)


def main() -> int:
    import soundfile as sf

    from app.services.diarization.embedder import SpeakerEmbedder, cosine
    from app.services.diarization.fbank import kaldi_fbank

    embedder = SpeakerEmbedder(threads=4)
    print(f"[model] path={embedder.model_path}")
    if not embedder.available:
        print(f"FAIL: {embedder.load_error}")
        return 1
    session = embedder._load()
    for i in session.get_inputs():
        print(f"[model] input  name={i.name} shape={i.shape} type={i.type}")
    for o in session.get_outputs():
        print(f"[model] output name={o.name} shape={o.shape} type={o.type}")
    print(f"[model] dim={embedder.dim} providers={session.get_providers()}")

    with tempfile.TemporaryDirectory(prefix="medpark_tts_") as tmp:
        tmp_dir = Path(tmp)
        files = synthesize(tmp_dir)
        waves: dict[str, list[np.ndarray]] = {}
        for voice, paths in files.items():
            waves[voice] = []
            for p in paths:
                data, sr = sf.read(str(p), dtype="float32")
                if sr != 16000:
                    raise RuntimeError(f"unexpected sample rate {sr} for {p}")
                if data.ndim == 2:
                    data = data.mean(axis=1)
                waves[voice].append(data)
            durs = [len(w) / 16000 for w in waves[voice]]
            print(f"[tts] {voice}: {len(durs)} files, {min(durs):.2f}-{max(durs):.2f} s each")

        embs = {v: [embedder.embed(w) for w in ws] for v, ws in waves.items()}

        same = []
        for v in VOICES:
            for a, b in itertools.combinations(range(len(embs[v])), 2):
                same.append(cosine(embs[v][a], embs[v][b]))
        cross = [cosine(ea, eb) for ea in embs[VOICES[0]] for eb in embs[VOICES[1]]]
        same_mean, same_min = float(np.mean(same)), float(np.min(same))
        cross_mean, cross_max = float(np.mean(cross)), float(np.max(cross))
        margin = same_min - cross_max
        print(f"[sep] same-speaker  n={len(same)} mean={same_mean:.4f} min={same_min:.4f}")
        print(f"[sep] cross-speaker n={len(cross)} mean={cross_mean:.4f} max={cross_max:.4f}")
        print(f"[sep] margin (same_min - cross_max) = {margin:.4f} (required >= {MARGIN})")

        # channel test
        clean = waves[VOICES[0]][0]
        degraded = band_limit_8k(clean)
        e_clean = embs[VOICES[0]][0]
        e_deg = embedder.embed(degraded)
        chan_cos = cosine(e_clean, e_deg)
        chan_cross = max(cosine(e_deg, eb) for eb in embs[VOICES[1]])
        print(f"[channel] 8 kHz band-limited vs clean self: cosine={chan_cos:.4f}; max cosine to other voice={chan_cross:.4f}")

        # timings
        sixty = np.concatenate([w for ws in waves.values() for w in ws])
        sixty = np.tile(sixty, int(np.ceil(60 * 16000 / len(sixty))))[: 60 * 16000]
        kaldi_fbank(sixty)  # warm-up
        t_fb = []
        for _ in range(5):
            t0 = time.perf_counter()
            kaldi_fbank(sixty)
            t_fb.append((time.perf_counter() - t0) * 1000)
        fbank_ms_60s = statistics.median(t_fb)

        def time_embed(seconds: float) -> float:
            speech = np.concatenate(waves[VOICES[1]])
            n = int(seconds * 16000)
            seg = np.tile(speech, int(np.ceil(n / len(speech))))[:n]
            for _ in range(3):
                embedder.embed(seg)
            ts = []
            for _ in range(10):
                t0 = time.perf_counter()
                embedder.embed(seg)
                ts.append((time.perf_counter() - t0) * 1000)
            return statistics.median(ts)

        emb_1p5 = time_embed(1.5)
        emb_8 = time_embed(8.0)
        print(f"[timing] fbank per 60 s audio: {fbank_ms_60s:.1f} ms (median of 5)")
        print(f"[timing] embed (fbank+onnx) per 1.5 s window: {emb_1p5:.1f} ms; per 8 s window: {emb_8:.1f} ms (median of 10, 4 threads)")

    ok = margin >= MARGIN and chan_cos > chan_cross
    status = "PASS" if ok else "FAIL"
    print(
        f"{status}: same_min={same_min:.4f} cross_max={cross_max:.4f} margin={margin:.4f} "
        f"channel_self={chan_cos:.4f} channel_cross_max={chan_cross:.4f} "
        f"fbank60s={fbank_ms_60s:.1f}ms embed1.5s={emb_1p5:.1f}ms embed8s={emb_8:.1f}ms"
    )
    return 0 if ok else 1


def _default_real_recording() -> Path | None:
    import soundfile as sf

    candidates = sorted(ROOT.glob("data/uploads/*/normalized_16k.wav"))
    best, best_seconds = None, 0.0
    for candidate in candidates:
        try:
            seconds = float(sf.info(str(candidate)).duration)
        except Exception:
            continue
        if seconds > best_seconds:
            best, best_seconds = candidate, seconds
    return best


def real_clustering_report(path: Path, thresholds=(0.35, 0.40, 0.45, 0.50, 0.55)) -> int:
    """VAD + embed + cluster one real recording at several thresholds; prints the statistics the model card quotes."""
    from app.core.config import settings
    from app.services.diarization.clustering import agglomerative_cosine, cosine_distance_matrix, diagnose_clusters
    from app.services.diarization.embedder import SpeakerEmbedder
    from app.services.diarization.speaker_engine import cut_windows, detect_speech_regions, load_wav16k, slice_wav

    embedder = SpeakerEmbedder(threads=4)
    if not embedder.available:
        print(f"FAIL: {embedder.load_error}")
        return 1
    wav = load_wav16k(path)
    print(f"[real] {path} ({len(wav) / 16000:.1f} s)")
    t0 = time.perf_counter()
    regions = detect_speech_regions(wav)
    t_vad = time.perf_counter() - t0
    windows = cut_windows(regions, settings.SPEAKER_WINDOW_MAX_S)
    speech = sum(e - s for s, e in regions)
    print(f"[real] VAD: {len(regions)} regions, {speech:.1f} s speech ({speech / max(len(wav) / 16000, 1e-9):.0%}) in {t_vad:.1f} s; "
          f"{len(windows)} windows <= {settings.SPEAKER_WINDOW_MAX_S:.0f} s")
    if len(windows) < 2:
        print("FAIL: fewer than two windows, nothing to cluster")
        return 1
    t0 = time.perf_counter()
    embeddings = embedder.embed_batch([slice_wav(wav, s, e) for _, s, e in windows])
    t_emb = time.perf_counter() - t0
    durations = np.array([e - s for _, s, e in windows])
    region_ids = np.array([r for r, _, _ in windows])
    print(f"[real] embedded {len(windows)} windows in {t_emb:.1f} s ({1000 * t_emb / len(windows):.1f} ms/window, CPU 4 threads)")
    sims = 1.0 - cosine_distance_matrix(embeddings)
    upper = np.triu_indices(len(windows), k=1)
    print(f"[real] all-pairs window cosine: mean={sims[upper].mean():.3f} p10={np.percentile(sims[upper], 10):.3f} "
          f"p50={np.percentile(sims[upper], 50):.3f} p90={np.percentile(sims[upper], 90):.3f}")
    for threshold in thresholds:
        labels = agglomerative_cosine(embeddings, threshold)
        diag = diagnose_clusters(embeddings, labels, durations, region_ids)
        centroids = []
        within = []
        sizes = []
        for label in sorted(diag):
            idx = np.array(diag[label].member_indices)
            sizes.append(diag[label].speech_seconds)
            centroid = embeddings[idx].mean(axis=0)
            centroids.append(centroid / max(np.linalg.norm(centroid), 1e-12))
            if len(idx) > 1:
                block = sims[np.ix_(idx, idx)][np.triu_indices(len(idx), k=1)]
                within.append(float(block.mean()))
        cross = []
        for a, b in itertools.combinations(range(len(centroids)), 2):
            cross.append(float(np.dot(centroids[a], centroids[b])))
        mixed = [f"C{l}" for l, d in diag.items() if d.mixed_suspect]
        short = [f"C{l}" for l, d in diag.items() if d.short_suspect]
        marker = " <- SPEAKER_CLUSTER_DISTANCE" if abs(threshold - settings.SPEAKER_CLUSTER_DISTANCE) < 1e-9 else ""
        print(
            f"[real] distance<={threshold:.2f}: {len(diag)} clusters, speech s={[round(x, 1) for x in sorted(sizes, reverse=True)[:8]]}"
            f"{'...' if len(sizes) > 8 else ''}; within-cluster cosine mean={np.mean(within) if within else float('nan'):.3f} "
            f"min={np.min(within) if within else float('nan'):.3f}; cross-centroid cosine max={max(cross) if cross else float('nan'):.3f} "
            f"mean={np.mean(cross) if cross else float('nan'):.3f}; mixed_suspect={mixed or 'none'} short_suspect={short or 'none'}{marker}"
        )
    print("PASS: real-recording clustering report complete (no ground truth: these are descriptive statistics, not accuracy)")
    return 0


if __name__ == "__main__":
    import argparse

    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    parser = argparse.ArgumentParser(description="CAM++ speaker embedder verification (TTS gate, or --real clustering report)")
    parser.add_argument("--real", nargs="?", const="", default=None, metavar="PATH",
                        help="cluster a real normalized_16k.wav (default: the longest under data/uploads) instead of the TTS gate")
    args = parser.parse_args()
    if args.real is None:
        sys.exit(main())
    real_path = Path(args.real) if args.real else _default_real_recording()
    if real_path is None or not real_path.is_file():
        print(f"FAIL: no real recording found ({real_path})")
        sys.exit(1)
    sys.exit(real_clustering_report(real_path))
