"""
Medpark Meeting Intelligence System - Abstract Extraction Interface
Defines the contract for structured information extraction from multilingual clinical transcripts.
"""

from abc import ABC, abstractmethod
from app.models.meeting import Meeting
from app.models.transcript import Transcript
from app.models.extraction import MinutesOfMeeting


class BaseExtractor(ABC):
    """Abstract interface for extracting structured, evidence-linked minutes."""

    @abstractmethod
    async def extract_minutes(self, meeting: Meeting, transcript: Transcript) -> MinutesOfMeeting:
        """
        Processes transcript segments and extracts structured decisions, actions, owners, and risks.
        """
        pass
