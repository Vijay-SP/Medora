"""
Medpark Meeting Intelligence System - Local File & Artifact Storage
Handles audio uploads, document exports, and SHA-256 cryptographic verification offline.
"""

import hashlib
import shutil
from pathlib import Path
from typing import BinaryIO
from app.core.config import settings
from app.core.exceptions import AudioProcessingError
from app.core.logging import logger


class FileManager:
    """Manages secure local storage for audio recordings and generated minutes."""
    
    ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".webm", ".ogg", ".aac", ".flac"}

    def __init__(self):
        settings.ensure_directories()

    def compute_sha256(self, file_path: Path) -> str:
        """Computes SHA-256 checksum of an audio or document file for audit integrity."""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    def save_uploaded_audio(self, meeting_id: str, filename: str, file_obj: BinaryIO) -> Path:
        """Saves incoming audio file to the local uploads directory."""
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
        return settings.UPLOADS_DIR / meeting_id / "normalized_16k.wav"

    def get_export_paths(self, meeting_id: str, revision: int = 1) -> tuple[Path, Path]:
        """Returns the PDF and DOCX export paths for a meeting revision."""
        export_dir = settings.EXPORTS_DIR / meeting_id
        export_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = export_dir / f"Medpark_MoM_Rev{revision}.pdf"
        docx_path = export_dir / f"Medpark_MoM_Rev{revision}.docx"
        return pdf_path, docx_path


file_manager = FileManager()
