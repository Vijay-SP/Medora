"""FastAPI entrypoint and service configuration for shared Mac ASR."""

from __future__ import annotations

from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path
import shutil
from typing import Any, Optional
import uuid
import wave

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.services.asr.whisper_cpp_engine import WhisperCppEngine
from app.services.speech.queue import SpeechQueue

logger = logging.getLogger(__name__)


class SpeechSettings(BaseModel):
    data_dir: Path
    max_pending_jobs: int = 10
    max_upload_bytes: int = 500_000_000
    api_key: str | None = None
    binary_path: Path = Path("/opt/homebrew/bin/whisper-cli")
    model_path: Path = Path("data/models/whisper.cpp/ggml-large-v3-q5_0.bin")
    vad_model_path: Path = Path("data/models/whisper.cpp/ggml-silero-v6.2.0.bin")
    threads: int = 4
    use_gpu: bool = True
    timeout_s: int = 1800
    host: str = "0.0.0.0"
    port: int = 8001
    job_ttl_seconds: int = 86400

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")


def _is_valid_audio(path: Path) -> tuple[bool, float]:
    """Validate audio header and compute duration if possible."""
    # 1. Check WAV via wave standard library
    try:
        with wave.open(str(path), "rb") as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate()
            duration = frames / float(rate) if rate else 0.0
            return True, duration
    except Exception:
        pass

    # 2. Check FLAC, OGG, MP3 magic bytes
    try:
        with open(str(path), "rb") as f:
            header = f.read(16)
        if header.startswith(b"fLaC") or header.startswith(b"OggS"):
            return True, 0.0
        if header.startswith(b"ID3") or (len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0):
            return True, 0.0
    except Exception:
        pass

    return False, 0.0


def create_app(config: SpeechSettings, engine: Any = None) -> FastAPI:
    config.data_dir = Path(config.data_dir)
    uploads_dir = config.data_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    db_path = config.data_dir / "speech_queue.db"

    if engine is None:
        engine = WhisperCppEngine(
            binary_path=config.binary_path,
            model_path=config.model_path,
            vad_model_path=config.vad_model_path,
            threads=config.threads,
            use_gpu=config.use_gpu,
            timeout_s=config.timeout_s,
        )

    queue = SpeechQueue(
        db_path=db_path,
        uploads_dir=uploads_dir,
        engine=engine,
        max_pending_jobs=config.max_pending_jobs,
        job_ttl_seconds=config.job_ttl_seconds,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        queue.start()
        yield
        queue.stop()

    app = FastAPI(title="Medora Shared Speech Server", version="1.0.0", lifespan=lifespan)
    app.state.config = config
    app.state.engine = engine
    app.state.queue = queue

    # Ensure queue starts even if lifespan is bypassed
    queue.start()

    @app.middleware("http")
    async def check_content_length(request: Request, call_next):
        if request.url.path == "/v1/asr/jobs" and request.method == "POST":
            content_length = request.headers.get("content-length")
            if content_length is not None:
                try:
                    if int(content_length) > config.max_upload_bytes:
                        return JSONResponse(status_code=413, content={"detail": "Payload too large"})
                except ValueError:
                    pass
        return await call_next(request)

    def verify_auth(request: Request) -> None:
        if not config.api_key:
            return
        auth_header = request.headers.get("Authorization")
        if not auth_header or auth_header != f"Bearer {config.api_key}":
            raise HTTPException(status_code=401, detail="Unauthorized")

    @app.get("/health", tags=["System"])
    def health_probe():
        return {"status": "ok", "version": "1.0.0"}

    @app.get("/ready", tags=["System"])
    def readiness_probe(auth: None = Depends(verify_auth)):
        health_info = engine.health() if hasattr(engine, "health") else {}
        is_ready = bool(health_info.get("ready", False))
        return {
            "ready": is_ready,
            "engine": health_info.get("engine", "whisper_cpp"),
            "model": health_info.get("model", ""),
            "device": health_info.get("device", ""),
            "queue_depth": queue.get_queue_depth(),
            "max_pending_jobs": config.max_pending_jobs,
        }

    @app.post("/v1/asr/jobs", status_code=202, tags=["ASR"])
    async def submit_asr_job(
        file: UploadFile = File(...),
        language: Optional[str] = Form(None),
        initial_prompt: Optional[str] = Form(None),
        context: Optional[str] = Form(None),
        idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
        auth: None = Depends(verify_auth),
    ):
        # 1. Engine readiness check
        health_info = engine.health() if hasattr(engine, "health") else {"ready": True}
        if not health_info.get("ready", False):
            raise HTTPException(status_code=503, detail="ASR engine not ready")

        # 2. Idempotency check
        if idempotency_key:
            existing = queue.get_job_by_idempotency_key(idempotency_key)
            if existing is not None:
                return JSONResponse(
                    status_code=202,
                    content={
                        "job_id": existing["job_id"],
                        "status": existing["status"],
                        "status_url": f"/v1/asr/jobs/{existing['job_id']}",
                    },
                )

        # 3. Queue capacity check
        if queue.get_queue_depth() >= config.max_pending_jobs:
            raise HTTPException(status_code=429, detail="ASR job queue is full")

        # 4. Language option validation
        if language is not None and language not in ("auto", "ro", "ru", "en"):
            raise HTTPException(status_code=422, detail=f"Unsupported language: {language}")

        # 5. Staged upload with byte cap enforcement
        staging_id = uuid.uuid4().hex
        staging_path = uploads_dir / f"staging_{staging_id}.wav"
        total_bytes = 0

        try:
            with open(staging_path, "wb") as out_file:
                while chunk := await file.read(65536):
                    total_bytes += len(chunk)
                    if total_bytes > config.max_upload_bytes:
                        raise HTTPException(status_code=413, detail="Payload too large")
                    out_file.write(chunk)
        except Exception:
            staging_path.unlink(missing_ok=True)
            raise

        # 6. Audio format validation
        is_valid, duration = _is_valid_audio(staging_path)
        if not is_valid:
            staging_path.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail="Invalid audio file or unsupported format")

        # 7. Move into permanent job directory
        job_id = str(uuid.uuid4())
        job_dir = uploads_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        final_audio_path = job_dir / "audio.wav"
        shutil.move(str(staging_path), str(final_audio_path))

        # 8. Extract prompt from context if present
        context_prompt_seed = None
        if context:
            try:
                parsed_ctx = json.loads(context)
                if isinstance(parsed_ctx, dict) and parsed_ctx.get("prompt_seed"):
                    context_prompt_seed = parsed_ctx["prompt_seed"]
            except Exception:
                pass

        effective_prompt = initial_prompt or context_prompt_seed

        # 9. Enqueue job
        queue.enqueue_job(
            job_id=job_id,
            audio_path=final_audio_path,
            duration_seconds=duration,
            language=language,
            initial_prompt=effective_prompt,
            idempotency_key=idempotency_key,
        )

        return JSONResponse(
            status_code=202,
            content={
                "job_id": job_id,
                "status": "queued",
                "status_url": f"/v1/asr/jobs/{job_id}",
            },
        )

    @app.get("/v1/asr/jobs/{job_id}", tags=["ASR"])
    def get_asr_job_status(job_id: str, auth: None = Depends(verify_auth)):
        job = queue.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")

        return {
            "job_id": job["job_id"],
            "status": job["status"],
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
            "result": job["result"],
            "error": job["error"],
        }

    @app.delete("/v1/asr/jobs/{job_id}", status_code=204, tags=["ASR"])
    def delete_asr_job(job_id: str, auth: None = Depends(verify_auth)):
        job = queue.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")

        if job["status"] in ("queued", "running"):
            raise HTTPException(status_code=409, detail="Job is currently active")

        queue.delete_job(job_id)
        return Response(status_code=204)

    return app


def get_default_settings() -> SpeechSettings:
    from app.core.config import settings
    base_dir = Path(__file__).resolve().parent.parent.parent
    return SpeechSettings(
        data_dir=Path(os.environ.get("SPEECH_DATA_DIR", str(base_dir / "data" / "speech"))),
        max_pending_jobs=int(os.environ.get("SPEECH_MAX_PENDING_JOBS", 10)),
        max_upload_bytes=int(os.environ.get("SPEECH_MAX_UPLOAD_BYTES", 500_000_000)),
        api_key=os.environ.get("SPEECH_API_KEY") or os.environ.get("SPEECH_SERVER_BEARER_TOKEN") or None,
        binary_path=Path(os.environ.get("WHISPER_CPP_BINARY") or os.environ.get("WHISPER_CPP_BINARY_PATH") or str(settings.WHISPER_CPP_BINARY)),
        model_path=Path(os.environ.get("WHISPER_CPP_MODEL") or os.environ.get("WHISPER_CPP_MODEL_PATH") or str(settings.WHISPER_CPP_MODEL)),
        vad_model_path=Path(os.environ.get("WHISPER_CPP_VAD_MODEL") or os.environ.get("WHISPER_CPP_VAD_MODEL_PATH") or str(settings.WHISPER_CPP_VAD_MODEL)),
        threads=int(os.environ.get("WHISPER_CPP_THREADS", settings.WHISPER_CPP_THREADS)),
        use_gpu=os.environ.get("WHISPER_CPP_USE_GPU", str(settings.WHISPER_CPP_USE_GPU)).lower() in ("true", "1"),
    )


app = create_app(get_default_settings())
