"""
Medpark Meeting Intelligence System - Thread-Safe Atomic Persistence
Maintains meeting state, transcripts, minutes, and delivery records locally.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import RLock
from typing import Optional
import uuid
from app.core.config import settings
from app.core.logging import logger
from app.storage.file_manager import file_manager
from app.models.meeting import Meeting
from app.models.transcript import Transcript
from app.models.extraction import MinutesOfMeeting
from app.models.delivery import DeliveryRecord
from app.models.person import Person, SpeakerMap


def _normalize_datetime(dt: Optional[datetime]) -> datetime:
    """Safely normalizes naive/aware datetimes to UTC for comparison and sorting."""
    if dt is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)



class MeetingRepository:
    """Thread-safe persistent store for meetings, transcripts, and approved minutes."""
    
    def __init__(self, data_dir: Optional[Path] = None):
        self.lock = RLock()
        # Resolved in the body, never as a default argument, so the store follows settings at call time.
        self._configure_paths(data_dir or settings.DATA_DIR)

    def _configure_paths(self, data_dir: Path) -> None:
        """Derives the store directory and JSON file paths from a data directory."""
        self.storage_dir = Path(data_dir) / "store"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.meetings_file = self.storage_dir / "meetings.json"
        self.transcripts_file = self.storage_dir / "transcripts.json"
        self.minutes_file = self.storage_dir / "minutes.json"
        self.deliveries_file = self.storage_dir / "deliveries.json"
        # Enrolled people and per-meeting attribution decisions. Descriptors only: the voiceprint
        # vectors themselves live under VOICEPRINTS_DIR (file_manager), never in a JSON store.
        self.people_file = self.storage_dir / "people.json"
        self.speaker_maps_file = self.storage_dir / "speaker_maps.json"

        self._init_storage()

    def reconfigure(self, data_dir: Path) -> None:
        """Repoints the store at another data directory (used to isolate tests from production data)."""
        with self.lock:
            self._configure_paths(data_dir)
            logger.info(f"Repository store repointed to {self.storage_dir}")

    def _init_storage(self) -> None:
        """Initializes empty JSON store files if they do not exist."""
        for f in [
            self.meetings_file, self.transcripts_file, self.minutes_file, self.deliveries_file,
            self.people_file, self.speaker_maps_file,
        ]:
            if not f.exists():
                with open(f, "w", encoding="utf-8") as fp:
                    json.dump({}, fp)

    def _read_json(self, path: Path) -> dict:
        """Loads a store file. Only an absent or empty file is an empty store; corruption fails loudly."""
        if not path.exists() or path.stat().st_size == 0:
            return {}
        try:
            with open(path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error(f"Unreadable store file {path}: {exc}")
            raise
        if not isinstance(data, dict):
            logger.error(f"Corrupt store file {path}: expected a JSON object, got {type(data).__name__}")
            raise ValueError(f"Corrupt store file {path}: expected a JSON object")
        return data

    def _write_json(self, path: Path, data: dict) -> None:
        # Unique temp name per writer: a shared '.tmp' suffix collides between concurrent writers.
        temp_path = path.with_name(f"{path.stem}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as fp:
                json.dump(data, fp, indent=2, default=str)
            temp_path.replace(path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    # --- Meetings CRUD ---
    def save_meeting(self, meeting: Meeting) -> Meeting:
        with self.lock:
            meeting.updated_at = datetime.now(timezone.utc)
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
            meetings.sort(key=lambda m: _normalize_datetime(m.scheduled_at), reverse=True)
            return meetings

    def delete_meeting(self, meeting_id: str) -> bool:
        """Deletes a meeting together with its transcript, minutes, deliveries, and stored artifacts."""
        with self.lock:
            data = self._read_json(self.meetings_file)
            if meeting_id not in data:
                return False
            del data[meeting_id]
            self._write_json(self.meetings_file, data)

            # Clinical content must not survive the meeting it belongs to.
            self.delete_transcript(meeting_id)
            self.delete_minutes(meeting_id)
            self.delete_deliveries(meeting_id)
            self.delete_speaker_map(meeting_id)

            # Store consistency wins over filesystem cleanup: a locked artifact (pipeline still
            # reading the normalized WAV, an in-flight download) must not abort an applied delete.
            try:
                file_manager.purge_meeting_artifacts(meeting_id)
            except Exception as exc:
                logger.warning(f"Could not purge artifacts of meeting {meeting_id}, they remain on disk: {exc}")
            try:
                file_manager.purge_meeting_embeddings(meeting_id)
            except Exception as exc:
                logger.warning(f"Could not purge segment embeddings of meeting {meeting_id}, they remain on disk: {exc}")

            logger.info(f"Deleted meeting {meeting_id} with transcript, minutes, deliveries, speaker map and artifacts")
            return True

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

    def delete_transcript(self, meeting_id: str) -> bool:
        with self.lock:
            data = self._read_json(self.transcripts_file)
            if meeting_id in data:
                del data[meeting_id]
                self._write_json(self.transcripts_file, data)
                return True
            return False

    def anonymise_suggestions_for_person(self, person_id: str) -> int:
        """
        Reverts every pending (unconfirmed) suggestion of a person to anonymous across all transcripts.

        Called when the person's voiceprint is purged (consent withdrawn, samples wiped, record deleted): a
        suggestion is derived from that biometric and must not outlive it. Confirmed/corrected segments are
        snapshots taken by a reviewer and are left untouched. Returns the number of segments changed.
        """
        with self.lock:
            data = self._read_json(self.transcripts_file)
            changed_segments = 0
            changed_meetings = 0
            for meeting_id, raw in data.items():
                transcript = Transcript.model_validate(raw)
                touched = 0
                for seg in transcript.segments:
                    if seg.suggestion is None or seg.suggestion.person_id != person_id:
                        continue
                    seg.suggestion = None
                    seg.suggested_identity = None
                    if seg.attribution_state == "suggested":
                        seg.attribution_state = "anonymous"
                    touched += 1
                if touched:
                    data[meeting_id] = transcript.model_dump(mode="json")
                    changed_segments += touched
                    changed_meetings += 1
            if changed_segments:
                self._write_json(self.transcripts_file, data)
                logger.info(
                    f"Anonymised {changed_segments} suggested segment(s) across {changed_meetings} transcript(s) for person {person_id}"
                )
            return changed_segments

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

    def delete_minutes(self, meeting_id: str) -> bool:
        with self.lock:
            data = self._read_json(self.minutes_file)
            if meeting_id in data:
                del data[meeting_id]
                self._write_json(self.minutes_file, data)
                return True
            return False

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
            records.sort(
                key=lambda r: (_normalize_datetime(r.created_at or r.sent_at), r.id),
                reverse=True,
            )
            return records

    def delete_deliveries(self, meeting_id: str) -> int:
        """Removes every delivery record attached to a meeting, returning how many were deleted."""
        with self.lock:
            data = self._read_json(self.deliveries_file)
            stale_ids = [key for key, val in data.items() if val.get("meeting_id") == meeting_id]
            for key in stale_ids:
                del data[key]
            if stale_ids:
                self._write_json(self.deliveries_file, data)
            return len(stale_ids)

    # --- People (enrolled voices) CRUD ---
    def save_person(self, person: Person) -> Person:
        with self.lock:
            person.updated_at = datetime.now(timezone.utc)
            data = self._read_json(self.people_file)
            data[person.id] = person.model_dump(mode="json")
            self._write_json(self.people_file, data)
            return person

    def get_person(self, person_id: str) -> Optional[Person]:
        with self.lock:
            data = self._read_json(self.people_file)
            raw = data.get(person_id)
            return Person.model_validate(raw) if raw else None

    def list_people(self, include_inactive: bool = False) -> list[Person]:
        with self.lock:
            data = self._read_json(self.people_file)
            people = [Person.model_validate(val) for val in data.values()]
            if not include_inactive:
                people = [p for p in people if p.is_active]
            people.sort(key=lambda p: (p.full_name.casefold(), p.id))
            return people

    def delete_person(self, person_id: str) -> bool:
        """
        Removes the person row only. The caller purges the biometrics (file_manager.purge_person_biometrics);
        meetings and transcripts are deliberately untouched: confirmed_display_name snapshots on past
        meetings remain, because a signed document must not change when a staff record is removed.
        """
        with self.lock:
            data = self._read_json(self.people_file)
            if person_id not in data:
                return False
            del data[person_id]
            self._write_json(self.people_file, data)
            logger.info(f"Deleted person {person_id} (biometrics purged separately; meeting snapshots kept)")
            return True

    # --- Speaker attribution maps (per-meeting reviewer decisions) ---
    def save_speaker_map(self, speaker_map: SpeakerMap) -> SpeakerMap:
        with self.lock:
            data = self._read_json(self.speaker_maps_file)
            data[speaker_map.meeting_id] = speaker_map.model_dump(mode="json")
            self._write_json(self.speaker_maps_file, data)
            return speaker_map

    def get_speaker_map(self, meeting_id: str) -> Optional[SpeakerMap]:
        with self.lock:
            data = self._read_json(self.speaker_maps_file)
            raw = data.get(meeting_id)
            return SpeakerMap.model_validate(raw) if raw else None

    def delete_speaker_map(self, meeting_id: str) -> bool:
        with self.lock:
            data = self._read_json(self.speaker_maps_file)
            if meeting_id in data:
                del data[meeting_id]
                self._write_json(self.speaker_maps_file, data)
                return True
            return False


repository = MeetingRepository()
