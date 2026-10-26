"""Copy serving to an isolated candidate and refresh keyed archetype rows from source."""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app_core.archetype_serving import load_model, validate_archetypes
from app_core.config import DATA_DIR
from scripts.export_data import export_snapshots, validate_public_frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--validate-existing', action='store_true', help='Finish validation of an existing isolated candidate without querying source again.')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if (output.exists() and not args.validate_existing) or output == DATA_DIR.resolve():
        raise ValueError('Choose a new candidate directory outside serving.')
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in DATA_DIR.iterdir() if p.is_file()}
    if not args.validate_existing:
        shutil.copytree(DATA_DIR, output)
    old_manifest = json.loads((DATA_DIR / 'manifest.json').read_text())
    manifest = (json.loads((output / 'manifest.json').read_text()) if args.validate_existing else
                export_snapshots(output, ['players', 'business_players'], pool_archetypes=True))
    assert manifest['datasets']['business_players']['scenario'] == old_manifest['datasets']['business_players']['scenario']
    # Reference cuts are frozen. Update provenance only if the source profile scope and traits match.
    original = pd.read_parquet(DATA_DIR / 'player_profiles.parquet')
    updated = pd.read_parquet(output / 'player_profiles.parquet')
    def signatures(frame, columns):
        return sorted(pd.util.hash_pandas_object(frame.loc[:, columns].astype(str), index=False).tolist())
    scalar_columns = [c for c in original if original[c].dtype != object]
    assert signatures(original, scalar_columns) == signatures(updated, scalar_columns), 'Source traits changed; review references explicitly'
    for filename in ['audience_reference.json', 'audience_segments_reference.json']:
        path = output / filename
        if path.exists():
            reference = json.loads(path.read_text())
            reference['source_profile_sha256'] = manifest['datasets']['players']['sha256']
            path.write_text(json.dumps(reference, indent=2)+'\n', encoding='utf8')
            if filename == 'audience_segments_reference.json':
                manifest['audience_segments_reference'] = {
                    'file': filename, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                    'definition_version': reference['definition_version']}
    for name, item in manifest['datasets'].items():
        path = output / item['file']
        frame = pd.read_parquet(path)
        validate_public_frame(name, frame)
        assert (len(frame),len(frame.columns),path.stat().st_size) == (item['rows'],item['columns'],item['size_bytes'])
        if name in {'players','business_players'}:
            validate_archetypes(frame, item['pool_archetypes'], load_model())
    old_business = pd.read_parquet(DATA_DIR / 'business_players.parquet')
    new_business = pd.read_parquet(output / 'business_players.parquet')
    from app_core.business import BUSINESS_PUBLIC_COLUMNS
    assert signatures(old_business, list(BUSINESS_PUBLIC_COLUMNS)) == signatures(new_business, list(BUSINESS_PUBLIC_COLUMNS))
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf8')
    from app_core import data
    from app_core.archetype_serving import coverage
    from app_core.audience_segments import prepare_segments
    data.DATA_DIR, data.MANIFEST_PATH = output, output / 'manifest.json'
    report = {}
    for name in ['players', 'business_players']:
        checked = data._validate_dataset(name, data._read_snapshot(name))
        report[name] = {
            'rows': len(checked),
            'coverage': coverage(checked).to_dict('records'),
            'kinds': checked.archetype_kind.value_counts().to_dict(),
            'sha256': manifest['datasets'][name]['sha256']}
    prepare_segments(updated, json.loads((output / 'audience_segments_reference.json').read_text()))
    report['business_scenario_preserved'] = True
    report['business_public_columns_preserved'] = True
    report['population_and_frozen_reference_cuts_preserved'] = True
    report['serving_promoted'] = False
    report['all_manifest_datasets_validated'] = len(manifest['datasets'])
    report['serving_baseline_sha256'] = before
    (output / 'archetype-validation.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf8')
    print(json.dumps({k: v for k, v in report.items() if k != 'serving_baseline_sha256'}, indent=2))
    assert before == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in DATA_DIR.iterdir() if p.is_file()}
    print(f'Complete candidate validated at {output}; serving hashes preserved.')


if __name__ == '__main__':
    main()
