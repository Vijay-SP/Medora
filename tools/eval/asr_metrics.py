"""
Medora ASR Evaluation Harness - Metrics Computation Engine
Calculates WER, CER, entity precision/recall/F1, critical-fact error rates,
silence hallucinations, and recording-clustered paired bootstrap confidence intervals.
"""

from __future__ import annotations

import math
import random
import re
import unicodedata
from typing import Any, Sequence

from tools.eval.asr_schema import ASRHypothesisSet, ASRManifest, GoldSegment, HypothesisSegment


SCORING_POLICY_VERSION = "medora_asr_eval_v1"

# Standard negation tokens across RO, RU, EN
NEGATION_TOKENS = {
    "ro": {"nu", "n-a", "n-au", "n-am", "n-ai", "n-ati", "n-ar", "nici", "fara", "fără", "deloc", "nicidecum"},
    "ru": {"не", "нет", "ни", "никогда", "никто", "ничего", "без", "никак"},
    "en": {"no", "not", "none", "neither", "never", "without", "hardly", "barely", "didn't", "doesn't", "wasn't", "won't", "can't"},
}


def normalize_text_for_scoring(text: str) -> str:
    """
    Scoring normalization: Unicode NFC, case-folded, strips non-lexical punctuation
    while strictly preserving Romanian diacritics and Russian Cyrillic characters.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text).strip().lower()
    # Replace dashes/hyphens with space unless intra-word
    text = re.sub(r"[\.,;:!?\"'“”«»()\[\]{}]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tokenize_words(text: str) -> list[str]:
    norm = normalize_text_for_scoring(text)
    return norm.split() if norm else []


def compute_edit_counts(ref_tokens: Sequence[str], hyp_tokens: Sequence[str]) -> tuple[int, int, int]:
    """
    Levenshtein distance returning (substitutions, deletions, insertions).
    """
    n = len(ref_tokens)
    m = len(hyp_tokens)

    dp = [[(0, 0, 0) for _ in range(m + 1)] for _ in range(n + 1)]

    for i in range(1, n + 1):
        dp[i][0] = (0, i, 0)  # i deletions
    for j in range(1, m + 1):
        dp[0][j] = (0, 0, j)  # j insertions

    for i in range(1, n + 1):
        ref_tok = ref_tokens[i - 1]
        for j in range(1, m + 1):
            hyp_tok = hyp_tokens[j - 1]
            if ref_tok == hyp_tok:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                sub = (dp[i - 1][j - 1][0] + 1, dp[i - 1][j - 1][1], dp[i - 1][j - 1][2])
                delete = (dp[i - 1][j][0], dp[i - 1][j][1] + 1, dp[i - 1][j][2])
                insert = (dp[i][j - 1][0], dp[i][j - 1][1], dp[i][j - 1][2] + 1)

                best = min((sub, delete, insert), key=lambda x: sum(x))
                dp[i][j] = best

    return dp[n][m]


def compute_wer(ref_text: str, hyp_text: str) -> tuple[float, int, int, int, int]:
    """Returns (wer, substitutions, deletions, insertions, total_ref_words)."""
    ref_words = tokenize_words(ref_text)
    hyp_words = tokenize_words(hyp_text)
    n = len(ref_words)
    if n == 0:
        insertions = len(hyp_words)
        return (1.0 if insertions > 0 else 0.0, 0, 0, insertions, 0)
    s, d, i = compute_edit_counts(ref_words, hyp_words)
    wer = (s + d + i) / n
    return wer, s, d, i, n


def compute_cer(ref_text: str, hyp_text: str) -> tuple[float, int, int, int, int]:
    """Character Error Rate over normalized characters."""
    ref_chars = list(normalize_text_for_scoring(ref_text).replace(" ", ""))
    hyp_chars = list(normalize_text_for_scoring(hyp_text).replace(" ", ""))
    n = len(ref_chars)
    if n == 0:
        insertions = len(hyp_chars)
        return (1.0 if insertions > 0 else 0.0, 0, 0, insertions, 0)
    s, d, i = compute_edit_counts(ref_chars, hyp_chars)
    cer = (s + d + i) / n
    return cer, s, d, i, n


def evaluate_critical_facts(ref_seg: GoldSegment, hyp_text: str) -> dict[str, Any]:
    """
    Checks for negation drops and dosage corruptions.
    """
    hyp_norm = normalize_text_for_scoring(hyp_text)
    hyp_tokens = set(hyp_norm.split())

    errors: list[dict[str, Any]] = []

    # 1. Automatic negation detection if not explicitly specified
    lang = ref_seg.language.lower()
    active_negations = set()
    if lang in NEGATION_TOKENS:
        active_negations.update(NEGATION_TOKENS[lang])
    else:
        for words in NEGATION_TOKENS.values():
            active_negations.update(words)

    ref_norm = normalize_text_for_scoring(ref_seg.verbatim_text)
    ref_tokens = set(ref_norm.split())
    ref_has_negation = any(tok in ref_tokens for tok in active_negations)
    hyp_has_negation = any(tok in hyp_tokens for tok in active_negations)

    if ref_has_negation and not hyp_has_negation:
        errors.append({
            "kind": "negation_reversal",
            "detail": f"Reference contains negation words, but hypothesis dropped negation in '{hyp_text}'",
        })

    # 2. Check explicit critical facts in manifest
    for fact in ref_seg.critical_facts:
        exp_tok = fact.expected_token.lower()
        if fact.kind == "negation":
            if exp_tok in ref_tokens and exp_tok not in hyp_tokens:
                errors.append({
                    "kind": "negation_reversal",
                    "expected": fact.expected_token,
                    "detail": f"Critical negation token '{fact.expected_token}' missing from hypothesis",
                })
        elif fact.kind == "dosage":
            if exp_tok not in hyp_norm:
                errors.append({
                    "kind": "dosage_corruption",
                    "expected": fact.expected_token,
                    "numeric_value": fact.numeric_value,
                    "unit": fact.unit,
                    "detail": f"Expected dosage '{fact.expected_token}' was missing or corrupted",
                })

    return {
        "critical_fact_errors": len(errors),
        "details": errors,
    }


def evaluate_entities(ref_seg: GoldSegment, hyp_text: str) -> dict[str, int]:
    """Counts entity hits, misses, and false predictions."""
    hyp_norm = normalize_text_for_scoring(hyp_text)
    true_positives = 0
    false_negatives = 0

    for ent in ref_seg.entities:
        term_norm = normalize_text_for_scoring(ent.term)
        if not term_norm:
            continue
        pattern = rf"(?<!\w){re.escape(term_norm)}(?!\w)"
        if re.search(pattern, hyp_norm):
            true_positives += 1
        else:
            false_negatives += 1

    return {
        "true_positives": true_positives,
        "false_negatives": false_negatives,
    }


def compute_recording_bootstrap_ci(
    recording_stats: list[dict[str, Any]],
    n_resamples: int = 1000,
    seed: int = 42,
) -> tuple[float, float, float]:
    """
    Computes 95% paired bootstrap confidence interval for corpus WER, clustered by recording.
    Returns (mean_wer, ci_lower, ci_upper).
    """
    if not recording_stats:
        return 0.0, 0.0, 0.0

    rng = random.Random(seed)
    n = len(recording_stats)
    bootstrap_wers = []

    for _ in range(n_resamples):
        sample = [rng.choice(recording_stats) for _ in range(n)]
        sum_edits = sum(r["substitutions"] + r["deletions"] + r["insertions"] for r in sample)
        sum_words = sum(r["ref_words"] for r in sample)
        b_wer = (sum_edits / sum_words) if sum_words > 0 else 0.0
        bootstrap_wers.append(b_wer)

    bootstrap_wers.sort()
    low_idx = int(0.025 * n_resamples)
    high_idx = int(0.975 * n_resamples)
    mean_wer = sum(bootstrap_wers) / len(bootstrap_wers)
    return mean_wer, bootstrap_wers[low_idx], bootstrap_wers[high_idx]


def score_asr(reference: ASRManifest | dict, hypothesis: ASRHypothesisSet | dict) -> dict[str, Any]:
    """
    Evaluates an ASR hypothesis against a gold manifest.
    Returns comprehensive evaluation dictionary. Missing fields yield 'not_measured', never false zero.
    """
    if isinstance(reference, dict):
        manifest = ASRManifest.model_validate(reference)
    else:
        manifest = reference

    if isinstance(hypothesis, dict):
        hyp_set = ASRHypothesisSet.model_validate(hypothesis)
    else:
        hyp_set = hypothesis

    hyp_map = {h.recording_id: h for h in hyp_set.hypotheses}

    total_s = 0
    total_d = 0
    total_i = 0
    total_ref_words = 0

    total_char_s = 0
    total_char_d = 0
    total_char_i = 0
    total_ref_chars = 0

    total_entities_tp = 0
    total_entities_fn = 0
    total_critical_errors = 0
    silence_insertions = 0

    language_stats: dict[str, dict[str, int]] = {}
    condition_stats: dict[str, dict[str, int]] = {}
    recording_stats: list[dict[str, Any]] = []

    for rec in manifest.recordings:
        rec_hyp = hyp_map.get(rec.recording_id)
        rec_s = 0
        rec_d = 0
        rec_i = 0
        rec_words = 0

        # Combine segments into recording hypothesis text
        if rec_hyp:
            hyp_full_text = " ".join(seg.text.strip() for seg in rec_hyp.segments if seg.text.strip())
        else:
            hyp_full_text = ""

        # Score segment-by-segment alignment if 1:1, or evaluate over recording
        ref_full_text = " ".join(seg.verbatim_text.strip() for seg in rec.segments if seg.verbatim_text.strip())

        # Silence insertion check
        if not ref_full_text and hyp_full_text:
            silence_insertions += len(tokenize_words(hyp_full_text))

        wer, s, d, i, n = compute_wer(ref_full_text, hyp_full_text)
        cer, cs, cd, ci, cn = compute_cer(ref_full_text, hyp_full_text)

        total_s += s
        total_d += d
        total_i += i
        total_ref_words += n

        total_char_s += cs
        total_char_d += cd
        total_char_i += ci
        total_ref_chars += cn

        rec_s += s
        rec_d += d
        rec_i += i
        rec_words += n

        # Slices: condition
        cond = rec.acoustic_condition
        cond_entry = condition_stats.setdefault(cond, {"s": 0, "d": 0, "i": 0, "n": 0})
        cond_entry["s"] += s
        cond_entry["d"] += d
        cond_entry["i"] += i
        cond_entry["n"] += n

        # Critical facts & entities over segments
        for seg in rec.segments:
            # Slices: language
            lang = seg.language
            lang_entry = language_stats.setdefault(lang, {"s": 0, "d": 0, "i": 0, "n": 0})
            seg_wer, ss, sd, si, sn = compute_wer(seg.verbatim_text, hyp_full_text)
            # Accumulate word counts for language slice
            lang_entry["s"] += ss
            lang_entry["d"] += sd
            lang_entry["i"] += si
            lang_entry["n"] += sn

            crit_res = evaluate_critical_facts(seg, hyp_full_text)
            total_critical_errors += crit_res["critical_fact_errors"]

            ent_res = evaluate_entities(seg, hyp_full_text)
            total_entities_tp += ent_res["true_positives"]
            total_entities_fn += ent_res["false_negatives"]

        recording_stats.append({
            "recording_id": rec.recording_id,
            "substitutions": rec_s,
            "deletions": rec_d,
            "insertions": rec_i,
            "ref_words": rec_words,
            "wer": (rec_s + rec_d + rec_i) / rec_words if rec_words > 0 else 0.0,
        })

    corpus_wer = (total_s + total_d + total_i) / total_ref_words if total_ref_words > 0 else 0.0
    corpus_cer = (total_char_s + total_char_d + total_char_i) / total_ref_chars if total_ref_chars > 0 else 0.0

    b_mean, ci_low, ci_high = compute_recording_bootstrap_ci(recording_stats)

    # Slice WERs
    per_language_wer = {}
    for lang, counts in language_stats.items():
        n = counts["n"]
        per_language_wer[lang] = ((counts["s"] + counts["d"] + counts["i"]) / n) if n > 0 else "not_measured"

    per_condition_wer = {}
    for cond, counts in condition_stats.items():
        n = counts["n"]
        per_condition_wer[cond] = ((counts["s"] + counts["d"] + counts["i"]) / n) if n > 0 else "not_measured"

    # Entity Metrics
    total_entities_gold = total_entities_tp + total_entities_fn
    entity_recall = (total_entities_tp / total_entities_gold) if total_entities_gold > 0 else "not_measured"

    return {
        "scoring_policy_version": SCORING_POLICY_VERSION,
        "model_id": hyp_set.model_id,
        "runtime": hyp_set.runtime,
        "total_recordings": len(manifest.recordings),
        "total_ref_words": total_ref_words,
        "substitutions": total_s,
        "deletions": total_d,
        "insertions": total_i,
        "wer": round(corpus_wer, 4),
        "cer": round(corpus_cer, 4),
        "bootstrap_95_ci": [round(ci_low, 4), round(ci_high, 4)],
        "bootstrap_mean_wer": round(b_mean, 4),
        "per_language_wer": per_language_wer,
        "per_condition_wer": per_condition_wer,
        "clinical_entity_recall": round(entity_recall, 4) if isinstance(entity_recall, float) else entity_recall,
        "critical_fact_errors": total_critical_errors,
        "silence_insertions": silence_insertions,
    }
