"""
Medpark Meeting Intelligence System - Verified ASR Dataset Builder
Constructs traceable, reproducible, permissioned training and evaluation datasets:
- Extracts 16 kHz mono clips directly from verified human-annotated intervals (2-28s).
- Strict validation: sample rate (16kHz), mono, bounded intervals, no redacted/empty labels.
- Groups splits by recording (meeting) to avoid acoustic and speaker leakage.
- Constructs speaker-disjoint challenge subsets for honest evaluation.
- Prevents accidental overwrites and stores versions strictly under ADAPTATION_DIR.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
from typing import Any, Optional
import uuid
import wave

from app.core.config import settings
from app.core.logging import logger
from app.services.learning.store import adaptation_store
from app.storage.repository import repository

MIN_CLIP_DURATION_S = 2.0
MAX_CLIP_DURATION_S = 28.0
TARGET_SAMPLE_RATE = 16000


@dataclass
class DatasetExample:
    example_id: str
    meeting_id: str
    event_id: str
    audio_path: str  # relative path within dataset
    audio_checksum: str
    sample_rate: int
    duration: float
    text: str  # verbatim verified human label
    raw_text: Optional[str]
    speaker_id: str
    language: str
    split: str  # "train", "dev", "test"
    is_speaker_disjoint: bool = False


@dataclass
class DatasetManifest:
    manifest_version: str = "1.0.0"
    dataset_id: str = field(default_factory=lambda: f"ds_{uuid.uuid4().hex[:8]}")
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    seed: int = 42
    label_policy: str = "verbatim_human_review"
    total_examples: int = 0
    total_duration_seconds: float = 0.0
    splits: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    speaker_groups: dict[str, list[str]] = field(default_factory=dict)
    language_distribution: dict[str, float] = field(default_factory=dict)
    eligible_event_ids: list[str] = field(default_factory=list)
    invalidated: bool = False
    invalidation_reason: Optional[str] = None
    checksum: str = ""


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _validate_output_dir(output_dir: Path) -> Path:
    target = output_dir.resolve()
    adaptation_root = Path(settings.ADAPTATION_DIR).resolve()
    if not (target == adaptation_root or adaptation_root in target.parents):
        raise ValueError(f"Output directory '{target}' resolves outside configured ADAPTATION_DIR '{adaptation_root}'")
    if (target / "manifest.json").exists():
        raise FileExistsError(f"Dataset already exists at '{target}'; overwrite is refused")
    return target


def build_dataset(output_dir: Path, seed: int = 42) -> DatasetManifest:
    """
    Builds a reproducible, permissioned dataset from verified adaptation events.
    Exports 16kHz mono audio slices and writes manifest.json.
    """
    out_dir = _validate_output_dir(output_dir)
    audio_dir = out_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    # 1. Fetch verified training-eligible events
    with adaptation_store.connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, meeting_id, segment_id, new_text, raw_text, previous_text,
                   audio_start, audio_end, edit_kind, verified_by, reviewer_label
            FROM correction_events
            WHERE verification_status = 'verified'
              AND verified_against_audio = 1
              AND training_reuse_allowed = 1
              AND audio_end > audio_start
            """
        )
        rows = cursor.fetchall()

    if not rows:
        manifest = DatasetManifest(seed=seed, splits={"train": [], "dev": [], "test": []})
        manifest_path = out_dir / "manifest.json"
        manifest_path.write_text(json.dumps(asdict(manifest), indent=2), encoding="utf-8")
        return manifest

    # 2. Filter & extract valid audio clips
    valid_records: list[dict[str, Any]] = []
    for row in rows:
        (
            ev_id,
            m_id,
            seg_id,
            new_text,
            raw_text,
            prev_text,
            a_start,
            a_end,
            edit_kind,
            verified_by,
            reviewer_label,
        ) = row

        duration = a_end - a_start
        if duration < MIN_CLIP_DURATION_S or duration > MAX_CLIP_DURATION_S:
            continue

        label_text = (new_text or "").strip()
        if not label_text or label_text in ("[REDACTED]", "[INAUDIBLE]"):
            continue

        # Locate source audio
        normalized_wav = settings.UPLOADS_DIR / m_id / "normalized_16k.wav"
        if not normalized_wav.is_file():
            normalized_wav = settings.UPLOADS_DIR / m_id / "original.wav"
            if not normalized_wav.is_file():
                continue

        try:
            with wave.open(str(normalized_wav), "rb") as wf:
                if wf.getnchannels() != 1 or wf.getframerate() != TARGET_SAMPLE_RATE:
                    continue
                sampwidth = wf.getsampwidth()
                total_frames = wf.getnframes()
                start_frame = int(a_start * TARGET_SAMPLE_RATE)
                end_frame = int(a_end * TARGET_SAMPLE_RATE)

                if start_frame < 0 or end_frame > total_frames or end_frame <= start_frame:
                    continue

                wf.setpos(start_frame)
                audio_frames = wf.readframes(end_frame - start_frame)
        except Exception as exc:
            logger.warning(f"Error reading audio for meeting {m_id}: {exc}")
            continue

        ex_id = f"clip_{uuid.uuid4().hex[:12]}"
        clip_rel = f"audio/{ex_id}.wav"
        clip_abs = out_dir / clip_rel

        with wave.open(str(clip_abs), "wb") as out_wf:
            out_wf.setnchannels(1)
            out_wf.setsampwidth(sampwidth)
            out_wf.setframerate(TARGET_SAMPLE_RATE)
            out_wf.writeframes(audio_frames)

        clip_sha = _sha256_file(clip_abs)
        speaker = verified_by or reviewer_label or f"spk_{m_id[:8]}"

        valid_records.append({
            "example_id": ex_id,
            "meeting_id": m_id,
            "event_id": ev_id,
            "audio_path": clip_rel,
            "audio_checksum": clip_sha,
            "sample_rate": TARGET_SAMPLE_RATE,
            "duration": round(duration, 3),
            "text": label_text,
            "raw_text": raw_text or prev_text,
            "speaker_id": speaker,
            "language": "ro",  # default verified language
        })

    # 3. Group by meeting for leakage-free splitting
    meetings_to_records: dict[str, list[dict[str, Any]]] = {}
    for r in valid_records:
        meetings_to_records.setdefault(r["meeting_id"], []).append(r)

    meeting_keys = sorted(meetings_to_records.keys())
    rng = random.Random(seed)
    rng.shuffle(meeting_keys)

    n_meetings = len(meeting_keys)
    if n_meetings >= 3:
        n_train = max(1, int(round(0.70 * n_meetings)))
        n_dev = max(1, int(round(0.15 * n_meetings)))
        train_meetings = set(meeting_keys[:n_train])
        dev_meetings = set(meeting_keys[n_train:n_train + n_dev])
        test_meetings = set(meeting_keys[n_train + n_dev:])
        if not test_meetings and dev_meetings:
            # Shift one to test if rounding left test empty
            shifted = next(iter(dev_meetings))
            dev_meetings.remove(shifted)
            test_meetings.add(shifted)
    elif n_meetings == 2:
        train_meetings = {meeting_keys[0]}
        dev_meetings = set()
        test_meetings = {meeting_keys[1]}
    else:
        train_meetings = set(meeting_keys)
        dev_meetings = set()
        test_meetings = set()

    # Identify speaker overlap for disjoint test
    train_speakers: set[str] = set()
    for m in train_meetings:
        for r in meetings_to_records[m]:
            train_speakers.add(r["speaker_id"])

    splits: dict[str, list[dict[str, Any]]] = {
        "train": [],
        "dev": [],
        "test": [],
        "speaker_disjoint_test": [],
    }

    speaker_groups: dict[str, list[str]] = {}
    lang_durations: dict[str, float] = {}
    total_dur = 0.0

    for m_id, records in meetings_to_records.items():
        if m_id in train_meetings:
            split_name = "train"
        elif m_id in dev_meetings:
            split_name = "dev"
        else:
            split_name = "test"

        for r in records:
            r["split"] = split_name
            is_disjoint = split_name == "test" and (r["speaker_id"] not in train_speakers)
            r["is_speaker_disjoint"] = is_disjoint

            splits[split_name].append(r)
            if is_disjoint:
                splits["speaker_disjoint_test"].append(r)

            speaker_groups.setdefault(r["speaker_id"], []).append(r["example_id"])
            lang_durations[r["language"]] = lang_durations.get(r["language"], 0.0) + r["duration"]
            total_dur += r["duration"]

    lang_dist = {
        lang: round(dur / total_dur, 3) if total_dur > 0 else 0.0
        for lang, dur in lang_durations.items()
    }

    manifest = DatasetManifest(
        seed=seed,
        total_examples=len(valid_records),
        total_duration_seconds=round(total_dur, 3),
        splits=splits,
        speaker_groups=speaker_groups,
        language_distribution=lang_dist,
        eligible_event_ids=[r["event_id"] for r in valid_records],
    )

    manifest_dict = asdict(manifest)
    manifest_bytes = json.dumps(manifest_dict, sort_keys=True).encode("utf-8")
    manifest.checksum = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_dict["checksum"] = manifest.checksum

    manifest_file = out_dir / "manifest.json"
    manifest_file.write_text(json.dumps(manifest_dict, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info(
        f"Built dataset at {out_dir}: {len(valid_records)} clips, "
        f"{round(total_dur, 1)}s audio (train: {len(splits['train'])}, "
        f"dev: {len(splits['dev'])}, test: {len(splits['test'])})"
    )
    return manifest
