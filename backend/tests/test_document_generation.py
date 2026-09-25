"""
Tests for PDF and DOCX document generation.
"""

from pathlib import Path
from datetime import datetime
from app.models.meeting import Meeting, MeetingType, Attendee
from app.models.extraction import (
    MinutesOfMeeting,
    DecisionItem,
    ActionItem,
    EvidenceQuote
)
from app.services.documents.generator import document_generator


def test_pdf_and_docx_generation(tmp_path: Path):
    meeting = Meeting(
        title="Ședință de Aprobare Buget și Echipamente Chirurgicale",
        meeting_type=MeetingType.EXECUTIVE,
        scheduled_at=datetime(2026, 9, 25, 14, 30),
        attendees=[Attendee(name="Dr. Elena Ceban", email="ceban@medpark.md")]
    )

    ev = EvidenceQuote(
        segment_id="s1",
        start=10.0,
        end=15.0,
        quote="Aprobăm achiziția laparoscopului conform specificațiilor tehnice.",
        speaker="Director General"
    )

    dec = DecisionItem(
        topic="Investiții Echipamente",
        decision="Aprobarea bugetului de 120,000 EUR pentru turnul laparoscopic Medpark.",
        evidence=[ev]
    )

    act = ActionItem(
        task="Finalizarea contractului cu furnizorul de tehnologie medicală.",
        owner="Dr. Elena Ceban",
        deadline_phrase="până la sfârșitul lunii",
        deadline_date="2026-09-30",
        evidence=[ev]
    )

    minutes = MinutesOfMeeting(
        meeting_id=meeting.id,
        title=meeting.title,
        meeting_type=meeting.meeting_type.value,
        summary_ro="Comitetul Director a analizat și aprobat cererile de achiziție pentru noul bloc chirurgical.",
        decisions=[dec],
        action_items=[act]
    )

    pdf_path = tmp_path / "test_mom.pdf"
    docx_path = tmp_path / "test_mom.docx"

    pdf_out, docx_out = document_generator.generate_all(meeting, minutes, pdf_path, docx_path)

    assert pdf_out.exists()
    assert pdf_out.stat().st_size > 1000

    assert docx_out.exists()
    assert docx_out.stat().st_size > 1000


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        test_pdf_and_docx_generation(Path(td))
    print("PDF and DOCX generation tests passed successfully!")
