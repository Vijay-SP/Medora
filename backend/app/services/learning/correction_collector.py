"""
Medpark Meeting Intelligence System - Correction Collector & Reconciliation Service
Idempotently projects eligible reviewer correction events into the adaptation catalog SQLite store.
Provides CLI reconciliation for saved-but-uncollected events.
"""

import argparse
import sys
from typing import Any, Optional
from app.core.config import settings
from app.core.logging import logger
from app.models.adaptation import CollectionResult
from app.models.transcript import Transcript
from app.services.learning.store import adaptation_store
from app.storage.file_manager import file_manager
from app.storage.repository import repository


def collect_event(
    event_id: str,
    meeting_id: str,
    transcript: Optional[Transcript] = None,
) -> CollectionResult:
    """
    Projects a single correction event into the SQLite adaptation catalog idempotently.
    Returns status: 'collected', 'ineligible', or 'retry_required'.
    """
    if not settings.ASR_LEARNING_ENABLED:
        return CollectionResult(
            status="ineligible",
            reason="learning_disabled",
            event_id=event_id,
            meeting_id=meeting_id,
        )

    if transcript is None:
        transcript = repository.get_transcript(meeting_id)

    if not transcript:
        return CollectionResult(
            status="ineligible",
            reason="transcript_not_found",
            event_id=event_id,
            meeting_id=meeting_id,
        )

    event = next((e for e in transcript.correction_events if e.id == event_id), None)
    if not event:
        return CollectionResult(
            status="ineligible",
            reason="event_not_found",
            event_id=event_id,
            meeting_id=meeting_id,
        )

    seg = next((s for s in transcript.segments if s.id == event.segment_id), None)
    if not seg:
        return CollectionResult(
            status="ineligible",
            reason="segment_not_found",
            event_id=event_id,
            meeting_id=meeting_id,
        )

    # Ineligibility checks:
    # 1. An empty string is a valid reviewed removal, but not a training label
    if not event.new_text.strip():
        return CollectionResult(
            status="ineligible",
            reason="empty_deletion",
            event_id=event_id,
            meeting_id=meeting_id,
        )

    # 2. Redactions or translations are excluded from acoustic training
    if event.edit_kind in ("redaction", "translation"):
        return CollectionResult(
            status="ineligible",
            reason=f"edit_kind_{event.edit_kind}_ineligible",
            event_id=event_id,
            meeting_id=meeting_id,
        )

    # Compute or locate audio metadata
    audio_checksum: Optional[str] = None
    try:
        audio_path = file_manager.get_normalized_audio_path(meeting_id)
        if audio_path.exists():
            audio_checksum = file_manager.compute_sha256(audio_path)
    except Exception as exc:
        logger.debug(f"Audio checksum computation skipped for meeting {meeting_id}: {exc}")

    try:
        adaptation_store.upsert_event(
            event,
            metadata={
                "audio_start": seg.start,
                "audio_end": seg.end,
                "audio_checksum": audio_checksum,
                "speaker_cluster": seg.cluster_id or seg.speaker,
                "language": seg.language,
                "collection_status": "collected",
                "eligibility_reason": f"reviewer_{event.edit_kind}",
            },
        )
        return CollectionResult(
            status="collected",
            event_id=event_id,
            meeting_id=meeting_id,
        )
    except Exception as exc:
        logger.error(f"Error projecting event {event_id} into adaptation catalog: {exc}")
        return CollectionResult(
            status="retry_required",
            reason=str(exc),
            event_id=event_id,
            meeting_id=meeting_id,
        )


def reconcile_meeting(meeting_id: str) -> dict[str, Any]:
    """
    Reconciles all uncollected or retry-required events for a given meeting.
    """
    transcript = repository.get_transcript(meeting_id)
    if not transcript or not transcript.correction_events:
        return {"meeting_id": meeting_id, "checked": 0, "collected": 0, "ineligible": 0, "errors": 0}

    checked = 0
    collected = 0
    ineligible = 0
    errors = 0

    for event in transcript.correction_events:
        checked += 1
        existing = adaptation_store.get_event(event.id)
        if existing and existing.get("collection_status") == "collected":
            continue

        result = collect_event(event.id, meeting_id, transcript=transcript)
        if result.status == "collected":
            collected += 1
        elif result.status == "ineligible":
            ineligible += 1
        else:
            errors += 1

    return {
        "meeting_id": meeting_id,
        "checked": checked,
        "collected": collected,
        "ineligible": ineligible,
        "errors": errors,
    }


def reconcile_all() -> dict[str, Any]:
    """
    Scans repository for all meetings with transcripts and reconciles their correction events.
    """
    meetings = repository.list_meetings()
    total_meetings = len(meetings)
    total_checked = 0
    total_collected = 0
    total_ineligible = 0
    total_errors = 0

    logger.info(f"Starting adaptation catalog reconciliation across {total_meetings} meetings...")
    for meeting in meetings:
        res = reconcile_meeting(meeting.id)
        total_checked += res["checked"]
        total_collected += res["collected"]
        total_ineligible += res["ineligible"]
        total_errors += res["errors"]

    summary = {
        "meetings_scanned": total_meetings,
        "events_checked": total_checked,
        "events_collected": total_collected,
        "events_ineligible": total_ineligible,
        "events_with_errors": total_errors,
    }
    logger.info(f"Reconciliation completed: {summary}")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Medpark ASR Adaptation Correction Collector")
    parser.add_argument("--reconcile", action="store_true", help="Reconcile uncollected events into adaptation catalog")
    parser.add_argument("--meeting-id", type=str, default=None, help="Reconcile a specific meeting only")
    args = parser.parse_args()

    if args.reconcile:
        if args.meeting_id:
            res = reconcile_meeting(args.meeting_id)
            print(f"Meeting {args.meeting_id} reconciliation: {res}")
        else:
            res = reconcile_all()
            print(f"Catalog reconciliation summary: {res}")
        sys.exit(0)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
