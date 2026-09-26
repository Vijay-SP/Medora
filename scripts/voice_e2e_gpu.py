"""
GPU-gated end-to-end proof of the speaker-identity feature through the real HTTP API.

    PYTHONPATH=backend .venv\\Scripts\\python.exe scripts\\voice_e2e_gpu.py [--keep] [--port N] [--timeout-min 20]
    PYTHONPATH=backend .venv\\Scripts\\python.exe scripts\\voice_e2e_gpu.py --selftest-pdf path\\to\\Medpark_MoM_Rev1.pdf

This is the ONLY voice script that touches the GPU. It refuses to run unless `nvidia-smi` reports less than
1000 MiB in use, because Whisper (CUDA) and the Ollama LLM must have the card to themselves.

What it does:
  1. Renders a two-voice meeting and prompted enrollment samples with the offline Windows SAPI voices
     ("Microsoft David Desktop" / "Microsoft Zira Desktop", 16 kHz mono PCM16). Whisper will transcribe English.
  2. Starts the API (uvicorn, child process) against an ISOLATED temp storage root: DATA_DIR, UPLOADS_DIR,
     EXPORTS_DIR, FIXTURES_DIR and VOICEPRINTS_DIR under %TEMP%; only MODELS_DIR is shared. SMTP is pinned to a
     dead port with simulated delivery off, and the meeting is SUPERVISED, so no email can be sent.
  3. Creates the meeting, uploads the wav, runs the full pipeline (normalize -> Whisper on CUDA -> embedding
     diarizer -> Ollama extraction -> documents) and waits for COMPLETED.
  4. Enrolls both voices through /voice-profiles, re-matches, confirms ONLY David's cluster through
     /speakers/{cluster}/confirm, then downloads the PDF and DOCX.
  5. Asserts: the attribution legend is printed, "David Voice" appears, "Zira Voice" never appears, anonymous
     "Vorbitor N" labels remain for the unconfirmed voice, and segments of the confirmed cluster below the
     2.0 s printable floor still render anonymously in the transcript API.

Exit codes: 0 PASS, 1 FAIL (assertion or pipeline failure, details printed), 2 refused/skipped (GPU busy, no
nvidia-smi, SAPI or Ollama unavailable).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

SR = 16000
GAP_S = 0.8
GPU_BUSY_MIB = 1000
VOICES = {"david": "Microsoft David Desktop", "zira": "Microsoft Zira Desktop"}
NAMES = {"david": "David Voice", "zira": "Zira Voice"}
LEGEND_MARKERS = ("Vorbitorii neidentificați", "revizor uman")
MEETING_TURNS = [
    ("david", "Good morning everyone, let us start with the report from the intensive care unit."),
    ("zira", "The unit admitted four new patients overnight and two of them remain on ventilation."),
    ("david", "Has the antibiotic protocol been updated according to the last committee decision?"),
    ("zira", "Yes, the pharmacy confirmed the new dosing schedule and the nurses were briefed yesterday."),
    ("david", "Yes, okay."),
    ("zira", "We still need approval for the additional monitoring equipment before the end of the month."),
    ("david", "I will prepare the purchase request and send it to the financial department on Friday."),
    ("zira", "Please include the maintenance contract, the previous one expired in August."),
    ("david", "We decided to approve the new antibiotic protocol starting on the first of October."),
    ("zira", "We can schedule the discharge procedure review for the next meeting together with the quality indicators."),
    ("david", "Agreed, then let us close the session and record the decisions in the minutes."),
    ("zira", "Thank you all, the summary will be circulated after the review is complete."),
]
ENROLL_PROMPTS = [
    "My name is {name} and I am recording this sample for voice enrollment in the hospital meeting system. "
    "The recording takes place in a quiet office with the laptop microphone.",
    "The purpose of this sample is only to recognise my voice in future meetings, never to transcribe it. "
    "I can withdraw this consent at any time and the voiceprint will be deleted.",
    "Numbers are useful for enrollment: one, two, three, four, five, six, seven, eight, nine, ten. "
    "Then the days of the week: Monday, Tuesday, Wednesday, Thursday, Friday.",
]


class Refused(Exception):
    """Preconditions not met: not a failure of the feature."""


class Failed(Exception):
    """The feature misbehaved."""


def log(msg: str) -> None:
    print(f"[voice-e2e] {msg}", flush=True)


# ---------------------------------------------------------------- GPU gate
def gpu_memory_used_mib() -> int:
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Refused(f"nvidia-smi not available: {exc}")
    if proc.returncode != 0:
        raise Refused(f"nvidia-smi failed: {proc.stderr.strip()[:200]}")
    values = [int(v.strip()) for v in proc.stdout.strip().splitlines() if v.strip().isdigit()]
    if not values:
        raise Refused(f"nvidia-smi returned no memory figure: {proc.stdout!r}")
    return max(values)


def gpu_gate() -> None:
    used = gpu_memory_used_mib()
    if used >= GPU_BUSY_MIB:
        raise Refused(f"GPU busy: {used} MiB in use (>= {GPU_BUSY_MIB} MiB). Another run owns the card; try later.")
    log(f"GPU gate passed: {used} MiB in use")


# ---------------------------------------------------------------- SAPI fixtures
def synthesize(items: list[dict], out_dir: Path) -> None:
    spec_path = out_dir / "tts_spec.json"
    spec_path.write_text(json.dumps(items), encoding="utf-8")
    script = r"""
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
"""
    script_path = out_dir / "tts.ps1"
    script_path.write_text(script, encoding="utf-8")
    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script_path), str(spec_path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Refused(f"SAPI synthesis unavailable: {exc}")
    if proc.returncode != 0:
        raise Refused(f"SAPI synthesis failed: {proc.stdout[-300:]} {proc.stderr[-300:]}")
    for item in items:
        path = Path(item["path"])
        if not path.is_file() or path.stat().st_size < 1000:
            raise Refused(f"SAPI produced no audio for {path}")


def read_wav(path: Path) -> np.ndarray:
    import soundfile as sf

    data, sr = sf.read(str(path), dtype="float32")
    if sr != SR:
        raise Failed(f"unexpected sample rate {sr} for {path}")
    if data.ndim == 2:
        data = data.mean(axis=1)
    return np.ascontiguousarray(data, dtype=np.float32)


def trim(x: np.ndarray, threshold: float = 0.01, margin_s: float = 0.05) -> np.ndarray:
    loud = np.flatnonzero(np.abs(x) > threshold)
    if len(loud) == 0:
        return x
    margin = int(margin_s * SR)
    return x[max(0, loud[0] - margin): min(len(x), loud[-1] + margin)]


def build_fixtures(work: Path) -> dict:
    import soundfile as sf

    tts_dir = work / "tts"
    tts_dir.mkdir(parents=True, exist_ok=True)
    items = [{"voice": VOICES[v], "text": t, "path": str(tts_dir / f"turn_{i:02d}_{v}.wav")} for i, (v, t) in enumerate(MEETING_TURNS)]
    for voice in VOICES:
        for j, prompt in enumerate(ENROLL_PROMPTS):
            items.append({"voice": VOICES[voice], "text": prompt.format(name=voice.capitalize()), "path": str(tts_dir / f"enroll_{voice}_{j}.wav")})
    synthesize(items, tts_dir)
    pieces = [np.zeros(int(GAP_S * SR), dtype=np.float32)]
    cursor = GAP_S
    turns = []
    for i, (voice, text) in enumerate(MEETING_TURNS):
        clip = trim(read_wav(tts_dir / f"turn_{i:02d}_{voice}.wav"))
        turns.append({"voice": voice, "text": text, "start": round(cursor, 3), "end": round(cursor + len(clip) / SR, 3)})
        pieces.append(clip)
        pieces.append(np.zeros(int(GAP_S * SR), dtype=np.float32))
        cursor += len(clip) / SR + GAP_S
    meeting_path = work / "two_voice_meeting_16k.wav"
    sf.write(str(meeting_path), np.concatenate(pieces), SR, subtype="PCM_16")
    samples = {voice: [tts_dir / f"enroll_{voice}_{j}.wav" for j in range(len(ENROLL_PROMPTS))] for voice in VOICES}
    log(f"fixtures ready: meeting {cursor:.1f} s, {len(turns)} turns, {sum(len(v) for v in samples.values())} enrollment samples")
    return {"meeting_path": meeting_path, "turns": turns, "samples": samples}


# ---------------------------------------------------------------- PDF / DOCX text
def _unescape_pdf_literal(raw: bytes) -> bytes:
    out = bytearray()
    i = 0
    escapes = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f", b"(": b"(", b")": b")", b"\\": b"\\"}
    while i < len(raw):
        c = raw[i:i + 1]
        if c == b"\\" and i + 1 < len(raw):
            nxt = raw[i + 1:i + 2]
            if nxt in escapes:
                out += escapes[nxt]
                i += 2
                continue
            octal = re.match(rb"[0-7]{1,3}", raw[i + 1:i + 4])
            if octal:
                out.append(int(octal.group(0), 8))
                i += 1 + len(octal.group(0))
                continue
        out += c
        i += 1
    return bytes(out)


def pdf_text(data: bytes) -> str:
    """
    Best-effort text of an fpdf2 PDF with embedded TrueType subsets: glyph ids are mapped back through each
    font's ToUnicode CMap while following the current /Fn Tf operator. Good enough to find names and the legend.
    """
    import zlib

    objects = {num: body for num, body in re.findall(rb"(\d+) 0 obj(.*?)endobj", data, re.S)}

    def stream_of(body: bytes) -> bytes | None:
        m = re.search(rb"stream\r?\n(.*?)\r?\nendstream", body, re.S)
        if not m:
            return None
        try:
            return zlib.decompress(m.group(1))
        except zlib.error:
            return m.group(1)

    cmaps: dict[bytes, dict[int, str]] = {}
    for name, num in set(re.findall(rb"/(F\d+) (\d+) 0 R", data)):
        m = re.search(rb"/ToUnicode (\d+) 0 R", objects.get(num, b""))
        if not m:
            continue
        cmap = stream_of(objects.get(m.group(1), b"")) or b""
        table: dict[int, str] = {}
        for block in re.findall(rb"beginbfchar(.*?)endbfchar", cmap, re.S):
            for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
                table[int(src, 16)] = bytes.fromhex(dst.decode()).decode("utf-16-be", "replace")
        for block in re.findall(rb"beginbfrange(.*?)endbfrange", cmap, re.S):
            for lo, hi, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
                base = int(dst, 16)
                for code in range(int(lo, 16), int(hi, 16) + 1):
                    table[code] = chr(base + code - int(lo, 16))
        cmaps[name] = table

    chunks: list[str] = []
    for body in objects.values():
        content = stream_of(body)
        if not content or b"BT" not in content or b"Tj" not in content and b"TJ" not in content:
            continue
        table: dict[int, str] = {}
        for m in re.finditer(rb"/(F\d+)\s+[\d.]+\s+Tf|\(((?:\\.|[^\\)])*)\)\s*Tj", content, re.S):
            if m.group(1):
                table = cmaps.get(m.group(1), {})
                continue
            raw = _unescape_pdf_literal(m.group(2))
            if table:
                glyphs = [int.from_bytes(raw[k:k + 2], "big") for k in range(0, len(raw) - 1, 2)]
                chunks.append("".join(table.get(g, "�") for g in glyphs))
            else:
                chunks.append(raw.decode("latin-1", "replace"))
            chunks.append("\n")
    return "".join(chunks)


def docx_text(data: bytes) -> str:
    with zipfile.ZipFile(_bytes_io(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    return re.sub(r"<[^>]+>", " ", xml)


def _bytes_io(data: bytes):
    import io

    return io.BytesIO(data)


# ---------------------------------------------------------------- API driver
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def start_api(work: Path, port: int) -> subprocess.Popen:
    env = dict(os.environ)
    env.update({
        "DATA_DIR": str(work / "data"),
        "UPLOADS_DIR": str(work / "uploads"),
        "EXPORTS_DIR": str(work / "exports"),
        "FIXTURES_DIR": str(work / "fixtures"),
        "VOICEPRINTS_DIR": str(work / "voiceprints"),
        "SMTP_HOST": "127.0.0.1",
        "SMTP_PORT": "9",
        "ALLOW_SIMULATED_DELIVERY": "false",
        "ENABLE_DEFAULT_ROUTING_POLICIES": "false",
        "N8N_ENABLED": "false",
        "VOICE_ID_ENABLED": "true",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "PYTHONIOENCODING": "utf-8",
    })
    env.setdefault("MODELS_DIR", str(ROOT / "data" / "models"))
    env.setdefault("WHISPER_DEVICE", "cuda")
    env.pop("PYTHONPATH", None)
    log_path = work / "api.log"
    log_file = open(log_path, "w", encoding="utf-8")
    cmd = [sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "127.0.0.1", "--port", str(port), "--log-level", "info"]
    proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env, stdout=log_file, stderr=subprocess.STDOUT)
    log(f"API starting on port {port} (log: {log_path})")
    return proc


class Api:
    def __init__(self, base_url: str):
        import httpx

        self.base = base_url
        self.client = httpx.Client(base_url=base_url, timeout=120.0)

    def wait_ready(self, seconds: int = 90) -> dict:
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                if self.client.get("/health").status_code == 200:
                    return self.client.get("/ready").json()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(1.0)
        raise Failed("API did not come up in time")

    def expect(self, res, *codes: int) -> dict:
        if res.status_code not in codes:
            raise Failed(f"{res.request.method} {res.request.url.path} -> {res.status_code}: {res.text[:400]}")
        return res.json() if res.content else {}


def run(args: argparse.Namespace) -> int:
    gpu_gate()
    work = Path(tempfile.mkdtemp(prefix="medpark_voice_e2e_"))
    log(f"isolated storage root: {work}")
    proc: subprocess.Popen | None = None
    try:
        fx = build_fixtures(work)
        port = args.port or free_port()
        proc = start_api(work, port)
        api = Api(f"http://127.0.0.1:{port}")
        ready = api.wait_ready()
        voice = ready.get("voice_id", {})
        if not voice.get("enabled"):
            raise Refused(f"/ready reports voice_id disabled: {voice}")
        if not ready.get("llm_service", {}).get("connected"):
            raise Refused(f"local LLM not serving ({ready.get('llm_service')}); the pipeline would fail at preflight")
        log(f"/ready: voice_id={voice} asr={ready.get('asr_service')}")

        # 1. meeting (SUPERVISED: nothing is ever dispatched) + upload + pipeline
        meeting = api.expect(api.client.post("/api/v1/meetings/", json={
            "title": "Voice E2E two-voice meeting", "meeting_type": "administrative", "workflow_mode": "supervised",
            "attendees": [], "distribution_list": ["outbox@example.invalid"],
        }), 201)
        meeting_id = meeting["id"]
        with open(fx["meeting_path"], "rb") as fp:
            api.expect(api.client.post(f"/api/v1/meetings/{meeting_id}/audio/upload", files={"file": ("meeting.wav", fp, "audio/wav")}), 200)
        api.expect(api.client.post(f"/api/v1/meetings/{meeting_id}/pipeline/start"), 200)
        t0 = time.time()
        deadline = t0 + args.timeout_min * 60
        status = {}
        while time.time() < deadline:
            status = api.expect(api.client.get(f"/api/v1/meetings/{meeting_id}/pipeline/status"), 200)
            if status["status"] in ("completed", "failed"):
                break
            time.sleep(5.0)
        log(f"pipeline {status.get('status')} in {time.time() - t0:.0f} s: {status.get('current_stage')} {status.get('error_message') or ''}")
        if status.get("status") != "completed":
            raise Failed(f"pipeline did not complete: {status}")
        meeting = api.expect(api.client.get(f"/api/v1/meetings/{meeting_id}"), 200)
        log(f"ASR device used: {meeting.get('asr_device_used')}; review_status={meeting.get('review_status')}")
        if meeting.get("asr_device_used") != "cuda":
            log("WARNING: the ASR stage did not report cuda; timings are not representative")

        transcript = api.expect(api.client.get(f"/api/v1/meetings/{meeting_id}/transcript/"), 200)
        segments = transcript["segments"]
        clusters = {}
        for seg in segments:
            clusters.setdefault(seg.get("cluster_id"), []).append(seg)
        log(f"transcript: {len(segments)} segments, clusters {{{', '.join(f'{k}: {len(v)}' for k, v in clusters.items())}}}")
        if any(seg["attribution_state"] in ("confirmed", "corrected") for seg in segments):
            raise Failed("the pipeline produced a confirmed segment without a human")
        if any(not re.match(r"^Speaker \d+$", seg["speaker"]) for seg in segments):
            raise Failed("a non-anonymous speaker label came out of the pipeline")

        # 2. enrollment through the API (explicit, consented; never from meeting audio)
        profiles = {}
        for voice_key, name in NAMES.items():
            profile = api.expect(api.client.post("/api/v1/voice-profiles/", json={"person_name": name, "role": "Medic", "email": ""}), 201)
            api.expect(api.client.post(f"/api/v1/voice-profiles/{profile['id']}/consent", json={"granted": True}), 200)
            for path in fx["samples"][voice_key]:
                with open(path, "rb") as fp:
                    quality = api.expect(api.client.post(f"/api/v1/voice-profiles/{profile['id']}/samples", files={"file": (path.name, fp, "audio/wav")}), 200)
                log(f"  sample {path.name}: {quality['verdict']} ({quality['speech_seconds']:.1f} s speech, {quality['mean_dbfs']:.1f} dBFS)")
            profile = api.expect(api.client.get(f"/api/v1/voice-profiles/{profile['id']}"), 200)
            if profile["state"] != "enrolled":
                raise Failed(f"{name} not enrolled: {profile}")
            profiles[voice_key] = profile
        log(f"enrolled: {', '.join(f'{p['person_name']} ({p['total_sample_seconds']:.0f} s)' for p in profiles.values())}")

        # 3. rematch from cached embeddings and confirm ONLY David's cluster
        speakers = api.expect(api.client.post(f"/api/v1/meetings/{meeting_id}/speakers/rematch"), 200)
        for card in speakers["clusters"]:
            log(f"  {card['cluster_id']} {card['state']} speech={card['total_speech_seconds']:.1f}s turns={card['turn_count']} "
                f"suggested={card['suggested_name']} band={card['match_band']} blocking={card['blocking_reasons']}")
        david_cards = [c for c in speakers["clusters"] if c["suggested_name"] == NAMES["david"] and not c["blocking_reasons"]]
        if not david_cards:
            raise Failed("no confirmable cluster was suggested as David Voice")
        david_card = max(david_cards, key=lambda c: c["total_speech_seconds"])
        if any(c["suggested_name"] == NAMES["zira"] for c in speakers["clusters"]) is False:
            log("WARNING: no cluster was suggested as Zira Voice")
        confirmed = api.expect(api.client.post(
            f"/api/v1/meetings/{meeting_id}/speakers/{david_card['cluster_id']}/confirm",
            json={"action": "confirm", "profile_id": profiles["david"]["id"], "expected_revision": speakers["current_revision"],
                  "reviewer_name": "E2E Reviewer", "reviewer_role": "Reviewer"},
        ), 200)
        log(f"confirmed {confirmed['cluster_id']} as {confirmed['confirmed_name']} for Rev.{confirmed['confirmed_for_revision']}: "
            f"{confirmed['printable_turns']} printable, {confirmed['unprintable_turns']} unprintable turns")

        # 4. transcript invariants after confirmation
        transcript = api.expect(api.client.get(f"/api/v1/meetings/{meeting_id}/transcript/"), 200)
        floor = 2.0
        for seg in transcript["segments"]:
            if seg["cluster_id"] == david_card["cluster_id"]:
                if seg["attribution_state"] != "confirmed":
                    raise Failed(f"segment {seg['id']} in the confirmed cluster is {seg['attribution_state']}")
                expect_printable = (seg.get("speech_seconds") or 0.0) >= floor
                if seg["printable_name"] != expect_printable:
                    raise Failed(f"segment {seg['id']} speech={seg.get('speech_seconds')} printable={seg['printable_name']}")
                expected_display = NAMES["david"] if expect_printable else seg["speaker"]
                if seg["display_speaker"] != expected_display:
                    raise Failed(f"segment {seg['id']} display_speaker={seg['display_speaker']} expected {expected_display}")
            elif seg["attribution_state"] in ("confirmed", "corrected"):
                raise Failed(f"segment {seg['id']} outside the confirmed cluster is {seg['attribution_state']}")
            if seg["speaker"] != seg["speaker"].strip() or not re.match(r"^Speaker \d+$", seg["speaker"]):
                raise Failed(f"anonymous label changed: {seg['speaker']!r}")

        # 5. documents
        pdf_bytes = api.client.get(f"/api/v1/meetings/{meeting_id}/export/pdf").content
        docx_bytes = api.client.get(f"/api/v1/meetings/{meeting_id}/export/docx").content
        (work / "final.pdf").write_bytes(pdf_bytes)
        (work / "final.docx").write_bytes(docx_bytes)
        text_docx = docx_text(docx_bytes)
        text_pdf = pdf_text(pdf_bytes)
        log(f"PDF {len(pdf_bytes)} bytes ({len(text_pdf)} chars extracted), DOCX {len(docx_bytes)} bytes")
        failures = []
        for label, text in (("DOCX", text_docx), ("PDF", text_pdf)):
            if label == "PDF" and len(text) < 200:
                log("WARNING: PDF text extraction yielded too little text; relying on the DOCX for the content checks")
                continue
            if not all(marker in text for marker in LEGEND_MARKERS):
                failures.append(f"{label}: attribution legend missing")
            if NAMES["david"] not in text:
                failures.append(f"{label}: confirmed name {NAMES['david']!r} missing")
            if NAMES["zira"] in text:
                failures.append(f"{label}: unconfirmed name {NAMES['zira']!r} printed")
            if "Vorbitor" not in text:
                failures.append(f"{label}: no anonymous 'Vorbitor N' label for the unconfirmed voice")
            for forbidden in ("Similarity", "cosine", "moderate", "strong", "weak"):
                if re.search(rf"\b{forbidden}\b", text):
                    failures.append(f"{label}: suggestion/score wording {forbidden!r} leaked into the document")
        if failures:
            raise Failed("; ".join(failures))
        deliveries = api.expect(api.client.get(f"/api/v1/meetings/{meeting_id}/deliveries"), 200)
        if deliveries:
            raise Failed(f"a delivery record exists on a supervised run: {deliveries}")
        log("PASS: legend printed, confirmed name present, unconfirmed name absent, short turns anonymous, nothing delivered")
        return 0
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
        if args.keep:
            log(f"kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


def selftest_pdf(path: Path) -> int:
    text = pdf_text(path.read_bytes())
    print(f"[pdf-selftest] {path}: {len(text)} chars")
    print(text[:1200])
    return 0 if len(text) >= 200 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keep", action="store_true", help="keep the isolated storage root and API log")
    parser.add_argument("--port", type=int, default=0, help="API port (default: a free one)")
    parser.add_argument("--timeout-min", type=float, default=20.0, help="pipeline wall-clock budget")
    parser.add_argument("--selftest-pdf", type=Path, default=None, help="only run the PDF text extractor on a file (no GPU)")
    args = parser.parse_args()
    if args.selftest_pdf:
        return selftest_pdf(args.selftest_pdf)
    try:
        return run(args)
    except Refused as exc:
        log(f"REFUSED: {exc}")
        return 2
    except Failed as exc:
        log(f"FAIL: {exc}")
        return 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    sys.exit(main())
