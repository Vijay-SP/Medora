"""
Medpark ASR Model Lifecycle Management CLI
Provides explicit administrative commands for model registry operations:
- list: List all registered artifacts and current statuses
- status: Show active artifact for a target runtime
- attach-eval: Link evaluation report to candidate
- approve: Record human reviewer approval tied to exact report hash
- activate: Safely activate an approved artifact
- rollback: Atomically restore previous working version
"""

import argparse
import json
from pathlib import Path
import sys

# Ensure backend on sys.path
repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(repo_root / "backend"))

from app.core.config import settings
from app.services.learning.model_registry import model_registry


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage ASR model artifacts and release lifecycle.")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # Subcommand: list
    sub_list = subparsers.add_parser("list", help="List registered model artifacts")
    sub_list.add_argument("--runtime", choices=["ctranslate2", "whisper_cpp"], default=None, help="Filter by runtime")

    # Subcommand: status
    sub_status = subparsers.add_parser("status", help="Show active model artifact for a runtime")
    sub_status.add_argument("--runtime", choices=["ctranslate2", "whisper_cpp"], required=True, help="Target runtime")

    # Subcommand: attach-eval
    sub_eval = subparsers.add_parser("attach-eval", help="Attach evaluation report to candidate artifact")
    sub_eval.add_argument("--artifact-id", required=True, help="Artifact identifier")
    sub_eval.add_argument("--report", required=True, help="Path to evaluate_asr.py output report JSON")

    # Subcommand: approve
    sub_app = subparsers.add_parser("approve", help="Approve evaluated candidate artifact")
    sub_app.add_argument("--artifact-id", required=True, help="Artifact identifier")
    sub_app.add_argument("--reviewer", required=True, help="Reviewer name / label")
    sub_app.add_argument("--report-hash", required=True, help="Exact SHA-256 hash of evaluation report")

    # Subcommand: activate
    sub_act = subparsers.add_parser("activate", help="Activate an approved model artifact")
    sub_act.add_argument("--artifact-id", required=True, help="Artifact identifier")
    sub_act.add_argument("--operator", required=True, help="Operator name / label")

    # Subcommand: rollback
    sub_rb = subparsers.add_parser("rollback", help="Rollback runtime to previous active model")
    sub_rb.add_argument("--runtime", choices=["ctranslate2", "whisper_cpp"], required=True, help="Target runtime")
    sub_rb.add_argument("--operator", required=True, help="Operator name / label")
    sub_rb.add_argument("--reason", required=True, help="Reason for rollback")

    args = parser.parse_args()

    if args.subcommand == "list":
        artifacts = model_registry.list_artifacts(target_runtime=args.runtime)
        print(f"\n--- Registered ASR Model Artifacts ({len(artifacts)}) ---")
        for art in artifacts:
            status_str = f"[{art.status.upper():10s}]"
            print(f"{status_str} {art.artifact_id} | {art.name:20s} v{art.version:6s} | {art.target_runtime:12s} ({art.quantization}) | eval_passed={art.evaluation_passed}")

    elif args.subcommand == "status":
        active = model_registry.get_active_artifact(target_runtime=args.runtime)
        if active:
            print(f"\nActive model for {args.runtime}:")
            print(f"  ID:          {active.artifact_id}")
            print(f"  Name:        {active.name} v{active.version}")
            print(f"  Base Model:  {active.base_model}")
            print(f"  Path:        {active.model_path}")
            print(f"  Activated:   {active.activated_at}")
            print(f"  Approved By: {active.approved_by}")
        else:
            print(f"\nNo active model registered for runtime '{args.runtime}'. (Baseline default is used)")

    elif args.subcommand == "attach-eval":
        report_path = Path(args.report)
        if not report_path.is_file():
            print(f"Error: Report file not found: {report_path}", file=sys.stderr)
            sys.exit(1)
        report_data = json.loads(report_path.read_text(encoding="utf-8"))
        passed = report_data.get("status") == "pass"
        report_hash = report_data.get("report_hash")
        if not report_hash:
            print("Error: Report missing 'report_hash'", file=sys.stderr)
            sys.exit(1)

        art = model_registry.attach_evaluation(args.artifact_id, report_hash=report_hash, evaluation_passed=passed)
        print(f"Attached evaluation to {art.artifact_id}: passed={passed}, status={art.status}")

    elif args.subcommand == "approve":
        try:
            art = model_registry.approve_artifact(args.artifact_id, reviewer_label=args.reviewer, evaluation_report_hash=args.report_hash)
            print(f"Artifact {art.artifact_id} APPROVED by {args.reviewer} (status: {art.status})")
        except Exception as exc:
            print(f"Approval failed: {exc}", file=sys.stderr)
            sys.exit(1)

    elif args.subcommand == "activate":
        try:
            art = model_registry.activate_artifact(args.artifact_id, operator_label=args.operator)
            print(f"Artifact {art.artifact_id} ACTIVATED for runtime {art.target_runtime} (previous: {art.previous_active_artifact_id})")
        except Exception as exc:
            print(f"Activation failed: {exc}", file=sys.stderr)
            sys.exit(1)

    elif args.subcommand == "rollback":
        try:
            restored = model_registry.rollback_runtime(args.runtime, operator_label=args.operator, reason=args.reason)
            if restored:
                print(f"Runtime {args.runtime} successfully ROLLED BACK to previous active artifact: {restored.artifact_id} ({restored.name} v{restored.version})")
            else:
                print(f"No previous artifact to rollback to.")
        except Exception as exc:
            print(f"Rollback failed: {exc}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
