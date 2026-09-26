"""Tests for ASR provider selection, factory instantiation, and /ready integration."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

_ROOT = Path(tempfile.mkdtemp(prefix="medpark_test_asr_factory_"))
_REPO_ROOT = Path(__file__).resolve().parents[2]
os.environ.update(
    {
        "DATA_DIR": str(_ROOT / "data"),
        "UPLOADS_DIR": str(_ROOT / "uploads"),
        "EXPORTS_DIR": str(_ROOT / "exports"),
        "FIXTURES_DIR": str(_ROOT / "fixtures"),
        "VOICEPRINTS_DIR": str(_ROOT / "voiceprints"),
        "MODELS_DIR": str(_ROOT / "models"),
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
sys.path.insert(0, str(_REPO_ROOT / "backend"))

from app.core.config import settings
from app.services.asr import get_asr_engine
from app.services.asr.remote_engine import RemoteASREngine
from app.services.asr.whisper_cpp_engine import WhisperCppEngine
from app.services.asr.whisper_engine import FasterWhisperEngine


class ASREngineSelectionTests(unittest.TestCase):
    def test_factory_returns_whisper_cpp_engine(self):
        with patch.object(settings, "ASR_PROVIDER", "whisper_cpp"):
            engine = get_asr_engine()
            self.assertIsInstance(engine, WhisperCppEngine)
            self.assertEqual(engine.device, "metal" if settings.WHISPER_CPP_USE_GPU else "cpu")

    def test_factory_returns_remote_engine(self):
        with patch.object(settings, "ASR_PROVIDER", "remote"), \
             patch.object(settings, "REMOTE_ASR_BASE_URL", "http://192.168.1.100:8001"), \
             patch.object(settings, "REMOTE_ASR_API_KEY", "lan-token"):
            engine = get_asr_engine()
            self.assertIsInstance(engine, RemoteASREngine)
            self.assertEqual(engine._base_url, "http://192.168.1.100:8001")
            self.assertEqual(engine._api_key, "lan-token")

    def test_factory_returns_faster_whisper_engine(self):
        with patch.object(settings, "ASR_PROVIDER", "faster_whisper"):
            engine = get_asr_engine()
            self.assertIsInstance(engine, FasterWhisperEngine)

    def test_ready_endpoint_with_remote_asr_connected(self):
        import asyncio
        from httpx import Response
        from app.main import readiness_check

        mock_response = Response(
            200,
            json={
                "ready": True,
                "engine": "whisper_cpp",
                "model": "ggml-large-v3-turbo.bin",
                "device": "metal",
                "queue_depth": 0,
                "max_pending_jobs": 10,
            },
        )

        with patch.object(settings, "ASR_PROVIDER", "remote"), \
             patch.object(settings, "REMOTE_ASR_BASE_URL", "http://192.168.1.50:8001"), \
             patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
            result = asyncio.run(readiness_check())
            self.assertTrue(result["ready"])
            self.assertEqual(result["asr_service"]["provider"], "remote")
            self.assertTrue(result["asr_service"]["connected"])
            self.assertTrue(result["asr_service"]["ready"])
            self.assertEqual(result["asr_service"]["device"], "metal")

    def test_ready_endpoint_with_remote_asr_down(self):
        import asyncio
        import httpx
        from app.main import readiness_check

        with patch.object(settings, "ASR_PROVIDER", "remote"), \
             patch.object(settings, "REMOTE_ASR_BASE_URL", "http://192.168.1.50:8001"), \
             patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=httpx.ConnectError("Connection refused")):
            result = asyncio.run(readiness_check())
            self.assertFalse(result["ready"])
            self.assertEqual(result["asr_service"]["provider"], "remote")
            self.assertFalse(result["asr_service"]["connected"])
            self.assertFalse(result["asr_service"]["ready"])
            self.assertIn("error", result["asr_service"])


if __name__ == "__main__":
    unittest.main()
