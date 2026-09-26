"""
Medpark Meeting Intelligence System - Deterministic Speaker Clustering (pure numpy)

Average-linkage agglomerative clustering over L2-normalised speaker embeddings, stopped by a cosine-distance
threshold, plus the per-cluster mixed-voice probe that replaced the vacuous "purity proxy"
(docs/SPEAKER_IDENTITY_DESIGN.md section 5.2). Everything here is deterministic: no random state is touched,
ties always resolve to the lowest index, and the same input matrix yields the same labels on every run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

# A cluster whose two 2-means halves each hold at least this share of the cluster's speech and whose half
# centroids agree less than MIXED_CENTROID_COSINE is reported as possibly containing two voices.
MIXED_MIN_HALF_SHARE = 0.30
MIXED_CENTROID_COSINE = 0.55
# Fewer distinct VAD-separated speech regions than this is too little evidence for bulk confirmation.
MIN_DISTINCT_REGIONS = 3
TWO_MEANS_MAX_ITERATIONS = 25


def _unit_rows(matrix: np.ndarray) -> np.ndarray:
    x = np.asarray(matrix, dtype=np.float64)
    if x.ndim != 2:
        raise ValueError(f"expected a 2-D embedding matrix, got shape {x.shape}")
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    return x / np.where(norms < 1e-12, 1.0, norms)


def cosine_distance_matrix(embeddings: np.ndarray) -> np.ndarray:
    """(n, n) cosine distances (1 - cosine similarity) in float64, exactly symmetric with a zero diagonal."""
    unit = _unit_rows(embeddings)
    sims = unit @ unit.T
    dist = 1.0 - sims
    dist = 0.5 * (dist + dist.T)
    np.fill_diagonal(dist, 0.0)
    return np.clip(dist, 0.0, 2.0)


def agglomerative_cosine(embeddings: np.ndarray, distance_threshold: float) -> np.ndarray:
    """
    Average-linkage agglomerative clustering with a cosine-distance stopping rule.

    Starts with one cluster per row and repeatedly merges the closest pair (Lance-Williams average-linkage
    update of the distance matrix) until the closest pair is farther apart than distance_threshold. The pair
    search is a row-major argmin over the upper triangle, so equal distances always merge the lexicographically
    smallest (i, j) first and the result is reproducible. Returns int labels of shape (n,), contiguous from 0
    and numbered by first appearance in row order. An empty matrix yields an empty label array.
    """
    matrix = np.asarray(embeddings)
    n = matrix.shape[0] if matrix.ndim == 2 else 0
    if n == 0:
        return np.zeros((0,), dtype=np.int64)
    if n == 1:
        return np.zeros((1,), dtype=np.int64)

    dist = cosine_distance_matrix(matrix)
    sizes = np.ones(n, dtype=np.float64)
    # Each row's current cluster: parents[j] == i means row j was absorbed by cluster i
    owner = np.arange(n)
    active = np.ones(n, dtype=bool)
    upper = np.triu(np.ones((n, n), dtype=bool), k=1)
    work = np.where(upper, dist, np.inf)

    while True:
        flat = int(np.argmin(work))
        i, j = divmod(flat, n)
        if not np.isfinite(work[i, j]) or work[i, j] > distance_threshold:
            break
        # Merge j into i (i < j by construction of the upper triangle)
        ni, nj = sizes[i], sizes[j]
        merged = (ni * dist[i, :] + nj * dist[j, :]) / (ni + nj)
        dist[i, :] = merged
        dist[:, i] = merged
        dist[i, i] = 0.0
        sizes[i] = ni + nj
        active[j] = False
        owner[owner == j] = i
        # Refresh the working upper triangle for row/column i and retire j
        row = np.where(upper[i, :] & active, dist[i, :], np.inf)
        col = np.where(upper[:, i] & active, dist[:, i], np.inf)
        work[i, :] = row
        work[:, i] = col
        work[j, :] = np.inf
        work[:, j] = np.inf

    labels = np.empty(n, dtype=np.int64)
    mapping: dict[int, int] = {}
    for idx in range(n):
        root = int(owner[idx])
        if root not in mapping:
            mapping[root] = len(mapping)
        labels[idx] = mapping[root]
    return labels


def two_means_split(embeddings: np.ndarray) -> tuple[np.ndarray, float]:
    """
    Deterministic 2-means over the rows of one cluster.

    Initial centroids are the two most distant members (lowest indices on ties); assignment is by cosine
    similarity with ties going to the first centroid. Returns (assignment in {0, 1} per row, cosine similarity
    between the two final half centroids). With fewer than two rows every row is in half 0 and the cosine is 1.0.
    """
    unit = _unit_rows(embeddings)
    n = unit.shape[0]
    if n < 2:
        return np.zeros(n, dtype=np.int64), 1.0
    dist = cosine_distance_matrix(unit)
    upper = np.where(np.triu(np.ones((n, n), dtype=bool), k=1), dist, -np.inf)
    a, b = divmod(int(np.argmax(upper)), n)
    centroids = np.stack([unit[a], unit[b]], axis=0)
    assignment = np.zeros(n, dtype=np.int64)
    for iteration in range(TWO_MEANS_MAX_ITERATIONS):
        sims = unit @ centroids.T
        # argmax returns the first maximum, so exact ties fall into half 0
        new_assignment = np.argmax(sims, axis=1)
        if iteration > 0 and np.array_equal(new_assignment, assignment):
            break
        assignment = new_assignment
        for half in (0, 1):
            members = unit[assignment == half]
            if len(members):
                centroid = members.mean(axis=0)
                norm = np.linalg.norm(centroid)
                centroids[half] = centroid / (norm if norm > 1e-12 else 1.0)
    if not np.any(assignment == 1) or not np.any(assignment == 0):
        return assignment, 1.0
    return assignment, float(np.dot(centroids[0], centroids[1]))


@dataclass
class ClusterDiagnostics:
    """Evidence about one cluster's trustworthiness, computed once at diarization time and cached."""
    label: int
    member_indices: list[int]
    speech_seconds: float
    region_count: int
    mixed_suspect: bool = False
    short_suspect: bool = False
    split_cosine: Optional[float] = None
    split_shares: tuple[float, float] = (1.0, 0.0)
    reasons: list[str] = field(default_factory=list)


def diagnose_clusters(
    embeddings: np.ndarray,
    labels: np.ndarray,
    durations: np.ndarray,
    region_ids: np.ndarray,
) -> dict[int, ClusterDiagnostics]:
    """
    Per-cluster mixed-voice and evidence checks.

    durations: seconds of speech in each window; region_ids: the VAD region each window was cut from.
    mixed_suspect: the 2-means split yields two halves each holding >= MIXED_MIN_HALF_SHARE of the cluster's
    speech whose centroids agree below MIXED_CENTROID_COSINE. short_suspect: fewer than MIN_DISTINCT_REGIONS
    distinct VAD regions. Neither check proves purity; both refuse bulk confirmation until a human listens.
    """
    labels = np.asarray(labels)
    durations = np.asarray(durations, dtype=np.float64)
    region_ids = np.asarray(region_ids)
    result: dict[int, ClusterDiagnostics] = {}
    for label in sorted({int(x) for x in labels.tolist()}):
        idx = np.flatnonzero(labels == label)
        total = float(durations[idx].sum())
        regions = int(len({int(r) for r in region_ids[idx].tolist()}))
        diag = ClusterDiagnostics(
            label=label,
            member_indices=[int(i) for i in idx],
            speech_seconds=round(total, 3),
            region_count=regions,
        )
        if regions < MIN_DISTINCT_REGIONS:
            diag.short_suspect = True
            diag.reasons.append(
                f"Only {regions} distinct speech region(s) in this cluster; at least {MIN_DISTINCT_REGIONS} are needed before it can be confirmed in bulk."
            )
        if len(idx) >= 2 and total > 0:
            assignment, split_cos = two_means_split(embeddings[idx])
            share0 = float(durations[idx][assignment == 0].sum() / total)
            share1 = float(durations[idx][assignment == 1].sum() / total)
            diag.split_cosine = round(split_cos, 4)
            diag.split_shares = (round(share0, 3), round(share1, 3))
            if min(share0, share1) >= MIXED_MIN_HALF_SHARE and split_cos < MIXED_CENTROID_COSINE:
                diag.mixed_suspect = True
                diag.reasons.append(
                    f"This cluster may contain two voices: it splits into halves of {share0:.0%} and {share1:.0%} of its speech "
                    f"that agree only {split_cos:.2f} (cosine). Listen before confirming; it cannot be confirmed in bulk."
                )
        result[label] = diag
    return result
