"""
Medpark Meeting Intelligence System - Domain Exceptions
Provides explicit domain errors for clean API error mapping and diagnostic tracing.
"""

class MedparkBaseException(Exception):
    """Base exception for all Medpark application domain errors."""
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class AudioProcessingError(MedparkBaseException):
    """Raised when audio conversion, normalization, or VAD segmentation fails."""
    pass


class ASREngineError(MedparkBaseException):
    """Raised when speech-to-text inference or model loading fails."""
    pass


class DiarizationError(MedparkBaseException):
    """Raised when speaker turn segmentation fails."""
    pass


class ExtractionError(MedparkBaseException):
    """Raised when LLM-based minutes or action extraction fails."""
    pass


class GroundingValidationError(MedparkBaseException):
    """Raised when extracted decisions/actions lack valid verbatim audio evidence."""
    pass


class ReviewStateError(MedparkBaseException):
    """Raised when an illegal review state transition is attempted (e.g. approving already sent minutes)."""
    pass


class DeliveryError(MedparkBaseException):
    """Raised when document dispatch via SMTP or n8n fails."""
    pass


class ResourceNotFoundError(MedparkBaseException):
    """Raised when a meeting, audio file, or revision does not exist."""
    pass
