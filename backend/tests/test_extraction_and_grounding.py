"""
Tests for multilingual extraction, code-switching, and evidence grounding.
"""

import asyncio
from datetime import datetime
from app.models.meeting import Meeting, MeetingType, Attendee
from app.models.transcript import Transcript, TranscriptSegment
from app.services.extraction.llm_engine import extraction_engine
from app.services.extraction.validator import evidence_validator


def test_code_switched_extraction_and_grounding():
    # Construct a realistic Medpark code-switched meeting transcript
    # Segment 1 (RO): Opening and proposal
    seg1 = TranscriptSegment(
        id="s1",
        start=0.0,
        end=5.2,
        speaker="Dr. Elena Ceban",
        raw_text="Bună dimineața tuturor. Deschidem ședința de comitet medical pentru revizuirea protocoalelor ATI."
    )
    # Segment 2 (RU): Discussion and decision agreement
    seg2 = TranscriptSegment(
        id="s2",
        start=5.5,
        end=11.0,
        speaker="Dr. Mihail Popov",
        raw_text="Да, по протоколу реанимации мы согласовали и утвердили новые дозировки антибиотиков."
    )
    # Segment 3 (RO/EN): Action item with deadline
    seg3 = TranscriptSegment(
        id="s3",
        start=11.2,
        end=17.5,
        speaker="Dr. Elena Ceban",
        raw_text="Perfect. Dr. Elena Ceban va pregăti documentația finală și raportul de gardă până vineri."
    )
    # Segment 4 (RO/RU): Operational risk
    seg4 = TranscriptSegment(
        id="s4",
        start=18.0,
        end=23.0,
        speaker="Dr. Mihail Popov",
        raw_text="Avem un risc cu stocul de hemostatice, нужно срочно проверить склад."
    )

    transcript = Transcript(
        meeting_id="med-test-01",
        segments=[seg1, seg2, seg3, seg4]
    )
    transcript.compute_stats()

    meeting = Meeting(
        id="med-test-01",
        title="Comitet Medical - Protocoale ATI & Hemostază",
        meeting_type=MeetingType.MEDICAL,
        scheduled_at=datetime(2026, 9, 25, 10, 0),
        attendees=[
            Attendee(name="Dr. Elena Ceban", role="Chirurg Șef", email="elena.ceban@medpark.md"),
            Attendee(name="Dr. Mihail Popov", role="Șef ATI", email="mihail.popov@medpark.md")
        ]
    )

    # Run extraction
    minutes = asyncio.run(extraction_engine.extract_minutes(meeting, transcript))

    # Verify structured outputs
    assert len(minutes.decisions) >= 1
    assert len(minutes.action_items) >= 1

    # Verify action item owner and deadline
    action = minutes.action_items[0]
    assert "Elena Ceban" in action.owner or action.owner != "Unassigned"
    assert action.deadline_phrase is not None
    assert action.deadline_date is not None  # Resolved to ISO date!

    # Verify Grounding: Every decision and action must cite valid audio timestamps
    for dec in minutes.decisions:
        assert len(dec.evidence) > 0
        assert dec.evidence[0].start >= 0.0

    for act in minutes.action_items:
        assert len(act.evidence) > 0
        assert act.evidence[0].quote in transcript.to_full_text()


if __name__ == "__main__":
    test_code_switched_extraction_and_grounding()
    print("Multilingual extraction and evidence grounding tests passed successfully!")
