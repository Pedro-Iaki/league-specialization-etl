from __future__ import annotations

import argparse
from pathlib import Path

from src.transform.consolidate_silver import process_partition


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the silver transformation for a single partition.")
    parser.add_argument("--patch", default="16.14.1")
    parser.add_argument("--region", default="na1")
    parser.add_argument("--queue", default="RANKED_SOLO_5x5")
    parser.add_argument("--db-path", type=Path, default=Path("data/database/extraction.db"))
    parser.add_argument("--silver-base", type=Path, default=Path("data/silver"))
    parser.add_argument("--quarantine-dir", type=Path, default=Path("data/quarantine"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    process_partition(
        target_patch=args.patch,
        target_region=args.region,
        target_queue=args.queue,
        db_path=args.db_path,
        silver_base=args.silver_base,
        quarantine_dir=args.quarantine_dir,
    )


if __name__ == "__main__":
    main()
