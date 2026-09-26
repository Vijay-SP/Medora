"""
A/B benchmark for the code-switching ASR engine (docs/ASR_CODE_SWITCHING.md).

Compares, on the same audio excerpt:
  baseline  - the OLD whole-file behaviour: one model.transcribe() pass with language=None (one language
              detected from the first 30 s and stamped on every segment), condition_on_previous_text=False,
              word_timestamps=False, vad_filter=True(min_silence 500 ms), no hotwords. --old-prompt adds the
              retired 257-token trilingual initial_prompt so the hallucinated opening is reproducible.
  windowed  - VAD windows, per-window restricted LID, forced-language sequential decode (engine default).
  batched   - same windows through MedparkBatchedPipeline (WHISPER_BATCH_SIZE windows per forward pass).

Usage (from the repository root, one strategy per process so only one WhisperModel ever exists):
  .venv\\Scripts\\python.exe scripts\\asr_ab_benchmark.py --strategy windowed --seconds 180
  .venv\\Scripts\\python.exe scripts\\asr_ab_benchmark.py --strategy batched --seconds 0     # full file

Safety: refuses to start while the GPU holds > 1000 MiB or Ollama has a model loaded (Whisper and the
extraction LLM cannot share 4 GB of VRAM); --wait polls every 30 s for up to 10 minutes instead.
Storage is isolated to a temp directory (only MODELS_DIR points at the real cache); nothing is emailed.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WAV = REPO_ROOT / ".audit" / "real-run" / "uploads" / "7142cbfc-4c95-4478-9b4b-97cf90d08d36" / "normalized_16k.wav"
VRAM_GATE_MIB = 1000
OLLAMA_PS_URL = "http://127.0.0.1:11434/api/ps"
EXCERPT_START, EXCERPT_END = 30.0, 90.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--wav", type=Path, default=DEFAULT_WAV, help="16 kHz mono WAV (default: the audited real recording)")
    parser.add_argument("--seconds", type=float, default=180.0, help="Length of the excerpt from the start; 0 = whole file")
    parser.add_argument("--strategy", choices=("windowed", "batched", "baseline"), default="windowed")
    parser.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    parser.add_argument("--old-prompt", action="store_true", help="baseline only: add the retired 257-token trilingual initial_prompt")
    parser.add_argument("--out", type=Path, default=None, help="JSON report path (default: %%TEMP%%/asr_ab_<strategy>.json)")
    parser.add_argument("--wait", action="store_true", help="Poll the VRAM/Ollama gate every 30 s for up to 10 min instead of refusing")
    return parser.parse_args()


def vram_used_mib() -> int | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10)
        return int(out.stdout.strip().splitlines()[0])
    except Exception:
        return None


def ollama_loaded_models() -> list[str]:
    try:
        import httpx
        response = httpx.get(OLLAMA_PS_URL, timeout=3.0)
        return [m.get("name", "?") for m in response.json().get("models", [])]
    except Exception:
        return []  # Ollama not running: nothing occupies the GPU


def gpu_gate(wait: bool) -> None:
    deadline = time.time() + 600
    while True:
        used = vram_used_mib()
        models = ollama_loaded_models()
        ok = (used is None or used < VRAM_GATE_MIB) and not models
        if ok:
            print(f"[gate] VRAM used {used} MiB, Ollama models {models or 'none'}: OK")
            return
        message = f"[gate] VRAM used {used} MiB (limit {VRAM_GATE_MIB}), Ollama models {models}"
        if not wait or time.time() > deadline:
            print(message + ": refusing to run (unload the LLM / wait for the other Whisper process).", file=sys.stderr)
            sys.exit(2)
        print(message + ": waiting 30 s ...")
        time.sleep(30)


class VramPeak(threading.Thread):
    """Samples nvidia-smi once a second; peak is an upper-bound of what the run added on top of the baseline."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.peak = vram_used_mib() or 0
        self.baseline = self.peak
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.is_set():
            used = vram_used_mib()
            if used is not None:
                self.peak = max(self.peak, used)
            self._stop.wait(1.0)

    def stop(self) -> None:
        self._stop.set()


def isolate_storage(strategy: str, device: str) -> Path:
    """Environment for app.core.config: temp data dirs, real model cache, dead SMTP, offline HF."""
    tmp = Path(tempfile.mkdtemp(prefix="medpark_asr_ab_"))
    for key in ("DATA_DIR", "UPLOADS_DIR", "EXPORTS_DIR", "FIXTURES_DIR", "VOICEPRINTS_DIR"):
        os.environ[key] = str(tmp / key.lower())
    os.environ["MODELS_DIR"] = str(REPO_ROOT / "data" / "models")
    os.environ.setdefault("SMTP_HOST", "127.0.0.1")
    os.environ.setdefault("SMTP_PORT", "9")
    os.environ.setdefault("ALLOW_SIMULATED_DELIVERY", "false")
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY"):
        os.environ.setdefault(key, "1")
    os.environ["WHISPER_STRATEGY"] = "windowed" if strategy == "baseline" else strategy
    os.environ["WHISPER_DEVICE"] = device
    return tmp


def write_excerpt(wav: Path, seconds: float, tmp: Path) -> tuple[Path, float]:
    import soundfile as sf
    audio, sr = sf.read(str(wav), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if seconds and seconds > 0:
        audio = audio[: int(seconds * sr)]
    path = tmp / f"excerpt_{int(seconds) if seconds else 'full'}.wav"
    sf.write(str(path), audio, sr)
    return path, audio.shape[0] / sr


def old_prompt() -> str:
    """The retired build_code_switch_prompt() output, byte-for-byte (kept here only for the before column)."""
    from app.services.asr.glossary import MEDPARK_ROMANIAN_TERMS, MEDPARK_RUSSIAN_TERMS
    parts = [
        "Ședință medicală și administrativă Medpark. Discuție trilingvă (Română, Русский, English).",
        "Teme clinice: " + ", ".join(MEDPARK_ROMANIAN_TERMS[:25]) + ".",
        "Термины: " + ", ".join(MEDPARK_RUSSIAN_TERMS[:15]) + ".",
    ]
    return " ".join(parts)[:800]


def run_baseline(engine, path: Path, use_old_prompt: bool) -> tuple[list[dict], dict]:
    from app.services.asr.text_lid import detect_text_language
    model = engine.load_model()
    t0 = time.perf_counter()
    segments_gen, info = model.transcribe(
        str(path),
        beam_size=5,
        language=None,
        initial_prompt=old_prompt() if use_old_prompt else None,
        condition_on_previous_text=False,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
        word_timestamps=False,
    )
    rows = []
    for seg in segments_gen:
        text = seg.text.strip()
        if not text:
            continue
        rows.append({
            "start": round(seg.start, 2), "end": round(seg.end, 2), "text": text, "language": info.language,
            "language_source": "file", "avg_logprob": seg.avg_logprob, "compression_ratio": seg.compression_ratio,
            "no_speech_prob": seg.no_speech_prob, "text_language": detect_text_language(text).language, "flag_reason": None,
        })
    wall = time.perf_counter() - t0
    stats = {"strategy": "baseline" + ("+old_prompt" if use_old_prompt else ""), "file_language": info.language,
             "file_language_probability": round(info.language_probability, 3), "seconds_total": round(wall, 2)}
    return rows, stats


def window_table(engine) -> list[dict]:
    """Per-window LID diagnostics from the engine's last run (not part of meeting.asr_stats)."""
    return [{
        "index": r.window.index, "start": round(r.window.start, 2), "end": round(r.window.end, 2), "duration": round(r.window.duration, 2),
        "acoustic": r.acoustic_language, "p1": round(r.acoustic_p1, 3), "ranking": [(l, round(p, 3)) for l, p in r.ranking],
        "language": r.language, "source": r.language_source, "confidence": r.language_confidence, "inherited": r.inherited,
        "rescored": bool(r.rescored), "hotword_echo": r.echo_redecoded, "text_lid": r.text_lid.language, "text_conf": r.text_lid.confidence,
        "mean_logprob": round(r.chosen.mean_logprob, 3) if r.chosen.segments else None, "text": r.chosen.text[:100],
    } for r in getattr(engine, "last_window_results", [])]


def run_engine(engine, path: Path) -> tuple[list[dict], dict]:
    from app.services.asr.text_lid import detect_text_language
    segments = engine.transcribe(path)
    rows = [{
        "start": s.start, "end": s.end, "text": s.raw_text, "language": s.language, "language_source": s.language_source,
        "language_confidence": s.language_confidence, "window_index": s.window_index, "avg_logprob": s.asr_avg_logprob,
        "compression_ratio": s.asr_compression_ratio, "no_speech_prob": s.asr_no_speech_prob,
        "text_language": detect_text_language(s.raw_text).language, "flag_reason": s.flag_reason,
        "corrections": [c.model_dump() for c in s.corrections], "spans": [sp.model_dump() for sp in s.language_spans],
    } for s in segments]
    return rows, dict(engine.last_run_stats)


def summarize(rows: list[dict], audio_seconds: float, wall: float) -> dict:
    durations = [round(r["end"] - r["start"], 2) for r in rows]
    languages: dict[str, int] = {}
    for r in rows:
        languages[r["language"]] = languages.get(r["language"], 0) + 1
    concrete = [r for r in rows if r["language"] in ("ro", "ru", "en") and r["text_language"] in ("ro", "ru", "en")]
    agreement = round(sum(1 for r in concrete if r["language"] == r["text_language"]) / len(concrete), 3) if concrete else None
    logprobs = [r["avg_logprob"] for r in rows if r.get("avg_logprob") is not None]
    return {
        "wall": round(wall, 2),
        "rtf": round(wall / audio_seconds, 4) if audio_seconds else None,
        "projected_minutes_per_60min_audio": round(wall / audio_seconds * 60, 1) if audio_seconds else None,
        "segments": len(rows),
        "integer_second_durations": sum(1 for d in durations if abs(d - round(d)) < 1e-9),
        "zero_gaps": sum(1 for a, b in zip(rows, rows[1:]) if abs(b["start"] - a["end"]) < 1e-9),
        "consecutive_duplicate_texts": sum(1 for a, b in zip(rows, rows[1:]) if a["text"].strip().lower() == b["text"].strip().lower()),
        "first_segment_duration": round(rows[0]["end"] - rows[0]["start"], 2) if rows else None,
        "segment_languages": languages,
        "text_vs_acoustic_agreement": agreement,
        "mean_avg_logprob": round(sum(logprobs) / len(logprobs), 4) if logprobs else None,
        "garbage_flagged": sum(1 for r in rows if r.get("flag_reason") == "low_confidence_asr"),
        "flagged_total": sum(1 for r in rows if r.get("flag_reason")),
        "translated_english_segments": sum(1 for r in rows if r["language"] == "en"),
    }


def excerpt_text(rows: list[dict], start: float, end: float) -> list[str]:
    return [f"[{r['start']:7.2f}-{r['end']:7.2f}] {r['language']:<5} {r['text']}" for r in rows if r["end"] > start and r["start"] < end]


def main() -> None:
    args = parse_args()
    if not args.wav.exists():
        print(f"WAV not found: {args.wav}", file=sys.stderr)
        sys.exit(1)
    if args.device != "cpu":
        gpu_gate(args.wait)

    tmp = isolate_storage(args.strategy, args.device)
    sys.path.insert(0, str(REPO_ROOT / "backend"))
    from app.core.config import settings  # noqa: E402  (sets the CUDA DLL path before ctranslate2 loads)
    from app.services.asr.whisper_engine import whisper_engine  # noqa: E402

    excerpt, audio_seconds = write_excerpt(args.wav, args.seconds, tmp)
    print(f"[audio] {excerpt} ({audio_seconds:.1f} s), strategy={args.strategy}, device={whisper_engine.device}, "
          f"compute={whisper_engine.compute_type}, model={settings.WHISPER_MODEL_NAME}")

    peak = VramPeak()
    peak.start()
    t_load = time.perf_counter()
    whisper_engine.load_model()
    load_seconds = time.perf_counter() - t_load

    t0 = time.perf_counter()
    if args.strategy == "baseline":
        rows, stats = run_baseline(whisper_engine, excerpt, args.old_prompt)
    else:
        rows, stats = run_engine(whisper_engine, excerpt)
    wall = time.perf_counter() - t0
    whisper_engine.release_model()
    peak.stop()

    summary = summarize(rows, audio_seconds, wall)
    summary["load_seconds"] = round(load_seconds, 2)
    summary["vram_peak_mib"] = peak.peak
    summary["vram_baseline_mib"] = peak.baseline
    text_30_90 = excerpt_text(rows, EXCERPT_START, EXCERPT_END)
    windows = window_table(whisper_engine) if args.strategy != "baseline" else []
    tag = ("+old_prompt" if args.old_prompt and args.strategy == "baseline" else "") + ("" if settings.ASR_HOTWORDS_ENABLED else "+nohotwords")
    report = {
        "strategy": args.strategy + tag,
        "wav": str(args.wav), "audio_seconds": round(audio_seconds, 2), "device": whisper_engine.device,
        "compute_type": whisper_engine.compute_type, "model": settings.WHISPER_MODEL_NAME,
        "hotwords_enabled": settings.ASR_HOTWORDS_ENABLED, "lexicon_enabled": settings.ASR_LEXICON_ENABLED,
        "summary": summary, "engine_stats": stats, "windows": windows, "transcript_30_90": text_30_90, "segments": rows,
    }
    out = args.out or Path(tempfile.gettempdir()) / f"asr_ab_{report['strategy']}_{int(args.seconds) if args.seconds else 'full'}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== SUMMARY ===")
    for key, value in summary.items():
        print(f"  {key:<34} {value}")
    print("\n=== ENGINE STATS ===")
    for key, value in stats.items():
        print(f"  {key:<34} {value}")
    if windows:
        print("\n=== WINDOWS ===")
        for w in windows:
            flags = ("I" if w["inherited"] else "-") + ("R" if w["rescored"] else "-") + ("E" if w["hotword_echo"] else "-")
            print(f"  {w['index']:>3} {w['start']:7.2f}-{w['end']:7.2f} {w['duration']:5.1f}s ac={w['acoustic']} p1={w['p1']:.2f} "
                  f"-> {w['language']:<5} {w['source']:<8} {flags} txt={w['text_lid']}/{w['text_conf']:.2f} lp={w['mean_logprob']} | {w['text'][:70]}")
    print(f"\n=== TRANSCRIPT {EXCERPT_START:.0f}-{EXCERPT_END:.0f} s ===")
    for line in text_30_90:
        print("  " + line)
    print(f"\n[report] {out}")


if __name__ == "__main__":
    main()
