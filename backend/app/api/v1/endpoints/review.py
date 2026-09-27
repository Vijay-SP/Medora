"""
Medpark Meeting Intelligence System - Review Workspace & Approval Endpoints

Stored minutes name people only through anonymous speaker tokens (S1, "Speaker 1"). Readers get them RESOLVED
by default (names where a reviewer confirmed/labelled the cluster, "Vorbitorul N" otherwise) through the
render layer; ?names=labels returns the stored token form. A PUT stores only what the reviewer actually
edited: every field still equal to its rendered form keeps its stored token text (see update_minutes).
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal, Optional
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from app.models.meeting import ProcessingStatus, ReviewStatus
from app.models.extraction import MinutesOfMeeting
from app.models.delivery import DeliveryRecord, DeliveryStatus
from app.models.transcript import Transcript
from app.storage.repository import repository
from app.storage.file_manager import file_manager
from app.services.documents.generator import document_generator, render_minutes_for_reader
from app.services.extraction.attribution_render import ANON, build_label_map
from app.services.delivery.router import delivery_router
from app.services.delivery.smtp_service import smtp_service
from app.services.delivery.n8n_service import n8n_service
from app.core.config import settings
from app.core.exceptions import DeliveryError
from app.core.logging import logger
from app.services.delivery.dispatch_lock import dispatch_lock, record_outcome

router = APIRouter(prefix="/meetings/{meeting_id}", tags=["Review & Approval"])


class ApprovalRequest(BaseModel):
    reviewer_name: str = "Dr. Elena Ceban"
    reviewer_role: str = "Director Medical / Reviewer"
    comments: str | None = None
    expected_revision: int | None = None  # Revision the reviewer actually read and signed off


class ApprovalResponse(BaseModel):
    meeting_id: str
    status: ReviewStatus
    approved_by: str
    approved_at: datetime
    revision: int
    delivery_record: DeliveryRecord | None


NamesMode = Literal["resolved", "labels"]


def _transcript_for(meeting_id: str) -> Transcript:
    """The stored transcript; without one there is nothing a name could be verified against (everything anonymous)."""
    return repository.get_transcript(meeting_id) or Transcript(meeting_id=meeting_id)


def _resolved(minutes: MinutesOfMeeting) -> MinutesOfMeeting:
    """
    The minutes as a reader sees them: prose speaker tokens resolved against the stored transcript, owners and
    evidence speakers as stored (per-segment printable rule) - exactly what the PDF/DOCX print.
    """
    return render_minutes_for_reader(minutes, _transcript_for(minutes.meeting_id))


# ---------------------------------------------------------------- PUT: un-rendering what the reader was shown
_Restorer = tuple[re.Pattern, Callable[[re.Match], str]]

_SUMMARY_FIELDS = (("summary_ro", "ro"), ("summary_ru", "ru"), ("summary_en", "en"))
_AGENDA_FIELDS = (("agenda_topics", "ro"), ("agenda_topics_ru", "ru"), ("agenda_topics_en", "en"))
_DECISION_FIELDS = (("topic", "ro"), ("decision", "ro"), ("topic_ru", "ru"), ("decision_ru", "ru"), ("topic_en", "en"), ("decision_en", "en"))
_ACTION_FIELDS = (("task", "ro"), ("task_ru", "ru"), ("task_en", "en"),
                  ("deadline_phrase", "ro"), ("deadline_phrase_ru", "ru"), ("deadline_phrase_en", "en"))
_RISK_FIELDS = (("description", "ro"), ("description_ru", "ru"), ("description_en", "en"))
_SERVER_OWNED_OWNER_SOURCES = ("speaker", "confirmed_speaker")


def _token_restorers(transcript: Transcript) -> dict[str, list[_Restorer]]:
    """
    Per locale, the substitutions that turn rendered display text back into S<n> tokens: every display name the
    render layer currently prints (longest first; a name shared by several clusters maps to the lowest label,
    which renders identically), then the anonymous localized form of any number.
    """
    restorers: dict[str, list[_Restorer]] = {}
    for locale in ("ro", "ru", "en"):
        by_display: dict[str, int] = {}
        for key, display in build_label_map(transcript, locale).items():
            match = re.fullmatch(r"S(\d+)", key)
            if match and display:
                n = int(match.group(1))
                by_display[display] = min(n, by_display.get(display, n))
        pairs: list[_Restorer] = [
            (re.compile(r"(?<!\w)" + re.escape(display) + r"(?!\w)"), lambda _m, n=n: f"S{n}")
            for display, n in sorted(by_display.items(), key=lambda kv: -len(kv[0]))
        ]
        prefix, _, suffix = ANON[locale].partition("{n}")
        pairs.append((re.compile(r"(?<!\w)" + re.escape(prefix) + r"(\d{1,2})" + re.escape(suffix) + r"(?!\w)"),
                      lambda m: f"S{int(m.group(1))}"))
        restorers[locale] = pairs
    return restorers


def _to_tokens(text: Optional[str], restorers: Optional[list[_Restorer]]) -> Optional[str]:
    if not text or restorers is None:
        return text
    for pattern, replacement in restorers:
        text = pattern.sub(replacement, text)
    return text


def _keep_unless_edited(submitted: Optional[str], shown: Optional[str], stored: Optional[str],
                        restorers: Optional[list[_Restorer]]) -> Optional[str]:
    """Unchanged (still the rendered text) -> the stored token text; edited -> the edit with rendered speakers re-tokenised."""
    if submitted == shown:
        return stored
    return _to_tokens(submitted, restorers)


def _keep_unless_edited_list(submitted: Optional[list[str]], shown: Optional[list[str]], stored: Optional[list[str]],
                             restorers: Optional[list[_Restorer]]) -> Optional[list[str]]:
    """Element-wise version for the agenda lists: an unchanged topic (wherever it moved) keeps its stored text."""
    if submitted == shown:
        return stored
    if submitted is None:
        return None
    originals: dict[str, str] = {}
    for shown_text, stored_text in zip(shown or [], stored or []):
        originals.setdefault(shown_text, stored_text)
    return [originals[text] if text in originals else (_to_tokens(text, restorers) or "") for text in submitted]


def _restore_stored_tokens(updated: MinutesOfMeeting, stored: MinutesOfMeeting, transcript: Transcript) -> int:
    """
    Readers (and the UI's editor) receive RESOLVED minutes, and a client that saves one field sends the whole
    object back. Storing that verbatim would bake the currently printed names (and frozen "Vorbitorul N" forms)
    into every field: a later reject/unknown could no longer revoke them, a later label could no longer render,
    and the translation LLM would see them. So, field by field (items matched by id): a value still equal to what
    the reader was shown keeps the stored token text; an edited value is stored as typed, with the names and
    anonymous forms the render layer prints turned back into S<n> tokens (labelled minutes only; impersonal
    minutes carry no tokens). Evidence speakers and speaker-attributed owners are server-owned: speakers.py keeps
    them per segment (printable floor). Returns the number of edited fields.
    """
    shown = render_minutes_for_reader(stored, transcript)
    restorers = _token_restorers(transcript) if stored.speaker_label_style == "labels" else {}
    edited = 0

    def merge(target, shown_obj, stored_obj, fields, keep=_keep_unless_edited) -> None:
        nonlocal edited
        for field, locale in fields:
            submitted = getattr(target, field)
            shown_value = getattr(shown_obj, field) if shown_obj is not None else None
            stored_value = getattr(stored_obj, field) if stored_obj is not None else None
            edited += submitted != shown_value
            setattr(target, field, keep(submitted, shown_value, stored_value, restorers.get(locale)))

    merge(updated, shown, stored, _SUMMARY_FIELDS)
    merge(updated, shown, stored, _AGENDA_FIELDS, keep=_keep_unless_edited_list)

    for kind, fields in (("decisions", _DECISION_FIELDS), ("action_items", _ACTION_FIELDS), ("risks_and_questions", _RISK_FIELDS)):
        stored_by_id = {item.id: item for item in getattr(stored, kind)}
        shown_by_id = {item.id: item for item in getattr(shown, kind)}
        for item in getattr(updated, kind):
            stored_item = stored_by_id.get(item.id)
            merge(item, shown_by_id.get(item.id), stored_item, fields)
            if stored_item is None:
                continue
            stored_quotes = {quote.segment_id: quote for quote in stored_item.evidence}
            for quote in item.evidence:
                original = stored_quotes.get(quote.segment_id)
                if original is not None:
                    quote.speaker = original.speaker
                    quote.speaker_person_id = original.speaker_person_id
                    quote.speaker_is_confirmed = original.speaker_is_confirmed
            if (kind == "action_items" and stored_item.owner_source in _SERVER_OWNED_OWNER_SOURCES
                    and item.owner_source in _SERVER_OWNED_OWNER_SOURCES):
                if item.owner != stored_item.owner:
                    logger.warning(f"Minutes {stored.meeting_id}: owner of action {item.id} comes from speaker attribution; "
                                   f"keeping the stored owner instead of the submitted one")
                item.owner, item.owner_source = stored_item.owner, stored_item.owner_source
    return edited


@router.get("/minutes", response_model=MinutesOfMeeting)
def get_minutes(meeting_id: str, names: NamesMode = Query("resolved", description="resolved: names where allowed; labels: stored S<n> tokens")) -> MinutesOfMeeting:
    """Retrieves the extracted Minutes of Meeting with decisions and actions, speaker tokens resolved by default."""
    minutes = repository.get_minutes(meeting_id)
    if not minutes:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Minutes not generated for this meeting")
    return _resolved(minutes) if names == "resolved" else minutes


@router.put("/minutes", response_model=MinutesOfMeeting)
def update_minutes(meeting_id: str, updated_minutes: MinutesOfMeeting) -> MinutesOfMeeting:
    """
    Allows clinical reviewer to edit summary, decisions, or action items before sign-off.

    Only what the reviewer actually changed is stored as typed: a field sent back exactly as the resolved GET
    rendered it keeps its stored token text, so saving one field never freezes the currently printed names into
    the others (see _restore_stored_tokens). Either GET form (resolved or ?names=labels) may be sent back.
    """
    meeting = repository.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")

    # An edit is always a new revision of a document the pipeline produced: with nothing stored there
    # is no server-owned provenance to inherit, and the caller could otherwise mint one from scratch.
    stored_minutes = repository.get_minutes(meeting_id)
    if not stored_minutes:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Minutes not generated for this meeting")

    # Lost-update guard: refuse edits written against an outdated revision
    if updated_minutes.revision < stored_minutes.revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Revision conflict: minutes were updated to Rev.{stored_minutes.revision} while you were editing Rev.{updated_minutes.revision}. Reload before saving."
        )

    updated_minutes.meeting_id = meeting_id
    updated_minutes.revision = meeting.current_revision + 1
    meeting.current_revision = updated_minutes.revision

    # Extraction provenance is server-owned and survives every edit: the payload's defaults
    # (is_degraded=False, a generic model_version, empty stats) must never launder a degraded
    # draft past assert_dispatchable() or erase the audit trail. Only needs_name_review stays
    # editable, because confirming non-roster names is exactly the reviewer's job.
    updated_minutes.is_degraded = stored_minutes.is_degraded
    updated_minutes.model_version = stored_minutes.model_version
    updated_minutes.failed_chunks = list(stored_minutes.failed_chunks)
    updated_minutes.extraction_stats = dict(stored_minutes.extraction_stats)
    updated_minutes.source_transcript_revision = stored_minutes.source_transcript_revision
    updated_minutes.needs_transcript_review = stored_minutes.needs_transcript_review
    # The token form of the stored prose is server-owned as well; names resolved for display go back to tokens.
    updated_minutes.speaker_label_style = stored_minutes.speaker_label_style
    edited = _restore_stored_tokens(updated_minutes, stored_minutes, _transcript_for(meeting_id))
    logger.info(f"Minutes {meeting_id} Rev.{updated_minutes.revision}: {edited} field(s) edited by the reviewer")

    # Invalidate prior approval for the new revision
    if meeting.review_status in (ReviewStatus.APPROVED, ReviewStatus.DELIVERED):
        meeting.review_status = ReviewStatus.PENDING_REVIEW
        meeting.approved_by = None
        meeting.approved_at = None
    
    # Re-generate PDF and DOCX with the new revision
    pdf_path, docx_path = file_manager.get_export_paths(meeting.id, revision=updated_minutes.revision)
    document_generator.generate_all(meeting, updated_minutes, pdf_path, docx_path)
    
    updated_minutes.pdf_path = str(pdf_path)
    updated_minutes.docx_path = str(docx_path)
    
    repository.save_meeting(meeting)
    return repository.save_minutes(updated_minutes)


@router.post("/review/approve", response_model=ApprovalResponse)
async def approve_and_dispatch(meeting_id: str, payload: ApprovalRequest) -> ApprovalResponse:
    with dispatch_lock():
        return await _approve_and_dispatch(meeting_id, payload)


async def _approve_and_dispatch(meeting_id: str, payload: ApprovalRequest) -> ApprovalResponse:
    """
    Formal human sign-off gate:
    1. Validates meeting state, prior delivery, and the revision the reviewer signed off
    2. Marks document as APPROVED
    3. Triggers automated delivery to official distribution lists via local SMTP and n8n
    """
    meeting = repository.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")

    minutes = repository.get_minutes(meeting_id)
    if not minutes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot approve meeting without generated minutes")

    if meeting.processing_status != ProcessingStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot approve meeting while processing is '{meeting.processing_status.value}'"
        )

    if meeting.review_status == ReviewStatus.DELIVERED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Minutes Rev.{minutes.revision} were already delivered. Edit the minutes to create a new revision before dispatching again."
        )

    if payload.expected_revision is not None and payload.expected_revision != minutes.revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Revision conflict: you reviewed Rev.{payload.expected_revision} but the stored minutes are at Rev.{minutes.revision}. Reload before approving."
        )

    # A degraded draft can neither be approved nor sent: checked before any state is mutated
    try:
        delivery_router.assert_dispatchable(minutes)
    except DeliveryError as guard:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=guard.message)

    # Repeated approvals return the already prepared attempt. Retrying delivery is a separate,
    # explicit action on the saved message, never an incidental effect of signing twice.
    prior = next((r for r in repository.list_deliveries(meeting_id) if r.revision == minutes.revision), None)
    if (prior and (prior.eml_available or prior.status in (DeliveryStatus.PENDING, DeliveryStatus.DISPATCHED))
            and meeting.review_status == ReviewStatus.APPROVED and meeting.approved_at):
        return ApprovalResponse(
            meeting_id=meeting.id, status=meeting.review_status, approved_by=meeting.approved_by,
            approved_at=meeting.approved_at, revision=minutes.revision, delivery_record=prior,
        )

    now = datetime.now(timezone.utc)
    meeting.review_status = ReviewStatus.APPROVED
    meeting.approved_by = f"{payload.reviewer_name} ({payload.reviewer_role})"
    meeting.approved_at = now
    meeting.error_message = None  # Clear any delivery error left by a previous attempt
    repository.save_meeting(meeting)

    # Deliver via exclusive channel: n8n or direct SMTP, both addressing the same resolved list
    pdf_path = Path(minutes.pdf_path) if minutes.pdf_path else None
    docx_path = Path(minutes.docx_path) if minutes.docx_path else None
    recipients = delivery_router.resolve_recipients(meeting)

    if settings.DELIVERY_CHANNEL == "n8n" and settings.N8N_ENABLED:
        delivery_rec = await n8n_service.trigger_workflow(meeting, minutes, recipients)
    else:
        delivery_rec = await smtp_service.deliver(meeting, minutes, pdf_path, docx_path, recipients)

    current = record_outcome(delivery_rec)

    return ApprovalResponse(
        meeting_id=meeting.id,
        status=current.review_status,
        approved_by=meeting.approved_by,
        approved_at=now,
        revision=minutes.revision,
        delivery_record=delivery_rec
    )


@router.post("/translate", response_model=MinutesOfMeeting)
async def translate_minutes(
    meeting_id: str,
    target_lang: Literal["ro", "ru", "en"] = "ru",
    force: bool = False,
) -> MinutesOfMeeting:
    """
    Translates dynamic MoM items (topics, decisions, actions, risks) into the target language.
    Results are cached on the minutes entity so repeated calls return instantly without extra LLM load.
    Translation always runs on the stored token text (labels survive it verbatim); the response is resolved
    for the reader exactly like GET /minutes.
    """
    minutes = repository.get_minutes(meeting_id)
    if not minutes:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Minutes not generated for this meeting")

    if target_lang == "ro":
        return _resolved(minutes)

    from app.services.translation.translation_service import translation_service
    updated = await translation_service.translate_mom(minutes, target_lang=target_lang, force_refresh=force)
    return _resolved(updated)


@router.post("/minutes/refresh", response_model=MinutesOfMeeting)
async def refresh_minutes(meeting_id: str) -> MinutesOfMeeting:
    """
    Regenerates Minutes of Meeting through the extraction engine using the current transcript.
    Clears needs_transcript_review flag, advances minutes revision, and invalidates previous approval.
    Does not automatically approve or send.
    """
    meeting = repository.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")

    transcript = repository.get_transcript(meeting_id)
    if not transcript:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transcript not found for this meeting")

    from app.services.extraction.extractor import extraction_engine

    minutes = await extraction_engine.extract_minutes(meeting, transcript)
    minutes.source_transcript_revision = transcript.revision
    minutes.needs_transcript_review = False
    minutes.revision = meeting.current_revision + 1
    meeting.current_revision = minutes.revision

    # Invalidate prior approval for the new revision
    meeting.review_status = ReviewStatus.PENDING_REVIEW
    meeting.approved_by = None
    meeting.approved_at = None

    pdf_path, docx_path = file_manager.get_export_paths(meeting.id, revision=minutes.revision)
    document_generator.generate_all(meeting, minutes, pdf_path, docx_path, transcript=transcript)

    minutes.pdf_path = str(pdf_path)
    minutes.docx_path = str(docx_path)

    repository.save_meeting(meeting)
    repository.save_minutes(minutes)
    logger.info(f"Minutes for meeting {meeting_id} refreshed to Rev.{minutes.revision} against transcript Rev.{transcript.revision}")
    return _resolved(minutes)


