"""Contract tests for the LAN remote ASR client.

Run with:
    PYTHONPATH=backend /private/tmp/medpark-llm-check/bin/python backend/tests/test_remote_asr_engine.py

The test transport is in-process; it never opens a network connection or loads an ASR model.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


_ROOT = Path(tempfile.mkdtemp(prefix="medpark_test_remote_asr_"))
_REPO_ROOT = Path(__file__).resolve().parents[2]
os.environ.update(
    {
        "DATA_DIR": str(_ROOT / "data"),
        "UPLOADS_DIR": str(_ROOT / "uploads"),
        "EXPORTS_DIR": str(_ROOT / "exports"),
        "FIXTURES_DIR": str(_ROOT / "fixtures"),
        "VOICEPRINTS_DIR": str(_ROOT / "voiceprints"),
        "MODELS_DIR": str(_REPO_ROOT / "data" / "models"),
        "SMTP_HOST": "127.0.0.1",
        "SMTP_PORT": "9",
        "ALLOW_SIMULATED_DELIVERY": "false",
        "REQUIRE_LOCAL_LLM": "false",
        "LLM_API_BASE_URL": "http://127.0.0.1:9",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
    }
)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

try:  # Keep the initial red test an assertion failure while the client does not exist.
    from app.services.asr.remote_engine import RemoteASREngine  # noqa: E402
except ImportError:
    RemoteASREngine = None


JOB_ID = "6eeeadba-1243-4d21-8658-dfbcd9193cf8"


def _audio_file() -> Path:
    path = _ROOT / "normalized.wav"
    path.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt ")
    return path


class RemoteASREngineTests(unittest.TestCase):
    def test_polls_opaque_job_until_completed_and_returns_anonymous_segments(self) -> None:
        """Removing queued-job polling or anonymous segment conversion breaks remote transcription."""
        self.assertIsNotNone(RemoteASREngine, "RemoteASREngine must implement the remote ASR contract")
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(f"{request.method} {request.url.path}")
            if request.method == "POST":
                self.assertEqual(request.url.path, "/v1/asr/jobs")
                self.assertEqual(request.headers.get("authorization"), "Bearer test-key")
                self.assertIn(b'name="language"\r\n\r\nauto', request.content)
                self.assertIn(b'name="initial_prompt"\r\n\r\nclinic prompt', request.content)
                return httpx.Response(
                    202,
                    json={"job_id": JOB_ID, "status": "queued", "status_url": "http://untrusted.invalid/steal"},
                    request=request,
                )
            if len(calls) == 2:
                return httpx.Response(200, json={"job_id": JOB_ID, "status": "queued", "result": None, "error": None}, request=request)
            if len(calls) == 3:
                return httpx.Response(200, json={"job_id": JOB_ID, "status": "running", "result": None, "error": None}, request=request)
            return httpx.Response(
                200,
                json={
                    "job_id": JOB_ID,
                    "status": "completed",
                    "result": {
                        "segments": [
                            {
                                "id": "server-segment",
                                "start": 0.0,
                                "end": 1.25,
                                "speaker": "Dr. Untrusted Name",
                                "raw_text": "Bună ziua.",
                                "language": "ro",
                                "confidence": 0.9,
                            }
                        ],
                        "engine": "whisper_cpp",
                        "model": "large-v3-turbo",
                        "device": "metal",
                        "duration_seconds": 1.25,
                    },
                    "error": None,
                },
                request=request,
            )

        engine = RemoteASREngine(
            "http://speech.local",
            api_key="test-key",
            poll_interval_s=0,
            transport=httpx.MockTransport(handler),
        )
        segments = engine.transcribe(_audio_file(), initial_prompt="clinic prompt")

        self.assertEqual(calls, ["POST /v1/asr/jobs", f"GET /v1/asr/jobs/{JOB_ID}", f"GET /v1/asr/jobs/{JOB_ID}", f"GET /v1/asr/jobs/{JOB_ID}"])
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].speaker, "Speaker 1")
        self.assertIsNone(segments[0].legacy_speaker_label)
        self.assertEqual(segments[0].raw_text, "Bună ziua.")
        self.assertEqual(engine.model_name, "large-v3-turbo")
        self.assertEqual(engine.device, "remote:metal")


if __name__ == "__main__":
    unittest.main()
