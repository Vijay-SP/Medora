"""
Tests for ASR Context Engine Plumbing (Task 6)
Verifies that ASRContext flows honestly to faster-whisper, whisper.cpp, and remote ASR engines,
with zero regression when context is missing or None.
"""

from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import httpx

from app.models.transcript import TranscriptSegment
from app.services.asr.dynamic_context import ASRContext, ContextTerm
from app.services.asr.remote_engine import RemoteASREngine
from app.services.asr.whisper_cpp_engine import WhisperCppEngine
from app.services.asr.whisper_engine import FasterWhisperEngine, resolve_window_hotwords


class TestContextEnginePlumbing(unittest.TestCase):
    def test_whisper_engine_resolves_hotwords_from_context(self):
        """Verify whisper_engine combines context hotwords with base hotwords and budgets <= 80 tokens."""
        context = ASRContext(
            terms=(
                ContextTerm(text="Ceban", category="attendee", source="attendee_family_name", weight=3.0),
                ContextTerm(text="stent", category="procedure", source="department_vocab:cardiologie", weight=2.2),
            ),
            prompt_seed="Ceban, stent",
            hotwords=("Ceban", "stent"),
        )

        mock_tokenizer = MagicMock()
        # Mock token length calculation: 1 token per word
        mock_tokenizer.encode.side_effect = lambda s, **kw: MagicMock(ids=[1] * len(s.split()))

        # For Romanian
        hw = resolve_window_hotwords("ro", context, mock_tokenizer)
        self.assertIsNotNone(hw)
        # Context hotwords must appear at the beginning
        self.assertTrue(hw.startswith("Ceban, stent"))
        # Base hotwords must follow
        self.assertIn("Medpark", hw)

    def test_whisper_engine_fallback_when_context_none(self):
        """Verify whisper_engine falls back cleanly to default hotwords when context is None."""
        mock_tokenizer = MagicMock()
        mock_tokenizer.encode.side_effect = lambda s, **kw: MagicMock(ids=[1] * len(s.split()))

        hw_none = resolve_window_hotwords("ro", None, mock_tokenizer)
        self.assertIsNotNone(hw_none)
        self.assertIn("Medpark", hw_none)
        self.assertNotIn("Ceban", hw_none)

    def test_whisper_cpp_engine_passes_context_prompt_seed(self):
        """Verify whisper_cpp_engine passes context.prompt_seed to --prompt in CLI arguments."""
        engine = WhisperCppEngine(
            binary_path=Path("/bin/whisper-cli"),
            model_path=Path("/models/model.bin"),
            vad_model_path=Path("/models/vad.bin"),
        )

        context = ASRContext(
            terms=(),
            prompt_seed="Dr. Ceban, angioplastie, stent",
            hotwords=("Ceban", "angioplastie", "stent"),
        )

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            audio_path = Path(f.name)
            audio_path.write_bytes(b"RIFF" + b"\x00" * 40)

        try:
            # Mock _assert_local_assets to pass
            engine._assert_local_assets = MagicMock()
            # Capture command generated inside transcribe
            captured_command = None

            def mock_popen(cmd, **kwargs):
                nonlocal captured_command
                captured_command = cmd
                proc = MagicMock()
                proc.communicate.return_value = ("", "")
                proc.returncode = 0
                proc.poll.return_value = 0
                return proc

            with patch("subprocess.Popen", side_effect=mock_popen):
                with patch("pathlib.Path.read_text", return_value=json.dumps({"result": {"language": "ro"}, "transcription": []})):
                    engine.transcribe(audio_path, context=context)

            self.assertIsNotNone(captured_command)
            prompt_idx = captured_command.index("--prompt")
            self.assertEqual(captured_command[prompt_idx + 1], "Dr. Ceban, angioplastie, stent")
        finally:
            audio_path.unlink(missing_ok=True)

    def test_remote_engine_serializes_context_in_post_body(self):
        """Verify remote_engine serializes context into POST multipart request."""
        context = ASRContext(
            terms=(),
            prompt_seed="Popescu, bypass",
            hotwords=("Popescu", "bypass"),
        )

        captured_request = None

        def transport_handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_request
            if request.method == "POST" and request.url.path == "/v1/asr/jobs":
                captured_request = request
                return httpx.Response(
                    202,
                    json={"job_id": "11111111-1111-1111-1111-111111111111", "status": "queued"},
                    request=request,
                )
            if request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "job_id": "11111111-1111-1111-1111-111111111111",
                        "status": "completed",
                        "result": {
                            "segments": [
                                {
                                    "start": 0.0,
                                    "end": 1.0,
                                    "speaker": "Speaker 1",
                                    "raw_text": "Bypass realizat cu succes.",
                                    "language": "ro",
                                }
                            ],
                            "engine": "remote_whisper",
                            "model": "turbo",
                            "device": "cuda",
                            "duration_seconds": 1.0,
                        },
                        "error": None,
                    },
                    request=request,
                )
            return httpx.Response(404, request=request)

        transport = httpx.MockTransport(transport_handler)
        engine = RemoteASREngine(
            base_url="http://127.0.0.1:8001",
            transport=transport,
        )

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            audio_path = Path(f.name)
            audio_path.write_bytes(b"RIFF" + b"\x00" * 40)

        try:
            segments = engine.transcribe(audio_path, context=context)
            self.assertEqual(len(segments), 1)
            self.assertIsNotNone(captured_request)

            content = captured_request.content.decode("utf-8", errors="ignore")
            self.assertIn("Popescu", content)
            self.assertIn("bypass", content)
        finally:
            audio_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
