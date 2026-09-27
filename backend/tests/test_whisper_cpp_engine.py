"""Offline contract tests for the local whisper.cpp CLI adapter.

The CLI itself is intentionally replaced only at the process boundary: these
tests exercise our argument construction, JSON validation and conversion to
the application's TranscriptSegment model without loading a model or audio.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


_ROOT = Path(tempfile.mkdtemp(prefix="medpark_test_whisper_cpp_"))
_REPO_ROOT = Path(__file__).resolve().parents[2]
os.environ["DATA_DIR"] = str(_ROOT / "data")
os.environ["UPLOADS_DIR"] = str(_ROOT / "uploads")
os.environ["EXPORTS_DIR"] = str(_ROOT / "exports")
os.environ["FIXTURES_DIR"] = str(_ROOT / "fixtures")
os.environ["VOICEPRINTS_DIR"] = str(_ROOT / "voiceprints")
os.environ["MODELS_DIR"] = str(_ROOT / "models")
sys.path.insert(0, str(_REPO_ROOT / "backend"))

from app.core.exceptions import ASREngineError  # noqa: E402
from app.services.asr.whisper_cpp_engine import WhisperCppEngine  # noqa: E402


def _files(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    binary = tmp_path / "whisper-cli"
    model = tmp_path / "ggml-large-v3-turbo.bin"
    vad = tmp_path / "ggml-silero-v6.2.0.bin"
    audio = tmp_path / "meeting.wav"
    for path in (binary, model, vad, audio):
        path.touch()
    binary.chmod(0o755)
    return binary, model, vad, audio


def _full_json(*, text: str = " Aprobăm CT-ul pe 12 octombrie.") -> dict:
    return {
        "result": {"language": "ro"},
        "transcription": [
            {
                "offsets": {"from": 120, "to": 2560},
                "text": text,
                "tokens": [
                    {"text": "[_BEG_]", "p": 0.99},
                    {"text": " Aprobăm", "p": 0.9},
                    {"text": " CT", "p": 0.8},
                ],
            }
        ],
    }


def _write_cli_json(command: list[str], payload: dict) -> None:
    output_base = Path(command[command.index("--output-file") + 1])
    output_base.with_suffix(".json").write_text(json.dumps(payload), encoding="utf-8")


class _CompletedProcess:
    returncode = 0

    def communicate(self, timeout: int):
        return "", ""


def test_transcribe_uses_local_vad_json_and_safe_decoder_options(tmp_path: Path):
    """Removing a local-input, VAD, JSON, or no-context CLI option breaks the adapter contract."""
    binary, model, vad, audio = _files(tmp_path)
    engine = WhisperCppEngine(binary, model, vad, threads=6, use_gpu=False)

    def fake_popen(command, **kwargs):
        _write_cli_json(command, _full_json())
        return _CompletedProcess()

    with patch("app.services.asr.whisper_cpp_engine.subprocess.Popen", side_effect=fake_popen) as run:
        segments = engine.transcribe(audio, initial_prompt="Medpark glossary", language=None)

    command = run.call_args.args[0]
    assert command[0] == str(binary)
    assert command[command.index("--model") + 1] == str(model)
    assert command[command.index("--vad-model") + 1] == str(vad)
    assert command[command.index("--file") + 1] == str(audio)
    assert command[command.index("--threads") + 1] == "6"
    assert command[command.index("--language") + 1] == "auto"
    assert command[command.index("--prompt") + 1] == "Medpark glossary"
    assert "--vad" in command
    assert "--output-json-full" in command
    assert command[command.index("--max-context") + 1] == "0"
    assert "--translate" not in command
    assert "--no-gpu" in command
    assert run.call_args.kwargs["start_new_session"] is True
    assert segments[0].start == 0.12
    assert segments[0].end == 2.56
    assert segments[0].raw_text == "Aprobăm CT-ul pe 12 octombrie."
    assert segments[0].raw_text_origin == "decoder"
    assert segments[0].display_text == "Aprobăm CT-ul pe 12 octombrie."
    assert segments[0].language == "ro"
    assert segments[0].speaker == "Speaker 1"
    assert segments[0].confidence == 0.85
    assert segments[0].is_flagged is True
    assert segments[0].flag_reason == "Contains numerical values/dates requiring verification"


def test_transcribe_rejects_non_monotonic_or_non_finite_offsets(tmp_path: Path):
    """Accepting malformed timestamp offsets would let corrupted CLI output enter the transcript."""
    binary, model, vad, audio = _files(tmp_path)
    engine = WhisperCppEngine(binary, model, vad)
    payload = _full_json()
    payload["transcription"].append(
        {"offsets": {"from": 2500, "to": float("inf")}, "text": " următorul segment", "tokens": []}
    )

    def fake_popen(command, **kwargs):
        _write_cli_json(command, payload)
        return _CompletedProcess()

    with patch("app.services.asr.whisper_cpp_engine.subprocess.Popen", side_effect=fake_popen):
        try:
            engine.transcribe(audio)
        except ASREngineError as exc:
            assert "timestamp" in str(exc).lower()
        else:
            raise AssertionError("non-finite CLI timestamps must be rejected")


def test_transcribe_flags_unknown_token_confidence(tmp_path: Path):
    """Dropping full-JSON token probabilities must produce a conservative reviewer flag."""
    binary, model, vad, audio = _files(tmp_path)
    engine = WhisperCppEngine(binary, model, vad)
    payload = _full_json(text="Discutăm protocolul.")
    del payload["transcription"][0]["tokens"]

    def fake_popen(command, **kwargs):
        _write_cli_json(command, payload)
        return _CompletedProcess()

    with patch("app.services.asr.whisper_cpp_engine.subprocess.Popen", side_effect=fake_popen):
        segments = engine.transcribe(audio)

    assert segments[0].confidence == 0.0
    assert segments[0].is_flagged is True
    assert segments[0].flag_reason == "ASR confidence unavailable"


def test_transcribe_rejects_missing_runtime_assets_and_timeout(tmp_path: Path):
    """Missing local assets or an unbounded CLI process must surface as ASREngineError."""
    binary, model, vad, audio = _files(tmp_path)
    binary.unlink()
    engine = WhisperCppEngine(binary, model, vad, timeout_s=1)

    try:
        engine.transcribe(audio)
    except ASREngineError as exc:
        assert "binary" in str(exc).lower()
    else:
        raise AssertionError("missing CLI binary must be rejected")

    binary.touch()
    binary.chmod(0o755)
    class _TimeoutProcess:
        pid = 12345
        returncode = None
        def communicate(self, timeout: int):
            raise subprocess.TimeoutExpired([str(binary)], timeout)
        def poll(self):
            return None
        def terminate(self):
            pass
        def wait(self, timeout=None):
            pass
        def kill(self):
            pass

    with patch(
        "app.services.asr.whisper_cpp_engine.subprocess.Popen",
        return_value=_TimeoutProcess(),
    ):
        try:
            engine.transcribe(audio)
        except ASREngineError as exc:
            assert "timed out" in str(exc).lower()
        else:
            raise AssertionError("CLI timeout must be surfaced")


def test_release_model_is_noop_and_device_reports_actual_mode(tmp_path: Path):
    """The one-shot CLI owns its process lifetime, so release must not claim cached-model behavior."""
    binary, model, vad, _ = _files(tmp_path)
    assert WhisperCppEngine(binary, model, vad, use_gpu=True).device == "metal"
    cpu_engine = WhisperCppEngine(binary, model, vad, use_gpu=False)
    assert cpu_engine.device == "cpu"
    assert cpu_engine.release_model() is None


if __name__ == "__main__":
    for test in (
        test_transcribe_uses_local_vad_json_and_safe_decoder_options,
        test_transcribe_rejects_non_monotonic_or_non_finite_offsets,
        test_transcribe_flags_unknown_token_confidence,
        test_transcribe_rejects_missing_runtime_assets_and_timeout,
        test_release_model_is_noop_and_device_reports_actual_mode,
    ):
        with tempfile.TemporaryDirectory(prefix="medpark_test_whisper_cpp_case_") as directory:
            test(Path(directory))
    print("whisper.cpp adapter tests passed")
