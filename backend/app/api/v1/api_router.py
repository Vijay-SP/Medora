"""
Medpark Meeting Intelligence System - Unified API v1 Router
"""

from fastapi import APIRouter
from app.api.v1.endpoints.meetings import router as meetings_router
from app.api.v1.endpoints.audio import router as audio_router
from app.api.v1.endpoints.pipeline import router as pipeline_router
from app.api.v1.endpoints.transcript import router as transcript_router
from app.api.v1.endpoints.review import router as review_router
from app.api.v1.endpoints.delivery import router as delivery_router
from app.api.v1.endpoints.people import router as people_router
from app.api.v1.endpoints.speakers import router as speakers_router
from app.api.v1.endpoints.learning import router as learning_router
from app.api.v1.endpoints.assistant import router as assistant_router

api_v1_router = APIRouter(prefix="/api/v1")

api_v1_router.include_router(meetings_router)
api_v1_router.include_router(audio_router)
api_v1_router.include_router(pipeline_router)
api_v1_router.include_router(transcript_router)
api_v1_router.include_router(review_router)
api_v1_router.include_router(delivery_router)
api_v1_router.include_router(people_router)
api_v1_router.include_router(speakers_router)
api_v1_router.include_router(learning_router)
api_v1_router.include_router(assistant_router)
