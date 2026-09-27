"""
Tests for bulk administrator speaker assignment (EU AI Act Human-in-the-Loop Refinement):
  - POST /meetings/{id}/speakers/bulk-assign sets names/designations on multiple clusters at once;
  - Updates transcript display_speaker, minutes action item owners and evidence quotes;
  - Regenerates PDF and DOCX with EU AI Act Article 50 transparency notices;
  - Allows assigning labels even when embeddings cache is absent (anonymous / no-ONNX mode);
  - Action 'reject' or empty label resets cluster back to anonymous.

Run:
  PYTHONPATH=backend .venv\\Scripts\\python.exe backend\\tests\\test_speaker_bulk_assign.py
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_ROOT = Path(tempfile.mkdtemp(prefix="medpark_test_bulk_assign_"))
_REPO_ROOT = Path(__file__).resolve().parents[2]
os.environ["DATA_DIR"] = str(_ROOT / "data")
os.environ["UPLOADS_DIR"] = str(_ROOT / "uploads")
os.environ["EXPORTS_DIR"] = str(_ROOT / "exports")
os.environ["FIXTURES_DIR"] = str(_ROOT / "fixtures")
os.environ["VOICEPRINTS_DIR"] = str(_ROOT / "voiceprints")
os.environ.setdefault("MODELS_DIR", str(_REPO_ROOT / "data" / "models"))
os.environ["SMTP_HOST"] = "127.0.0.1"
os.environ["SMTP_PORT"] = "9"
os.environ["ALLOW_SIMULATED_DELIVERY"] = "false"
os.environ["REQUIRE_LOCAL_LLM"] = "false"
os.environ["LLM_API_BASE_URL"] = "http://127.0.0.1:9"
os.environ["WHISPER_DEVICE"] = "cpu"
os.environ["VOICE_ID_ENABLED"] = "false"  # Explicitly test with voice-id disabled!
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import re  # noqa: E402
import sys  # noqa: E402
import zipfile  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from app.core.config import settings  # noqa: E402
from app.models.extraction import ActionItem, DecisionItem, EvidenceQuote, MinutesOfMeeting, RiskOrQuestionItem  # noqa: E402
from app.models.meeting import Attendee, Meeting, ProcessingStatus, ReviewStatus, WorkflowMode  # noqa: E402
from app.models.transcript import Transcript, TranscriptSegment  # noqa: E402
from app.services.documents.generator import document_generator  # noqa: E402
from app.storage.file_manager import file_manager  # noqa: E402
from app.storage.repository import repository  # noqa: E402
from voice_e2e_gpu import pdf_text  # noqa: E402

ROSTER = "Dr. Elena Ceban"
DESIGNATION = "Chirurg Principal"
REVIEWER = {"reviewer_name": "Admin Medpark", "reviewer_role": "Administrator"}

SEGMENT_SPEC = [
    ("a1", 0.0, 5.0, "Deschidem ședința clinică de astăzi.", "Speaker 1", "SPEAKER_01", 4.5),
    ("a2", 5.5, 9.0, "Eu voi prelua cazul din secția chirurgie.", "Speaker 1", "SPEAKER_01", 3.2),
    ("b1", 10.0, 15.0, "Protocoalele post-operatorii au fost revizuite.", "Speaker 2", "SPEAKER_02", 4.8),
    ("b2", 15.5, 20.0, "Verificăm parametrii vitali la fiecare 2 ore.", "Speaker 2", "SPEAKER_02", 4.2),
    ("c1", 21.0, 26.0, "Voi trimite cererea la laborator.", "Speaker 3", "SPEAKER_03", 4.5),
]


def _client():
    from fastapi.testclient import TestClient
    from app.main import app

    return TestClient(app)


def _setup_meeting() -> Meeting:
    meeting = Meeting(
        title="Sedinta Chirurgie Generala",
        meeting_type="medical",
        workflow_mode=WorkflowMode.SUPERVISED,
        review_status=ReviewStatus.PENDING_REVIEW,
        processing_status=ProcessingStatus.COMPLETED,
        current_revision=1,
        attendees=[
            Attendee(name=ROSTER, email="elena.ceban@medpark.md", role="Chirurg", department="General Surgery"),
            Attendee(name="Dr. Mihai Popa", email="mihai.popa@medpark.md", role="Medic", department="ATI"),
        ],
    )
    repository.save_meeting(meeting)

    segments = [
        TranscriptSegment(id=s[0], start=s[1], end=s[2], raw_text=s[3], speaker=s[4], cluster_id=s[5], speech_seconds=s[6])
        for s in SEGMENT_SPEC
    ]
    transcript = Transcript(meeting_id=meeting.id, segments=segments, languages_detected=["ro"])
    transcript.compute_stats()
    repository.save_transcript(transcript)

    minutes = MinutesOfMeeting(
        meeting_id=meeting.id,
        title="Proces-verbal — Sedinta de chirurgie",
        revision=1,
        speaker_label_style="labels",
        summary_ro="S1 a deschis ședința. S2 a revizuit protocoalele. S3 a confirmat trimiterea la laborator.",
        summary_en="S1 opened the meeting. S2 reviewed protocols. S3 confirmed lab submission.",
        decisions=[
            DecisionItem(
                topic="Protocoale chirurgicale",
                decision="Se aproba noul protocol.",
                evidence=[EvidenceQuote(segment_id="b1", quote="Protocoalele post-operatorii au fost revizuite.", start=10.0, end=15.0, speaker="Speaker 2")],
            )
        ],
        action_items=[
            ActionItem(
                task="Preluare caz chirurgie",
                owner="Speaker 1",
                owner_source="speaker",
                priority="high",
                evidence=[EvidenceQuote(segment_id="a2", quote="Eu voi prelua cazul din secția chirurgie.", start=5.5, end=9.0, speaker="Speaker 1")],
            ),
            ActionItem(
                task="Monitorizare parametri",
                owner="Speaker 2",
                owner_source="speaker",
                priority="medium",
                evidence=[EvidenceQuote(segment_id="b2", quote="Verificăm parametrii vitali la fiecare 2 ore.", start=15.5, end=20.0, speaker="Speaker 2")],
            ),
        ],
    )
    pdf_path, docx_path = file_manager.get_export_paths(meeting.id, revision=1)
    document_generator.generate_all(meeting, minutes, pdf_path, docx_path, transcript=transcript)
    minutes.pdf_path, minutes.docx_path = str(pdf_path), str(docx_path)
    repository.save_minutes(minutes)
    return meeting


def test_bulk_speaker_assignment_replaces_names_and_updates_exports():
    meeting = _setup_meeting()
    with _client() as client:
        # 1. Check initial listing
        res0 = client.get(f"/api/v1/meetings/{meeting.id}/speakers")
        assert res0.status_code == 200
        clusters0 = {c["cluster_id"]: c for c in res0.json()["clusters"]}
        assert set(clusters0) == {"SPEAKER_01", "SPEAKER_02", "SPEAKER_03"}
        assert all(c["state"] == "anonymous" for c in clusters0.values())

        # 2. Bulk assign: SPEAKER_01 -> attendee ROSTER, SPEAKER_02 -> custom DESIGNATION
        body = {
            "assignments": [
                {"cluster_id": "SPEAKER_01", "attendee_id": meeting.attendees[0].id, "action": "label"},
                {"cluster_id": "SPEAKER_02", "display_label": DESIGNATION, "action": "label"},
            ],
            "expected_revision": 1,
            **REVIEWER,
        }
        res = client.post(f"/api/v1/meetings/{meeting.id}/speakers/bulk-assign", json=body)
        assert res.status_code == 200, res.text
        clusters = {c["cluster_id"]: c for c in res.json()["clusters"]}

        # Check returned clusters
        assert clusters["SPEAKER_01"]["current_label"] == ROSTER
        assert clusters["SPEAKER_01"]["state"] == "corrected"
        assert clusters["SPEAKER_02"]["current_label"] == DESIGNATION
        assert clusters["SPEAKER_02"]["state"] == "corrected"
        assert clusters["SPEAKER_03"]["state"] == "anonymous"
        assert clusters["SPEAKER_03"]["current_label"] is None

        # 3. Check transcript
        transcript = repository.get_transcript(meeting.id)
        assert transcript is not None
        segs = {s.id: s for s in transcript.segments}
        assert segs["a1"].display_speaker == ROSTER
        assert segs["a2"].display_speaker == ROSTER
        assert segs["b1"].display_speaker == DESIGNATION
        assert segs["b2"].display_speaker == DESIGNATION
        assert segs["c1"].display_speaker == "Speaker 3"

        # 4. Check minutes read API (names=resolved)
        min_res = client.get(f"/api/v1/meetings/{meeting.id}/minutes")
        assert min_res.status_code == 200
        min_data = min_res.json()
        assert ROSTER in min_data["summary_ro"]
        assert DESIGNATION in min_data["summary_ro"]
        # Action item owners updated
        act1 = next(a for a in min_data["action_items"] if a["task"] == "Preluare caz chirurgie")
        assert act1["owner"] == ROSTER
        assert act1["owner_source"] == "confirmed_speaker"
        act2 = next(a for a in min_data["action_items"] if a["task"] == "Monitorizare parametri")
        assert act2["owner"] == DESIGNATION
        assert act2["owner_source"] == "confirmed_speaker"

        # 5. Check generated exports (PDF & DOCX)
        minutes = repository.get_minutes(meeting.id)
        assert minutes is not None and minutes.pdf_path and minutes.docx_path
        assert Path(minutes.pdf_path).exists()
        assert Path(minutes.docx_path).exists()

        pdf_content = pdf_text(Path(minutes.pdf_path).read_bytes())
        assert ROSTER in pdf_content
        assert DESIGNATION in pdf_content
        assert "Art. 50 EU AI Act" in pdf_content

        with zipfile.ZipFile(minutes.docx_path) as zf:
            docx_xml = zf.read("word/document.xml").decode("utf-8")
        assert ROSTER in docx_xml
        assert DESIGNATION in docx_xml
        assert "Art. 50" in docx_xml

        # 6. Reset SPEAKER_02 back to anonymous via bulk-assign action "reject"
        reset_body = {
            "assignments": [
                {"cluster_id": "SPEAKER_02", "action": "reject"},
            ],
            **REVIEWER,
        }
        res_reset = client.post(f"/api/v1/meetings/{meeting.id}/speakers/bulk-assign", json=reset_body)
        assert res_reset.status_code == 200
        clusters_after = {c["cluster_id"]: c for c in res_reset.json()["clusters"]}
        assert clusters_after["SPEAKER_01"]["current_label"] == ROSTER
        assert clusters_after["SPEAKER_02"]["state"] == "anonymous"
        assert clusters_after["SPEAKER_02"]["current_label"] is None


if __name__ == "__main__":
    test_bulk_speaker_assignment_replaces_names_and_updates_exports()
    print("PASS test_bulk_speaker_assignment_replaces_names_and_updates_exports")
