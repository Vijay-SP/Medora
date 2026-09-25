"""
Medpark Meeting Intelligence System - Thread-Safe Atomic Persistence
Maintains meeting state, transcripts, minutes, and delivery records locally.
"""

import json
from pathlib import Path
from threading import RLock
from typing import Optional
from app.core.config import settings
from app.core.logging import logger
from app.models.meeting import Meeting
from app.models.transcript import Transcript
from app.models.extraction import MinutesOfMeeting
from app.models.delivery import DeliveryRecord


class MeetingRepository:
    """Thread-safe persistent store for meetings, transcripts, and approved minutes."""
    
    def __init__(self, data_dir: Path = settings.DATA_DIR):
        self.lock = RLock()
        self.storage_dir = data_dir / "store"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        self.meetings_file = self.storage_dir / "meetings.json"
        self.transcripts_file = self.storage_dir / "transcripts.json"
        self.minutes_file = self.storage_dir / "minutes.json"
        self.deliveries_file = self.storage_dir / "deliveries.json"
        
        self._init_storage()

    def _init_storage(self) -> None:
        """Initializes empty JSON store files if they do not exist."""
        for f in [self.meetings_file, self.transcripts_file, self.minutes_file, self.deliveries_file]:
            if not f.exists():
                with open(f, "w", encoding="utf-8") as fp:
                    json.dump({}, fp)

    def _read_json(self, path: Path) -> dict:
        try:
            with open(path, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except Exception:
            return {}

    def _write_json(self, path: Path, data: dict) -> None:
        temp_path = path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as fp:
            json.dump(data, fp, indent=2, default=str)
        temp_path.replace(path)

    # --- Meetings CRUD ---
    def save_meeting(self, meeting: Meeting) -> Meeting:
        with self.lock:
            data = self._read_json(self.meetings_file)
            data[meeting.id] = meeting.model_dump(mode="json")
            self._write_json(self.meetings_file, data)
            return meeting

    def get_meeting(self, meeting_id: str) -> Optional[Meeting]:
        with self.lock:
            data = self._read_json(self.meetings_file)
            raw = data.get(meeting_id)
            return Meeting.model_validate(raw) if raw else None

    def list_meetings(self) -> list[Meeting]:
        with self.lock:
            data = self._read_json(self.meetings_file)
            meetings = [Meeting.model_validate(val) for val in data.values()]
            meetings.sort(key=lambda m: m.scheduled_at, reverse=True)
            return meetings

    def delete_meeting(self, meeting_id: str) -> bool:
        with self.lock:
            data = self._read_json(self.meetings_file)
            if meeting_id in data:
                del data[meeting_id]
                self._write_json(self.meetings_file, data)
                return True
            return False

    # --- Transcripts CRUD ---
    def save_transcript(self, transcript: Transcript) -> Transcript:
        with self.lock:
            data = self._read_json(self.transcripts_file)
            data[transcript.meeting_id] = transcript.model_dump(mode="json")
            self._write_json(self.transcripts_file, data)
            return transcript

    def get_transcript(self, meeting_id: str) -> Optional[Transcript]:
        with self.lock:
            data = self._read_json(self.transcripts_file)
            raw = data.get(meeting_id)
            return Transcript.model_validate(raw) if raw else None

    # --- Minutes of Meeting CRUD ---
    def save_minutes(self, minutes: MinutesOfMeeting) -> MinutesOfMeeting:
        with self.lock:
            data = self._read_json(self.minutes_file)
            data[minutes.meeting_id] = minutes.model_dump(mode="json")
            self._write_json(self.minutes_file, data)
            return minutes

    def get_minutes(self, meeting_id: str) -> Optional[MinutesOfMeeting]:
        with self.lock:
            data = self._read_json(self.minutes_file)
            raw = data.get(meeting_id)
            return MinutesOfMeeting.model_validate(raw) if raw else None

    # --- Deliveries CRUD ---
    def save_delivery(self, record: DeliveryRecord) -> DeliveryRecord:
        with self.lock:
            data = self._read_json(self.deliveries_file)
            data[record.id] = record.model_dump(mode="json")
            self._write_json(self.deliveries_file, data)
            return record

    def list_deliveries(self, meeting_id: Optional[str] = None) -> list[DeliveryRecord]:
        with self.lock:
            data = self._read_json(self.deliveries_file)
            records = [DeliveryRecord.model_validate(val) for val in data.values()]
            if meeting_id:
                records = [r for r in records if r.meeting_id == meeting_id]
            records.sort(key=lambda r: r.sent_at or r.id, reverse=True)
            return records


repository = MeetingRepository()
