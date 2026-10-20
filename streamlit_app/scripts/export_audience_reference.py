"""Freeze audience score cuts for a manually refreshed local player snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))
from app_core.audience import build_reference


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=APP_ROOT / "data/player_profiles.parquet")
    parser.add_argument("--output", type=Path, default=APP_ROOT / "data/audience_reference.json")
    args = parser.parse_args()
    reference = build_reference(pd.read_parquet(args.snapshot), hashlib.sha256(args.snapshot.read_bytes()).hexdigest())
    args.output.write_text(json.dumps(reference, indent=2) + "\n", encoding="utf-8")
    print(f"Frozen {reference['cohort_n']:,} profiles; cuts {reference['right_closed_score_cuts']} -> {args.output}")


if __name__ == "__main__":
    main()
