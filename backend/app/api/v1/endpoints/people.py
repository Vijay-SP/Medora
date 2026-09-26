"""
Medpark Meeting Intelligence System - People & Voice Enrollment Endpoints (prefix /voice-profiles)

Enrollment is explicit and consented: a person records prompted samples, each sample is assessed, and the
active voiceprint is rebuilt from every stored sample. No endpoint ever returns an embedding vector and no
endpoint enrolls from meeting audio (retro-enrollment is refused by design, see docs/SPEAKER_IDENTITY_DESIGN.md §5.5).
"""

from datetime import datetime, timezone
from pathlib import Path
import shutil
import tempfile
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
import numpy as np
import soundfile as sf

from app.core.config import settings
from app.core.exceptions import AudioProcessingError
from app.core.logging import logger
from app.models.person import (
    EMBEDDING_MODEL_NAME,
    ConsentRecord,
    Person,
    PersonSummary,
    SampleQuality,
    Voiceprint,
    compute_space_id,
    summarize_person,
)
from app.services.audio.preprocessor import audio_preprocessor
from app.services.diarization.embedder import speaker_embedder
from app.services.diarization.enrollment import assess_sample, build_voiceprint
from app.storage.file_manager import file_manager
from app.storage.repository import repository

router = APIRouter(prefix="/voice-profiles", tags=["People & Voices"])

CONSENT_STATEMENT_VERSION = "v1"


class VoiceProfileCreateRequest(BaseModel):
    person_name: str = Field(..., min_length=1, max_length=200)
    role: str = "Member"
    email: str = ""


class ConsentRequest(BaseModel):
    granted: bool


class VoiceStatusResponse(BaseModel):
    enabled: bool
    embedder_available: bool
    space_id: Optional[str] = None
    model: str = EMBEDDING_MODEL_NAME
    dim: Optional[int] = None
    enrolled: int = 0
    not_enrolled: int = 0
    needs_reenrollment: int = 0


def _embedder_available() -> bool:
    """The feature flag and the ONNX session must both hold; probing loads the model lazily (CPU only)."""
    return bool(settings.VOICE_ID_ENABLED) and speaker_embedder.available


def _active_space_id() -> Optional[str]:
    """The embedder's own space id; the digest-based fallback only bridges a session that failed to load."""
    space_id = speaker_embedder.space_id
    if space_id:
        return space_id
    digest = speaker_embedder.model_sha256
    return compute_space_id(digest) if digest else None


def _get_person_or_404(person_id: str) -> Person:
    person = repository.get_person(person_id)
    if not person:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice profile not found")
    return person


def _summary(person: Person) -> PersonSummary:
    return summarize_person(person, _active_space_id())


def _purge_biometrics(person: Person) -> int:
    """
    Removes every voiceprint artifact and enrollment sample of a person; idempotent (0 when nothing is left).

    Suggestions on meeting transcripts were computed from the voiceprint that is being deleted, so they go
    with it: pending "Is this {name}?" questions are reverted to anonymous on every meeting. Names a reviewer
    already confirmed are snapshots and stay (a signed document must not change because a record was removed).
    """
    removed = file_manager.purge_person_biometrics(person.id)
    person.voiceprints = []
    anonymised = repository.anonymise_suggestions_for_person(person.id)
    if anonymised:
        logger.info(f"Reverted {anonymised} pending speaker suggestion(s) for person {person.id} after purging its voiceprint")
    return removed


def _load_wav16k(wav_path: Path) -> np.ndarray:
    """Mono float32 waveform at the embedder's rate, from a WAV the preprocessor already normalized."""
    data, sample_rate = sf.read(str(wav_path), dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    if sample_rate != settings.DEFAULT_SAMPLE_RATE:
        raise AudioProcessingError(f"Normalized sample is {sample_rate} Hz, expected {settings.DEFAULT_SAMPLE_RATE} Hz")
    return np.ascontiguousarray(data, dtype=np.float32)


def _next_sample_index(person_id: str) -> int:
    existing = file_manager.list_enrollment_sample_paths(person_id)
    indices = [int(p.stem) for p in existing if p.stem.isdigit()]
    return (max(indices) + 1) if indices else 0


def _rebuild_voiceprint(person: Person) -> Voiceprint:
    """
    Rebuilds the person's voiceprint from ALL stored samples via enrollment.build_voiceprint, which writes the
    vector as .npy, decides is_active against the enrollment thresholds and explains any shortfall in
    quality_warnings. Previous artifacts are removed so exactly one descriptor per person remains.
    """
    sample_paths = file_manager.list_enrollment_sample_paths(person.id)
    voiceprint, _embeddings = build_voiceprint(person.id, sample_paths)
    for previous in person.voiceprints:
        if previous.id != voiceprint.id:
            file_manager.get_voiceprint_path(person.id, previous.id).unlink(missing_ok=True)
    person.voiceprints = [voiceprint]
    return voiceprint


@router.get("/status", response_model=VoiceStatusResponse)
def get_voice_status() -> VoiceStatusResponse:
    """Feature availability plus enrollment counts; never a vector."""
    available = _embedder_available()
    space_id = _active_space_id()
    counts = {"enrolled": 0, "not_enrolled": 0, "needs_reenrollment": 0}
    for person in repository.list_people():
        counts[person.enrollment_state(space_id)] += 1
    return VoiceStatusResponse(
        enabled=available,
        embedder_available=speaker_embedder.available,
        space_id=space_id,
        model=EMBEDDING_MODEL_NAME,
        dim=speaker_embedder.dim if speaker_embedder.available else None,
        **counts,
    )


# The collection routes are registered slash-less ("/api/v1/voice-profiles"), exactly as the frontend calls
# them: with the SPA mounted by StaticFiles at "/", a slash-less request never reaches Starlette's
# redirect_slashes, so a "/"-only route is a 404/405 from the built UI. "/" stays as a hidden alias.
@router.get("", response_model=list[PersonSummary])
@router.get("/", response_model=list[PersonSummary], include_in_schema=False)
def list_voice_profiles() -> list[PersonSummary]:
    """Lists active people with their enrollment state."""
    return [_summary(person) for person in repository.list_people()]


@router.post("", response_model=PersonSummary, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=PersonSummary, status_code=status.HTTP_201_CREATED, include_in_schema=False)
def create_voice_profile(payload: VoiceProfileCreateRequest) -> PersonSummary:
    """Creates a person record; enrollment requires consent and samples afterwards."""
    person = Person(full_name=payload.person_name.strip(), role=payload.role.strip() or "Member", email=payload.email.strip())
    repository.save_person(person)
    logger.info(f"Created voice profile {person.id} for {person.full_name}")
    return _summary(person)


@router.get("/{person_id}", response_model=PersonSummary)
def get_voice_profile(person_id: str) -> PersonSummary:
    """Returns one person's enrollment summary."""
    return _summary(_get_person_or_404(person_id))


@router.delete("/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_voice_profile(person_id: str) -> None:
    """
    Removes the person and every biometric artifact. Names already confirmed on past meetings are
    snapshots and stay: a signed document must not change because a staff record was deleted.
    """
    person = _get_person_or_404(person_id)
    removed = _purge_biometrics(person)
    repository.delete_person(person.id)
    logger.info(f"Deleted voice profile {person.id} ({removed} biometric file(s) purged)")


@router.post("/{person_id}/consent", response_model=PersonSummary)
def set_voice_consent(person_id: str, payload: ConsentRequest) -> PersonSummary:
    """Records or withdraws biometric consent; withdrawal deletes all voiceprints and samples."""
    person = _get_person_or_404(person_id)
    now = datetime.now(timezone.utc)
    if payload.granted:
        # Enrollment samples are kept so the voiceprint can be rebuilt from all of them (and re-enrolled on
        # a model change); the consent statement covers that retention.
        person.consent = ConsentRecord(given=True, given_at=now, statement_version=CONSENT_STATEMENT_VERSION, retain_audio=True)
        logger.info(f"Biometric consent recorded for person {person.id}")
    else:
        if person.consent is None:
            person.consent = ConsentRecord(given=False, statement_version=CONSENT_STATEMENT_VERSION)
        person.consent.withdrawn_at = now
        person.consent.retain_audio = False
        removed = _purge_biometrics(person)
        logger.info(f"Biometric consent withdrawn for person {person.id}; {removed} biometric file(s) purged")
    repository.save_person(person)
    return _summary(person)


@router.post("/{person_id}/samples", response_model=SampleQuality)
async def upload_voice_sample(person_id: str, file: UploadFile = File(...)) -> SampleQuality:
    """
    Assesses one prompted enrollment recording. A rejected sample stores nothing; an accepted one is kept
    as 16 kHz WAV and the person's voiceprint is rebuilt from every stored sample.
    """
    person = await run_in_threadpool(_get_person_or_404, person_id)
    if not person.consent_effective:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Biometric consent has not been given for this person; record consent before enrolling"
        )
    if not _embedder_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=speaker_embedder.load_error or "Speaker embedder unavailable or voice identification disabled"
        )

    suffix = Path(file.filename or "sample.webm").suffix.lower() or ".webm"
    if suffix not in file_manager.ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported audio format '{suffix}'. Allowed: {', '.join(sorted(file_manager.ALLOWED_AUDIO_EXTENSIONS))}"
        )

    def _assess_and_store() -> SampleQuality:
        with tempfile.TemporaryDirectory(prefix="medpark_enroll_") as tmp:
            source = Path(tmp) / f"upload{suffix}"
            with open(source, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            normalized, _duration = audio_preprocessor.normalize(source, Path(tmp) / "sample_16k.wav")
            quality = assess_sample(_load_wav16k(normalized))
            if quality.verdict == "reject":
                logger.info(f"Enrollment sample rejected for person {person.id}: {'; '.join(quality.reasons)}")
                return quality

            target = file_manager.get_enrollment_sample_path(person.id, _next_sample_index(person.id))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(normalized, target)

        voiceprint = _rebuild_voiceprint(person)
        repository.save_person(person)
        # The enrollment verdict rides along with the sample verdict so the drawer can show both verbatim.
        if voiceprint.is_active:
            quality.reasons.append(
                f"Enrollment complete: {voiceprint.sample_count} sample(s), {voiceprint.total_speech_seconds:.1f} s of speech."
            )
        else:
            quality.reasons.extend(w for w in voiceprint.quality_warnings if w not in quality.reasons)
        logger.info(
            f"Enrollment sample accepted for person {person.id} ({quality.verdict}); voiceprint "
            f"{'active' if voiceprint.is_active else 'pending'} with {voiceprint.total_speech_seconds:.1f} s of speech"
        )
        return quality

    return await run_in_threadpool(_assess_and_store)


@router.delete("/{person_id}/samples", status_code=status.HTTP_204_NO_CONTENT)
def wipe_voice_samples(person_id: str) -> None:
    """Deletes all samples and voiceprints of a person so enrollment can start over."""
    person = _get_person_or_404(person_id)
    removed = _purge_biometrics(person)
    repository.save_person(person)
    logger.info(f"Wiped enrollment of person {person.id} ({removed} biometric file(s) purged)")
