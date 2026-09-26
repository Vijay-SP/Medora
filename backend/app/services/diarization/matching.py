"""
Medpark Meeting Intelligence System - Open-Set Voiceprint Matching

Scores every speaker cluster INDEPENDENTLY against every enrolled voiceprint of the active embedding space.
There is deliberately no one-to-one assignment, no Hungarian solver and no forced choice: an unenrolled visitor
must come out as "no match", and two clusters that both resemble one person are reported as a merge
suggestion rather than one of them being pushed onto somebody else (docs/SPEAKER_IDENTITY_DESIGN.md 5.3/5.4).
A match here is only ever a SUGGESTION for a reviewer; nothing in this module writes a name anywhere.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import numpy as np
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logging import logger
from app.models.person import Person, Voiceprint
from app.services.diarization.embedder import cosine, speaker_embedder

MatchBand = Literal["strong", "moderate", "weak", "no_match"]

BAND_STRONG = 0.80
BAND_MODERATE = 0.65
BAND_WEAK = 0.50


class Candidate(BaseModel):
    """One person's similarity to one cluster. score is a cosine similarity, never a probability."""
    person_id: str
    person_name: str
    score: float
    margin: float = Field(..., description="score minus the runner-up person's score (0.0 when nobody else is enrolled)")
    band: MatchBand
    voiceprint_id: Optional[str] = None


class VoiceprintRef(BaseModel):
    """Owner and identity of one loaded voiceprint; the vector itself travels beside it, never inside it."""
    person_id: str
    person_name: str
    voiceprint_id: str
    space_id: str


def band_for_score(score: float) -> MatchBand:
    """strong >= 0.80, moderate 0.65-0.80, weak 0.50-0.65, otherwise no_match."""
    if score >= BAND_STRONG:
        return "strong"
    if score >= BAND_MODERATE:
        return "moderate"
    if score >= BAND_WEAK:
        return "weak"
    return "no_match"


def voiceprint_vector_path(voiceprint: Voiceprint) -> Path:
    """Absolute path of a voiceprint's .npy artifact (artifact_path is relative to VOICEPRINTS_DIR)."""
    return Path(settings.VOICEPRINTS_DIR) / voiceprint.artifact_path


def load_voiceprint_vector(voiceprint: Voiceprint) -> Optional[np.ndarray]:
    """Loads and L2-normalises a stored voiceprint vector; None (with a log line) when it cannot be read."""
    path = voiceprint_vector_path(voiceprint)
    try:
        vector = np.load(path, allow_pickle=False)
    except (OSError, ValueError) as exc:
        logger.warning(f"Voiceprint {voiceprint.id} could not be loaded from {path}: {exc}")
        return None
    vector = np.asarray(vector, dtype=np.float32).reshape(-1)
    if vector.shape[0] != voiceprint.dim:
        logger.warning(f"Voiceprint {voiceprint.id} has {vector.shape[0]} dimensions, expected {voiceprint.dim}; skipped")
        return None
    norm = float(np.linalg.norm(vector))
    if norm < 1e-12:
        logger.warning(f"Voiceprint {voiceprint.id} is a zero vector; skipped")
        return None
    return vector / norm


def collect_voiceprints(
    people: list[Person],
    space_id: Optional[str],
) -> tuple[list[tuple[VoiceprintRef, np.ndarray]], list[str]]:
    """
    Every active voiceprint of every active, consenting person in the given embedding space, with its vector.
    The second value lists, in plain English, why people or voiceprints were skipped (surfaced as warnings).
    """
    refs: list[tuple[VoiceprintRef, np.ndarray]] = []
    skipped: list[str] = []
    if not space_id:
        if people:
            skipped.append("speaker embedder unavailable: no voiceprint can be compared")
        return refs, skipped
    for person in people:
        if not person.is_active:
            continue
        if not person.consent_effective:
            if person.voiceprints:
                skipped.append(f"{person.full_name}: biometric consent not in effect; voiceprints ignored")
            continue
        active_in_space = person.active_voiceprints(space_id)
        if not active_in_space:
            if person.voiceprints:
                skipped.append(f"{person.full_name}: no voiceprint in the active embedding space (needs re-enrollment)")
            continue
        for vp in active_in_space:
            vector = load_voiceprint_vector(vp)
            if vector is None:
                skipped.append(f"{person.full_name}: voiceprint {vp.id} unreadable")
                continue
            refs.append((VoiceprintRef(person_id=person.id, person_name=person.full_name, voiceprint_id=vp.id, space_id=vp.space_id), vector))
    return refs, skipped


def score_vector(vector: np.ndarray, refs: list[tuple[VoiceprintRef, np.ndarray]]) -> list[Candidate]:
    """
    Ranks every enrolled person against one embedding (cluster centroid or single turn).
    A person with several voiceprints is scored by the best one. Sorted by score descending, then by name so
    equal scores are ordered deterministically. margin is top1 - top2 over PERSONS, not voiceprints.
    """
    best: dict[str, tuple[VoiceprintRef, float]] = {}
    for ref, vp_vector in refs:
        score = cosine(vector, vp_vector)
        current = best.get(ref.person_id)
        if current is None or score > current[1]:
            best[ref.person_id] = (ref, score)
    ranked = sorted(best.values(), key=lambda item: (-item[1], item[0].person_name, item[0].person_id))
    candidates: list[Candidate] = []
    for position, (ref, score) in enumerate(ranked):
        # top-1: distance to the runner-up (0.0 when nobody else is enrolled); others: distance to the top-1 (<= 0)
        if position == 0:
            runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
        else:
            runner_up = ranked[0][1]
        candidates.append(Candidate(
            person_id=ref.person_id,
            person_name=ref.person_name,
            score=round(float(score), 4),
            margin=round(float(score - runner_up), 4),
            band=band_for_score(float(score)),
            voiceprint_id=ref.voiceprint_id,
        ))
    return candidates


def pick_suggestion(candidates: list[Candidate]) -> Optional[Candidate]:
    """
    The single candidate a reviewer may be asked about, or None.
    Requires the top score >= SPEAKER_MATCH_MIN_SCORE and top1 - top2 >= SPEAKER_MATCH_MIN_MARGIN; anything
    else is open-set rejection and the cluster stays anonymous.
    """
    if not candidates:
        return None
    top = candidates[0]
    if top.score < settings.SPEAKER_MATCH_MIN_SCORE:
        return None
    if top.margin < settings.SPEAKER_MATCH_MIN_MARGIN:
        return None
    if top.band == "no_match":
        return None
    return top


def score_clusters(
    cluster_centroids: dict[str, np.ndarray],
    people: list[Person],
    space_id: Optional[str] = None,
) -> dict[str, list[Candidate]]:
    """
    Scores each cluster centroid against every active voiceprint in the active embedding space.

    Clusters are scored independently: one person may be the best match of several clusters (see
    merge_suggestions), and a cluster resembling nobody gets an empty or sub-threshold list. Voiceprints from
    another space are skipped (the reason is logged), never compared.
    """
    active_space = space_id or speaker_embedder.space_id
    refs, skipped = collect_voiceprints(people, active_space)
    for reason in skipped:
        logger.info(f"Voiceprint matching skipped: {reason}")
    result: dict[str, list[Candidate]] = {}
    for cluster_id, centroid in cluster_centroids.items():
        result[cluster_id] = score_vector(np.asarray(centroid, dtype=np.float32), refs) if refs else []
    return result


def merge_suggestions(candidates_by_cluster: dict[str, list[Candidate]]) -> list[tuple[str, str]]:
    """
    Pairs of clusters whose suggested person is the same. Two clusters matching one person is a benign
    "this person appears as two speakers" outcome to show the reviewer, never a conflict to resolve by
    reassigning one of them.
    """
    by_person: dict[str, list[str]] = {}
    for cluster_id in sorted(candidates_by_cluster):
        suggestion = pick_suggestion(candidates_by_cluster[cluster_id])
        if suggestion is not None:
            by_person.setdefault(suggestion.person_id, []).append(cluster_id)
    pairs: list[tuple[str, str]] = []
    for clusters in by_person.values():
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                pairs.append((clusters[i], clusters[j]))
    return pairs
