"""
Test for Person clinical context metadata (department, title, specialty, primary_language)
and meeting attendee roster integration with department filtering.

    PYTHONPATH=backend .venv\\Scripts\\python.exe backend\\tests\\test_person_departments_and_roster.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(tempfile.mkdtemp(prefix="medpark_test_dept_roster_"))
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ISOLATION_ENV = {
    "DATA_DIR": str(_ROOT / "data"),
    "UPLOADS_DIR": str(_ROOT / "uploads"),
    "EXPORTS_DIR": str(_ROOT / "exports"),
    "FIXTURES_DIR": str(_ROOT / "fixtures"),
    "VOICEPRINTS_DIR": str(_ROOT / "voiceprints"),
    "SMTP_HOST": "127.0.0.1",
    "SMTP_PORT": "9",
    "ALLOW_SIMULATED_DELIVERY": "false",
    "REQUIRE_LOCAL_LLM": "false",
    "LLM_API_BASE_URL": "http://127.0.0.1:9",
    "WHISPER_DEVICE": "cpu",
    "VOICE_ID_ENABLED": "true",
}
os.environ.update(_ISOLATION_ENV)
os.environ.setdefault("MODELS_DIR", str(_REPO_ROOT / "data" / "models"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.models.meeting import Attendee, Meeting, MeetingType, WorkflowMode
from app.models.person import Person
from app.storage.repository import repository


def test_person_model_and_repository():
    p = Person(
        full_name="Elena Ceban",
        title="Dr.",
        role="Chief Surgeon",
        email="elena.ceban@medpark.md",
        department="Surgery",
        specialty="Cardiovascular Surgery",
        primary_language="ro",
    )
    saved = repository.save_person(p)
    loaded = repository.get_person(saved.id)
    assert loaded is not None
    assert loaded.department == "Surgery"
    assert loaded.title == "Dr."
    assert loaded.specialty == "Cardiovascular Surgery"
    assert loaded.primary_language == "ro"
    assert loaded.role == "Chief Surgeon"
    print("PASS test_person_model_and_repository")


def test_voice_profiles_api_department_filtering():
    client = TestClient(app)

    # Create Cardiology doctor
    r1 = client.post(
        "/api/v1/voice-profiles/",
        json={
            "person_name": "Ion Ciobanu",
            "title": "Dr.",
            "role": "Cardiologist",
            "email": "ion.ciobanu@medpark.md",
            "department": "Cardiology",
            "specialty": "Interventional Cardiology",
            "primary_language": "ro",
        },
    )
    assert r1.status_code == 201, r1.text
    d1 = r1.json()
    assert d1["department"] == "Cardiology"
    assert d1["title"] == "Dr."
    assert d1["specialty"] == "Interventional Cardiology"

    # Create Surgery doctor
    r2 = client.post(
        "/api/v1/voice-profiles/",
        json={
            "person_name": "Mihail Popov",
            "title": "Prof. Dr.",
            "role": "Chief Surgeon",
            "email": "mihail.popov@medpark.md",
            "department": "Surgery",
            "specialty": "Abdominal Surgery",
            "primary_language": "ru",
        },
    )
    assert r2.status_code == 201, r2.text

    # List all
    all_res = client.get("/api/v1/voice-profiles/")
    assert all_res.status_code == 200
    all_profiles = all_res.json()
    names = [p["person_name"] for p in all_profiles]
    assert "Ion Ciobanu" in names
    assert "Mihail Popov" in names

    # Filter by Cardiology
    cardio_res = client.get("/api/v1/voice-profiles/?department=Cardiology")
    assert cardio_res.status_code == 200
    cardio_list = cardio_res.json()
    cardio_names = [p["person_name"] for p in cardio_list]
    assert "Ion Ciobanu" in cardio_names
    assert "Mihail Popov" not in cardio_names

    # Filter by Surgery
    surgery_res = client.get("/api/v1/voice-profiles/?department=surgery")
    assert surgery_res.status_code == 200
    surgery_list = surgery_res.json()
    surgery_names = [p["person_name"] for p in surgery_list]
    assert "Mihail Popov" in surgery_names
    assert "Ion Ciobanu" not in surgery_names

    print("PASS test_voice_profiles_api_department_filtering")


def test_meeting_with_registered_attendees_and_guests():
    client = TestClient(app)

    # Find the person ID for Ion Ciobanu
    cardio_res = client.get("/api/v1/voice-profiles/?department=Cardiology")
    ion = cardio_res.json()[0]

    meeting_payload = {
        "title": "Cardiology & Surgery Joint Board",
        "meeting_type": "medical",
        "workflow_mode": "supervised",
        "scheduled_at": datetime.now(timezone.utc).isoformat(),
        "attendees": [
            {
                "id": "att-1",
                "name": "Dr. Ion Ciobanu",
                "role": "Cardiologist",
                "email": "ion.ciobanu@medpark.md",
                "department": "Cardiology",
                "person_id": ion["id"],
            },
            {
                "id": "guest-1",
                "name": "Prof. Guest Specialist",
                "role": "External Consultant",
                "email": "guest@univ-paris.fr",
                "department": "External Guest",
                "person_id": None,
            },
        ],
        "distribution_list": [],
    }

    create_res = client.post("/api/v1/meetings/", json=meeting_payload)
    assert create_res.status_code == 201, create_res.text
    meeting_data = create_res.json()
    assert len(meeting_data["attendees"]) == 2
    att1 = meeting_data["attendees"][0]
    assert att1["person_id"] == ion["id"]
    assert att1["department"] == "Cardiology"
    att2 = meeting_data["attendees"][1]
    assert att2["person_id"] is None
    assert att2["department"] == "External Guest"

    # Fetch meeting by ID
    get_res = client.get(f"/api/v1/meetings/{meeting_data['id']}")
    assert get_res.status_code == 200
    fetched = get_res.json()
    assert fetched["attendees"][0]["name"] == "Dr. Ion Ciobanu"
    assert fetched["attendees"][1]["name"] == "Prof. Guest Specialist"

    print("PASS test_meeting_with_registered_attendees_and_guests")


if __name__ == "__main__":
    test_person_model_and_repository()
    test_voice_profiles_api_department_filtering()
    test_meeting_with_registered_attendees_and_guests()
    print("ALL TESTS PASSED!")
