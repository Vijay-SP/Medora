"""
Medpark Meeting Intelligence System - Embedding Speaker Diarization Engine (Silero VAD + CAM++ on CPU)

Replaces the former AcousticDiarizer, whose four hand-made features were measured to be at chance (every
vector inside a 3.85 degree cone). Pipeline per docs/SPEAKER_IDENTITY_DESIGN.md section 4, Layer A/B:

  1. Silero VAD (faster-whisper's bundled model, offline) over the normalized 16 kHz wav.
  2. Speech regions are cut at every transcript segment boundary inside them (fast turn-taking with gaps
     shorter than Silero's min-silence merges consecutive turns into ONE region; a window blending two turns
     is a 50/50 voice mix that no clustering or purity probe can separate) and the pieces inside a segment are
     cut into windows of at most SPEAKER_WINDOW_MAX_S seconds, embedded in one CPU batch by
     app.services.diarization.embedder (WeSpeaker CAM++, Kaldi fbank).
  3. Deterministic average-linkage clustering stopped at SPEAKER_CLUSTER_DISTANCE (biased toward
     over-splitting: an extra cluster costs a reviewer a click, a merged one puts a doctor's words under
     another's name), then per-cluster mixed-voice / too-few-regions probes.
  4. Every transcript segment takes the cluster with the largest speech-time overlap; segments straddling two
     clusters are flagged, never split. Labels are anonymous 'Speaker N' by first appearance and cluster ids
     'SPEAKER_NN'. The diarizer depends only on segment start/end/text, never on ASR internals.
  5. Cluster centroids are scored against enrolled voiceprints (matching.py). A match becomes a SUGGESTION on
     the segments; a confirmed name can only be written by a reviewer through the speakers API.
  6. Without the ONNX model every segment stays 'Speaker 1' and a WARNING is logged; there is no fallback to
     the at-chance acoustic features.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from app.core.config import settings
from app.core.logging import logger
from app.models.meeting import Attendee
from app.models.person import Person
from app.models.transcript import SpeakerSuggestion, TranscriptSegment
from app.services.diarization.base import BaseDiarizationEngine
from app.services.diarization.clustering import ClusterDiagnostics, agglomerative_cosine, diagnose_clusters
from app.services.diarization.embedder import EXPECTED_SAMPLE_RATE, MIN_SECONDS, speaker_embedder
from app.services.diarization.matching import merge_suggestions, pick_suggestion, score_clusters
from app.storage.file_manager import file_manager

# Silero settings for turn-level boundaries (ASR's own pass uses a coarser 500 ms silence)
VAD_THRESHOLD = 0.5
VAD_MIN_SPEECH_MS = 250
VAD_MIN_SILENCE_MS = 400
VAD_SPEECH_PAD_MS = 200
# A transcript segment gets its own cached embedding only with at least this much VAD speech inside it
SEGMENT_EMBED_MIN_SPEECH_S = 0.5
# A segment whose second-best cluster holds at least this share of its speech straddles a speaker change
STRADDLE_SHARE = 0.30
STRADDLE_FLAG_REASON = "Speaker change mid-segment"
DEFAULT_ANONYMOUS_LABEL = "Speaker 1"
CLUSTER_ID_PATTERN = re.compile(r"^SPEAKER_(\d+)$")
SIDECAR_VERSION = 1


def cluster_label(cluster_id: Optional[str]) -> Optional[str]:
    """The anonymous label a cluster id stands for ('SPEAKER_02' -> 'Speaker 2'); None for anything else."""
    match = CLUSTER_ID_PATTERN.match(cluster_id or "")
    return f"Speaker {int(match.group(1))}" if match else None


# ---------------------------------------------------------------- audio / VAD helpers (shared with enrollment)
def load_wav16k(path: Path) -> np.ndarray:
    """Mono float32 waveform of a 16 kHz file; refuses any other sample rate instead of resampling silently."""
    data, sample_rate = sf.read(str(path), dtype="float32")
    if data.ndim == 2:
        data = data.mean(axis=1)
    if sample_rate != EXPECTED_SAMPLE_RATE:
        raise ValueError(f"expected {EXPECTED_SAMPLE_RATE} Hz audio, got {sample_rate} Hz: {path}")
    return np.ascontiguousarray(data, dtype=np.float32)


def detect_speech_regions(
    wav16k: np.ndarray,
    threshold: float = VAD_THRESHOLD,
    min_speech_ms: int = VAD_MIN_SPEECH_MS,
    min_silence_ms: int = VAD_MIN_SILENCE_MS,
    speech_pad_ms: int = VAD_SPEECH_PAD_MS,
) -> list[tuple[float, float]]:
    """Silero VAD speech regions as (start_s, end_s), chronological and non-overlapping."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    wav = np.asarray(wav16k, dtype=np.float32).reshape(-1)
    if len(wav) == 0:
        return []
    options = VadOptions(
        threshold=threshold,
        min_speech_duration_ms=min_speech_ms,
        min_silence_duration_ms=min_silence_ms,
        speech_pad_ms=speech_pad_ms,
    )
    stamps = get_speech_timestamps(wav, options, sampling_rate=EXPECTED_SAMPLE_RATE)
    regions: list[tuple[float, float]] = []
    total = len(wav) / EXPECTED_SAMPLE_RATE
    for stamp in stamps:
        start = max(0.0, float(stamp["start"]) / EXPECTED_SAMPLE_RATE)
        end = min(total, float(stamp["end"]) / EXPECTED_SAMPLE_RATE)
        if end - start > 0:
            regions.append((start, end))
    return regions


def intersect_regions_with_segments(
    regions: list[tuple[float, float]],
    spans: list[tuple[float, float]],
) -> tuple[list[tuple[float, float]], float]:
    """
    Cuts each VAD region at every segment boundary that falls inside it and keeps the pieces lying inside a
    segment: (pieces, seconds of VAD speech outside every segment). Pieces are chronological, non-overlapping,
    each inside exactly one VAD region and never crossing a segment boundary, so a window cut from a piece
    holds one ASR turn even when Silero merged several turns (gaps below its min-silence) into one region.
    Speech Whisper never transcribed is left out of clustering: nothing would be labelled from it. Without
    spans the regions come back unchanged.
    """
    if not spans:
        return list(regions), 0.0
    seg_start = np.array([s for s, _ in spans], dtype=np.float64)
    seg_end = np.array([e for _, e in spans], dtype=np.float64)
    boundaries = np.unique(np.concatenate([seg_start, seg_end]))
    pieces: list[tuple[float, float]] = []
    outside = 0.0
    for start, end in regions:
        if end - start <= 0:
            continue
        inner = boundaries[(boundaries > start) & (boundaries < end)]
        edges = np.concatenate([[start], inner, [end]])
        for a, b in zip(edges[:-1], edges[1:]):
            mid = 0.5 * (a + b)
            if np.any((seg_start <= mid) & (mid <= seg_end)):
                pieces.append((float(a), float(b)))
            else:
                outside += float(b - a)
    return pieces, outside


def cut_windows(regions: list[tuple[float, float]], max_seconds: float) -> list[tuple[int, float, float]]:
    """
    Splits each speech region into equal parts no longer than max_seconds: (region_index, start_s, end_s).
    Parts shorter than the embedder's minimum are dropped so every window can be embedded. Windows never
    cross a region boundary, so whatever bounded the regions (VAD silence, a segment edge) bounds the windows.
    """
    windows: list[tuple[int, float, float]] = []
    for region_index, (start, end) in enumerate(regions):
        duration = end - start
        if duration <= 0:
            continue
        parts = max(1, int(math.ceil(duration / max(max_seconds, 1e-6))))
        step = duration / parts
        for part in range(parts):
            w_start = start + part * step
            w_end = end if part == parts - 1 else start + (part + 1) * step
            if w_end - w_start >= MIN_SECONDS:
                windows.append((region_index, w_start, w_end))
    return windows


def slice_wav(wav16k: np.ndarray, start_s: float, end_s: float) -> np.ndarray:
    a = max(0, int(round(start_s * EXPECTED_SAMPLE_RATE)))
    b = min(len(wav16k), int(round(end_s * EXPECTED_SAMPLE_RATE)))
    return wav16k[a:b]


def pooled_speech(wav16k: np.ndarray, spans: list[tuple[float, float]]) -> np.ndarray:
    """Concatenation of the given (start_s, end_s) speech spans: one forward pass over pooled speech."""
    pieces = [slice_wav(wav16k, s, e) for s, e in spans]
    pieces = [p for p in pieces if len(p)]
    if not pieces:
        return np.zeros((0,), dtype=np.float32)
    return np.concatenate(pieces)


def _unit(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return vector / (norm if norm > 1e-12 else 1.0)


# ---------------------------------------------------------------- engine
class EmbeddingDiarizer(BaseDiarizationEngine):
    """Speaker clustering on CAM++ embeddings; anonymous labels, reviewer-gated identity suggestions."""

    def assign_speakers(
        self,
        audio_path: Path,
        segments: list[TranscriptSegment],
        attendees: Optional[list[Attendee]] = None,
        meeting_id: Optional[str] = None,
        people: Optional[list[Person]] = None,
    ) -> list[TranscriptSegment]:
        if not segments:
            return []
        for seg in segments:
            self._reset_attribution(seg)

        if not speaker_embedder.available:
            logger.warning(
                f"speaker diarization unavailable ({speaker_embedder.load_error}); "
                f"all {len(segments)} segments keep the label '{DEFAULT_ANONYMOUS_LABEL}'"
            )
            return segments

        try:
            wav = load_wav16k(Path(audio_path))
        except Exception as exc:
            logger.warning(f"speaker diarization unavailable: could not read {audio_path}: {exc}")
            return segments

        vad_regions = detect_speech_regions(wav)
        # A "region" from here on is VAD speech bounded by silence OR by a segment edge: the unit that is embedded
        # and clustered on its own, and the unit the "distinct regions" evidence check counts.
        regions, outside = intersect_regions_with_segments(vad_regions, [(seg.start, seg.end) for seg in segments])
        windows = cut_windows(regions, settings.SPEAKER_WINDOW_MAX_S)
        if not windows:
            logger.warning(f"speaker diarization found no speech in {audio_path}; every segment stays '{DEFAULT_ANONYMOUS_LABEL}'")
            return segments

        w_region = np.array([w[0] for w in windows], dtype=np.int64)
        w_start = np.array([w[1] for w in windows], dtype=np.float64)
        w_end = np.array([w[2] for w in windows], dtype=np.float64)
        w_duration = w_end - w_start
        logger.info(
            f"Diarization: {len(vad_regions)} VAD regions ({float(sum(e - s for s, e in vad_regions)):.1f} s speech) cut at "
            f"segment edges into {len(regions)} regions ({outside:.1f} s outside every segment dropped), "
            f"{len(windows)} windows <= {settings.SPEAKER_WINDOW_MAX_S:.0f} s"
        )

        window_embeddings = speaker_embedder.embed_batch([slice_wav(wav, s, e) for _, s, e in windows])
        labels = agglomerative_cosine(window_embeddings, settings.SPEAKER_CLUSTER_DISTANCE)
        diagnostics = diagnose_clusters(window_embeddings, labels, w_duration, w_region)

        # --- segment labelling by largest speech-time overlap, numbered by first appearance
        order = sorted(range(len(segments)), key=lambda i: (segments[i].start, segments[i].end))
        n_labels = int(labels.max()) + 1
        label_to_number: dict[int, int] = {}
        segment_label: list[int] = [0] * len(segments)
        segment_spans: list[list[tuple[float, float]]] = [[] for _ in segments]
        straddling = 0
        for i in order:
            seg = segments[i]
            overlap = np.clip(np.minimum(seg.end, w_end) - np.maximum(seg.start, w_start), 0.0, None)
            speech = float(overlap.sum())
            seg.speech_seconds = round(speech, 3)
            if speech > 0:
                per_label = np.bincount(labels, weights=overlap, minlength=n_labels)
                best = int(np.argmax(per_label))
                shares = per_label / speech
                second = float(np.sort(shares)[-2]) if n_labels > 1 else 0.0
                if second >= STRADDLE_SHARE and shares[best] >= STRADDLE_SHARE:
                    straddling += 1
                    seg.is_flagged = True
                    if not seg.flag_reason:
                        seg.flag_reason = STRADDLE_FLAG_REASON
                    elif STRADDLE_FLAG_REASON not in seg.flag_reason:
                        seg.flag_reason = f"{seg.flag_reason}; {STRADDLE_FLAG_REASON}"
                for w_idx in np.flatnonzero(overlap > 0):
                    segment_spans[i].append((max(seg.start, float(w_start[w_idx])), min(seg.end, float(w_end[w_idx]))))
            else:
                # Whisper placed the segment inside VAD silence: borrow the nearest window's cluster, no speech credit
                mid = 0.5 * (seg.start + seg.end)
                distance = np.where(mid < w_start, w_start - mid, np.where(mid > w_end, mid - w_end, 0.0))
                best = int(labels[int(np.argmin(distance))])
            segment_label[i] = best
            if best not in label_to_number:
                label_to_number[best] = len(label_to_number) + 1

        cluster_ids: dict[int, str] = {}
        for i, seg in enumerate(segments):
            number = label_to_number[segment_label[i]]
            seg.speaker = f"Speaker {number}"
            seg.cluster_id = f"SPEAKER_{number:02d}"
            cluster_ids[segment_label[i]] = seg.cluster_id

        # --- per-segment embeddings over the segment's own pooled speech (cached for re-scoring / sampling)
        embed_indices = [i for i, seg in enumerate(segments) if (seg.speech_seconds or 0.0) >= SEGMENT_EMBED_MIN_SPEECH_S]
        segment_matrix = np.zeros((0, speaker_embedder.dim), dtype=np.float32)
        if embed_indices:
            pooled = [pooled_speech(wav, segment_spans[i]) for i in embed_indices]
            keep = [k for k, p in enumerate(pooled) if len(p) >= int(MIN_SECONDS * EXPECTED_SAMPLE_RATE)]
            embed_indices = [embed_indices[k] for k in keep]
            if keep:
                segment_matrix = speaker_embedder.embed_batch([pooled[k] for k in keep])

        # --- cluster centroids (duration-weighted over window embeddings) and voiceprint suggestions
        centroids: dict[str, np.ndarray] = {}
        for label, cluster_id in cluster_ids.items():
            members = labels == label
            weights = w_duration[members]
            centroids[cluster_id] = _unit((window_embeddings[members] * weights[:, None]).sum(axis=0) / max(float(weights.sum()), 1e-9))

        space_id = speaker_embedder.space_id
        candidates_by_cluster = {}
        suggested_clusters = 0
        if people and settings.VOICE_ID_ENABLED and space_id:
            candidates_by_cluster = score_clusters(centroids, people, space_id)
            for i, seg in enumerate(segments):
                pick = pick_suggestion(candidates_by_cluster.get(seg.cluster_id, []))
                if pick is None:
                    continue
                seg.suggestion = SpeakerSuggestion(
                    person_id=pick.person_id, person_name=pick.person_name, score=pick.score,
                    margin=pick.margin, band=pick.band, space_id=space_id,
                )
                seg.suggested_identity = pick.person_name
                seg.attribution_state = "suggested"
            suggested_clusters = sum(1 for cid in cluster_ids.values() if pick_suggestion(candidates_by_cluster.get(cid, [])))
            for a, b in merge_suggestions(candidates_by_cluster):
                logger.info(f"Diarization: clusters {a} and {b} both resemble the same enrolled person (merge suggestion, not applied)")

        if meeting_id:
            self._cache_embeddings(
                meeting_id, segments, embed_indices, segment_matrix, cluster_ids, diagnostics, labels, w_duration,
                candidates_by_cluster, space_id,
            )

        suspect = [cluster_ids[l] for l, d in diagnostics.items() if l in cluster_ids and (d.mixed_suspect or d.short_suspect)]
        logger.info(
            f"Diarization clustered {len(windows)} windows into {n_labels} clusters; {len(cluster_ids)} appear on "
            f"{len(segments)} segments ({straddling} straddling a speaker change, {len(embed_indices)} with cached "
            f"embeddings, {suggested_clusters} clusters with a voiceprint suggestion, suspect: {suspect or 'none'})"
        )
        return segments

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _reset_attribution(seg: TranscriptSegment) -> None:
        """A freshly diarized segment carries no identity: only a reviewer can add one later."""
        seg.speaker = DEFAULT_ANONYMOUS_LABEL
        seg.cluster_id = None
        seg.attribution_state = "anonymous"
        seg.speaker_id = None
        seg.confirmed_display_name = None
        seg.confirmed_by = None
        seg.confirmed_at = None
        seg.confirmed_for_revision = None
        seg.suggestion = None
        seg.suggested_identity = None
        seg.speech_seconds = None
        seg.printable_name = False

    @staticmethod
    def _cache_embeddings(
        meeting_id: str,
        segments: list[TranscriptSegment],
        embed_indices: list[int],
        matrix: np.ndarray,
        cluster_ids: dict[int, str],
        diagnostics: dict[int, ClusterDiagnostics],
        labels: np.ndarray,
        w_duration: np.ndarray,
        candidates_by_cluster: dict,
        space_id: Optional[str],
    ) -> None:
        """
        Writes the (n, dim) segment-embedding matrix and its sidecar under VOICEPRINTS_DIR/meetings/<id>/.
        Best effort: the cache only serves re-scoring and turn sampling, so a failure must not fail the run.
        """
        try:
            matrix_path, sidecar_path = file_manager.get_segment_embedding_paths(meeting_id)
            digest = file_manager.save_embedding_matrix(matrix_path, matrix)
            clusters: dict[str, dict] = {}
            for label, cluster_id in cluster_ids.items():
                diag = diagnostics.get(label)
                members = labels == label
                clusters[cluster_id] = {
                    "display_label": f"Speaker {int(cluster_id.split('_')[-1])}",
                    "window_count": int(members.sum()),
                    "window_speech_seconds": round(float(w_duration[members].sum()), 3),
                    "region_count": diag.region_count if diag else 0,
                    "mixed_suspect": bool(diag.mixed_suspect) if diag else True,
                    "short_suspect": bool(diag.short_suspect) if diag else True,
                    "split_cosine": diag.split_cosine if diag else None,
                    "split_shares": list(diag.split_shares) if diag else [1.0, 0.0],
                    "reasons": list(diag.reasons) if diag else ["Cluster diagnostics were not computed."],
                    "candidates": [c.model_dump() for c in candidates_by_cluster.get(cluster_id, [])],
                }
            sidecar = {
                "version": SIDECAR_VERSION,
                "meeting_id": meeting_id,
                "segment_ids": [segments[i].id for i in embed_indices],
                "space_id": space_id,
                "model_sha256": speaker_embedder.model_sha256,
                "sha256": digest,
                "dim": int(matrix.shape[1]) if matrix.ndim == 2 else speaker_embedder.dim,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "clusters": clusters,
                "merge_suggestions": [list(pair) for pair in merge_suggestions(candidates_by_cluster)],
            }
            temp_path = sidecar_path.with_name(f"{sidecar_path.stem}.tmp.json")
            temp_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
            temp_path.replace(sidecar_path)
            logger.info(f"Cached {len(embed_indices)} segment embeddings for meeting {meeting_id} at {matrix_path}")
        except Exception as exc:
            logger.warning(f"Could not cache segment embeddings for meeting {meeting_id}: {exc}")


def load_cached_embeddings(meeting_id: str) -> Optional[tuple[np.ndarray, dict]]:
    """
    (matrix, sidecar) cached by the diarizer for a meeting, or None when absent or when the matrix does not
    match the sidecar's sha256 / row count (a stale or partially written cache must not be scored).
    """
    try:
        matrix_path, sidecar_path = file_manager.get_segment_embedding_paths(meeting_id)
    except Exception:
        return None
    if not matrix_path.is_file() or not sidecar_path.is_file():
        return None
    try:
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        if file_manager.compute_sha256(matrix_path) != sidecar.get("sha256"):
            logger.warning(f"Segment embedding cache for meeting {meeting_id} does not match its sidecar; ignored")
            return None
        matrix = np.load(matrix_path, allow_pickle=False)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.warning(f"Segment embedding cache for meeting {meeting_id} unreadable: {exc}")
        return None
    if matrix.ndim != 2 or matrix.shape[0] != len(sidecar.get("segment_ids", [])):
        logger.warning(f"Segment embedding cache for meeting {meeting_id} has an inconsistent shape; ignored")
        return None
    return matrix.astype(np.float32, copy=False), sidecar


diarization_engine = EmbeddingDiarizer()
