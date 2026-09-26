"""
Medpark Meeting Intelligence System - Local File & Artifact Storage
Handles audio uploads, document exports, and SHA-256 cryptographic verification offline.
"""

import hashlib
import re
import shutil
from pathlib import Path
from typing import BinaryIO
from app.core.config import settings
from app.core.exceptions import AudioProcessingError, ResourceNotFoundError
from app.core.logging import logger

# Meeting identifiers are joined into filesystem paths, so only opaque id characters are accepted.
MEETING_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class FileManager:
    """Manages secure local storage for audio recordings and generated minutes."""

    ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".webm", ".ogg", ".aac", ".flac", ".mp4"}

    def __init__(self):
        settings.ensure_directories()

    def _validate_meeting_id(self, meeting_id: str) -> str:
        """Rejects identifiers that could escape the storage directories (path traversal)."""
        if not isinstance(meeting_id, str) or not MEETING_ID_PATTERN.match(meeting_id):
            logger.warning(f"Rejected unsafe meeting identifier for filesystem access: {meeting_id!r}")
            raise ResourceNotFoundError(f"Invalid meeting identifier '{meeting_id}'")
        return meeting_id

    def compute_sha256(self, file_path: Path) -> str:
        """Computes SHA-256 checksum of an audio or document file for audit integrity."""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    def save_uploaded_audio(self, meeting_id: str, filename: str, file_obj: BinaryIO) -> Path:
        """Saves incoming audio file to the local uploads directory."""
        self._validate_meeting_id(meeting_id)
        ext = Path(filename).suffix.lower()
        if ext not in self.ALLOWED_AUDIO_EXTENSIONS:
            raise AudioProcessingError(f"Unsupported audio format '{ext}'. Allowed: {', '.join(self.ALLOWED_AUDIO_EXTENSIONS)}")

        dest_dir = settings.UPLOADS_DIR / meeting_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        
        target_path = dest_dir / f"original{ext}"
        with open(target_path, "wb") as buffer:
            shutil.copyfileobj(file_obj, buffer)
            
        logger.info(f"Saved uploaded audio for meeting {meeting_id} to {target_path} ({target_path.stat().st_size} bytes)")
        return target_path

    def get_normalized_audio_path(self, meeting_id: str) -> Path:
        """Returns the standard 16kHz mono WAV path for a meeting."""
        self._validate_meeting_id(meeting_id)
        return settings.UPLOADS_DIR / meeting_id / "normalized_16k.wav"

    def get_export_paths(self, meeting_id: str, revision: int = 1) -> tuple[Path, Path]:
        """Returns the PDF and DOCX export paths for a meeting revision."""
        self._validate_meeting_id(meeting_id)
        export_dir = settings.EXPORTS_DIR / meeting_id
        export_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = export_dir / f"Medpark_MoM_Rev{revision}.pdf"
        docx_path = export_dir / f"Medpark_MoM_Rev{revision}.docx"
        return pdf_path, docx_path

    def purge_meeting_artifacts(self, meeting_id: str) -> None:
        """Removes the uploaded audio and generated exports of a deleted meeting (PHI retention)."""
        self._validate_meeting_id(meeting_id)
        failures: list[str] = []
        for directory in [settings.UPLOADS_DIR / meeting_id, settings.EXPORTS_DIR / meeting_id]:
            if not directory.exists():
                continue
            try:
                shutil.rmtree(directory)
                logger.info(f"Purged artifact directory {directory} for meeting {meeting_id}")
            except OSError as exc:
                # An open handle (pipeline reading the audio, download in flight) locks one
                # directory on Windows; the remaining artifacts must still be purged.
                failures.append(f"{directory}: {exc}")
        if failures:
            raise OSError(f"Artifacts still in use for meeting {meeting_id}: {'; '.join(failures)}")

    # --- Biometric artifacts (VOICEPRINTS_DIR only; nothing biometric ever goes into a JSON store) ---
    def _validate_opaque_id(self, value: str, kind: str) -> str:
        """Person, voiceprint and meeting ids share the same opaque-id rule before touching the filesystem."""
        if not isinstance(value, str) or not MEETING_ID_PATTERN.match(value):
            logger.warning(f"Rejected unsafe {kind} identifier for filesystem access: {value!r}")
            raise ResourceNotFoundError(f"Invalid {kind} identifier '{value}'")
        return value

    def _person_dir(self, person_id: str) -> Path:
        self._validate_opaque_id(person_id, "person")
        return settings.VOICEPRINTS_DIR / "people" / person_id

    def _meeting_embeddings_dir(self, meeting_id: str) -> Path:
        self._validate_meeting_id(meeting_id)
        return settings.VOICEPRINTS_DIR / "meetings" / meeting_id

    def get_voiceprint_path(self, person_id: str, voiceprint_id: str) -> Path:
        """Absolute .npy path of one voiceprint (Voiceprint.artifact_path stores it relative to VOICEPRINTS_DIR)."""
        self._validate_opaque_id(voiceprint_id, "voiceprint")
        return self._person_dir(person_id) / f"{voiceprint_id}.npy"

    def get_enrollment_sample_path(self, person_id: str, index: int) -> Path:
        """Absolute path of the index-th stored enrollment sample (16 kHz mono PCM16 WAV)."""
        if not isinstance(index, int) or index < 0:
            raise ResourceNotFoundError(f"Invalid enrollment sample index {index!r}")
        return self._person_dir(person_id) / "samples" / f"{index:03d}.wav"

    def list_enrollment_sample_paths(self, person_id: str) -> list[Path]:
        """Stored enrollment samples of a person in index order (empty when none were kept)."""
        samples_dir = self._person_dir(person_id) / "samples"
        if not samples_dir.is_dir():
            return []
        return sorted(p for p in samples_dir.glob("*.wav") if p.is_file())

    def get_segment_embedding_paths(self, meeting_id: str) -> tuple[Path, Path]:
        """Cached per-segment embedding matrix (.npy) and its sidecar (.json) for a meeting."""
        directory = self._meeting_embeddings_dir(meeting_id)
        return directory / "segments.npy", directory / "segments.json"

    def save_embedding_matrix(self, path: Path, matrix) -> str:
        """Writes an embedding matrix as .npy (atomic replace) and returns the sha256 of the written file."""
        import numpy as np

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f"{path.stem}.{path.suffix.lstrip('.')}.tmp.npy")
        try:
            np.save(temp_path, np.asarray(matrix, dtype=np.float32), allow_pickle=False)
            temp_path.replace(path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
        return self.compute_sha256(path)

    def _remove_tree(self, directory: Path, what: str) -> int:
        """Removes a directory tree, returning the number of files deleted (0 when absent)."""
        if not directory.exists():
            return 0
        count = sum(1 for p in directory.rglob("*") if p.is_file())
        shutil.rmtree(directory)
        logger.info(f"Purged {count} {what} file(s) under {directory}")
        return count

    def purge_person_biometrics(self, person_id: str) -> int:
        """Deletes every voiceprint and enrollment sample of a person (consent withdrawal / profile deletion)."""
        return self._remove_tree(self._person_dir(person_id), "biometric")

    def purge_meeting_embeddings(self, meeting_id: str) -> int:
        """Deletes the cached segment embeddings of a meeting (new upload / meeting deletion)."""
        return self._remove_tree(self._meeting_embeddings_dir(meeting_id), "segment embedding")


file_manager = FileManager()
