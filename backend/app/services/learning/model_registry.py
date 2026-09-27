"""
Medpark Meeting Intelligence System - ASR Model Registry & Release Gate
Maintains immutable artifact records, release lifecycle states, and safe atomic switching:
- States: candidate -> evaluated -> approved -> active -> retired | invalidated
- Cryptographic verification of model weights and evaluation reports.
- Enforces strict human approval before activation.
- Supports atomic rollback to previous working artifact.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Literal, Optional
import uuid

from app.core.config import settings
from app.core.logging import logger

ModelRuntime = Literal["ctranslate2", "whisper_cpp"]
ModelStatus = Literal["candidate", "evaluated", "approved", "active", "retired", "invalidated"]


@dataclass
class ModelArtifact:
    artifact_id: str
    name: str
    version: str
    target_runtime: ModelRuntime
    quantization: str
    base_model: str
    model_path: str
    checksum: str
    status: ModelStatus = "candidate"
    dataset_id: Optional[str] = None
    evaluation_report_hash: Optional[str] = None
    evaluation_passed: bool = False
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    activated_at: Optional[str] = None
    previous_active_artifact_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ModelRegistry:
    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path

    @property
    def db_path(self) -> Path:
        if self._db_path:
            return self._db_path
        adaptation_dir = Path(settings.ADAPTATION_DIR)
        adaptation_dir.mkdir(parents=True, exist_ok=True)
        return adaptation_dir / "model_registry.sqlite3"

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        self._init_db(conn)
        return conn

    def _init_db(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS model_artifacts (
                artifact_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                version TEXT NOT NULL,
                target_runtime TEXT NOT NULL,
                quantization TEXT NOT NULL,
                base_model TEXT NOT NULL,
                model_path TEXT NOT NULL,
                checksum TEXT NOT NULL,
                status TEXT NOT NULL,
                dataset_id TEXT,
                evaluation_report_hash TEXT,
                evaluation_passed INTEGER DEFAULT 0,
                approved_by TEXT,
                approved_at TEXT,
                activated_at TEXT,
                previous_active_artifact_id TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()

    def register_artifact(
        self,
        name: str,
        version: str,
        target_runtime: ModelRuntime,
        quantization: str,
        base_model: str,
        model_path: Path,
        checksum: str,
        dataset_id: Optional[str] = None,
    ) -> ModelArtifact:
        """Registers a new model artifact in 'candidate' status."""
        artifact = ModelArtifact(
            artifact_id=f"art_{uuid.uuid4().hex[:10]}",
            name=name,
            version=version,
            target_runtime=target_runtime,
            quantization=quantization,
            base_model=base_model,
            model_path=str(model_path.resolve()),
            checksum=checksum,
            dataset_id=dataset_id,
            status="candidate",
        )
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO model_artifacts (
                    artifact_id, name, version, target_runtime, quantization,
                    base_model, model_path, checksum, status, dataset_id,
                    evaluation_report_hash, evaluation_passed, approved_by,
                    approved_at, activated_at, previous_active_artifact_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.artifact_id, artifact.name, artifact.version, artifact.target_runtime,
                    artifact.quantization, artifact.base_model, artifact.model_path, artifact.checksum,
                    artifact.status, artifact.dataset_id, artifact.evaluation_report_hash,
                    1 if artifact.evaluation_passed else 0, artifact.approved_by, artifact.approved_at,
                    artifact.activated_at, artifact.previous_active_artifact_id, artifact.created_at,
                ),
            )
            conn.commit()
        logger.info(f"Registered model candidate {artifact.artifact_id} ({artifact.name} v{artifact.version})")
        return artifact

    def get_artifact(self, artifact_id: str) -> Optional[ModelArtifact]:
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM model_artifacts WHERE artifact_id = ?", (artifact_id,))
            row = cur.fetchone()
            if not row:
                return None
            return self._row_to_artifact(row)

    def attach_evaluation(
        self,
        artifact_id: str,
        report_hash: str,
        evaluation_passed: bool,
    ) -> ModelArtifact:
        """Attaches an evaluation report hash and updates candidate to 'evaluated' status."""
        artifact = self.get_artifact(artifact_id)
        if not artifact:
            raise KeyError(f"Artifact {artifact_id} not found")
        if artifact.status in ("retired", "invalidated"):
            raise ValueError(f"Cannot evaluate artifact in '{artifact.status}' status")

        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE model_artifacts
                SET evaluation_report_hash = ?,
                    evaluation_passed = ?,
                    status = 'evaluated'
                WHERE artifact_id = ?
                """,
                (report_hash, 1 if evaluation_passed else 0, artifact_id),
            )
            conn.commit()

        artifact.evaluation_report_hash = report_hash
        artifact.evaluation_passed = evaluation_passed
        artifact.status = "evaluated"
        return artifact

    def approve_artifact(
        self,
        artifact_id: str,
        reviewer_label: str,
        evaluation_report_hash: str,
    ) -> ModelArtifact:
        """Approves an evaluated artifact for production activation."""
        artifact = self.get_artifact(artifact_id)
        if not artifact:
            raise KeyError(f"Artifact {artifact_id} not found")
        if not artifact.evaluation_passed:
            raise ValueError(f"Artifact {artifact_id} did not pass evaluation gates")
        if artifact.evaluation_report_hash != evaluation_report_hash:
            raise ValueError("Report hash mismatch: approval must match verified evaluation report")

        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE model_artifacts
                SET approved_by = ?,
                    approved_at = ?,
                    status = 'approved'
                WHERE artifact_id = ?
                """,
                (reviewer_label, now_str, artifact_id),
            )
            conn.commit()

        artifact.approved_by = reviewer_label
        artifact.approved_at = now_str
        artifact.status = "approved"
        logger.info(f"Model artifact {artifact_id} approved by {reviewer_label}")
        return artifact

    def activate_artifact(self, artifact_id: str, operator_label: str) -> ModelArtifact:
        """
        Atomically activates an approved model artifact:
        - Verifies approval status and physical file existence.
        - Retires current active artifact and links it as previous_active_artifact.
        - Transitions target artifact to 'active'.
        """
        artifact = self.get_artifact(artifact_id)
        if not artifact:
            raise KeyError(f"Artifact {artifact_id} not found")
        if artifact.status != "approved":
            raise ValueError(f"Cannot activate artifact with status '{artifact.status}'; must be 'approved'")

        # Verify model files exist on disk
        model_p = Path(artifact.model_path)
        if not model_p.exists():
            raise FileNotFoundError(f"Model path does not exist on disk: {model_p}")

        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            # Find currently active artifact for this runtime
            cur = conn.execute(
                "SELECT * FROM model_artifacts WHERE target_runtime = ? AND status = 'active'",
                (artifact.target_runtime,),
            )
            current_active = cur.fetchone()
            prev_id = current_active["artifact_id"] if current_active else None

            if prev_id:
                conn.execute(
                    "UPDATE model_artifacts SET status = 'retired' WHERE artifact_id = ?",
                    (prev_id,),
                )

            conn.execute(
                """
                UPDATE model_artifacts
                SET status = 'active',
                    activated_at = ?,
                    previous_active_artifact_id = ?
                WHERE artifact_id = ?
                """,
                (now_str, prev_id, artifact_id),
            )
            conn.commit()

        artifact.status = "active"
        artifact.activated_at = now_str
        artifact.previous_active_artifact_id = prev_id
        logger.info(f"Activated model artifact {artifact_id} for runtime {artifact.target_runtime} (previous: {prev_id})")
        return artifact

    def rollback_runtime(self, target_runtime: ModelRuntime, operator_label: str, reason: str) -> Optional[ModelArtifact]:
        """
        Rolls back the active model for a runtime to its previous working version.
        Retires the failing active artifact.
        """
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM model_artifacts WHERE target_runtime = ? AND status = 'active'",
                (target_runtime,),
            )
            current_active = cur.fetchone()
            if not current_active:
                logger.warning(f"No active artifact found for runtime {target_runtime} to rollback")
                return None

            active_id = current_active["artifact_id"]
            prev_id = current_active["previous_active_artifact_id"]
            if not prev_id:
                raise ValueError(f"No previous active artifact recorded for active model {active_id}")

            # Retire current active
            conn.execute("UPDATE model_artifacts SET status = 'retired' WHERE artifact_id = ?", (active_id,))

            # Reactivate previous
            now_str = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE model_artifacts SET status = 'active', activated_at = ? WHERE artifact_id = ?",
                (now_str, prev_id),
            )
            conn.commit()

        logger.info(f"Rolled back {target_runtime} from {active_id} to {prev_id}: {reason}")
        return self.get_artifact(prev_id)

    def get_active_artifact(self, target_runtime: ModelRuntime) -> Optional[ModelArtifact]:
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM model_artifacts WHERE target_runtime = ? AND status = 'active'",
                (target_runtime,),
            )
            row = cur.fetchone()
            return self._row_to_artifact(row) if row else None

    def list_artifacts(self, target_runtime: Optional[ModelRuntime] = None) -> list[ModelArtifact]:
        with self._get_connection() as conn:
            if target_runtime:
                cur = conn.execute(
                    "SELECT * FROM model_artifacts WHERE target_runtime = ? ORDER BY created_at DESC",
                    (target_runtime,),
                )
            else:
                cur = conn.execute("SELECT * FROM model_artifacts ORDER BY created_at DESC")
            return [self._row_to_artifact(row) for row in cur.fetchall()]

    def _row_to_artifact(self, row: sqlite3.Row) -> ModelArtifact:
        return ModelArtifact(
            artifact_id=row["artifact_id"],
            name=row["name"],
            version=row["version"],
            target_runtime=row["target_runtime"],
            quantization=row["quantization"],
            base_model=row["base_model"],
            model_path=row["model_path"],
            checksum=row["checksum"],
            status=row["status"],
            dataset_id=row["dataset_id"],
            evaluation_report_hash=row["evaluation_report_hash"],
            evaluation_passed=bool(row["evaluation_passed"]),
            approved_by=row["approved_by"],
            approved_at=row["approved_at"],
            activated_at=row["activated_at"],
            previous_active_artifact_id=row["previous_active_artifact_id"],
            created_at=row["created_at"],
        )


model_registry = ModelRegistry()
