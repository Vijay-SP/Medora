"""
Medpark Meeting Intelligence System - Main Application Entrypoint
100% Offline, Privacy-Compliant Hospital Meeting Transcription & Minutes Delivery.
"""

from contextlib import asynccontextmanager
from pathlib import Path
import socket
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.core.config import settings
from app.core.logging import logger
from app.api.v1.api_router import api_v1_router


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
    yield
    # Shutdown sequence
    logger.info("Shutting down Medpark Meeting Intelligence System.")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="On-premise offline multilingual meeting intelligence for Medpark International Hospital.",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS Middleware for internal web application
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOW_ORIGINS + ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API Routers
app.include_router(api_v1_router)


@app.get("/health", tags=["System"])
def health_check():
    """Liveness probe confirming service process availability."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "offline_strict": settings.OFFLINE_STRICT
    }


@app.get("/ready", tags=["System"])
async def readiness_check():
    """
    Truthful readiness probe:
    Validates storage, local ASR cache, local LLM endpoint connectivity, and internal SMTP reachability.
    """
    storage_ok = settings.DATA_DIR.exists() and settings.UPLOADS_DIR.exists() and settings.EXPORTS_DIR.exists()
    
    # Check LLM server reachability
    llm_connected = False
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            resp = await client.get(f"{settings.LLM_API_BASE_URL.rsplit('/', 1)[0]}/models")
            llm_connected = (resp.status_code == 200)
    except Exception:
        llm_connected = False

    # Check SMTP port reachability (Mailpit / Hospital SMTP)
    smtp_connected = False
    try:
        s = socket.create_connection((settings.SMTP_HOST, settings.SMTP_PORT), timeout=1.0)
        s.close()
        smtp_connected = True
    except Exception:
        smtp_connected = False

    # ASR model cache check
    asr_cached = any(settings.MODELS_DIR.glob("**/*whisper*")) or any(settings.MODELS_DIR.glob("**/*.bin"))

    # If policy requires strict LLM, ready is False when LLM is down
    is_ready = storage_ok
    if settings.REQUIRE_LOCAL_LLM and not llm_connected:
        is_ready = False

    return {
        "ready": is_ready,
        "storage": {
            "ready": storage_ok,
            "data_dir": str(settings.DATA_DIR)
        },
        "asr_service": {
            "model_name": settings.WHISPER_MODEL_NAME,
            "cached_locally": asr_cached,
            "device": settings.WHISPER_DEVICE
        },
        "llm_service": {
            "endpoint": settings.LLM_API_BASE_URL,
            "connected": llm_connected,
            "mode": "neural_server" if llm_connected else ("required_failing" if settings.REQUIRE_LOCAL_LLM else "degraded_fallback")
        },
        "smtp_service": {
            "host": f"{settings.SMTP_HOST}:{settings.SMTP_PORT}",
            "reachable": smtp_connected
        }
    }


# Mount compiled React frontend if built
dist_dir = settings.BASE_DIR / "frontend" / "dist"
if dist_dir.exists():
    logger.info(f"Mounting compiled frontend UI from: {dist_dir}")
    app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="frontend")
