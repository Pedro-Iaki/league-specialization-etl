"""Run local family cohort experiments independently of Streamlit."""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from app_core.family_experiments import load_spec, plan_experiments, run_experiments


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('spec', type=Path, help='Experiment JSON; data paths resolve from the repository root.')
    parser.add_argument('--plan', action='store_true', help='Validate and print the grid without waiting or writing.')
    parser.add_argument('--output', type=Path, help='Override the result directory; reuse it to resume.')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    try:
        spec = load_spec(args.spec)
        if args.output:
            spec['output'] = str(args.output)
        if args.plan:
            for run in plan_experiments(spec):
                print(f'{run["id"]}: {run["policy"]}')
            print(f'{len(plan_experiments(spec))} main runs; follow-ups: {spec["followups"]}')
        else:
            run_experiments(spec)
    except (ValueError, OSError, RuntimeError) as error:
        logging.error('%s', error)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
