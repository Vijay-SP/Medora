"""
Medpark Meeting Intelligence System - Map/Reduce Merge
Deterministically de-duplicates items reported by overlapping transcript chunks.
"""

from difflib import SequenceMatcher
from app.services.extraction.validator import normalise_text


# Same item iff evidence sets intersect OR (text similarity >= threshold AND the items sit close together)
SIMILARITY_THRESHOLD = 0.82
MAX_INDEX_DISTANCE = 12

_LEVEL_RANK = {"low": 0, "medium": 1, "high": 2}
_MAX_FIELDS = ("priority", "severity")
_FIRST_NON_NULL_FIELDS = ("owner_mention", "owner_speaker", "deadline_phrase")


def _same_item(a: dict, b: dict, text_key: str) -> bool:
    ev_a, ev_b = set(a["evidence_idx"]), set(b["evidence_idx"])
    same_chunk = a.get("chunk") is not None and a.get("chunk") == b.get("chunk")
    if same_chunk:
        # Within ONE map call a shared line does not make two items the same (adjacent tasks often
        # share a line) but a repeated text does: the model occasionally loops and re-emits an item
        # with fresh indices. Items without a "chunk" tag are compared with the cross-chunk rule.
        ratio = SequenceMatcher(None, normalise_text(a.get(text_key, "")), normalise_text(b.get(text_key, ""))).ratio()
        return ratio >= SIMILARITY_THRESHOLD
    if ev_a & ev_b:
        return True
    if abs(min(ev_a) - min(ev_b)) > MAX_INDEX_DISTANCE:
        return False
    ratio = SequenceMatcher(None, normalise_text(a.get(text_key, "")), normalise_text(b.get(text_key, ""))).ratio()
    return ratio >= SIMILARITY_THRESHOLD


def _merge_pair(base: dict, other: dict, text_key: str) -> dict:
    """Merged text = longer; evidence = union; priority/severity = max; owner/deadline = first non-null."""
    longer, shorter = (base, other) if len(base.get(text_key, "")) >= len(other.get(text_key, "")) else (other, base)
    merged = dict(longer)
    merged["evidence_idx"] = sorted(set(base["evidence_idx"]) | set(other["evidence_idx"]))
    merged["chunk"] = base.get("chunk")  # a merged item keeps the earliest chunk it was seen in
    for field in _MAX_FIELDS:
        if field in base or field in other:
            merged[field] = max(base.get(field, "low"), other.get(field, "low"), key=lambda v: _LEVEL_RANK.get(v, 0))
    for field in _FIRST_NON_NULL_FIELDS:
        if field in base or field in other:
            merged[field] = base.get(field) if base.get(field) is not None else other.get(field)
    return merged


def merge_items(items: list[dict], text_key: str) -> list[dict]:
    """
    Folds duplicate items (same evidence or near-identical nearby text) into one and orders the
    result by the smallest cited line index. Input order is the chunk order, so the earlier
    report is always the base of a merge.
    """
    merged: list[dict] = []
    for item in items:
        if not item.get("evidence_idx"):
            continue
        for pos, existing in enumerate(merged):
            if _same_item(existing, item, text_key):
                merged[pos] = _merge_pair(existing, item, text_key)
                break
        else:
            merged.append(dict(item))
    merged.sort(key=lambda it: min(it["evidence_idx"]))
    return merged
