"""
Proves that faster-whisper is genuinely running on the GPU, not silently on the CPU.

    PYTHONPATH=backend .venv\\Scripts\\python.exe scripts\\verify_gpu.py

Three checks, and only B is authoritative:
  A. CTranslate2 reports the GPU and loads the model on cuda:0  -- passes even when cuBLAS is
     missing, because cuBLAS is loaded lazily at the first matrix multiply.
  B. CTranslate2 logs "Loaded cuBLAS library version ..." -- emitted only after a successful
     LoadLibraryA + GetProcAddress, i.e. the GEMMs actually ran on the GPU.
  C. The transcription completes and its wall time is reported.

The C++ logger inside ctranslate2.dll writes through the DLL's own C runtime, so neither
sys.stderr nor an os.dup2() on fd 2 inside this process can capture it; only the process-level
handle a parent passes in can. The transcription therefore runs in a child interpreter whose
stderr this script owns. Exit code 0 only when B holds.
"""
import os
import subprocess
import sys

CHILD_FLAG = "--child"


def _child() -> int:
    import logging
    import time

    from app.core import config  # noqa: F401  - triggers _bootstrap_cuda_dll_path() before ctranslate2 loads
    import ctranslate2
    from app.core.config import settings

    if ctranslate2.get_cuda_device_count() == 0:
        print("NO_CUDA_DEVICE")
        return 2
    ctranslate2.set_log_level(logging.INFO)

    from faster_whisper import WhisperModel

    fixture = settings.FIXTURES_DIR / "sample_speech_15s.wav"
    if not fixture.exists():
        print(f"FIXTURE_MISSING {fixture}")
        return 2

    model = WhisperModel(
        settings.WHISPER_MODEL_NAME,
        device="cuda",
        compute_type=settings.WHISPER_COMPUTE_TYPE,
        download_root=str(settings.MODELS_DIR),
        local_files_only=True,
    )
    t0 = time.time()
    segments, info = model.transcribe(str(fixture), beam_size=settings.WHISPER_BEAM_SIZE)
    segments = list(segments)  # transcribe() is lazy: the GEMMs only happen on iteration
    print(f"RESULT segments={len(segments)} seconds={time.time() - t0:.2f} lang={info.language} p={info.language_probability:.2f}")
    for s in segments[:3]:
        print(f"SEG [{s.start:6.2f}-{s.end:6.2f}] {s.text.strip()[:90]}")
    return 0


def main() -> int:
    if CHILD_FLAG in sys.argv:
        return _child()

    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("HF_HUB_OFFLINE", "1")
    env.setdefault("TRANSFORMERS_OFFLINE", "1")
    proc = subprocess.run(
        [sys.executable, os.path.abspath(__file__), CHILD_FLAG],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
    )
    out, log = proc.stdout, proc.stderr

    if "NO_CUDA_DEVICE" in out:
        print("FAIL: CTranslate2 sees no CUDA device on this machine.")
        return 2
    if "FIXTURE_MISSING" in out:
        print("FAIL:", out.strip())
        return 2

    check_a = "on device cuda:0" in log
    check_b = "Loaded cuBLAS library version" in log
    cublas_line = next((ln.split("[info]")[-1].strip() for ln in log.splitlines() if "cuBLAS" in ln), "(not logged)")
    result_line = next((ln for ln in out.splitlines() if ln.startswith("RESULT")), "RESULT (no result line)")

    print(f"A. model on cuda:0 ............ {'ok' if check_a else 'NO'}")
    print(f"B. cuBLAS loaded (authoritative) {'ok' if check_b else 'NO'}   {cublas_line}")
    print(f"C. {result_line[7:]}")
    for ln in out.splitlines():
        if ln.startswith("SEG "):
            print("     " + ln[4:])

    if proc.returncode != 0 and not check_b:
        print("\nchild stderr tail:\n" + "\n".join(log.splitlines()[-8:]))
    if not check_b:
        print("\nFAIL: GEMMs did not run through cuBLAS -> this was NOT a GPU run.")
        print("      Ensure nvidia-cublas-cu12 is installed in the venv and config._bootstrap_cuda_dll_path ran first.")
        return 1
    print("\nPASS: faster-whisper is running on the GPU.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
