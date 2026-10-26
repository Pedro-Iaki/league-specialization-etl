"""Freeze audience score cuts for a manually refreshed local player snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))
from app_core.audience import build_reference
from app_core.audience_segments import REFERENCE_FILE, build_segment_reference
from app_core.family_exports import validate_family_frame


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=APP_ROOT / "data/player_profiles.parquet")
    parser.add_argument("--output", type=Path)
    parser.add_argument('--audience-segments', action='store_true',
                        help='Freeze the wider family-audience base instead of the legacy paired focus reference.')
    args = parser.parse_args()
    players = pd.read_parquet(args.snapshot)
    source_hash = hashlib.sha256(args.snapshot.read_bytes()).hexdigest()
    if args.audience_segments:
        validate_family_frame(players, players.attrs.get('family_affinity'))
        reference = build_segment_reference(players, source_hash)
    else:
        reference = build_reference(players, source_hash)
    output = args.output or APP_ROOT / 'data' / (REFERENCE_FILE if args.audience_segments else 'audience_reference.json')
    manifest_path = output.parent / 'manifest.json'
    manifest = None
    if args.audience_segments and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if manifest.get('datasets', {}).get('players', {}).get('sha256') != source_hash:
            raise ValueError('Candidate manifest belongs to a different player snapshot')
    output.write_text(json.dumps(reference, indent=2) + "\n", encoding="utf-8")
    if manifest is not None:
        manifest['audience_segments_reference'] = {
            'file': output.name, 'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
            'definition_version': reference['definition_version'],
        }
        temporary = manifest_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        temporary.replace(manifest_path)
    print(f"Frozen {reference['source_profile_count']:,} source profiles -> {output}")


if __name__ == "__main__":
    main()
