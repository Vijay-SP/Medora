"""
Unit tests for domain models, validation, and contracts.
"""

from datetime import datetime
from app.models.meeting import Meeting, MeetingType, WorkflowMode, Attendee
from app.models.transcript import Transcript, TranscriptSegment
from app.models.extraction import DecisionItem, ActionItem, EvidenceQuote, MinutesOfMeeting
from app.models.delivery import DEFAULT_ROUTING_POLICIES


def test_meeting_creation():
    attendee = Attendee(name="Dr. Elena Ceban", role="Chirurg", email="elena.ceban@medpark.md")
    meeting = Meeting(
        title="Ședință Medicală Test",
        meeting_type=MeetingType.MEDICAL,
        workflow_mode=WorkflowMode.AUTO_PILOT,
        attendees=[attendee]
    )
    assert meeting.id is not None
    assert meeting.title == "Ședință Medicală Test"
    assert len(meeting.attendees) == 1
    assert meeting.attendees[0].email == "elena.ceban@medpark.md"


def test_transcript_formatting():
    seg1 = TranscriptSegment(start=0.0, end=4.5, speaker="Dr. Ceban", raw_text="Bună ziua, începem ședința.")
    seg2 = TranscriptSegment(start=5.0, end=10.0, speaker="Dr. Rusu", raw_text="Да, по протоколу всё готово.")
    transcript = Transcript(meeting_id="test-123", segments=[seg1, seg2])
    transcript.compute_stats()

    assert transcript.total_words == 9
    assert "Dr. Ceban" in transcript.to_full_text()
    assert "по протоколу" in transcript.to_full_text()


def test_evidence_grounding_quote():
    ev = EvidenceQuote(segment_id="seg-1", start=2.0, end=5.0, quote="S-a aprobat achiziția.")
    dec = DecisionItem(topic="Achiziții", decision="Aprobare buget", evidence=[ev])
    assert len(dec.evidence) == 1
    assert dec.evidence[0].quote == "S-a aprobat achiziția."


def test_routing_policies():
    assert "medical" in DEFAULT_ROUTING_POLICIES
    assert "executive" in DEFAULT_ROUTING_POLICIES
    assert "administrative" in DEFAULT_ROUTING_POLICIES
    assert len(DEFAULT_ROUTING_POLICIES["medical"].default_recipients) > 0


if __name__ == "__main__":
    test_meeting_creation()
    test_transcript_formatting()
    test_evidence_grounding_quote()
    test_routing_policies()
    print("All model tests passed successfully!")
