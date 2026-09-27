"""Local, one-shot whisper.cpp ASR adapter for Apple Metal or CPU execution."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import threading
from typing import Any, Optional

from app.core.config import settings
from app.core.exceptions import ASREngineError
from app.models.transcript import Correction, TranscriptSegment
from app.services.asr.base import BaseASREngine
from app.services.asr.dynamic_context import ASRContext
from app.services.asr.dialect_adapter import normalize_dialect
from app.services.asr.glossary import MEDPARK_MEDICAL_VOCABULARY, build_code_switch_prompt
from app.services.asr.lexicon import correct_segment
from app.services.asr.text_lid import detect_text_language


def _dtw_preset_for_model(model_name: str) -> Optional[str]:
    lower = model_name.lower()
    if "turbo" in lower:
        return "large.v3.turbo"
    if "large" in lower:
        return "large.v3"
    if "medium" in lower:
        return "medium"
    if "small" in lower:
        return "small"
    if "base" in lower:
        return "base"
    if "tiny" in lower:
        return "tiny"
    return None


CRITICAL_REVIEW_TERM_PATTERNS = tuple(
    (term, re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE))
    for term in MEDPARK_MEDICAL_VOCABULARY[:20]
)
_CANCEL_WAIT_S = 5


class WhisperCppEngine(BaseASREngine):
    """Runs the local ``whisper-cli`` once per request and reads its full JSON output."""

    def __init__(
        self,
        binary_path: Path | str,
        model_path: Path | str,
        vad_model_path: Path | str,
        threads: int = 4,
        timeout_s: int = 1800,
        use_gpu: bool = True,
    ) -> None:
        if threads < 1:
            raise ValueError("threads must be at least 1")
        if timeout_s < 1:
            raise ValueError("timeout_s must be at least 1")
        self.binary_path = Path(binary_path)
        self.model_path = Path(model_path)
        self.vad_model_path = Path(vad_model_path)
        self.threads = threads
        self.timeout_s = timeout_s
        self.use_gpu = use_gpu
        self.device = "metal" if use_gpu else "cpu"
        self.model_name = self.model_path.name
        self._process_lock = threading.Lock()
        self._active_process: subprocess.Popen[str] | None = None

    def is_available(self) -> bool:
        """Whether the executable and both local inference assets are available without loading them."""
        return self.binary_path.is_file() and os.access(self.binary_path, os.X_OK) and self.model_path.is_file() and self.vad_model_path.is_file()

    def health(self) -> dict[str, str | bool]:
        """Minimal readiness provenance for the speech service health endpoint."""
        return {
            "ready": self.is_available(),
            "engine": "whisper_cpp",
            "model": self.model_name,
            "device": self.device,
        }

    def release_model(self) -> None:
        """No-op: whisper.cpp runs in a child process that exits after each transcription."""
        return None

    def cancel(self) -> None:
        """Terminate the active CLI process group, then bound the wait for shutdown callers."""
        with self._process_lock:
            process = self._active_process
        if process is None or process.poll() is not None:
            return
        self._terminate_process(process)

    def transcribe(
        self,
        audio_path: Path,
        initial_prompt: Optional[str] = None,
        language: Optional[str] = None,
        *,
        context: Optional[ASRContext] = None,
    ) -> list[TranscriptSegment]:
        audio_path = Path(audio_path)
        self._assert_local_assets(audio_path)
        prompt = (context.prompt_seed if context and context.prompt_seed else None) or initial_prompt or build_code_switch_prompt()

        with tempfile.TemporaryDirectory(prefix="medora_whisper_cpp_") as temporary_directory:
            output_base = Path(temporary_directory) / "transcript"
            command = self._command(audio_path, output_base, prompt, language)
            try:
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    start_new_session=True,
                )
            except OSError as exc:
                raise ASREngineError("Unable to start local whisper.cpp CLI") from exc

            with self._process_lock:
                self._active_process = process
            try:
                process.communicate(timeout=self.timeout_s)
            except subprocess.TimeoutExpired as exc:
                self._terminate_process(process)
                raise ASREngineError("Local whisper.cpp transcription timed out") from exc
            finally:
                with self._process_lock:
                    if self._active_process is process:
                        self._active_process = None

            if process.returncode != 0:
                raise ASREngineError(f"Local whisper.cpp CLI exited with status {process.returncode}")

            output_path = output_base.with_suffix(".json")
            try:
                raw_output = output_path.read_text(encoding="utf-8")
                payload = json.loads(raw_output)
            except (OSError, json.JSONDecodeError) as exc:
                raise ASREngineError("Local whisper.cpp CLI did not produce valid JSON output") from exc
            return self._parse_segments(payload)

    def _assert_local_assets(self, audio_path: Path) -> None:
        if not audio_path.is_file():
            raise ASREngineError("ASR audio input file is missing")
        if not self.binary_path.is_file() or not os.access(self.binary_path, os.X_OK):
            raise ASREngineError("Local whisper.cpp binary is missing or not executable")
        if not self.model_path.is_file():
            raise ASREngineError("Local whisper.cpp model is missing")
        if not self.vad_model_path.is_file():
            raise ASREngineError("Local whisper.cpp VAD model is missing")

    def _command(self, audio_path: Path, output_base: Path, prompt: str, language: Optional[str]) -> list[str]:
        command = [
            str(self.binary_path),
            "--model",
            str(self.model_path),
            "--file",
            str(audio_path),
            "--threads",
            str(self.threads),
            "--language",
            language or "auto",
            "--prompt",
            prompt,
            "--max-context",
            "0",
            "--no-fallback",
            "--vad",
            "--vad-model",
            str(self.vad_model_path),
            "--output-json-full",
            "--output-file",
            str(output_base),
            "--no-prints",
        ]
        dtw_preset = _dtw_preset_for_model(self.model_path.name)
        if dtw_preset:
            command.extend(["--dtw", dtw_preset])
        if not self.use_gpu:
            command.append("--no-gpu")
        return command

    def _terminate_process(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (AttributeError, OSError):
            process.terminate()
        try:
            process.wait(timeout=_CANCEL_WAIT_S)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (AttributeError, OSError):
                process.kill()
            try:
                process.wait(timeout=_CANCEL_WAIT_S)
            except subprocess.TimeoutExpired:
                pass

    def _parse_segments(self, payload: Any) -> list[TranscriptSegment]:
        if not isinstance(payload, dict):
            raise ASREngineError("Local whisper.cpp JSON output must be an object")
        result = payload.get("result")
        transcription = payload.get("transcription")
        if not isinstance(result, dict) or not isinstance(result.get("language"), str) or not result["language"].strip():
            raise ASREngineError("Local whisper.cpp JSON output has no detected language")
        if not isinstance(transcription, list):
            raise ASREngineError("Local whisper.cpp JSON output has no transcription segments")

        language = result["language"].strip()
        previous_start = -1.0
        segments: list[TranscriptSegment] = []
        for index, item in enumerate(transcription):
            if not isinstance(item, dict):
                raise ASREngineError(f"Local whisper.cpp segment {index} is malformed")
            text = item.get("text")
            if not isinstance(text, str):
                raise ASREngineError(f"Local whisper.cpp segment {index} has invalid text")
            text = text.strip()
            if not text:
                continue
            offsets = item.get("offsets")
            if not isinstance(offsets, dict):
                raise ASREngineError(f"Local whisper.cpp segment {index} has invalid timestamps")
            start = self._timestamp_seconds(offsets.get("from"), index)
            end = self._timestamp_seconds(offsets.get("to"), index)
            if end <= start or start < previous_start:
                raise ASREngineError(f"Local whisper.cpp segment {index} has out-of-order timestamps")
            previous_start = start
            confidence, average_log_probability = self._confidence(item.get("tokens"), index)

            # Multilingual script & language verification (prevents transliterated Romanian or mistranslations)
            text_lid = detect_text_language(text)
            seg_language = language
            lang_source = "acoustic"
            lang_conf = 1.0 if seg_language != "und" else 0.0
            if text_lid.is_concrete and text_lid.confidence >= 0.70 and text_lid.language != language:
                seg_language = text_lid.language
                lang_source = "text"
                lang_conf = text_lid.confidence

            # Clinical lexicon & dialect post-processing (recovers near-miss proper nouns, abbreviations, regional terms)
            raw_decoder_text = text
            text_to_normalize = raw_decoder_text
            all_corrections: list[Correction] = []
            normalization_version: Optional[str] = None

            if settings.ASR_LEXICON_ENABLED and seg_language in ("ro", "ru", "en"):
                cleaned_text, raw_corrections = correct_segment(text_to_normalize, seg_language)
                if cleaned_text != text_to_normalize:
                    text_to_normalize = cleaned_text
                    all_corrections.extend([Correction(was=c["was"], now=c["now"], score=c["score"]) for c in raw_corrections])
                    normalization_version = "lexicon_v1"

            dialect_res = normalize_dialect(text_to_normalize, seg_language)
            if dialect_res.text != text_to_normalize:
                text_to_normalize = dialect_res.text
                all_corrections.extend([Correction(was=c["was"], now=c["now"], score=c["score"]) for c in dialect_res.corrections])
                normalization_version = (
                    f"{normalization_version}+dialect_v1" if normalization_version else "dialect_v1"
                )

            normalized_text = text_to_normalize if text_to_normalize != raw_decoder_text else None
            corrections = all_corrections

            is_flagged, flag_reason = self._check_review_flags(text_to_normalize, average_log_probability)
            if average_log_probability is None:
                is_flagged = True
                flag_reason = "ASR confidence unavailable"
            segments.append(
                TranscriptSegment(
                    start=round(start, 3),
                    end=round(end, 3),
                    speaker="Speaker 1",
                    raw_text=raw_decoder_text,
                    normalized_text=normalized_text,
                    raw_text_origin="decoder",
                    normalization_version=normalization_version,
                    language=seg_language,
                    confidence=round(confidence, 2),
                    language_confidence=round(lang_conf, 2),
                    language_source=lang_source,
                    corrections=corrections,
                    asr_avg_logprob=average_log_probability,
                    is_flagged=is_flagged,
                    flag_reason=flag_reason,
                )
            )
        return segments

    @staticmethod
    def _timestamp_seconds(value: Any, index: int) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ASREngineError(f"Local whisper.cpp segment {index} has invalid timestamp offsets")
        return float(value) / 1000.0

    @staticmethod
    def _confidence(tokens: Any, index: int) -> tuple[float, float | None]:
        if tokens is None:
            return 0.0, None
        if not isinstance(tokens, list):
            raise ASREngineError(f"Local whisper.cpp segment {index} has invalid token data")
        probabilities: list[float] = []
        for token in tokens:
            if not isinstance(token, dict):
                raise ASREngineError(f"Local whisper.cpp segment {index} has invalid token data")
            token_text = token.get("text")
            probability = token.get("p")
            if not isinstance(token_text, str):
                raise ASREngineError(f"Local whisper.cpp segment {index} has invalid token data")
            if token_text.startswith("[") and token_text.endswith("]"):
                continue
            if isinstance(probability, bool) or not isinstance(probability, (int, float)) or not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
                raise ASREngineError(f"Local whisper.cpp segment {index} has invalid token probability")
            probabilities.append(float(probability))
        if not probabilities:
            return 0.0, None
        return sum(probabilities) / len(probabilities), sum(math.log(probability) for probability in probabilities if probability > 0) / len(probabilities) if all(probability > 0 for probability in probabilities) else float("-inf")

    @staticmethod
    def _check_review_flags(text: str, average_log_probability: float | None) -> tuple[bool, str | None]:
        if average_log_probability is not None and average_log_probability < -1.1:
            return True, "Low acoustic confidence / unclear speech"
        if any(char.isdigit() for char in text):
            return True, "Contains numerical values/dates requiring verification"
        for term, pattern in CRITICAL_REVIEW_TERM_PATTERNS:
            if pattern.search(text):
                return True, f"Contains critical medical term: '{term}'"
        return False, None
