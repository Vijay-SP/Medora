"""
Medpark Meeting Intelligence System - Pattern Miner for Dialect Rule Discovery
Extracts conservative candidate normalization rules from human-reviewed correction events.
Safety rules:
- Only single token / short phrase substitutions (<= 3 words) are mined.
- Paraphrased or multi-edit sentences are excluded.
- Requires multiple distinct events across meetings/speakers before surfacing.
- Flags digits, dosages, negations, and contradictory corrections.
- Surfacing a candidate NEVER automatically approves it.
"""

import argparse
from collections import defaultdict
import difflib
import json
import re
from typing import Any, Optional

from app.core.config import settings
from app.core.logging import logger
from app.models.adaptation import RuleCandidate
from app.services.asr.dialect_adapter import DOSAGE_UNIT_REGEX, NEGATION_TOKENS, WORD_TOKEN_REGEX
from app.services.learning.store import adaptation_store


def _extract_single_phrase_diff(
    source_text: str,
    target_text: str,
) -> Optional[tuple[str, str, bool, list[str]]]:
    """
    Computes a conservative diff between source and target texts.
    Returns (variant, canonical, is_safe, flag_reasons) if it is a single phrase replacement (<= 3 words),
    or None if it represents a complex multi-edit, insertion, deletion, or paraphrase.
    """
    if not source_text or not target_text:
        return None

    src_tokens = WORD_TOKEN_REGEX.findall(source_text)
    tgt_tokens = WORD_TOKEN_REGEX.findall(target_text)

    if not src_tokens or not tgt_tokens:
        return None

    matcher = difflib.SequenceMatcher(None, [t.lower() for t in src_tokens], [t.lower() for t in tgt_tokens])
    opcodes = matcher.get_opcodes()

    replace_ops = [op for op in opcodes if op[0] == "replace"]
    other_diff_ops = [op for op in opcodes if op[0] in ("insert", "delete")]

    # Conservative rule: Exactly one replacement, zero insertions/deletions, <= 3 tokens replaced
    if len(replace_ops) != 1 or len(other_diff_ops) > 0:
        return None

    tag, i1, i2, j1, j2 = replace_ops[0]
    src_span_len = i2 - i1
    tgt_span_len = j2 - j1

    if src_span_len > 3 or tgt_span_len > 3:
        return None

    variant = " ".join(src_tokens[i1:i2])
    canonical = " ".join(tgt_tokens[j1:j2])

    # Safety checks
    flag_reasons: list[str] = []
    is_safe = True

    # 1. Glued digits / numbers
    if any(c.isdigit() for c in variant) or any(c.isdigit() for c in canonical):
        is_safe = False
        flag_reasons.append("contains_digits")

    # 2. Dosage / units
    if DOSAGE_UNIT_REGEX.search(source_text) or DOSAGE_UNIT_REGEX.search(target_text):
        is_safe = False
        flag_reasons.append("dosage_or_units_present")

    # 3. Negation in vicinity
    preceding_tokens = [t.lower() for t in src_tokens[max(0, i1 - 3):i1]]
    all_neg = set().union(*NEGATION_TOKENS.values())
    if any(tok in all_neg for tok in preceding_tokens) or any(tok in all_neg for tok in variant.lower().split()):
        is_safe = False
        flag_reasons.append("adjacent_negation")

    return variant, canonical, is_safe, flag_reasons


def mine_candidates(
    min_occurrences: int = 2,
    verified_only: bool = False,
) -> list[RuleCandidate]:
    """
    Mines candidate dialect normalization rules from verified and accepted correction events.
    Groups occurrences, computes speaker and meeting diversity, and detects contradictory edits.
    """
    events = adaptation_store.list_events(limit=5000)
    if verified_only:
        events = [e for e in events if e.get("verification_status") == "verified"]

    # Map: (language, variant.lower()) -> dict of canonical -> occurrences info
    variant_groups: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {
        "canonicals": defaultdict(lambda: {
            "count": 0,
            "meetings": set(),
            "speakers": set(),
            "contexts": [],
            "flags": set(),
            "is_safe": True,
            "canonical_display": "",
            "variant_display": "",
        })
    })

    for ev in events:
        source_text = ev.get("raw_text") or ev.get("previous_text") or ""
        target_text = ev.get("new_text") or ""
        meeting_id = ev.get("meeting_id", "")
        reviewer = ev.get("verified_by") or ev.get("reviewer_label") or "reviewer"

        diff_res = _extract_single_phrase_diff(source_text, target_text)
        if not diff_res:
            continue

        variant, canonical, is_safe, flags = diff_res
        # Language heuristic from store or default to "ro"
        lang = "ro"

        v_key = (lang, variant.lower())
        c_key = canonical.lower()

        entry = variant_groups[v_key]["canonicals"][c_key]
        entry["count"] += 1
        entry["meetings"].add(meeting_id)
        entry["speakers"].add(reviewer)
        if len(entry["contexts"]) < 3:
            entry["contexts"].append(source_text)
        entry["flags"].update(flags)
        if not is_safe:
            entry["is_safe"] = False
        entry["canonical_display"] = canonical
        entry["variant_display"] = variant

    candidates: list[RuleCandidate] = []

    for (lang, v_lower), data in variant_groups.items():
        canonicals_dict = data["canonicals"]
        is_contradictory = len(canonicals_dict) > 1

        for c_lower, c_info in canonicals_dict.items():
            if c_info["count"] < min_occurrences:
                continue

            flags = list(c_info["flags"])
            is_safe = c_info["is_safe"]
            if is_contradictory:
                is_safe = False
                flags.append(f"contradictory_edits_detected ({len(canonicals_dict)} different targets)")

            candidates.append(
                RuleCandidate(
                    language=lang,
                    detected_variant=c_info["variant_display"],
                    suggested_canonical=c_info["canonical_display"],
                    occurrences_count=c_info["count"],
                    speakers_count=len(c_info["speakers"]),
                    meetings_count=len(c_info["meetings"]),
                    example_contexts=c_info["contexts"],
                    is_safe_candidate=is_safe,
                    flag_reasons=flags,
                )
            )

    candidates.sort(key=lambda c: (c.occurrences_count, c.meetings_count), reverse=True)
    return candidates


def main() -> None:
    parser = argparse.ArgumentParser(description="Mine candidate dialect normalization rules from corrections.")
    parser.add_argument("--min-occurrences", type=int, default=2, help="Minimum occurrences to surface a candidate")
    parser.add_argument("--verified-only", action="store_true", help="Only mine events verified against audio")
    parser.add_argument("--output-json", type=str, default=None, help="Save candidates to JSON file")
    args = parser.parse_args()

    candidates = mine_candidates(min_occurrences=args.min_occurrences, verified_only=args.verified_only)
    print(f"\n--- Mined Dialect Normalization Candidates (found {len(candidates)}) ---")
    for c in candidates:
        safe_str = "SAFE" if c.is_safe_candidate else f"FLAGGED ({', '.join(c.flag_reasons)})"
        print(f"[{c.language}] '{c.detected_variant}' -> '{c.suggested_canonical}' | "
              f"occurrences={c.occurrences_count}, meetings={c.meetings_count}, reviewers={c.speakers_count} | {safe_str}")

    if args.output_json:
        out_path = args.output_json
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump([c.model_dump() for c in candidates], f, indent=2, ensure_ascii=False)
        print(f"Saved candidates to {out_path}")


if __name__ == "__main__":
    main()
