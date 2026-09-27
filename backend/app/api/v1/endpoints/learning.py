"""
Medpark Meeting Intelligence System - ASR Adaptation Learning Review Endpoints
Provides reviewer inbox for verifying human corrections, recording explicit consent,
and inspecting candidate counts and eligible audio durations without making unsupported accuracy claims.
"""

from datetime import datetime, timezone
from typing import Any, Optional
from fastapi import APIRouter, HTTPException, Query, status
from app.core.logging import logger
from app.models.adaptation import (
    ApproveRuleRequest,
    CorrectionEvent,
    LearningInboxResponse,
    NormalizationRule,
    RejectCorrectionRequest,
    RollbackRuleRequest,
    RuleCandidate,
    VerifyCorrectionRequest,
)
from app.services.asr.dialect_adapter import load_rules, save_local_rule
from app.services.learning.pattern_miner import mine_candidates
from app.services.learning.store import adaptation_store
from app.storage.repository import repository

router = APIRouter(prefix="/learning", tags=["ASR Adaptation & Learning"])


def _calculate_eligible_audio_duration() -> float:
    """Computes total audio duration in seconds for verified training-eligible clips."""
    try:
        with adaptation_store.connection() as conn:
            cursor = conn.execute(
                """
                SELECT SUM(coalesce(audio_end, 0.0) - coalesce(audio_start, 0.0))
                FROM correction_events
                WHERE verification_status = 'verified'
                  AND verified_against_audio = 1
                  AND training_reuse_allowed = 1
                  AND audio_end > audio_start
                """
            )
            val = cursor.fetchone()[0]
            return float(val) if val is not None else 0.0
    except Exception as exc:
        logger.debug(f"Could not compute eligible audio duration: {exc}")
        return 0.0


@router.get("/corrections", response_model=LearningInboxResponse)
def get_learning_corrections(
    meeting_id: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
) -> LearningInboxResponse:
    """
    Returns learning inbox items with distinct counts and eligible audio duration.
    Candidate counts reflect distinct verified events, meetings, and speakers.
    """
    actual_status = status_filter if isinstance(status_filter, str) else None
    actual_limit = limit if isinstance(limit, int) else 100
    counts = adaptation_store.count_distinct_accepted_events()
    eligible_duration = _calculate_eligible_audio_duration()
    events = adaptation_store.list_events(meeting_id=meeting_id, verification_status=actual_status, limit=actual_limit)

    return LearningInboxResponse(
        counts=counts,
        eligible_audio_duration_seconds=round(eligible_duration, 2),
        corrections=events,
    )


@router.post("/corrections/{event_id}/verify", response_model=CorrectionEvent)
def verify_correction(event_id: str, payload: VerifyCorrectionRequest) -> CorrectionEvent:
    """
    Explicit human verification of a transcript correction for dataset training eligibility.
    Requires:
    - Exact matching transcript revision (conflict protection)
    - Non-obsolete segment text
    - Explicit verified_against_audio=true and training_reuse_allowed=true
    - Eligible edit kind (transcription or normalization; excludes redactions, translations, and editorial edits)
    - Non-empty verbatim text
    - Reviewer audit label (does not claim authenticated clinical authority)
    """
    event_dict = adaptation_store.get_event(event_id)
    if not event_dict:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Correction event not found in catalog")

    meeting_id = event_dict["meeting_id"]
    with repository.lock:
        transcript = repository.get_transcript(meeting_id)
        if not transcript:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting transcript not found")

        ev = next((e for e in transcript.correction_events if e.id == event_id), None)
        if not ev:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found in transcript history")

        seg = next((s for s in transcript.segments if s.id == ev.segment_id), None)
        if not seg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found in transcript")

        # 1. Conflict protection & obsolete text check
        if payload.expected_revision != ev.transcript_revision:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Conflict: verification targeted revision {payload.expected_revision}, but event is at revision {ev.transcript_revision}.",
            )

        if seg.corrected_text != ev.new_text:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Conflict: cannot verify obsolete text; the segment has been further modified since this correction.",
            )

        # 2. Exclusions and policy requirements
        if not payload.verified_against_audio:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Audio verification is required: reviewer must confirm listening to the audio interval.",
            )

        if not payload.training_reuse_allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Explicit training reuse permission is required to verify an adaptation label.",
            )

        if not ev.new_text.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Empty deletion text cannot be verified as an acoustic training label.",
            )

        if payload.edit_kind in ("redaction", "translation", "editorial"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Edit kind '{payload.edit_kind}' is excluded from acoustic training datasets.",
            )

        if not payload.reviewer_label or not payload.reviewer_label.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reviewer label is required for audit provenance (note: typed name does not claim authenticated clinical authority).",
            )

        # 3. Apply verification
        ev.verified_against_audio = True
        ev.training_reuse_allowed = True
        ev.verification_status = "verified"
        ev.verified_by = payload.reviewer_label.strip()
        ev.verified_at = datetime.now(timezone.utc)
        ev.edit_kind = payload.edit_kind
        ev.rejection_reason = None

        repository.save_transcript(transcript)

        adaptation_store.upsert_event(
            ev,
            metadata={
                "audio_start": payload.audio_start,
                "audio_end": payload.audio_end,
                "collection_status": "collected",
            },
        )
        logger.info(f"Correction event {event_id} verified by {ev.verified_by} for meeting {meeting_id}")
        return ev


@router.post("/corrections/{event_id}/reject", response_model=CorrectionEvent)
def reject_correction(event_id: str, payload: RejectCorrectionRequest) -> CorrectionEvent:
    """
    Rejects a correction event from training reuse.
    Retains full audit history without removing the transcript change.
    """
    event_dict = adaptation_store.get_event(event_id)
    if not event_dict:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Correction event not found in catalog")

    meeting_id = event_dict["meeting_id"]
    with repository.lock:
        transcript = repository.get_transcript(meeting_id)
        if not transcript:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting transcript not found")

        ev = next((e for e in transcript.correction_events if e.id == event_id), None)
        if not ev:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found in transcript history")

        ev.verification_status = "rejected"
        ev.verified_against_audio = False
        ev.training_reuse_allowed = False
        ev.rejection_reason = payload.reason
        ev.verified_by = payload.reviewer_label.strip() if payload.reviewer_label else None
        ev.verified_at = datetime.now(timezone.utc)

        repository.save_transcript(transcript)

        adaptation_store.upsert_event(
            ev,
            metadata={"collection_status": "collected"},
        )
        logger.info(f"Correction event {event_id} marked rejected for training: {payload.reason}")
        return ev


@router.get("/rules", response_model=list[NormalizationRule])
def get_normalization_rules(version: Optional[str] = None) -> list[NormalizationRule]:
    """Lists packaged seed and locally approved dialect normalization rules."""
    return load_rules(version_filter=version)


@router.get("/rules/candidates", response_model=list[RuleCandidate])
def get_rule_candidates(
    min_occurrences: int = Query(2, ge=1, le=100),
    verified_only: bool = Query(False),
) -> list[RuleCandidate]:
    """Returns mined candidate normalization rules requiring clinician review."""
    return mine_candidates(min_occurrences=min_occurrences, verified_only=verified_only)


@router.post("/rules/{rule_id}/approve", response_model=NormalizationRule)
def approve_normalization_rule(rule_id: str, payload: ApproveRuleRequest) -> NormalizationRule:
    """
    Approves or activates a dialect normalization rule.
    Writes locally approved rule to ADAPTATION_DIR/rules.json without touching tracked code.
    """
    rules = load_rules()
    target_rule = next((r for r in rules if r.id == rule_id), None)
    if not target_rule:
        # If not an existing rule, check if it's a mined candidate ID
        candidates = mine_candidates(min_occurrences=1)
        candidate = next((c for c in candidates if c.id == rule_id), None)
        if not candidate:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule or candidate not found")
        target_rule = NormalizationRule(
            id=f"learned_{candidate.language}_{rule_id[:8]}",
            language=candidate.language,
            variants=[candidate.detected_variant],
            canonical=payload.canonical or candidate.suggested_canonical,
            scope="clinical",
            action=payload.action or ("safe_replace" if candidate.is_safe_candidate else "suggest_only"),
            version="local-v1",
            approval="approved",
        )
    else:
        if payload.action:
            target_rule.action = payload.action
        if payload.canonical:
            target_rule.canonical = payload.canonical
        target_rule.approval = "approved"

    save_local_rule(target_rule)
    logger.info(f"Dialect normalization rule {target_rule.id} approved by {payload.reviewer_label}")
    return target_rule


@router.post("/rules/{rule_id}/rollback", response_model=NormalizationRule)
def rollback_normalization_rule(rule_id: str, payload: RollbackRuleRequest) -> NormalizationRule:
    """
    Rolls back or disables a dialect normalization rule.
    Persists rollback state in ADAPTATION_DIR/rules.json.
    """
    rules = load_rules()
    target_rule = next((r for r in rules if r.id == rule_id), None)
    if not target_rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")

    target_rule.approval = "rolled_back"
    save_local_rule(target_rule)
    logger.info(f"Dialect normalization rule {rule_id} rolled back by {payload.reviewer_label}: {payload.reason}")
    return target_rule
