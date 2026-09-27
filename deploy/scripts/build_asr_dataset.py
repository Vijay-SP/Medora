"""
CLI Script to build verified ASR adaptation datasets.
Usage:
    python deploy/scripts/build_asr_dataset.py --output-name v1 --seed 42
"""

import argparse
import os
from pathlib import Path
import sys

# Ensure repository root and backend are on PYTHONPATH
repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(repo_root / "backend"))

from app.core.config import settings
from app.services.learning.dataset_builder import build_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Build verified ASR adaptation dataset.")
    parser.add_argument("--output-name", type=str, default="v1", help="Name of dataset version directory")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for recording split")
    args = parser.parse_args()

    target_dir = Path(settings.ADAPTATION_DIR) / "datasets" / args.output_name
    print(f"Building adaptation dataset '{args.output_name}' at: {target_dir}")

    try:
        manifest = build_dataset(target_dir, seed=args.seed)
        print("\n--- Dataset Build Complete ---")
        print(f"Dataset ID:         {manifest.dataset_id}")
        print(f"Total Clips:        {manifest.total_examples}")
        print(f"Total Audio:        {manifest.total_duration_seconds:.2f} seconds")
        print(f"Splits:")
        for s_name, ex_list in manifest.splits.items():
            print(f"  - {s_name:20s}: {len(ex_list):4d} examples")
        print(f"Manifest Checksum:  {manifest.checksum[:16]}...")
        print(f"Output Directory:   {target_dir}\n")
    except Exception as exc:
        print(f"Error building dataset: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
