"""
Medpark Meeting Intelligence System - Main Application Entrypoint
100% Offline, Privacy-Compliant Hospital Meeting Transcription & Minutes Delivery.
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import html
import socket
import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from app.core.config import settings
from app.core.exceptions import (
    ASREngineError,
    AudioProcessingError,
    DeliveryError,
    ExtractionError,
    GroundingValidationError,
    MedparkBaseException,
    ResourceNotFoundError,
    ReviewStateError,
)
from app.core.logging import logger
from app.models.meeting import ProcessingStatus
from app.storage.repository import repository
from app.services.diarization.embedder import SPACE_MODEL_NAME, speaker_embedder
from app.services.extraction.llm_client import llm_client
from app.services.pipeline_orchestrator import ACTIVE_PROCESSING_STATUSES
from app.api.v1.api_router import api_v1_router

# Vendored Swagger UI / ReDoc assets. FastAPI's default documentation pages fetch their bundles
# from cdn.jsdelivr.net, which contradicts the strict offline policy, so the pages are rendered
# only from local files served under /static/docs. When a bundle is not vendored, the page falls
# back to a self-contained HTML reference rendered from the live schema: never a CDN request, and
# never an unusable documentation route.
DOCS_ASSETS_DIR = Path(__file__).resolve().parent / "static" / "docs"
SWAGGER_JS_FILE = "swagger-ui-bundle.js"
SWAGGER_CSS_FILE = "swagger-ui.css"
REDOC_JS_FILE = "redoc.standalone.js"
DOCS_FAVICON_URL = "/static/docs/favicon.png"  # Local path: the FastAPI default points to a CDN
DOCS_HTTP_METHODS = ("get", "post", "put", "patch", "delete")


def _reconcile_interrupted_runs() -> None:
    """
    Marks meetings left in a processing status by a previous process as FAILED.
    No pipeline run survives a restart, so a stale status is always wrong and would otherwise
    lock the meeting out of both /pipeline/start and /audio/upload permanently.
    """
    for meeting in repository.list_meetings():
        if meeting.processing_status in ACTIVE_PROCESSING_STATUSES:
            meeting.processing_status = ProcessingStatus.FAILED
            meeting.error_message = "Procesare întreruptă de repornirea serverului. Reluați pipeline-ul."
            meeting.current_stage_detail = meeting.error_message
            repository.save_meeting(meeting)
            logger.warning(f"Reconciled interrupted pipeline state for meeting {meeting.id}.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup sequence
    logger.info("==================================================================")
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info("Mode: STRICT OFFLINE (Zero external API / cloud telemetry calls)")
    logger.info(f"Target Timezone: {settings.DEFAULT_TIMEZONE}")
    logger.info(f"Storage Directory: {settings.DATA_DIR}")
    logger.info(f"Delivery Channel: {settings.DELIVERY_CHANNEL.upper()}")
    logger.info("==================================================================")
    settings.ensure_directories()
    _reconcile_interrupted_runs()
    # The local LLM is a hard dependency of every pipeline run. Startup still completes so that
    # /ready can report the outage and the operator can bring Ollama up without restarting the API.
    llm_ok, llm_detail = await llm_client.health()
    if llm_ok:
        logger.info(f"Local LLM ready: {settings.LLM_MODEL_NAME} at {settings.LLM_API_BASE_URL} ({llm_detail})")
    elif settings.REQUIRE_LOCAL_LLM:
        logger.critical(
            f"Local LLM '{settings.LLM_MODEL_NAME}' is NOT serving at {settings.LLM_API_BASE_URL} ({llm_detail}). "
            "REQUIRE_LOCAL_LLM is enabled: every pipeline run will fail at preflight until it is available."
        )
    else:
        logger.warning(f"Local LLM not serving ({llm_detail}); LLM_FALLBACK_MODE={settings.LLM_FALLBACK_MODE}")
    yield
    # Shutdown sequence
    logger.info("Shutting down Medpark Meeting Intelligence System.")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="On-premise offline multilingual meeting intelligence for Medpark International Hospital.",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None
)

# CORS Middleware for internal web application
# Only the configured allowlist is served: a wildcard combined with credentials would let any
# site call this API with the reviewer's credentials. The compiled UI is served same-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Domain exception to HTTP status mapping. Starlette resolves handlers along the exception MRO,
# so the MedparkBaseException entry catches any domain error not listed explicitly.
DOMAIN_EXCEPTION_STATUS_MAP: dict[type[MedparkBaseException], int] = {
    AudioProcessingError: 400,
    ResourceNotFoundError: 404,
    ReviewStateError: 409,
    GroundingValidationError: 422,
    ASREngineError: 500,
    ExtractionError: 500,
    DeliveryError: 500,
    MedparkBaseException: 500,
}


def _register_domain_exception_handlers(application: FastAPI) -> None:
    """Translates domain errors into truthful HTTP responses shaped like HTTPException."""
    for exception_type, status_code in DOMAIN_EXCEPTION_STATUS_MAP.items():
        async def handler(request: Request, exc: Exception, _status_code: int = status_code) -> JSONResponse:
            message = getattr(exc, "message", str(exc))
            logger.warning(f"{type(exc).__name__} on {request.method} {request.url.path}: {message}")
            return JSONResponse(status_code=_status_code, content={"detail": message})

        application.add_exception_handler(exception_type, handler)


_register_domain_exception_handlers(app)

# Mount API Routers
app.include_router(api_v1_router)

# Offline API documentation served exclusively from vendored assets (no CDN requests)
if DOCS_ASSETS_DIR.exists():
    app.mount("/static/docs", StaticFiles(directory=str(DOCS_ASSETS_DIR)), name="docs-assets")


def _docs_assets_vendored(*filenames: str) -> bool:
    """True only when every bundle a documentation page needs is present under /static/docs."""
    return all((DOCS_ASSETS_DIR / filename).exists() for filename in filenames)


def _render_offline_reference(missing_bundle: str) -> HTMLResponse:
    """
    Self-contained API reference rendered from the live OpenAPI schema.
    Used when the Swagger UI / ReDoc bundles are not vendored: the documentation route stays
    usable on an air-gapped host instead of failing, and still issues zero external requests.
    """
    schema = app.openapi()
    rows: list[str] = []
    for path, operations in sorted(schema.get("paths", {}).items()):
        for method, operation in sorted(operations.items()):
            if method.lower() not in DOCS_HTTP_METHODS:
                continue
            summary = operation.get("summary") or (operation.get("description") or "").strip().split("\n")[0]
            rows.append(
                f"<tr><td class=\"method {method.lower()}\">{method.upper()}</td>"
                f"<td class=\"path\">{html.escape(path)}</td>"
                f"<td>{html.escape(summary)}</td></tr>"
            )

    body = "\n".join(rows) or "<tr><td colspan=\"3\">No routes registered.</td></tr>"
    return HTMLResponse(
        f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{html.escape(settings.APP_NAME)} - API</title>
<style>
 body {{ font-family: Segoe UI, Arial, sans-serif; margin: 2rem auto; max-width: 68rem; color: #1f2933; }}
 h1 {{ font-size: 1.4rem; margin-bottom: .25rem; }}
 .note {{ background: #f4f6f8; border-left: 4px solid #0b7285; padding: .75rem 1rem; font-size: .85rem; }}
 table {{ border-collapse: collapse; width: 100%; margin-top: 1.5rem; font-size: .9rem; }}
 th, td {{ border-bottom: 1px solid #dde3e8; padding: .5rem .6rem; text-align: left; vertical-align: top; }}
 .method {{ font-weight: 700; white-space: nowrap; }}
 .get {{ color: #0b7285; }} .post {{ color: #2b8a3e; }} .put, .patch {{ color: #b8860b; }} .delete {{ color: #c92a2a; }}
 .path {{ font-family: Consolas, monospace; white-space: nowrap; }}
</style></head><body>
<h1>{html.escape(settings.APP_NAME)} - API v{html.escape(settings.APP_VERSION)}</h1>
<p class="note">Interactive documentation is disabled because <code>{html.escape(missing_bundle)}</code> is not
vendored in <code>{html.escape(str(DOCS_ASSETS_DIR))}</code>. Drop the Swagger UI / ReDoc bundles there to enable it.
The machine-readable schema is always available at <a href="{app.openapi_url}">{app.openapi_url}</a>.</p>
<table><thead><tr><th>Method</th><th>Path</th><th>Summary</th></tr></thead>
<tbody>
{body}
</tbody></table>
</body></html>"""
    )


@app.get("/docs", include_in_schema=False)
def swagger_ui_offline():
    """Swagger UI rendered from local assets instead of cdn.jsdelivr.net."""
    if not _docs_assets_vendored(SWAGGER_JS_FILE, SWAGGER_CSS_FILE):
        return _render_offline_reference(SWAGGER_JS_FILE)
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{settings.APP_NAME} - API",
        swagger_js_url=f"/static/docs/{SWAGGER_JS_FILE}",
        swagger_css_url=f"/static/docs/{SWAGGER_CSS_FILE}",
        swagger_favicon_url=DOCS_FAVICON_URL
    )


@app.get("/redoc", include_in_schema=False)
def redoc_offline():
    """ReDoc rendered from local assets instead of cdn.jsdelivr.net."""
    if not _docs_assets_vendored(REDOC_JS_FILE):
        return _render_offline_reference(REDOC_JS_FILE)
    return get_redoc_html(
        openapi_url=app.openapi_url,
        title=f"{settings.APP_NAME} - API",
        redoc_js_url=f"/static/docs/{REDOC_JS_FILE}",
        redoc_favicon_url=DOCS_FAVICON_URL,
        with_google_fonts=False
    )


@app.get("/health", tags=["System"])
def health_check():
    """Liveness probe confirming service process availability."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "offline_strict": settings.OFFLINE_STRICT
    }


async def _llm_model_loaded() -> bool:
    """True when the configured model is currently resident (GET /api/ps); False on any error."""
    try:
        async with httpx.AsyncClient(timeout=settings.LLM_HEALTH_TIMEOUT_S) as client:
            resp = await client.get(f"{settings.LLM_API_BASE_URL.rstrip('/')}/api/ps")
        if resp.status_code != 200:
            return False
        wanted = settings.LLM_MODEL_NAME
        for entry in resp.json().get("models", []):
            names = {entry.get("name", ""), entry.get("model", "")}
            if wanted in names or f"{wanted}:latest" in names:
                return True
        return False
    except Exception:
        return False


def _voice_id_readiness() -> dict:
    """
    Speaker identification status for /ready. The feature is usable only when the flag is on AND the
    CPU embedder loads; a missing ONNX file (or a load failure) is reported with its reason, never
    raised. The people count is best-effort so a store problem cannot take the whole probe down.
    """
    embedder_available = False
    dim = None
    space_id = None
    load_detail = None
    try:
        embedder_available = speaker_embedder.available
        if embedder_available:
            dim = speaker_embedder.dim
            space_id = speaker_embedder.space_id
        else:
            load_detail = speaker_embedder.load_error
    except Exception as exc:
        load_detail = f"embedder error: {exc}"

    if not settings.VOICE_ID_ENABLED:
        reason = "disabled by configuration (VOICE_ID_ENABLED=false)"
    elif not embedder_available:
        model_path = Path(speaker_embedder.model_path)
        reason = "embedder model missing" if not model_path.is_file() else (load_detail or "embedder failed to load")
    else:
        reason = "ready"

    enrolled_people = 0
    try:
        enrolled_people = sum(1 for person in repository.list_people() if person.enrollment_state(space_id) == "enrolled")
    except Exception as exc:
        logger.warning(f"Could not count enrolled people for /ready: {exc}")

    return {
        "enabled": bool(settings.VOICE_ID_ENABLED and embedder_available),
        "reason": reason,
        "embedder_available": embedder_available,
        "model": SPACE_MODEL_NAME,
        "dim": dim,
        "space_id": space_id,
        "enrolled_people": enrolled_people
    }


@app.get("/ready", tags=["System"])
async def readiness_check():
    """
    Truthful readiness probe:
    Validates storage, local ASR cache, local LLM server + model availability, internal SMTP reachability,
    and the speaker identification feature (flag + CPU embedder + enrolled people).
    """
    storage_ok = settings.DATA_DIR.exists() and settings.UPLOADS_DIR.exists() and settings.EXPORTS_DIR.exists()

    # Check LLM server reachability and model presence. Neither call loads the model: a probe that
    # pulled 2.7 GB into VRAM would evict a running Whisper transcription.
    llm_connected, _llm_detail = await llm_client.health()
    llm_loaded = llm_connected and await _llm_model_loaded()

    # The first call creates the ONNX session (CPU, ~30 MB); off the event loop so it cannot stall the API
    voice_id = await asyncio.to_thread(_voice_id_readiness)

    # Check SMTP port reachability (Mailpit / Hospital SMTP)
    smtp_connected = False
    try:
        s = socket.create_connection((settings.SMTP_HOST, settings.SMTP_PORT), timeout=1.0)
        s.close()
        smtp_connected = True
    except Exception:
        smtp_connected = False

    # ASR service readiness probe
    asr_provider = settings.ASR_PROVIDER
    asr_ready = True
    if asr_provider == "remote":
        asr_service = {
            "provider": "remote",
            "endpoint": settings.REMOTE_ASR_BASE_URL,
            "connected": False,
            "ready": False,
        }
        try:
            headers = {"Authorization": f"Bearer {settings.REMOTE_ASR_API_KEY}"} if settings.REMOTE_ASR_API_KEY else {}
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{settings.REMOTE_ASR_BASE_URL.rstrip('/')}/ready", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                asr_ready = bool(data.get("ready", False))
                asr_service.update({
                    "connected": True,
                    "ready": asr_ready,
                    "model_name": data.get("model", ""),
                    "device": data.get("device", "remote"),
                    "queue_depth": data.get("queue_depth", 0),
                })
        except Exception as exc:
            asr_service["error"] = str(exc)
            asr_ready = False
    elif asr_provider == "whisper_cpp":
        from app.services.asr.whisper_cpp_engine import WhisperCppEngine
        cpp_engine = WhisperCppEngine(
            binary_path=settings.WHISPER_CPP_BINARY,
            model_path=settings.WHISPER_CPP_MODEL,
            vad_model_path=settings.WHISPER_CPP_VAD_MODEL,
            threads=settings.WHISPER_CPP_THREADS,
            use_gpu=settings.WHISPER_CPP_USE_GPU,
            timeout_s=settings.WHISPER_CPP_TIMEOUT_S,
        )
        h = cpp_engine.health()
        asr_ready = bool(h.get("ready", False))
        asr_service = {
            "provider": "whisper_cpp",
            "model_name": h.get("model", ""),
            "cached_locally": asr_ready,
            "device": h.get("device", "metal" if settings.WHISPER_CPP_USE_GPU else "cpu"),
            "ready": asr_ready,
        }
    else:
        asr_cached = any(settings.MODELS_DIR.glob("**/*whisper*")) or any(settings.MODELS_DIR.glob("**/*.bin"))
        asr_service = {
            "provider": "faster_whisper",
            "model_name": settings.WHISPER_MODEL_NAME,
            "cached_locally": asr_cached,
            "device": settings.WHISPER_DEVICE,
        }

    # If policy requires strict LLM, ready is False when LLM is down
    is_ready = storage_ok
    if settings.REQUIRE_LOCAL_LLM and not llm_connected:
        is_ready = False
    if asr_provider == "remote" and not asr_ready:
        is_ready = False

    return {
        "ready": is_ready,
        "storage": {
            "ready": storage_ok,
            "data_dir": str(settings.DATA_DIR)
        },
        "asr_service": asr_service,
        "llm_service": {
            "endpoint": settings.LLM_API_BASE_URL,
            "engine": "ollama",
            "model": settings.LLM_MODEL_NAME,
            "connected": llm_connected,
            "loaded": llm_loaded,
            "mode": "neural_server" if llm_connected else "unavailable"
        },
        "smtp_service": {
            "host": f"{settings.SMTP_HOST}:{settings.SMTP_PORT}",
            "reachable": smtp_connected
        },
        "voice_id": voice_id
    }


# Mount compiled React frontend if built
dist_dir = settings.BASE_DIR / "frontend" / "dist"
if dist_dir.exists():
    logger.info(f"Mounting compiled frontend UI from: {dist_dir}")
    app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="frontend")
