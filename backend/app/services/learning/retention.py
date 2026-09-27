"""
Medpark Meeting Intelligence System - Adaptation Retention and Source Invalidation
Enforces strict consent, privacy, and dataset lifecycle rules:
- Deleting a meeting or replacing its audio immediately revokes training eligibility.
- Invalidates dependent manifests and schedules physical deletion of derived clips.
- Surfaces locked files honestly without aborting data deletion.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Optional

from app.core.config import settings
from app.core.logging import logger
from app.services.learning.store import adaptation_store


@dataclass
class InvalidationReport:
    meeting_id: str
    reason: str
    invalidated_events_count: int
    deleted_clips_count: int
    locked_files: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def invalidate_source(meeting_id: str, reason: str) -> InvalidationReport:
    """
    Invalidates all adaptation events and derived dataset artifacts for a meeting.
    Called when a meeting is deleted or when its source audio is replaced.
    """
    invalidated_count = 0
    deleted_clips_count = 0
    locked_files: list[str] = []

    # 1. Update SQLite adaptation catalog
    try:
        with adaptation_store.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE correction_events
                SET verification_status = 'rejected',
                    training_reuse_allowed = 0,
                    rejection_reason = ?
                WHERE meeting_id = ?
                """,
                (f"source_invalidated: {reason}", meeting_id),
            )
            invalidated_count = cursor.rowcount
            conn.commit()
    except Exception as exc:
        logger.warning(f"Failed to invalidate adaptation events for {meeting_id}: {exc}")

    # 2. Scan datasets in ADAPTATION_DIR to invalidate manifests and remove derived clips
    adaptation_dir = Path(settings.ADAPTATION_DIR)
    if adaptation_dir.is_dir():
        for manifest_file in adaptation_dir.glob("**/manifest.json"):
            try:
                data = json.loads(manifest_file.read_text(encoding="utf-8"))
                manifest_touched = False
                affected_examples = []

                splits = data.get("splits", {})
                for split_name, examples in splits.items():
                    for ex in examples:
                        if ex.get("meeting_id") == meeting_id:
                            manifest_touched = True
                            affected_examples.append(ex)

                if manifest_touched:
                    data["invalidated"] = True
                    data["invalidation_reason"] = f"Referenced source meeting {meeting_id} was invalidated: {reason}"
                    data["invalidated_at"] = datetime.now(timezone.utc).isoformat()
                    manifest_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

                    dataset_root = manifest_file.parent
                    for ex in affected_examples:
                        clip_rel = ex.get("audio_path")
                        if clip_rel:
                            clip_path = (dataset_root / clip_rel).resolve()
                            if clip_path.is_file():
                                try:
                                    clip_path.unlink()
                                    deleted_clips_count += 1
                                except OSError as exc:
                                    locked_files.append(f"{clip_path}: {exc}")
                                    logger.warning(f"Could not delete locked clip {clip_path}: {exc}")
            except Exception as exc:
                logger.warning(f"Error checking manifest {manifest_file} during invalidation: {exc}")

    logger.info(
        f"Invalidated source {meeting_id} ({reason}): {invalidated_count} events updated, "
        f"{deleted_clips_count} clips deleted, {len(locked_files)} locked files."
    )
    return InvalidationReport(
        meeting_id=meeting_id,
        reason=reason,
        invalidated_events_count=invalidated_count,
        deleted_clips_count=deleted_clips_count,
        locked_files=locked_files,
    )
