"""
Offline TestClient flow for the people / voice-profile API (V5: /api/v1/voice-profiles).

    PYTHONPATH=backend .venv\\Scripts\\python.exe backend\\tests\\test_voice_profiles_api.py

Enrollment samples are rendered with the offline Windows SAPI voice "Microsoft Zira Desktop" (16 kHz mono
PCM16 through System.Speech) so the CPU embedder sees real speech; the test skips cleanly when SAPI or the
ONNX model is unavailable. Storage (including VOICEPRINTS_DIR) is isolated before any app import; the LLM
and SMTP endpoints point at dead ports. No GPU, no Whisper, no Ollama.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_ROOT = Path(tempfile.mkdtemp(prefix="medpark_test_voice_api_"))
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ISOLATION_ENV = {
    "DATA_DIR": str(_ROOT / "data"),
    "UPLOADS_DIR": str(_ROOT / "uploads"),
    "EXPORTS_DIR": str(_ROOT / "exports"),
    "FIXTURES_DIR": str(_ROOT / "fixtures"),
    "VOICEPRINTS_DIR": str(_ROOT / "voiceprints"),
    "SMTP_HOST": "127.0.0.1",
    "SMTP_PORT": "9",
    "ALLOW_SIMULATED_DELIVERY": "false",
    "REQUIRE_LOCAL_LLM": "false",
    "LLM_API_BASE_URL": "http://127.0.0.1:9",
    "WHISPER_DEVICE": "cpu",
    "VOICE_ID_ENABLED": "true",
}
os.environ.update(_ISOLATION_ENV)
os.environ.setdefault("MODELS_DIR", str(_REPO_ROOT / "data" / "models"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import json  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from typing import Optional  # noqa: E402

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.services.diarization.embedder import speaker_embedder  # noqa: E402
from app.storage.repository import repository  # noqa: E402

SR = 16000
VOICE = "Microsoft Zira Desktop"
# Each prompt renders to roughly 14-16 s of speech at SAPI rate 0: above the 10 s "good" threshold on its own,
# and three of them exceed the 20 s enrollment minimum together.
ENROLL_PROMPTS = [
    "My name is Zira and I am recording this sample for voice enrollment in the hospital meeting system. "
    "The recording takes place in a quiet office with the laptop microphone, at the usual distance, "
    "and I am speaking at my normal pace without reading too quickly.",
    "The purpose of this sample is only to recognise my voice in future meetings, never to transcribe it. "
    "I can withdraw this consent at any time and the voiceprint will be deleted together with these recordings, "
    "which is explained on the enrollment screen before I start.",
    "Numbers are useful for enrollment: one, two, three, four, five, six, seven, eight, nine, ten. "
    "Then the days of the week: Monday, Tuesday, Wednesday, Thursday, Friday, Saturday and Sunday, "
    "and finally the months from January to December spoken slowly.",
]
FLOAT_VECTOR = re.compile(r"\[\s*-?\d+\.\d+(?:\s*,\s*-?\d+\.\d+){15,}")
API = "/api/v1/voice-profiles"

_FIXTURE: Optional[dict] = None
_TTS_ERROR: Optional[str] = None


class _Skip(Exception):
    pass


def _skip(reason: str):
    try:
        import pytest

        pytest.skip(reason)
    except ImportError:
        raise _Skip(reason)


def _client():
    from fastapi.testclient import TestClient
    from app.main import app

    return TestClient(app)


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
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"TTS synthesis failed: {proc.stdout[-400:]} {proc.stderr[-400:]}")
    for item in items:
        path = Path(item["path"])
        if not path.is_file() or path.stat().st_size < 1000:
            raise RuntimeError(f"TTS produced no audio for {path}")


def _fixture() -> dict:
    """Three good enrollment samples plus a 1 s clip, a silent clip and a clipped clip; synthesised once."""
    global _FIXTURE, _TTS_ERROR
    if _FIXTURE is not None:
        return _FIXTURE
    if _TTS_ERROR is not None:
        _skip(_TTS_ERROR)
    if not speaker_embedder.available:
        _TTS_ERROR = f"speaker embedder unavailable: {speaker_embedder.load_error}"
        _skip(_TTS_ERROR)
    tts_dir = _ROOT / "tts"
    tts_dir.mkdir(parents=True, exist_ok=True)
    items = [{"voice": VOICE, "text": text, "path": str(tts_dir / f"enroll_{i}.wav")} for i, text in enumerate(ENROLL_PROMPTS)]
    try:
        synthesize(items, tts_dir)
    except Exception as exc:  # noqa: BLE001
        _TTS_ERROR = f"SAPI synthesis unavailable: {exc}"
        _skip(_TTS_ERROR)
    good = [Path(item["path"]) for item in items]
    first, sr = sf.read(str(good[0]), dtype="float32")
    assert sr == SR
    one_second = tts_dir / "one_second.wav"
    sf.write(str(one_second), first[: SR], SR, subtype="PCM_16")
    silent = tts_dir / "silent.wav"
    sf.write(str(silent), np.zeros(SR * 6, dtype=np.float32), SR, subtype="PCM_16")
    clipped = tts_dir / "clipped.wav"
    sf.write(str(clipped), np.clip(first * 40.0, -1.0, 1.0), SR, subtype="PCM_16")
    _FIXTURE = {"good": good, "one_second": one_second, "silent": silent, "clipped": clipped}
    return _FIXTURE


def _upload(client, person_id: str, path: Path, filename: Optional[str] = None):
    with open(path, "rb") as fp:
        return client.post(f"{API}/{person_id}/samples", files={"file": (filename or path.name, fp, "audio/wav")})


def _person_files(person_id: str) -> list[Path]:
    root = Path(settings.VOICEPRINTS_DIR) / "people" / person_id
    return sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []


def _assert_no_vector(payload) -> None:
    text = json.dumps(payload)
    assert not FLOAT_VECTOR.search(text), "an API response carried an embedding vector"
    assert "artifact_path" not in text and "embedding" not in text.replace("embedding_model", "")


def _assert_isolated() -> None:
    assert repository.storage_dir.is_relative_to(_ROOT)
    assert Path(settings.VOICEPRINTS_DIR).is_relative_to(_ROOT)


# ---------------------------------------------------------------- the enrollment flow
def test_enrollment_flow_end_to_end():
    _assert_isolated()
    fx = _fixture()
    with _client() as client:
        # create
        res = client.post(API + "/", json={"person_name": "Dr. Zira Test", "role": "Medic", "email": "zira@example.invalid"})
        assert res.status_code == 201, res.text
        profile = res.json()
        _assert_no_vector(profile)
        person_id = profile["id"]
        assert profile["person_name"] == "Dr. Zira Test" and profile["state"] == "not_enrolled"
        assert profile["sample_count"] == 0 and profile["total_sample_seconds"] == 0.0
        assert profile["consent_given_at"] is None and profile["enrolled_at"] is None
        assert profile["embedding_model"] == "campplus-LM"
        assert client.get(f"{API}/{person_id}").status_code == 200
        assert any(p["id"] == person_id for p in client.get(API + "/").json())

        # samples are refused before consent, and nothing is stored
        res = _upload(client, person_id, fx["good"][0])
        assert res.status_code == 422, res.text
        assert _person_files(person_id) == []

        # consent
        res = client.post(f"{API}/{person_id}/consent", json={"granted": True})
        assert res.status_code == 200, res.text
        assert res.json()["consent_given_at"] is not None and res.json()["state"] == "not_enrolled"

        # a 1 s clip is rejected and stores nothing
        res = _upload(client, person_id, fx["one_second"])
        assert res.status_code == 200, res.text
        quality = res.json()
        assert quality["verdict"] == "reject" and quality["reasons"], quality
        assert quality["speech_seconds"] < settings.SPEAKER_MIN_SAMPLE_SPEECH_S
        assert _person_files(person_id) == []
        # silence and clipping are rejected too
        res = _upload(client, person_id, fx["silent"])
        assert res.status_code == 200 and res.json()["verdict"] == "reject", res.text
        assert res.json()["speech_seconds"] < settings.SPEAKER_MIN_SAMPLE_SPEECH_S
        res = _upload(client, person_id, fx["clipped"])
        assert res.status_code == 200 and res.json()["verdict"] == "reject", res.text
        assert res.json()["clipped_fraction"] > 0.02
        assert _person_files(person_id) == []
        # a wrong container is a 400, not a stored file
        assert _upload(client, person_id, fx["good"][0], filename="notes.txt").status_code == 400
        assert client.get(f"{API}/{person_id}").json()["state"] == "not_enrolled"

        # the first good sample: accepted, stored, but not yet enrolled (< 20 s of speech)
        res = _upload(client, person_id, fx["good"][0])
        assert res.status_code == 200, res.text
        quality = res.json()
        assert quality["verdict"] == "good", quality
        assert quality["speech_seconds"] > 10.0 and -35.0 <= quality["mean_dbfs"] <= -6.0 and quality["clipped_fraction"] <= 0.02
        stored = _person_files(person_id)
        assert any(p.suffix == ".wav" for p in stored), "accepted samples are kept for re-enrollment"
        profile = client.get(f"{API}/{person_id}").json()
        assert profile["sample_count"] == 1 and profile["total_sample_seconds"] > 10.0
        if profile["state"] == "not_enrolled":
            assert profile["quality_warnings"], "the summary must explain what is missing"

        # enough speech across samples -> enrolled
        for path in fx["good"][1:]:
            res = _upload(client, person_id, path)
            assert res.status_code == 200 and res.json()["verdict"] in ("good", "usable"), res.text
        profile = client.get(f"{API}/{person_id}").json()
        _assert_no_vector(profile)
        assert profile["state"] == "enrolled", profile
        assert profile["sample_count"] == 3 and profile["total_sample_seconds"] >= settings.SPEAKER_MIN_ENROLL_SPEECH_S
        assert profile["enrolled_at"] is not None and profile["embedding_model_version"] == speaker_embedder.space_id
        stored = _person_files(person_id)
        assert sum(1 for p in stored if p.suffix == ".npy") == 1 and sum(1 for p in stored if p.suffix == ".wav") == 3

        # status endpoint is truthful
        status = client.get(f"{API}/status").json()
        assert status["enabled"] is True and status["embedder_available"] is True
        assert status["space_id"] == speaker_embedder.space_id and status["model"] == "campplus-LM" and status["dim"] == 512
        assert status["enrolled"] == 1 and status["not_enrolled"] == 0 and status["needs_reenrollment"] == 0

        # no JSON store contains a vector after an enrollment
        for store in sorted(repository.storage_dir.glob("*.json")):
            assert not FLOAT_VECTOR.search(store.read_text(encoding="utf-8")), f"{store.name} contains a float vector"

        # wipe -> not enrolled, files gone
        assert client.delete(f"{API}/{person_id}/samples").status_code == 204
        profile = client.get(f"{API}/{person_id}").json()
        assert profile["state"] == "not_enrolled" and profile["sample_count"] == 0 and profile["total_sample_seconds"] == 0.0
        assert _person_files(person_id) == []
        assert client.get(f"{API}/status").json()["enrolled"] == 0

        # re-enroll one sample, then withdraw consent -> everything purged
        assert _upload(client, person_id, fx["good"][0]).json()["verdict"] == "good"
        assert _person_files(person_id)
        res = client.post(f"{API}/{person_id}/consent", json={"granted": False})
        assert res.status_code == 200, res.text
        assert res.json()["consent_given_at"] is None and res.json()["state"] == "not_enrolled" and res.json()["sample_count"] == 0
        assert _person_files(person_id) == []
        assert _upload(client, person_id, fx["good"][0]).status_code == 422, "withdrawn consent blocks new samples"

        # delete -> row and files gone
        assert client.post(f"{API}/{person_id}/consent", json={"granted": True}).status_code == 200
        assert _upload(client, person_id, fx["good"][1]).json()["verdict"] == "good"
        assert _person_files(person_id)
        assert client.delete(f"{API}/{person_id}").status_code == 204
        assert client.get(f"{API}/{person_id}").status_code == 404
        assert _person_files(person_id) == []
        assert repository.get_person(person_id) is None
        assert client.delete(f"{API}/{person_id}").status_code == 404
        assert client.get(f"{API}/status").json()["enrolled"] == 0


def test_update_voice_profile_metadata():
    _assert_isolated()
    with _client() as client:
        # create
        res = client.post(
            API + "/",
            json={
                "person_name": "Elena Ceban",
                "role": "Consultant",
                "email": "elena.ceban@medpark.md",
                "department": "Cardiology",
                "title": "Dr.",
                "primary_language": "ro",
                "specialty": "Interventional Cardiology",
            },
        )
        assert res.status_code == 201, res.text
        person = res.json()
        person_id = person["id"]
        assert person["person_name"] == "Elena Ceban"
        assert person["role"] == "Consultant"
        assert person["department"] == "Cardiology"

        # update metadata via PUT
        update_res = client.put(
            f"{API}/{person_id}",
            json={
                "person_name": "Prof. Dr. Elena Ceban",
                "role": "Head of Department",
                "email": "elena.ceban.head@medpark.md",
                "department": "Cardiovascular Surgery",
                "title": "Prof. Dr.",
                "primary_language": "ru",
                "specialty": "Advanced Cardiac Surgery",
            },
        )
        assert update_res.status_code == 200, update_res.text
        updated = update_res.json()
        _assert_no_vector(updated)
        assert updated["id"] == person_id
        assert updated["person_name"] == "Prof. Dr. Elena Ceban"
        assert updated["role"] == "Head of Department"
        assert updated["email"] == "elena.ceban.head@medpark.md"
        assert updated["department"] == "Cardiovascular Surgery"
        assert updated["title"] == "Prof. Dr."
        assert updated["primary_language"] == "ru"
        assert updated["specialty"] == "Advanced Cardiac Surgery"

        # verify persistence via GET
        get_res = client.get(f"{API}/{person_id}")
        assert get_res.status_code == 200
        fetched = get_res.json()
        assert fetched["person_name"] == "Prof. Dr. Elena Ceban"
        assert fetched["department"] == "Cardiovascular Surgery"
        assert fetched["primary_language"] == "ru"

        # partial update via PATCH
        patch_res = client.patch(
            f"{API}/{person_id}",
            json={"role": "Chief Surgeon"},
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["role"] == "Chief Surgeon"
        assert patch_res.json()["department"] == "Cardiovascular Surgery"

        # 404 on nonexistent person
        assert client.put(f"{API}/nonexistent-id", json={"person_name": "Nobody"}).status_code == 404


def test_no_endpoint_enrolls_from_meeting_audio():
    """Retro-enrollment is refused by design: the only sample route is the explicit prompted upload."""
    from app.main import app

    # the OpenAPI schema is the version-independent view of the mounted routes (FastAPI 0.141 keeps
    # included routers as lazy _IncludedRouter entries in app.routes)
    paths = app.openapi()["paths"]
    voice_routes = sorted((path, method.upper()) for path, ops in paths.items() if path.startswith(API) for method in ops)
    assert voice_routes, "voice-profile routes are mounted"
    for path, _method in voice_routes:
        assert "meeting" not in path and "cluster" not in path and "segment" not in path, path
    assert (f"{API}/{{person_id}}/samples", "DELETE") in voice_routes
    assert (f"{API}/{{person_id}}/samples", "POST") in voice_routes
    # and no speakers route accepts audio or writes a voiceprint
    speaker_routes = [path for path in paths if "/speakers" in path]
    assert speaker_routes, "speakers routes are mounted"
    assert all("enroll" not in path and "voiceprint" not in path and "sample" not in path for path in speaker_routes)


def test_samples_return_503_when_the_model_file_is_missing():
    """Runs a child interpreter with SPEAKER_EMBEDDER_MODEL_PATH pointing at a missing file."""
    fx = _fixture()
    child_root = Path(tempfile.mkdtemp(prefix="medpark_test_voice_api_503_"))
    env = dict(os.environ)
    env.update({
        "DATA_DIR": str(child_root / "data"),
        "UPLOADS_DIR": str(child_root / "uploads"),
        "EXPORTS_DIR": str(child_root / "exports"),
        "FIXTURES_DIR": str(child_root / "fixtures"),
        "VOICEPRINTS_DIR": str(child_root / "voiceprints"),
        "SPEAKER_EMBEDDER_MODEL_PATH": str(child_root / "missing" / "voxceleb_CAM++_LM.onnx"),
        "PYTHONPATH": str(_REPO_ROOT / "backend"),
        "PYTHONIOENCODING": "utf-8",
    })
    script = child_root / "probe_503.py"
    script.write_text(
        "import json, sys\n"
        "from fastapi.testclient import TestClient\n"
        "from app.main import app\n"
        "from app.services.diarization.embedder import speaker_embedder\n"
        "assert speaker_embedder.available is False, 'the model must be missing in this child'\n"
        "with TestClient(app) as client:\n"
        f"    person = client.post('{API}/', json={{'person_name': 'Dr. No Model', 'role': 'Medic', 'email': ''}}).json()\n"
        f"    assert client.post('{API}/' + person['id'] + '/consent', json={{'granted': True}}).status_code == 200\n"
        f"    with open(sys.argv[1], 'rb') as fp:\n"
        f"        res = client.post('{API}/' + person['id'] + '/samples', files={{'file': ('sample.wav', fp, 'audio/wav')}})\n"
        "    assert res.status_code == 503, (res.status_code, res.text)\n"
        f"    status = client.get('{API}/status').json()\n"
        "    assert status['embedder_available'] is False and status['space_id'] is None, status\n"
        f"    assert client.get('{API}/' + person['id']).json()['state'] == 'not_enrolled'\n"
        "    ready = client.get('/ready').json()['voice_id']\n"
        "    assert ready['enabled'] is False and ready['embedder_available'] is False and 'missing' in ready['reason'], ready\n"
        "print('CHILD_OK', json.dumps(status))\n",
        encoding="utf-8",
    )
    proc = subprocess.run([sys.executable, str(script), str(fx["good"][0])], capture_output=True, text=True, env=env, timeout=300)
    assert proc.returncode == 0 and "CHILD_OK" in proc.stdout, f"stdout: {proc.stdout[-800:]}\nstderr: {proc.stderr[-1500:]}"


if __name__ == "__main__":
    import traceback

    tests = [(n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)]
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
            print("    " + "\n    ".join(traceback.format_exc().strip().splitlines()[-4:]))
    print(f"{len(tests) - failed}/{len(tests)} passed (root: {_ROOT})")
    sys.exit(1 if failed else 0)
