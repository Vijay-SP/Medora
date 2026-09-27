"""
Medpark Meeting Intelligence System - Pipeline Orchestrator
Coordinates end-to-end execution across audio normalization, ASR, diarization, extraction, and delivery.
"""

import asyncio
from pathlib import Path
import time
from typing import Any
from app.core.config import settings
from app.core.exceptions import DeliveryError, DiarizationError, LLMUnavailable
from app.core.logging import logger
from app.models.meeting import Meeting, ProcessingStatus, ReviewStatus, WorkflowMode
from app.models.transcript import Transcript, TranscriptSegment
from app.models.extraction import MinutesOfMeeting
from app.storage.repository import repository
from app.storage.file_manager import file_manager
from app.services.audio.preprocessor import audio_preprocessor
from app.services.asr import get_asr_engine
from app.services.diarization.speaker_engine import diarization_engine
from app.services.extraction.llm_engine import extraction_engine
from app.services.documents.generator import document_generator
from app.services.delivery.router import delivery_router

# Statuses that mean a run is still in flight. Derived from the terminal states instead of being
# enumerated, so a newly added processing stage is guarded automatically by every caller.
TERMINAL_PROCESSING_STATUSES = frozenset({
    ProcessingStatus.IDLE,
    ProcessingStatus.COMPLETED,
    ProcessingStatus.FAILED
})
ACTIVE_PROCESSING_STATUSES = frozenset(
    stage for stage in ProcessingStatus if stage not in TERMINAL_PROCESSING_STATUSES
)

# Whisper (~1.8 GB) and the local LLM (~2.7 GB, resident from the first map call until the
# extraction engine's final unload) cannot share the 4 GB VRAM, and each engine is a process-wide
# singleton. Since the blocking stages run in worker threads, two pipelines for two different
# meetings could otherwise load Whisper while the other run's LLM is resident, load two Whisper
# models, release a model the other run is using, or evict the LLM in the middle of the other
# run's map sequence. Only one run at a time may hold the GPU stages (ASR through extraction).
_GPU_STAGE_LOCK = asyncio.Semaphore(1)

# Attribution states that carry a person's name onto a segment. Only a human reviewer may put a
# segment into one of them (POST /speakers/{cluster}/confirm); the diarizer stops at "suggested".
HUMAN_CONFIRMED_ATTRIBUTION_STATES = frozenset({"confirmed", "corrected"})


def collect_asr_stats(engine: Any = None) -> dict:
    """
    Snapshot of the ASR engine's last run (strategy, window languages, rescoring, garbage flags, RTF)
    as published by the engine's last_run_stats. Read defensively: an engine build without the
    attribute, or a stage entered before any transcription, yields {} rather than an AttributeError.
    Copied so a later run cannot mutate the dict already persisted on this meeting.
    """
    if engine is None:
        try:
            from app.services.asr.whisper_engine import whisper_engine
            engine = whisper_engine
        except Exception:
            engine = None
    stats = getattr(engine, "last_run_stats", None)
    return dict(stats) if isinstance(stats, dict) else {}


def record_asr_stats(meeting: Meeting, stats: dict) -> None:
    """
    Stores the ASR run statistics on the meeting when the model carries the asr_stats field
    (additive contract K1). A Meeting model without the field logs the stats instead of raising:
    pydantic rejects assignment to an undeclared attribute, and the audit line must never fail a run.
    """
    if "asr_stats" in Meeting.model_fields:
        meeting.asr_stats = stats
    elif stats:
        logger.warning(f"Meeting model has no asr_stats field; ASR run statistics not persisted: {stats}")


def find_human_attributed_segments(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    """
    Returns the segments that claim a human-confirmed speaker identity.
    A segment counts when its attribution state is confirmed/corrected OR when it carries a confirmed
    person id / display name / printable flag: any one of them alone would already put a name on the
    document. The fields are read with their contract defaults so a transcript model without the
    attribution fields (legacy rows) is treated as fully anonymous rather than crashing the check.
    """
    return [
        seg for seg in segments
        if getattr(seg, "attribution_state", "anonymous") in HUMAN_CONFIRMED_ATTRIBUTION_STATES
        or getattr(seg, "speaker_id", None) is not None
        or getattr(seg, "confirmed_display_name", None) is not None
        or getattr(seg, "printable_name", False)
    ]


class PipelineOrchestrator:
    """Manages sequential execution of speech-to-email processing stages."""

    def _next_revision(self, meeting: Meeting) -> int:
        """
        Returns the revision this run must write.
        A re-run never reuses the revision of an already exported document, keeping the
        immutable revision history and meeting.current_revision consistent.
        """
        if repository.get_minutes(meeting.id):
            meeting.current_revision += 1
        return meeting.current_revision

    async def run_pipeline(self, meeting_id: str) -> Meeting:
        meeting = repository.get_meeting(meeting_id)
        if not meeting:
            raise ValueError(f"Meeting with ID '{meeting_id}' not found.")

        if not meeting.original_audio_path:
            raise ValueError(f"Meeting '{meeting_id}' has no uploaded audio file.")

        start_time = time.time()
        logger.info(f"=== Starting Pipeline for Meeting: '{meeting.title}' (Mode: {meeting.workflow_mode.value.upper()}) ===")

        try:
            # Stage 0: Extraction preflight. The local LLM is required for Stage 4; asking the server
            # for its version and model list takes seconds, whereas discovering the outage after ASR
            # would waste minutes of GPU time. LLMUnavailable propagates to the except below.
            meeting.processing_status = ProcessingStatus.PREPROCESSING
            meeting.processing_progress = 5
            meeting.current_stage_detail = "Verificare disponibilitate LLM local..."
            meeting.error_message = None  # A fresh run must not display the previous run's failure
            repository.save_meeting(meeting)

            provenance = await extraction_engine.preflight()
            logger.info(f"Extraction preflight passed: {provenance}")

            # Stage 1: Audio Normalization
            meeting.processing_status = ProcessingStatus.PREPROCESSING
            meeting.processing_progress = 10
            meeting.current_stage_detail = "Normalizare audio 16kHz mono cu FFmpeg..."
            repository.save_meeting(meeting)

            original_path = Path(meeting.original_audio_path)
            normalized_path = file_manager.get_normalized_audio_path(meeting.id)
            # Blocking inference and media work runs off the event loop so the API stays responsive
            _, duration = await asyncio.to_thread(audio_preprocessor.normalize, original_path, normalized_path)

            meeting.normalized_audio_path = str(normalized_path)
            meeting.audio_duration_seconds = duration
            repository.save_meeting(meeting)

            # Stage 2: Multilingual Speech-to-Text (ASR)
            meeting.processing_status = ProcessingStatus.TRANSCRIBING
            meeting.processing_progress = 30
            meeting.current_stage_detail = "Transkripție multilingvă (Română / Русский / English)..."
            repository.save_meeting(meeting)

            # Serialized across concurrent runs from ASR through extraction: Whisper load, inference and
            # VRAM release, then the LLM's residency until extract_minutes() unloads it in its finally,
            # must never interleave with another meeting's GPU work. The no-speech return below leaves
            # the block early, releasing the lock.
            async with _GPU_STAGE_LOCK:
                asr_engine = get_asr_engine()
                from app.services.asr.dynamic_context import build_context
                asr_context = build_context(meeting)
                if asr_context.terms:
                    logger.info(f"ASR context applied: {len(asr_context.terms)} terms, {len(asr_context.hotwords)} hotwords")
                segments = await asyncio.to_thread(asr_engine.transcribe, normalized_path, context=asr_context)
                await asyncio.to_thread(asr_engine.release_model)

                # Recorded after the run so a CPU fallback taken inside the engine is visible in the audit,
                # together with the per-window language statistics of this transcription (strategy,
                # window_languages, rescored_windows, garbage_flagged, rtf) for the reviewer and the docs.
                meeting.asr_device_used = asr_engine.device
                asr_stats = collect_asr_stats(asr_engine)
                record_asr_stats(meeting, asr_stats)
                if asr_stats:
                    logger.info(
                        f"ASR run stats for meeting {meeting_id}: strategy={asr_stats.get('strategy')} "
                        f"device={asr_stats.get('device')} windows={asr_stats.get('windows')} "
                        f"window_languages={asr_stats.get('window_languages')} rtf={asr_stats.get('rtf')}"
                    )
                repository.save_meeting(meeting)

                # Handle No-Speech audio accurately without fabricating data
                if not segments:
                    logger.warning(f"No intelligible speech detected in meeting {meeting_id}.")
                    transcript = Transcript(meeting_id=meeting.id, segments=[])
                    transcript.compute_stats()
                    repository.save_transcript(transcript)

                    minutes = MinutesOfMeeting(
                        meeting_id=meeting.id,
                        title=meeting.title,
                        meeting_type=meeting.meeting_type.value,
                        summary_ro="Nu a fost detectată nicio intervenție vocală inteligibilă în înregistrarea audio procesată.",
                        summary_en="No intelligible vocal speech was detected in the processed audio recording.",
                        agenda_topics=[meeting.agenda] if meeting.agenda else [],
                        decisions=[],
                        action_items=[],
                        risks_and_questions=[],
                        revision=self._next_revision(meeting),
                        model_version="no-speech-detected",
                        source_transcript_revision=1,
                        needs_transcript_review=False,
                    )
                    repository.save_minutes(minutes)

                    pdf_path, docx_path = file_manager.get_export_paths(meeting.id, revision=minutes.revision)
                    await asyncio.to_thread(document_generator.generate_all, meeting, minutes, pdf_path, docx_path)
                    minutes.pdf_path = str(pdf_path)
                    minutes.docx_path = str(docx_path)
                    repository.save_minutes(minutes)

                    elapsed = time.time() - start_time
                    meeting.processing_status = ProcessingStatus.COMPLETED
                    meeting.processing_progress = 100
                    meeting.processing_time_seconds = round(elapsed, 2)
                    meeting.review_status = ReviewStatus.PENDING_REVIEW
                    meeting.current_stage_detail = "Procesare finalizată: Nicio replică vocală detectată în înregistrare."
                    repository.save_meeting(meeting)
                    return meeting

                # Stage 3: Speaker Diarization
                meeting.processing_status = ProcessingStatus.DIARIZING
                meeting.processing_progress = 55
                meeting.current_stage_detail = "Clustere acustice și identificare replici vorbitori..."
                repository.save_meeting(meeting)

                # Enrolled people are only offered for suggestions while the feature is switched on; with
                # VOICE_ID_ENABLED off the diarizer runs purely anonymous and no voiceprint is compared.
                people = repository.list_people() if settings.VOICE_ID_ENABLED else []
                diarized_segments = await asyncio.to_thread(
                    diarization_engine.assign_speakers,
                    normalized_path,
                    segments,
                    meeting.attendees,
                    meeting_id=meeting.id,
                    people=people
                )

                # Auto-Pilot has no human in the loop, so no segment may leave diarization with a confirmed
                # identity: a name on an unreviewed document would be the machine attributing a doctor's
                # words on its own authority. Checked before extraction and document generation so the
                # violation never reaches the LLM prompt or a PDF.
                if meeting.workflow_mode == WorkflowMode.AUTO_PILOT and not settings.ALLOW_AUTO_CONFIRM_SPEAKERS:
                    attributed = find_human_attributed_segments(diarized_segments)
                    if attributed:
                        raise DiarizationError(
                            f"Pipeline Auto-Pilot oprit: {len(attributed)} segmente au primit o identitate de vorbitor "
                            "confirmată fără revizor uman. Identificarea vocală poate fi confirmată doar de o persoană, "
                            "în modul supervizat.",
                            details={"segment_ids": [seg.id for seg in attributed]}
                        )

                transcript = Transcript(meeting_id=meeting.id, segments=diarized_segments)
                transcript.compute_stats()
                repository.save_transcript(transcript)

                # Stage 4: Evidence-Linked Information Extraction (the engine unloads the LLM when done,
                # so the VRAM is free for the next meeting's ASR)
                meeting.processing_status = ProcessingStatus.EXTRACTING
                meeting.processing_progress = 75
                meeting.current_stage_detail = "Extragere decizii, acțiuni și traducere multilingvă (RO, RU, EN)..."
                repository.save_meeting(meeting)

                minutes = await extraction_engine.extract_minutes(meeting, transcript)

            minutes.source_transcript_revision = transcript.revision
            minutes.needs_transcript_review = False
            minutes.revision = self._next_revision(meeting)
            repository.save_minutes(minutes)

            # Stage 5: Document Generation (PDF & DOCX)
            meeting.processing_status = ProcessingStatus.GENERATING_DOCS
            meeting.processing_progress = 90
            meeting.current_stage_detail = "Generare proces-verbal oficial PDF și DOCX..."
            repository.save_meeting(meeting)

            pdf_path, docx_path = file_manager.get_export_paths(meeting.id, revision=minutes.revision)
            await asyncio.to_thread(document_generator.generate_all, meeting, minutes, pdf_path, docx_path)

            minutes.pdf_path = str(pdf_path)
            minutes.docx_path = str(docx_path)
            repository.save_minutes(minutes)

            # Stage 6: Delivery Routing Evaluation
            if meeting.workflow_mode == WorkflowMode.AUTO_PILOT:
                logger.info("Auto-Pilot processing complete: human sign-off is required before email dispatch.")
                # A degraded draft is never auto-approved: the documents exist, so the run completes,
                # but the meeting is held for a human exactly like a supervised run.
                try:
                    delivery_router.assert_dispatchable(minutes)
                except DeliveryError as guard:
                    meeting.review_status = ReviewStatus.PENDING_REVIEW
                    meeting.error_message = guard.message
                    meeting.current_stage_detail = "Document DRAFT degradat reținut pentru revizuire umană. Expedierea automată a fost blocată."
                    logger.warning(f"Auto-Pilot dispatch blocked for meeting {meeting_id}: {guard.message}")
                else:
                    meeting.review_status = ReviewStatus.PENDING_REVIEW
                    meeting.approved_by = None
                    meeting.approved_at = None
                    meeting.current_stage_detail = "Document pregătit. Aprobarea umană este obligatorie înainte de email."
            else:
                logger.info("Supervised Mode active: Holding document for clinical reviewer sign-off.")
                meeting.review_status = ReviewStatus.PENDING_REVIEW
                meeting.current_stage_detail = "Document pregătit. În așteptarea revizuirii și aprobării clinice."

            elapsed = time.time() - start_time
            meeting.processing_status = ProcessingStatus.COMPLETED
            meeting.processing_progress = 100
            meeting.processing_time_seconds = round(elapsed, 2)
            if not meeting.error_message:
                meeting.current_stage_detail = f"Procesare finalizată cu succes în {elapsed:.1f} secunde."
            repository.save_meeting(meeting)

            logger.info(f"=== Pipeline completed successfully in {elapsed:.2f}s ===")
            return meeting

        except Exception as e:
            if isinstance(e, LLMUnavailable):
                # Expected operational outage, caught at preflight before any GPU work: no traceback needed
                logger.error(f"Pipeline aborted for meeting {meeting_id}: {e}")
            else:
                logger.error(f"Pipeline error for meeting {meeting_id}: {e}", exc_info=True)
            meeting.processing_status = ProcessingStatus.FAILED
            meeting.error_message = str(e)
            meeting.current_stage_detail = f"Eroare: {e}"
            repository.save_meeting(meeting)
            raise


pipeline_orchestrator = PipelineOrchestrator()
