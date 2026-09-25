"""
Medpark Meeting Intelligence System - Pipeline Orchestrator
Coordinates end-to-end execution across audio normalization, ASR, diarization, extraction, and delivery.
"""

import time
from pathlib import Path
from app.core.config import settings
from app.core.logging import logger
from app.models.meeting import Meeting, ProcessingStatus, ReviewStatus, WorkflowMode
from app.models.transcript import Transcript
from app.models.extraction import MinutesOfMeeting
from app.models.delivery import DeliveryStatus
from app.storage.repository import repository
from app.storage.file_manager import file_manager
from app.services.audio.preprocessor import audio_preprocessor
from app.services.asr.whisper_engine import whisper_engine
from app.services.diarization.speaker_engine import diarization_engine
from app.services.extraction.llm_engine import extraction_engine
from app.services.documents.generator import document_generator
from app.services.delivery.smtp_service import smtp_service
from app.services.delivery.n8n_service import n8n_service


class PipelineOrchestrator:
    """Manages sequential execution of speech-to-email processing stages."""

    async def run_pipeline(self, meeting_id: str) -> Meeting:
        meeting = repository.get_meeting(meeting_id)
        if not meeting:
            raise ValueError(f"Meeting with ID '{meeting_id}' not found.")

        if not meeting.original_audio_path:
            raise ValueError(f"Meeting '{meeting_id}' has no uploaded audio file.")

        start_time = time.time()
        logger.info(f"=== Starting Pipeline for Meeting: '{meeting.title}' (Mode: {meeting.workflow_mode.value.upper()}) ===")

        try:
            # Stage 1: Audio Normalization
            meeting.processing_status = ProcessingStatus.PREPROCESSING
            meeting.processing_progress = 10
            meeting.current_stage_detail = "Normalizare audio 16kHz mono cu FFmpeg..."
            repository.save_meeting(meeting)

            original_path = Path(meeting.original_audio_path)
            normalized_path = file_manager.get_normalized_audio_path(meeting.id)
            _, duration = audio_preprocessor.normalize(original_path, normalized_path)
            
            meeting.normalized_audio_path = str(normalized_path)
            meeting.audio_duration_seconds = duration
            repository.save_meeting(meeting)

            # Stage 2: Multilingual Speech-to-Text (ASR)
            meeting.processing_status = ProcessingStatus.TRANSCRIBING
            meeting.processing_progress = 30
            meeting.current_stage_detail = "Transkripție multilingvă (Română / Русский / English)..."
            repository.save_meeting(meeting)

            segments = whisper_engine.transcribe(normalized_path)
            whisper_engine.release_model()

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
                    model_version="no-speech-detected"
                )
                repository.save_minutes(minutes)

                pdf_path, docx_path = file_manager.get_export_paths(meeting.id, revision=minutes.revision)
                document_generator.generate_all(meeting, minutes, pdf_path, docx_path)
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

            diarized_segments = diarization_engine.assign_speakers(normalized_path, segments, meeting.attendees)
            
            transcript = Transcript(meeting_id=meeting.id, segments=diarized_segments)
            transcript.compute_stats()
            repository.save_transcript(transcript)

            # Stage 4: Evidence-Linked Information Extraction
            meeting.processing_status = ProcessingStatus.EXTRACTING
            meeting.processing_progress = 75
            meeting.current_stage_detail = "Extragere decizii, acțiuni și verificare dovezi audio..."
            repository.save_meeting(meeting)

            minutes = await extraction_engine.extract_minutes(meeting, transcript)
            repository.save_minutes(minutes)

            # Stage 5: Document Generation (PDF & DOCX)
            meeting.processing_status = ProcessingStatus.GENERATING_DOCS
            meeting.processing_progress = 90
            meeting.current_stage_detail = "Generare proces-verbal oficial PDF și DOCX..."
            repository.save_meeting(meeting)

            pdf_path, docx_path = file_manager.get_export_paths(meeting.id, revision=minutes.revision)
            document_generator.generate_all(meeting, minutes, pdf_path, docx_path)

            minutes.pdf_path = str(pdf_path)
            minutes.docx_path = str(docx_path)
            repository.save_minutes(minutes)

            # Stage 6: Delivery Routing Evaluation
            if meeting.workflow_mode == WorkflowMode.AUTO_PILOT:
                logger.info("Auto-Pilot Mode active: Proceeding to automatic approval & email dispatch...")
                meeting.review_status = ReviewStatus.APPROVED
                meeting.approved_by = "Auto-Pilot Pipeline"
                meeting.current_stage_detail = "Trimitere email către lista de distribuție..."

                # Exclusive delivery routing: n8n or direct SMTP
                if settings.DELIVERY_CHANNEL == "n8n" and settings.N8N_ENABLED:
                    logger.info("Routing via n8n automation engine...")
                    delivery_record = await n8n_service.trigger_workflow(meeting, minutes, meeting.distribution_list)
                else:
                    delivery_record = await smtp_service.deliver(meeting, minutes, pdf_path, docx_path)

                if delivery_record:
                    repository.save_delivery(delivery_record)
                    if delivery_record.status == DeliveryStatus.DISPATCHED:
                        meeting.review_status = ReviewStatus.DELIVERED
                    else:
                        meeting.review_status = ReviewStatus.APPROVED
                        meeting.error_message = delivery_record.error_message
                        logger.warning(f"Delivery not completed: {delivery_record.status} ({delivery_record.error_message})")
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
            logger.error(f"Pipeline error for meeting {meeting_id}: {e}", exc_info=True)
            meeting.processing_status = ProcessingStatus.FAILED
            meeting.error_message = str(e)
            meeting.current_stage_detail = f"Eroare: {e}"
            repository.save_meeting(meeting)
            raise


pipeline_orchestrator = PipelineOrchestrator()
