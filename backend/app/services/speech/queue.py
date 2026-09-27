"""SQLite-backed durable FIFO queue and background worker for shared ASR jobs."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import shutil
import sqlite3
import threading
import time
from typing import Any

from app.models.transcript import TranscriptSegment

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SpeechQueue:
    """Manages persistent speech transcription jobs and a dedicated single-threaded worker."""

    def __init__(
        self,
        db_path: Path,
        uploads_dir: Path,
        engine: Any,
        max_pending_jobs: int = 10,
        job_ttl_seconds: int = 86400,
    ) -> None:
        self.db_path = Path(db_path)
        self.uploads_dir = Path(uploads_dir)
        self.engine = engine
        self.max_pending_jobs = max_pending_jobs
        self.job_ttl_seconds = job_ttl_seconds

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._worker_thread: threading.Thread | None = None

        self._init_db()

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._lock, self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS speech_jobs (
                    job_id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE,
                    status TEXT NOT NULL,
                    language TEXT,
                    initial_prompt TEXT,
                    audio_path TEXT NOT NULL,
                    duration_seconds REAL,
                    result TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_speech_jobs_status_created ON speech_jobs(status, created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_speech_jobs_idempotency ON speech_jobs(idempotency_key)"
            )
            # Recover running jobs after unclean shutdown
            now = _utc_now_iso()
            conn.execute(
                """
                UPDATE speech_jobs
                SET status = 'failed', error = 'Interrupted by server restart', updated_at = ?
                WHERE status = 'running'
                """,
                (now,),
            )
            conn.commit()

    def start(self) -> None:
        with self._lock:
            if self._worker_thread is None or not self._worker_thread.is_alive():
                self._stop_event.clear()
                self._worker_thread = threading.Thread(
                    target=self._worker_loop,
                    name="speech-queue-worker",
                    daemon=True,
                )
                self._worker_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self.engine is not None and hasattr(self.engine, "cancel"):
            try:
                self.engine.cancel()
            except Exception:
                pass
        if self._worker_thread is not None and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5.0)

    def get_queue_depth(self) -> int:
        with self._lock, self._connection() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM speech_jobs WHERE status IN ('queued', 'running')"
            )
            return cursor.fetchone()[0]

    def get_job_by_idempotency_key(self, idempotency_key: str) -> dict[str, Any] | None:
        with self._lock, self._connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM speech_jobs WHERE idempotency_key = ?",
                (idempotency_key,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_dict(row)

    def enqueue_job(
        self,
        job_id: str,
        audio_path: Path,
        duration_seconds: float,
        language: str | None = None,
        initial_prompt: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        now = _utc_now_iso()
        with self._lock, self._connection() as conn:
            conn.execute(
                """
                INSERT INTO speech_jobs (
                    job_id, idempotency_key, status, language, initial_prompt,
                    audio_path, duration_seconds, created_at, updated_at
                ) VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    idempotency_key,
                    language,
                    initial_prompt,
                    str(audio_path),
                    duration_seconds,
                    now,
                    now,
                ),
            )
            conn.commit()

        self._wake_event.set()
        return {
            "job_id": job_id,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
        }

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock, self._connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM speech_jobs WHERE job_id = ?",
                (job_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_dict(row)

    def delete_job(self, job_id: str) -> bool:
        with self._lock, self._connection() as conn:
            cursor = conn.execute(
                "SELECT status, audio_path FROM speech_jobs WHERE job_id = ?",
                (job_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return False
            status = row["status"]
            if status in ("queued", "running"):
                raise ValueError("Job is currently active")

            # Clean up job files
            audio_path = Path(row["audio_path"])
            job_dir = self.uploads_dir / job_id
            if job_dir.exists():
                shutil.rmtree(job_dir, ignore_errors=True)
            elif audio_path.exists():
                audio_path.unlink(missing_ok=True)

            conn.execute("DELETE FROM speech_jobs WHERE job_id = ?", (job_id,))
            conn.commit()
            return True

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        result_raw = row["result"]
        result = json.loads(result_raw) if result_raw else None
        return {
            "job_id": row["job_id"],
            "status": row["status"],
            "language": row["language"],
            "initial_prompt": row["initial_prompt"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "result": result,
            "error": row["error"],
        }

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            job = self._claim_next_job()
            if job is None:
                self._wake_event.wait(timeout=1.0)
                self._wake_event.clear()
                continue

            self._process_job(job)

    def _claim_next_job(self) -> dict[str, Any] | None:
        with self._lock, self._connection() as conn:
            cursor = conn.execute(
                """
                SELECT job_id, audio_path, language, initial_prompt, duration_seconds
                FROM speech_jobs
                WHERE status = 'queued'
                ORDER BY created_at ASC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
            if row is None:
                return None

            job_id = row["job_id"]
            now = _utc_now_iso()
            conn.execute(
                """
                UPDATE speech_jobs
                SET status = 'running', updated_at = ?
                WHERE job_id = ? AND status = 'queued'
                """,
                (now, job_id),
            )
            conn.commit()
            return {
                "job_id": job_id,
                "audio_path": Path(row["audio_path"]),
                "language": row["language"],
                "initial_prompt": row["initial_prompt"],
                "duration_seconds": row["duration_seconds"] or 0.0,
            }

    def _process_job(self, job: dict[str, Any]) -> None:
        job_id = job["job_id"]
        audio_path = job["audio_path"]
        language = job["language"]
        initial_prompt = job["initial_prompt"]

        try:
            asr_ctx = None
            if initial_prompt:
                try:
                    from app.services.asr.dynamic_context import ASRContext
                    asr_ctx = ASRContext(prompt_seed=initial_prompt)
                except Exception:
                    asr_ctx = None

            transcribe_kwargs = {
                "initial_prompt": initial_prompt,
                "language": language,
            }
            import inspect
            sig = inspect.signature(self.engine.transcribe)
            if "context" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                transcribe_kwargs["context"] = asr_ctx

            segments: list[TranscriptSegment] = self.engine.transcribe(
                audio_path,
                **transcribe_kwargs,
            )

            # Calculate total duration
            max_seg_end = max((seg.end for seg in segments), default=0.0)
            duration_seconds = max(job["duration_seconds"], max_seg_end)

            segments_data = []
            for seg in segments:
                if hasattr(seg, "model_dump"):
                    segments_data.append(seg.model_dump())
                elif hasattr(seg, "__dict__"):
                    segments_data.append(seg.__dict__)
                else:
                    segments_data.append(dict(seg))

            health = self.engine.health() if hasattr(self.engine, "health") else {}
            engine_name = health.get("engine") or getattr(self.engine, "engine", "whisper_cpp")
            model_name = health.get("model") or getattr(self.engine, "model_name", "unknown")
            device_name = health.get("device") or getattr(self.engine, "device", "metal")

            payload = {
                "segments": segments_data,
                "engine": engine_name,
                "model": model_name,
                "device": device_name,
                "duration_seconds": round(duration_seconds, 3),
            }

            now = _utc_now_iso()
            with self._lock, self._connection() as conn:
                conn.execute(
                    """
                    UPDATE speech_jobs
                    SET status = 'completed', result = ?, updated_at = ?
                    WHERE job_id = ?
                    """,
                    (json.dumps(payload), now, job_id),
                )
                conn.commit()

        except Exception as exc:
            logger.exception("Failed to transcribe speech job %s", job_id)
            now = _utc_now_iso()
            with self._lock, self._connection() as conn:
                conn.execute(
                    """
                    UPDATE speech_jobs
                    SET status = 'failed', error = ?, updated_at = ?
                    WHERE job_id = ?
                    """,
                    (str(exc), now, job_id),
                )
                conn.commit()
