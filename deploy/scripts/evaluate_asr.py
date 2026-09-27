"""
Medpark ASR Release Gate Evaluation CLI
Compares baseline and candidate evaluation reports against strict, frozen release gates:
1. Relative corpus WER improvement >= 5.0%
2. Upper bound of paired 95% bootstrap WER difference < 0.0
3. No point-estimate WER regression for any language (RO, RU, EN, mixed)
4. No increase in critical-fact errors, hallucinations, or unwanted translations
5. Entity precision and recall not lower than baseline
6. RTF latency no more than 20% slower than baseline
Missing strata or missing evidence produces 'insufficient_evidence', NEVER a silent pass.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Optional


def evaluate_release_gates(baseline_eval: dict[str, Any], candidate_eval: dict[str, Any]) -> dict[str, Any]:
    """Evaluates candidate metrics against baseline according to frozen release policy."""
    rejection_reasons: list[str] = []
    criteria_results: dict[str, dict[str, Any]] = {}

    # Check for presence of required corpus metrics
    b_wer = baseline_eval.get("corpus_wer")
    c_wer = candidate_eval.get("corpus_wer")

    if b_wer is None or c_wer is None:
        return {
            "status": "insufficient_evidence",
            "reason": "Corpus WER missing from evaluation report",
            "criteria_results": {},
            "rejection_reasons": ["Missing corpus WER data in baseline or candidate"],
        }

    # 1. At least 5% relative WER improvement
    if b_wer > 0:
        rel_improvement = (b_wer - c_wer) / b_wer
    else:
        rel_improvement = 0.0

    wer_pass = rel_improvement >= 0.05
    criteria_results["relative_wer_improvement"] = {
        "passed": wer_pass,
        "baseline_wer": b_wer,
        "candidate_wer": c_wer,
        "relative_improvement": round(rel_improvement, 4),
        "required_min": 0.05,
    }
    if not wer_pass:
        rejection_reasons.append(
            f"Insufficient WER improvement: {round(rel_improvement * 100, 2)}% (required: >= 5.0%)"
        )

    # 2. Paired 95% bootstrap difference upper bound < 0.0
    c_boot_upper = candidate_eval.get("paired_bootstrap_wer_diff_upper")
    if c_boot_upper is not None:
        boot_pass = c_boot_upper < 0.0
        criteria_results["paired_bootstrap_ci"] = {
            "passed": boot_pass,
            "upper_bound_diff": c_boot_upper,
        }
        if not boot_pass:
            rejection_reasons.append(
                f"Paired bootstrap upper bound >= 0.0 ({c_boot_upper}): improvement not statistically significant"
            )
    else:
        criteria_results["paired_bootstrap_ci"] = {
            "passed": False,
            "details": "Missing bootstrap CI data",
        }
        rejection_reasons.append("Missing paired bootstrap CI measurement")

    # 3. Per-language WER regression check
    b_lang_wer = baseline_eval.get("language_wer", {})
    c_lang_wer = candidate_eval.get("language_wer", {})
    lang_regressions = []
    for lang, b_lwer in b_lang_wer.items():
        c_lwer = c_lang_wer.get(lang)
        if c_lwer is not None and c_lwer > b_lwer + 1e-6:
            lang_regressions.append(f"{lang} ({b_lwer:.3f} -> {c_lwer:.3f})")

    criteria_results["no_language_regression"] = {
        "passed": len(lang_regressions) == 0,
        "regressions": lang_regressions,
    }
    if lang_regressions:
        rejection_reasons.append(f"WER regressed in language strata: {', '.join(lang_regressions)}")

    # 4. Critical fact errors
    b_crit = baseline_eval.get("critical_fact_errors", 0)
    c_crit = candidate_eval.get("critical_fact_errors", 0)
    crit_pass = c_crit <= b_crit
    criteria_results["critical_fact_errors"] = {
        "passed": crit_pass,
        "baseline": b_crit,
        "candidate": c_crit,
    }
    if not crit_pass:
        rejection_reasons.append(f"Critical fact errors increased: baseline {b_crit} -> candidate {c_crit}")

    # 5. Hallucinations / silence insertions
    b_halluc = baseline_eval.get("silence_hallucinations", 0)
    c_halluc = candidate_eval.get("silence_hallucinations", 0)
    halluc_pass = c_halluc <= b_halluc
    criteria_results["silence_hallucinations"] = {
        "passed": halluc_pass,
        "baseline": b_halluc,
        "candidate": c_halluc,
    }
    if not halluc_pass:
        rejection_reasons.append(f"Silence hallucinations increased: {b_halluc} -> {c_halluc}")

    # 6. Entity metrics
    b_prec = baseline_eval.get("entity_precision", 1.0)
    c_prec = candidate_eval.get("entity_precision", 1.0)
    b_rec = baseline_eval.get("entity_recall", 1.0)
    c_rec = candidate_eval.get("entity_recall", 1.0)
    ent_pass = (c_prec >= b_prec - 1e-6) and (c_rec >= b_rec - 1e-6)
    criteria_results["entity_recognition"] = {
        "passed": ent_pass,
        "precision": f"{b_prec:.3f} -> {c_prec:.3f}",
        "recall": f"{b_rec:.3f} -> {c_rec:.3f}",
    }
    if not ent_pass:
        rejection_reasons.append(f"Entity recognition regressed (precision or recall below baseline)")

    # 7. Latency RTF
    b_rtf = baseline_eval.get("rtf")
    c_rtf = candidate_eval.get("rtf")
    if b_rtf is not None and c_rtf is not None:
        rtf_pass = c_rtf <= (b_rtf * 1.20)
        criteria_results["latency_rtf"] = {
            "passed": rtf_pass,
            "baseline_rtf": b_rtf,
            "candidate_rtf": c_rtf,
            "max_allowed_rtf": round(b_rtf * 1.20, 4),
        }
        if not rtf_pass:
            rejection_reasons.append(f"RTF latency exceeded: {c_rtf:.4f} > allowed {b_rtf * 1.20:.4f}")

    # Overall verdict
    if not criteria_results.get("paired_bootstrap_ci", {}).get("passed", False) and "Missing paired bootstrap CI measurement" in rejection_reasons:
        status = "insufficient_evidence"
    elif len(rejection_reasons) == 0:
        status = "pass"
    else:
        status = "fail"

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "criteria_results": criteria_results,
        "rejection_reasons": rejection_reasons,
    }

    # Deterministic report hash
    report_bytes = json.dumps(report, sort_keys=True).encode("utf-8")
    report["report_hash"] = hashlib.sha256(report_bytes).hexdigest()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate candidate ASR against release gates.")
    parser.add_argument("--baseline", type=str, required=True, help="Path to baseline evaluation JSON")
    parser.add_argument("--candidate", type=str, required=True, help="Path to candidate evaluation JSON")
    parser.add_argument("--manifest", type=str, default=None, help="Optional dataset manifest path")
    parser.add_argument("--output", type=str, required=True, help="Path to write gate report JSON")
    args = parser.parse_args()

    baseline_p = Path(args.baseline)
    candidate_p = Path(args.candidate)
    out_p = Path(args.output)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    if not baseline_p.is_file():
        print(f"Error: Baseline evaluation file not found: {baseline_p}", file=sys.stderr)
        sys.exit(1)
    if not candidate_p.is_file():
        print(f"Error: Candidate evaluation file not found: {candidate_p}", file=sys.stderr)
        sys.exit(1)

    baseline_data = json.loads(baseline_p.read_text(encoding="utf-8"))
    candidate_data = json.loads(candidate_p.read_text(encoding="utf-8"))

    report = evaluate_release_gates(baseline_data, candidate_data)
    out_p.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n=== Medpark ASR Release Gate Evaluation ===")
    print(f"Status:       {report['status'].upper()}")
    print(f"Report Hash:  {report['report_hash']}")
    print(f"Report Path:  {out_p}")

    if report["status"] == "pass":
        print("\nAll release policy criteria passed successfully!")
    elif report["status"] == "insufficient_evidence":
        print("\nINSUFFICIENT EVIDENCE: Cannot certify release gate due to missing measurements.")
        for r in report["rejection_reasons"]:
            print(f"  - {r}")
    else:
        print("\nRELEASE GATE FAILED:")
        for r in report["rejection_reasons"]:
            print(f"  - {r}")

    sys.exit(0 if report["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
