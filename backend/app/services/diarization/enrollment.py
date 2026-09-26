"""
Medpark Meeting Intelligence System - Voiceprint Enrollment Quality Gate

Explicit enrollment under a controlled prompt is the ONLY path to a voiceprint (docs/SPEAKER_IDENTITY_DESIGN.md
5.5: no retro-enrollment from meeting audio). assess_sample() judges one recording before anything is stored;
build_voiceprint() averages the per-sample embeddings of every stored sample into one vector and reports the
cohesion between them. Nothing here decides who a person is; it only decides whether a recording is good enough
to represent the person who consented to record it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

from app.core.config import settings
from app.core.logging import logger
from app.models.person import SampleQuality, Voiceprint
from app.services.diarization.clustering import agglomerative_cosine, cosine_distance_matrix
from app.services.diarization.embedder import EXPECTED_SAMPLE_RATE, MIN_SECONDS, speaker_embedder
from app.services.diarization.speaker_engine import cut_windows, detect_speech_regions, load_wav16k, pooled_speech, slice_wav
from app.storage.file_manager import file_manager

# Level gates (dBFS of the RMS over the speech portion) and clipping gate (fraction of samples with |x| > 0.99)
LEVEL_REJECT_LOW_DBFS = -45.0
LEVEL_USABLE_LOW_DBFS = -35.0
LEVEL_REJECT_HIGH_DBFS = -6.0
CLIP_AMPLITUDE = 0.99
CLIP_REJECT_FRACTION = 0.02
# "usable" rather than "good" when the speech is short: between the minimum and this many seconds
USABLE_MAX_SPEECH_S = 10.0
# Two-voice probe: a second AHC cluster holding at least this share of the sample's speech rejects it
TWO_VOICE_MIN_SHARE = 0.30
# Only windows at least this long vote in the probe: sub-second windows (list-style prompts such as "one, two,
# three" leave the VAD 0.7-0.8 s regions) embed at cosine ~0.28 to the same voice and forge a second cluster
TWO_VOICE_MIN_WINDOW_S = 1.5


def _rms_dbfs(samples: np.ndarray) -> float:
    if len(samples) == 0:
        return -120.0
    rms = float(np.sqrt(np.mean(np.square(samples.astype(np.float64)))))
    return 20.0 * np.log10(max(rms, 1e-6))


def two_voice_check(wav16k: np.ndarray, regions: list[tuple[float, float]]) -> Optional[tuple[float, float]]:
    """
    Clusters the sample's own windows of at least TWO_VOICE_MIN_WINDOW_S at SPEAKER_CLUSTER_DISTANCE. Returns
    (share of the largest cluster, share of the second largest) when two clusters each hold >= TWO_VOICE_MIN_SHARE
    of the speech, else None. None also when the embedder is unavailable or fewer than two windows qualify.
    """
    if not speaker_embedder.available:
        return None
    windows = [w for w in cut_windows(regions, settings.SPEAKER_WINDOW_MAX_S) if w[2] - w[1] >= TWO_VOICE_MIN_WINDOW_S]
    if len(windows) < 2:
        return None
    embeddings = speaker_embedder.embed_batch([slice_wav(wav16k, s, e) for _, s, e in windows])
    labels = agglomerative_cosine(embeddings, settings.SPEAKER_CLUSTER_DISTANCE)
    durations = np.array([e - s for _, s, e in windows], dtype=np.float64)
    total = float(durations.sum())
    if total <= 0 or int(labels.max()) == 0:
        return None
    shares = sorted((float(durations[labels == label].sum() / total) for label in set(labels.tolist())), reverse=True)
    if len(shares) >= 2 and shares[1] >= TWO_VOICE_MIN_SHARE:
        return shares[0], shares[1]
    return None


def assess_sample(wav16k: np.ndarray) -> SampleQuality:
    """
    Quality verdict for one enrollment recording (16 kHz mono float32 in [-1, 1]).

    reject: too little speech, too quiet / too loud, clipped, or apparently two voices.
    usable: accepted but short (speech between the minimum and USABLE_MAX_SPEECH_S) or quiet (-45..-35 dBFS).
    good: everything else. Reasons are plain English and rendered verbatim to the person enrolling.
    """
    wav = np.asarray(wav16k, dtype=np.float32).reshape(-1)
    duration = len(wav) / EXPECTED_SAMPLE_RATE
    regions = detect_speech_regions(wav) if len(wav) else []
    speech_seconds = float(sum(e - s for s, e in regions))
    speech = pooled_speech(wav, regions) if regions else wav
    mean_dbfs = _rms_dbfs(speech)
    clipped_fraction = float(np.mean(np.abs(wav) > CLIP_AMPLITUDE)) if len(wav) else 0.0
    reasons: list[str] = []
    verdict = "good"

    min_speech = settings.SPEAKER_MIN_SAMPLE_SPEECH_S
    if speech_seconds < min_speech:
        verdict = "reject"
        reasons.append(
            f"Only {speech_seconds:.1f} s of speech detected; at least {min_speech:.0f} s are needed. "
            "Read the full prompt in one take."
        )
    if mean_dbfs < LEVEL_REJECT_LOW_DBFS:
        verdict = "reject"
        reasons.append(f"Recording is too quiet ({mean_dbfs:.0f} dBFS). Move closer to the microphone or raise the input level.")
    elif mean_dbfs > LEVEL_REJECT_HIGH_DBFS:
        verdict = "reject"
        reasons.append(f"Recording is too loud ({mean_dbfs:.0f} dBFS). Move away from the microphone or lower the input level.")
    if clipped_fraction > CLIP_REJECT_FRACTION:
        verdict = "reject"
        reasons.append(f"{clipped_fraction:.1%} of the samples are clipped (distorted). Lower the input level and record again.")

    if verdict != "reject" and speech_seconds >= min_speech:
        try:
            two_voices = two_voice_check(wav, regions)
        except Exception as exc:  # the probe must never turn a readable file into a crash
            logger.warning(f"Two-voice check failed, sample judged on level/duration only: {exc}")
            two_voices = None
        if two_voices is not None:
            verdict = "reject"
            reasons.append(
                f"The recording appears to contain two different voices ({two_voices[0]:.0%} / {two_voices[1]:.0%} of the speech). "
                "Record alone, in a quiet room, with nobody else speaking."
            )

    if verdict != "reject":
        if speech_seconds < USABLE_MAX_SPEECH_S:
            verdict = "usable"
            reasons.append(f"Short sample ({speech_seconds:.1f} s of speech). Longer samples give a more reliable voiceprint.")
        if LEVEL_REJECT_LOW_DBFS <= mean_dbfs < LEVEL_USABLE_LOW_DBFS:
            verdict = "usable"
            reasons.append(f"Quiet recording ({mean_dbfs:.0f} dBFS). Speaking a little closer to the microphone would help.")
        if verdict == "good":
            reasons.append(f"Good sample: {speech_seconds:.1f} s of clear speech at {mean_dbfs:.0f} dBFS.")

    return SampleQuality(
        duration_seconds=round(duration, 2),
        speech_seconds=round(speech_seconds, 2),
        mean_dbfs=round(float(mean_dbfs), 1),
        clipped_fraction=round(clipped_fraction, 4),
        verdict=verdict,
        reasons=reasons,
    )


def embed_sample(wav16k: np.ndarray) -> tuple[Optional[np.ndarray], float]:
    """(L2-normalised embedding over the sample's pooled VAD speech, speech seconds); embedding None if too short."""
    wav = np.asarray(wav16k, dtype=np.float32).reshape(-1)
    regions = detect_speech_regions(wav)
    speech = pooled_speech(wav, regions)
    speech_seconds = float(sum(e - s for s, e in regions))
    if len(speech) < int(MIN_SECONDS * EXPECTED_SAMPLE_RATE):
        return None, speech_seconds
    return speaker_embedder.embed(speech), speech_seconds


def mean_pairwise_cosine(embeddings: np.ndarray) -> Optional[float]:
    """Mean cosine over all pairs of rows; None with fewer than two rows."""
    n = embeddings.shape[0]
    if n < 2:
        return None
    dist = cosine_distance_matrix(embeddings)
    upper = np.triu_indices(n, k=1)
    return float(np.mean(1.0 - dist[upper]))


def build_voiceprint(person_id: str, sample_paths: list[Path], persist: bool = True) -> tuple[Voiceprint, np.ndarray]:
    """
    Rebuilds a person's voiceprint from ALL stored samples.

    Each sample is embedded once over its pooled VAD speech; the voiceprint is the L2-normalised mean of those
    embeddings and cohesion is their mean pairwise cosine. The Voiceprint is active only when total speech reaches
    SPEAKER_MIN_ENROLL_SPEECH_S and cohesion reaches SPEAKER_MIN_COHESION; otherwise quality_warnings say what is
    missing and is_active is False. With persist=True the vector is written to
    file_manager.get_voiceprint_path(person_id, voiceprint.id) and artifact_path points at it (relative to
    VOICEPRINTS_DIR). Returns (Voiceprint, per-sample embedding matrix (n, dim)); the matrix is never stored.
    Raises RuntimeError when the embedder is unavailable.
    """
    if not speaker_embedder.available:
        raise RuntimeError(speaker_embedder.load_error or "speaker embedder unavailable")
    space_id = speaker_embedder.space_id
    model_sha256 = speaker_embedder.model_sha256
    if not space_id or not model_sha256:
        raise RuntimeError("speaker embedder has no defined embedding space")

    embeddings: list[np.ndarray] = []
    total_speech = 0.0
    warnings: list[str] = []
    for path in sample_paths:
        try:
            wav = load_wav16k(Path(path))
        except Exception as exc:
            warnings.append(f"Sample {Path(path).name} could not be read and was skipped ({exc}).")
            continue
        embedding, speech_seconds = embed_sample(wav)
        if embedding is None:
            warnings.append(f"Sample {Path(path).name} holds no usable speech and was skipped.")
            continue
        embeddings.append(embedding)
        total_speech += speech_seconds

    matrix = np.stack(embeddings, axis=0) if embeddings else np.zeros((0, speaker_embedder.dim), dtype=np.float32)
    cohesion = mean_pairwise_cosine(matrix) if len(embeddings) else None

    missing_speech = settings.SPEAKER_MIN_ENROLL_SPEECH_S - total_speech
    if missing_speech > 0:
        warnings.append(
            f"{total_speech:.1f} s of speech enrolled so far; {missing_speech:.1f} s more are needed "
            f"(at least {settings.SPEAKER_MIN_ENROLL_SPEECH_S:.0f} s in total)."
        )
    if len(embeddings) < 2:
        warnings.append("Record at least two samples so their consistency can be measured.")
    elif cohesion is not None and cohesion < settings.SPEAKER_MIN_COHESION:
        warnings.append(
            f"The samples do not sound alike (cohesion {cohesion:.2f}, needed {settings.SPEAKER_MIN_COHESION:.2f}). "
            "Record in the same room with the same microphone, or delete the samples and start over."
        )
    qualifies = (
        len(embeddings) >= 2
        and total_speech >= settings.SPEAKER_MIN_ENROLL_SPEECH_S
        and cohesion is not None
        and cohesion >= settings.SPEAKER_MIN_COHESION
    )

    voiceprint = Voiceprint(
        space_id=space_id,
        model_sha256=model_sha256,
        dim=int(speaker_embedder.dim),
        artifact_path="",
        sample_count=len(embeddings),
        total_speech_seconds=round(total_speech, 2),
        cohesion=round(cohesion, 4) if cohesion is not None else None,
        quality_warnings=warnings,
        is_active=qualifies,
    )
    vector_path = file_manager.get_voiceprint_path(person_id, voiceprint.id)
    voiceprint.artifact_path = vector_path.relative_to(Path(settings.VOICEPRINTS_DIR)).as_posix()
    if persist and len(embeddings):
        mean = matrix.astype(np.float64).mean(axis=0)
        norm = float(np.linalg.norm(mean))
        vector = (mean / (norm if norm > 1e-12 else 1.0)).astype(np.float32)
        file_manager.save_embedding_matrix(vector_path, vector.reshape(1, -1))
        logger.info(
            f"Voiceprint {voiceprint.id} built for person {person_id}: {len(embeddings)} samples, "
            f"{total_speech:.1f} s speech, cohesion={cohesion if cohesion is None else round(cohesion, 3)}, active={qualifies}"
        )
    return voiceprint, matrix
