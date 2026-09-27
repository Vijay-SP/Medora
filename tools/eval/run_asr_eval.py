"""
Medora ASR Evaluation Runner CLI
Scores ASR hypotheses against gold manifests offline without running the inference pipeline.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# Ensure repository root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.eval.asr_schema import ASRHypothesisSet, ASRManifest
from tools.eval.asr_metrics import score_asr


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate ASR hypotheses against gold reference manifest.")
    parser.add_argument("--manifest", type=Path, required=True, help="Path to gold reference manifest JSON")
    parser.add_argument("--hypotheses", type=Path, required=True, help="Path to candidate hypothesis JSON")
    parser.add_argument("--output", type=Path, default=None, help="Path to save evaluation report JSON")
    parser.add_argument("--compare", type=Path, default=None, help="Optional baseline hypothesis JSON for comparison")

    args = parser.parse_args()

    if not args.manifest.is_file():
        print(f"Error: Manifest file '{args.manifest}' does not exist.", file=sys.stderr)
        return 1
    if not args.hypotheses.is_file():
        print(f"Error: Hypothesis file '{args.hypotheses}' does not exist.", file=sys.stderr)
        return 1

    with open(args.manifest, "r", encoding="utf-8") as f:
        manifest_raw = json.load(f)
    manifest = ASRManifest.model_validate(manifest_raw)

    with open(args.hypotheses, "r", encoding="utf-8") as f:
        hyp_raw = json.load(f)
    hypotheses = ASRHypothesisSet.model_validate(hyp_raw)

    report = score_asr(manifest, hypotheses)

    print("==================================================================")
    print("                MEDORA ASR EVALUATION REPORT                      ")
    print("==================================================================")
    print(f"Scoring Policy  : {report['scoring_policy_version']}")
    print(f"Model ID        : {report['model_id']} ({report['runtime']})")
    print(f"Recordings      : {report['total_recordings']}")
    print(f"Total Words     : {report['total_ref_words']}")
    print(f"Corpus WER      : {report['wer'] * 100:.2f}% (S={report['substitutions']}, D={report['deletions']}, I={report['insertions']})")
    print(f"Corpus CER      : {report['cer'] * 100:.2f}%")
    print(f"95% Bootstrap CI: [{report['bootstrap_95_ci'][0] * 100:.2f}%, {report['bootstrap_95_ci'][1] * 100:.2f}%]")
    print(f"Entity Recall   : {report['clinical_entity_recall'] if report['clinical_entity_recall'] == 'not_measured' else f'{report['clinical_entity_recall']*100:.2f}%'}")
    print(f"Critical Errors : {report['critical_fact_errors']} (negations/dosages)")
    print(f"Silence Insert  : {report['silence_insertions']} words")
    print("------------------------------------------------------------------")
    print("Per-Language Breakdown:")
    for lang, wer_val in report["per_language_wer"].items():
        val_str = f"{wer_val * 100:.2f}%" if isinstance(wer_val, float) else str(wer_val)
        print(f"  - {lang.upper():<5}: {val_str}")
    print("==================================================================")

    if args.compare and args.compare.is_file():
        with open(args.compare, "r", encoding="utf-8") as f:
            base_raw = json.load(f)
        baseline_hyp = ASRHypothesisSet.model_validate(base_raw)
        base_report = score_asr(manifest, baseline_hyp)

        delta_wer = report["wer"] - base_report["wer"]
        rel_wer_impr = ((base_report["wer"] - report["wer"]) / base_report["wer"] * 100) if base_report["wer"] > 0 else 0.0

        print("\n================== COMPARISON WITH BASELINE ==================")
        print(f"Baseline Model  : {base_report['model_id']}")
        print(f"Baseline WER    : {base_report['wer'] * 100:.2f}%")
        print(f"Candidate WER   : {report['wer'] * 100:.2f}%")
        print(f"Absolute Delta  : {delta_wer * 100:+.2f}%")
        print(f"Relative Gain   : {rel_wer_impr:+.2f}%")
        print(f"Critical Regress: Candidate={report['critical_fact_errors']} vs Baseline={base_report['critical_fact_errors']}")
        print("================================================================")
        report["comparison"] = {
            "baseline_model_id": base_report["model_id"],
            "baseline_wer": base_report["wer"],
            "delta_wer": delta_wer,
            "relative_wer_improvement_pct": round(rel_wer_impr, 2),
            "baseline_critical_errors": base_report["critical_fact_errors"],
        }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\nReport written to: {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
