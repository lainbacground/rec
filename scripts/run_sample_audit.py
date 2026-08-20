"""Run REC end to end on the tiny synthetic portfolio fixture."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault(
    "MPLCONFIGDIR", str(REPOSITORY_ROOT / "outputs" / ".matplotlib-cache")
)
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from rec.data_loader import load_csv  # noqa: E402
from rec.reporting import generate_audit_outputs  # noqa: E402
from rec.validation import validate_dataset  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a CSV and generate reproducible REC audit artifacts."
    )
    parser.add_argument(
        "input_csv",
        nargs="?",
        type=Path,
        default=REPOSITORY_ROOT / "examples" / "synthetic_audit.csv",
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        type=Path,
        default=REPOSITORY_ROOT / "outputs" / "sample_audit",
        help="Must be outputs/ or a directory beneath outputs/.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = validate_dataset(load_csv(args.input_csv))
    if not result.is_valid:
        print("The audit input is invalid:", file=sys.stderr)
        for issue in result.issues:
            print(f"- {issue}", file=sys.stderr)
        return 1

    artifacts = generate_audit_outputs(
        result,
        output_dir=args.output_dir,
        run_metadata={
            "Dataset name": args.input_csv.name,
            "Run identifier": "synthetic-portfolio-example",
        },
    )
    print(f"Generated {len(artifacts.all_files)} audit artifacts in {artifacts.output_dir}")
    for path in artifacts.all_files:
        print(f"- {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
