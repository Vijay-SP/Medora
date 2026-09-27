"""HTTP client for the queued LAN ASR service.

This module deliberately depends only on ``httpx`` and transcript models: choosing the
remote provider must never import a CUDA or Whisper runtime into the backend process.
"""

from __future__ import annotations

import json
import math
import time
import uuid
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ValidationError

from app.core.exceptions import ASREngineError
from app.models.transcript import TranscriptSegment
from app.services.asr.base import BaseASREngine


_MAX_TIMESTAMP_SECONDS = 24 * 60 * 60


class _Submission(BaseModel):
    job_id: str
    status: Literal["queued", "running"]


class _JobStatus(BaseModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    result: dict[str, Any] | None = None
    error: str | None = None


class _CompletedResult(BaseModel):
    segments: list[TranscriptSegment]
    engine: str
    model: str
    device: str
    duration_seconds: float


class RemoteASREngine(BaseASREngine):
    """Submit normalized WAV audio to one configured, opaque-job ASR origin."""

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        timeout_s: float = 3600,
        poll_interval_s: float = 2,
        request_timeout_s: float = 30,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        parsed = httpx.URL(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.host:
            raise ValueError("Remote ASR base_url must be an absolute http(s) origin")
        if timeout_s <= 0 or poll_interval_s < 0 or request_timeout_s <= 0:
            raise ValueError("Remote ASR timeouts must be positive and poll_interval_s non-negative")

        self._base_url = str(parsed).rstrip("/")
        self._api_key = api_key
        self.timeout_s = timeout_s
        self.poll_interval_s = poll_interval_s
        self.request_timeout_s = request_timeout_s
        self.model_name: str | None = None
        self.device = "remote:unknown"
        self._client = httpx.Client(
            base_url=f"{self._base_url}/",
            timeout=request_timeout_s,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else None,
            transport=transport,
            trust_env=False,
            follow_redirects=False,
        )

    def release_model(self) -> None:
        """The model belongs to the remote worker, so there is nothing to unload locally."""

    def transcribe(
        self,
        audio_path: Path,
        initial_prompt: str | None = None,
        language: str | None = None,
        *,
        context: Any | None = None,
    ) -> list[TranscriptSegment]:
        if not audio_path.is_file():
            raise ASREngineError(f"Audio file does not exist: {audio_path}")
        requested_language = language or "auto"
        if requested_language not in {"auto", "ro", "ru", "en"}:
            raise ASREngineError(f"Unsupported remote ASR language: {requested_language!r}")

        deadline = time.monotonic() + self.timeout_s
        idempotency_key = str(uuid.uuid4())
        job_id = self._submit(audio_path, requested_language, initial_prompt, idempotency_key, context=context)
        return self._poll(job_id, deadline)

    def _submit(
        self,
        audio_path: Path,
        language: str,
        initial_prompt: str | None,
        idempotency_key: str,
        context: Any | None = None,
    ) -> str:
        data: dict[str, Any] = {"language": language}
        if initial_prompt:
            data["initial_prompt"] = initial_prompt
        if context is not None:
            prompt_seed = getattr(context, "prompt_seed", "")
            hotwords = list(getattr(context, "hotwords", []))
            data["context"] = json.dumps({
                "prompt_seed": prompt_seed,
                "hotwords": hotwords,
            })
        try:
            with audio_path.open("rb") as audio:
                response = self._client.post(
                    "v1/asr/jobs",
                    data=data,
                    files={"file": (audio_path.name, audio, "audio/wav")},
                    headers={"Idempotency-Key": idempotency_key},
                )
        except httpx.HTTPError as exc:
            raise ASREngineError(f"Remote ASR submit unavailable: {exc}") from exc
        if response.status_code != 202:
            raise ASREngineError(f"Remote ASR submit failed with HTTP {response.status_code}")
        try:
            submission = _Submission.model_validate(response.json())
            job_id = str(uuid.UUID(submission.job_id))
        except (ValueError, ValidationError) as exc:
            raise ASREngineError("Remote ASR submit returned an invalid job response") from exc
        return job_id

    def _poll(self, job_id: str, deadline: float) -> list[TranscriptSegment]:
        while True:
            if time.monotonic() >= deadline:
                raise ASREngineError(f"Remote ASR job {job_id} timed out")
            try:
                response = self._client.get(f"v1/asr/jobs/{job_id}")
            except httpx.HTTPError as exc:
                raise ASREngineError(f"Remote ASR job {job_id} polling failed: {exc}") from exc
            if response.status_code != 200:
                raise ASREngineError(f"Remote ASR job {job_id} polling failed with HTTP {response.status_code}")
            try:
                job = _JobStatus.model_validate(response.json())
            except (ValueError, ValidationError) as exc:
                raise ASREngineError(f"Remote ASR job {job_id} returned an invalid status response") from exc
            if job.job_id != job_id:
                raise ASREngineError("Remote ASR job response did not match the submitted job")
            if job.status == "failed":
                raise ASREngineError(job.error or f"Remote ASR job {job_id} failed")
            if job.status == "completed":
                return self._validated_segments(job_id, job.result)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ASREngineError(f"Remote ASR job {job_id} timed out")
            if self.poll_interval_s:
                time.sleep(min(self.poll_interval_s, remaining))

    def _validated_segments(self, job_id: str, raw_result: dict[str, Any] | None) -> list[TranscriptSegment]:
        try:
            result = _CompletedResult.model_validate(raw_result)
        except ValidationError as exc:
            raise ASREngineError(f"Remote ASR job {job_id} returned an invalid completed result") from exc
        if (
            not math.isfinite(result.duration_seconds)
            or result.duration_seconds < 0
            or result.duration_seconds > _MAX_TIMESTAMP_SECONDS
        ):
            raise ASREngineError(f"Remote ASR job {job_id} returned an invalid duration")

        previous_start = -1.0
        output: list[TranscriptSegment] = []
        for segment in result.segments:
            if (
                not math.isfinite(segment.start)
                or not math.isfinite(segment.end)
                or segment.start < 0
                or segment.end < segment.start
                or segment.end > result.duration_seconds
                or segment.end > _MAX_TIMESTAMP_SECONDS
                or segment.start < previous_start
            ):
                raise ASREngineError(f"Remote ASR job {job_id} returned invalid segment timestamps")
            previous_start = segment.start
            # The remote service performs ASR, never speaker identification. Do not retain any
            # server-provided identity fields, including legacy metadata generated by model parsing.
            raw_origin = getattr(segment, "raw_text_origin", "legacy_unknown")
            if raw_origin not in ("decoder", "legacy_unknown"):
                raw_origin = "legacy_unknown"

            output.append(
                TranscriptSegment(
                    id=segment.id,
                    start=segment.start,
                    end=segment.end,
                    speaker="Speaker 1",
                    raw_text=segment.raw_text,
                    normalized_text=getattr(segment, "normalized_text", None),
                    raw_text_origin=raw_origin,
                    normalization_version=getattr(segment, "normalization_version", None),
                    language=segment.language,
                    confidence=segment.confidence,
                    is_flagged=segment.is_flagged,
                    flag_reason=segment.flag_reason,
                )
            )

        self.model_name = result.model
        self.device = f"remote:{result.device}"
        return output
