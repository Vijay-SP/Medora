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
from app.services.documents.generator import document_generator, truncate_quote


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


def test_evidence_quote_truncation_is_honest():
    """A quote is only marked as cut when it was actually cut."""
    short_quote = "Aprobăm achiziția."
    assert truncate_quote(short_quote, 40) == short_quote
    assert not truncate_quote(short_quote, 40).endswith("...")

    long_quote = "Aprobăm achiziția laparoscopului conform specificațiilor tehnice convenite cu furnizorul."
    truncated = truncate_quote(long_quote, 40)
    assert truncated.endswith("...")
    assert len(truncated) <= 43
    assert long_quote.startswith(truncated[:-3].rstrip())

    # Exactly at the limit is not a truncation
    exact = "x" * 40
    assert truncate_quote(exact, 40) == exact


def test_pdf_wraps_overlong_content(tmp_path: Path):
    """Long titles, topics and tasks must wrap onto more pages, never be clipped at the margin."""
    long_title = "Ședință Extraordinară " + ("de Analiză a Protocoalelor Clinice Interdisciplinare " * 6)
    meeting = Meeting(
        title=long_title[:200],
        meeting_type=MeetingType.MEDICAL,
        scheduled_at=datetime(2026, 9, 25, 9, 0),
        attendees=[Attendee(name="Dr. Mihail Popov", email="popov@medpark.md")]
    )

    dec = DecisionItem(
        topic="Reorganizarea Fluxului Operator " * 8,
        decision="Se aprobă " + ("reorganizarea completă a fluxului operator pe trei ture succesive. " * 12),
        evidence=[]
    )
    act = ActionItem(
        task="Redactarea " + ("procedurii operaționale standard pentru fiecare secție implicată. " * 12),
        owner="Dr. Mihail Popov " * 10,
        priority="high",
        evidence=[]
    )
    minutes = MinutesOfMeeting(
        meeting_id=meeting.id,
        title=meeting.title,
        meeting_type=meeting.meeting_type.value,
        summary_ro="Rezumat extins. " * 80,
        decisions=[dec],
        action_items=[act]
    )

    pdf_path = tmp_path / "overflow_mom.pdf"
    docx_path = tmp_path / "overflow_mom.docx"
    pdf_out, docx_out = document_generator.generate_all(meeting, minutes, pdf_path, docx_path)

    assert pdf_out.exists()
    assert docx_out.exists()
    # Content this long cannot fit on a single page unless it was clipped
    assert pdf_out.read_bytes().count(b"/Type /Page\n") > 1 or pdf_out.stat().st_size > 5000


if __name__ == "__main__":
    import tempfile
    test_evidence_quote_truncation_is_honest()
    with tempfile.TemporaryDirectory() as td:
        test_pdf_and_docx_generation(Path(td))
    with tempfile.TemporaryDirectory() as td:
        test_pdf_wraps_overlong_content(Path(td))
    print("PDF and DOCX generation tests passed successfully!")
