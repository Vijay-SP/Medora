"""
Medpark Meeting Intelligence System - Adaptation Catalog Storage
Manages SQLite catalog under ADAPTATION_DIR for auditable correction tracking and dataset provenance.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any, Optional
from app.core.config import settings
from app.core.logging import logger
from app.models.adaptation import CorrectionEvent


class AdaptationStore:
    """SQLite adaptation catalog manager with WAL mode and idempotent upserts."""

    def __init__(self, db_path: Optional[Path] = None):
        self._custom_db_path = db_path

    @property
    def db_path(self) -> Path:
        if self._custom_db_path:
            return self._custom_db_path
        target_dir = settings.ADAPTATION_DIR or (settings.DATA_DIR / "adaptation")
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir / "adaptation_catalog.sqlite3"

    def _get_connection(self) -> sqlite3.Connection:
        path = self.db_path
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    @contextmanager
    def connection(self):
        conn = self._get_connection()
        try:
            yield conn
        finally:
            conn.close()

    def init_db(self) -> None:
        """Initializes catalog tables and indexes if they do not exist."""
        with self.connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS correction_events (
                    id TEXT PRIMARY KEY,
                    meeting_id TEXT NOT NULL,
                    segment_id TEXT NOT NULL,
                    transcript_revision INTEGER NOT NULL,
                    request_id TEXT,
                    edit_kind TEXT NOT NULL,
                    previous_text TEXT NOT NULL,
                    new_text TEXT NOT NULL,
                    raw_text TEXT,
                    normalized_text TEXT,
                    raw_text_origin TEXT,
                    reviewer_label TEXT,
                    created_at TEXT NOT NULL,
                    verified_against_audio INTEGER NOT NULL DEFAULT 0,
                    training_reuse_allowed INTEGER NOT NULL DEFAULT 0,
                    verification_status TEXT NOT NULL DEFAULT 'unverified',
                    verified_by TEXT,
                    verified_at TEXT,
                    rejection_reason TEXT,
                    audio_start REAL,
                    audio_end REAL,
                    audio_checksum TEXT,
                    speaker_cluster TEXT,
                    language TEXT,
                    eligibility_reason TEXT,
                    collection_status TEXT NOT NULL DEFAULT 'collected',
                    collected_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_corrections_meeting ON correction_events(meeting_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_corrections_request ON correction_events(request_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_corrections_segment ON correction_events(segment_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_corrections_status ON correction_events(verification_status, collection_status);")
            conn.commit()
        logger.debug(f"Initialized adaptation catalog SQLite at {self.db_path}")

    def upsert_event(self, event: CorrectionEvent, metadata: Optional[dict[str, Any]] = None) -> None:
        """Inserts or updates a correction event in the adaptation catalog."""
        self.init_db()
        meta = metadata or {}
        now_iso = datetime.now(timezone.utc).isoformat()
        collected_at = meta.get("collected_at", now_iso)
        collection_status = meta.get("collection_status", "collected")
        eligibility_reason = meta.get("eligibility_reason")
        audio_start = meta.get("audio_start")
        audio_end = meta.get("audio_end")
        audio_checksum = meta.get("audio_checksum")
        speaker_cluster = meta.get("speaker_cluster")
        language = meta.get("language")

        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO correction_events (
                    id, meeting_id, segment_id, transcript_revision, request_id,
                    edit_kind, previous_text, new_text, raw_text, normalized_text,
                    raw_text_origin, reviewer_label, created_at,
                    verified_against_audio, training_reuse_allowed, verification_status,
                    verified_by, verified_at, rejection_reason,
                    audio_start, audio_end, audio_checksum, speaker_cluster, language,
                    eligibility_reason, collection_status, collected_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?
                )
                ON CONFLICT(id) DO UPDATE SET
                    transcript_revision = excluded.transcript_revision,
                    request_id = excluded.request_id,
                    edit_kind = excluded.edit_kind,
                    previous_text = excluded.previous_text,
                    new_text = excluded.new_text,
                    raw_text = excluded.raw_text,
                    normalized_text = excluded.normalized_text,
                    raw_text_origin = excluded.raw_text_origin,
                    reviewer_label = excluded.reviewer_label,
                    verified_against_audio = excluded.verified_against_audio,
                    training_reuse_allowed = excluded.training_reuse_allowed,
                    verification_status = excluded.verification_status,
                    verified_by = excluded.verified_by,
                    verified_at = excluded.verified_at,
                    rejection_reason = excluded.rejection_reason,
                    audio_start = coalesce(excluded.audio_start, correction_events.audio_start),
                    audio_end = coalesce(excluded.audio_end, correction_events.audio_end),
                    audio_checksum = coalesce(excluded.audio_checksum, correction_events.audio_checksum),
                    speaker_cluster = coalesce(excluded.speaker_cluster, correction_events.speaker_cluster),
                    language = coalesce(excluded.language, correction_events.language),
                    eligibility_reason = excluded.eligibility_reason,
                    collection_status = excluded.collection_status,
                    updated_at = excluded.updated_at;
                """,
                (
                    event.id,
                    event.meeting_id,
                    event.segment_id,
                    event.transcript_revision,
                    event.request_id,
                    event.edit_kind,
                    event.previous_text,
                    event.new_text,
                    event.raw_text,
                    event.normalized_text,
                    event.raw_text_origin,
                    event.reviewer_label,
                    event.created_at.isoformat(),
                    1 if event.verified_against_audio else 0,
                    1 if event.training_reuse_allowed else 0,
                    event.verification_status,
                    event.verified_by,
                    event.verified_at.isoformat() if event.verified_at else None,
                    event.rejection_reason,
                    audio_start,
                    audio_end,
                    audio_checksum,
                    speaker_cluster,
                    language,
                    eligibility_reason,
                    collection_status,
                    collected_at,
                    now_iso,
                ),
            )
            conn.commit()

    def get_event(self, event_id: str) -> Optional[dict[str, Any]]:
        """Retrieves a single correction event by ID."""
        self.init_db()
        with self.connection() as conn:
            cursor = conn.execute("SELECT * FROM correction_events WHERE id = ?", (event_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_event_by_request_id(self, request_id: str) -> Optional[dict[str, Any]]:
        """Retrieves a single correction event by request ID."""
        self.init_db()
        with self.connection() as conn:
            cursor = conn.execute("SELECT * FROM correction_events WHERE request_id = ?", (request_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_events(
        self,
        meeting_id: Optional[str] = None,
        verification_status: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Lists correction events with optional filtering."""
        self.init_db()
        query = "SELECT * FROM correction_events WHERE 1=1"
        params: list[Any] = []
        if meeting_id:
            query += " AND meeting_id = ?"
            params.append(meeting_id)
        if verification_status:
            query += " AND verification_status = ?"
            params.append(verification_status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self.connection() as conn:
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def count_distinct_accepted_events(self) -> dict[str, int]:
        """
        Calculates distinct counts for accepted/verified corrections, recordings, and speakers.
        Candidate counts represent distinct accepted events, recordings, and speakers, not repeated saves.
        """
        self.init_db()
        with self.connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM correction_events").fetchone()[0]
            unverified = conn.execute(
                "SELECT COUNT(*) FROM correction_events WHERE verification_status = 'unverified'"
            ).fetchone()[0]
            rejected = conn.execute(
                "SELECT COUNT(*) FROM correction_events WHERE verification_status = 'rejected'"
            ).fetchone()[0]

            verified_cursor = conn.execute(
                """
                SELECT 
                    COUNT(DISTINCT id),
                    COUNT(DISTINCT meeting_id),
                    COUNT(DISTINCT coalesce(speaker_cluster, 'unknown'))
                FROM correction_events
                WHERE verification_status = 'verified'
                  AND verified_against_audio = 1
                  AND training_reuse_allowed = 1
                """
            )
            v_events, v_meetings, v_speakers = verified_cursor.fetchone()

            return {
                "total_events": total,
                "unverified_events": unverified,
                "rejected_events": rejected,
                "distinct_verified_events": v_events or 0,
                "distinct_verified_meetings": v_meetings or 0,
                "distinct_verified_speakers": v_speakers or 0,
            }


# Global store singleton
adaptation_store = AdaptationStore()
