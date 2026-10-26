"""One-time reproduction of the accepted laboratory fit; never called by exports."""
import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app_core.archetype_serving import (
    FEATURE_ID,
    IDS,
    MODEL_PATH,
    NAMES,
    describe_loadings,
    infer_loadings,
    pool_features,
)
from app_core.families import VECTORS_DIR, load_membership
from app_core.family_affinity import load_family_definition
from app_core.pool_archetypes import (
    ArchetypeSettings,
    assign_archetypes,
    family_weights,
    fit_archetypes,
    load_pool_features,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=MODEL_PATH)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Frozen model already exists; create a new version to replace it.')
    frame, families = load_pool_features()
    members, manifest = load_membership()
    definition = load_family_definition()
    features = np.stack([pool_features(pool, definition)[0] for pool in members.members])
    np.testing.assert_allclose(features, frame[families].to_numpy(), atol=1e-12, rtol=0)
    eligible = frame.pool_size.ge(4) & frame[families].sum(axis=1).gt(0)
    assert (len(frame), int(frame.pool_size.eq(0).sum()), int((frame.pool_size.between(1, 3)).sum()), int(eligible.sum())) == (38403, 17765, 7290, 13348)
    settings = ArchetypeSettings(8, 0., False, .4, 4, .2, 1., 42)
    x = features[eligible]
    loading, profiles, error = fit_archetypes(x, settings, 25)
    assignment = assign_archetypes(loading, .2)
    counts = np.bincount(assignment.archetype, minlength=8).tolist()
    assert counts == [2476, 1554, 2835, 3581, 825, 1039, 544, 494], counts
    assert int(assignment.kind.eq('Diffuse').sum()) == 573
    model = {'model_id': 'player-pool-archetypes-v1', 'feature_id': FEATURE_ID,
                 'family_sha256': definition.sha256, 'family_order': families, 'ids': list(IDS), 'names': list(NAMES),
                 'name_glossary': {'A3': 'Attack damage carries: ranged characters focused on sustained attacks.'},
                 'profiles': profiles.tolist(), 'family_weights': family_weights(x, 1., 25).tolist(),
                 'minimum_pool': 4, 'threshold': .2, 'settings': asdict(settings),
                 'inference': {'algorithm': 'fixed-profile KL multiplicative updates; constant per-row initialization',
                            'max_iter': 10000, 'atol': 1e-9},
                 'normalization': 'profiles peak at one in unweighted affinity units; infer directly in this loading scale',
                 'membership': 'Existing model-active pool; all lifetime mastery; no cutoff; equal weights only for zero-total pools; full overlap attribution; unknown mass retained',
                 'training': {'as_of_date': '2026-10-20', 'membership_sha256': manifest['sha256'],
                           'vectors_sha256': hashlib.sha256((VECTORS_DIR / 'vectors.parquet').read_bytes()).hexdigest(),
                           'profiles': len(frame), 'eligible': len(x), 'lab_primary_counts': counts,
                           'lab_kind_counts': assignment.kind.value_counts().to_dict(), 'reconstruction_error': error},
                 'versions': {p: version(p) for p in ['numpy', 'scipy', 'scikit-learn']},
                 'naming_review': 'Informal recognizability feedback from League players; not statistical validation'}
    inferred = infer_loadings(x, model)
    described = [describe_loadings(row, model) for row in inferred]
    evidence = {'feature_max_abs_difference': float(np.max(np.abs(features - frame[families].to_numpy()))),
                    'loading_abs_difference_quantiles': np.quantile(np.abs(inferred-loading), [0,.5,.95,.99,1]).tolist(),
                    'primary_changes': int((inferred.argmax(axis=1) != loading.argmax(axis=1)).sum()),
                    'threshold_decision_changes': int(((inferred >= .2) != (loading >= .2)).sum()),
                    'kind_changes': sum(row['archetype_kind'] != kind for row, kind in zip(described, assignment.kind)),
                    'inference_primary_counts': np.bincount(inferred.argmax(axis=1), minlength=8).tolist(),
                    'inference_kind_counts': {kind: sum(r['archetype_kind'] == kind for r in described) for kind in ['Single','Blend','Diffuse']},
                    'note': 'Fixed-component inference optimizes each row to convergence; joint laboratory fit stops globally. Differences are reported, not hidden.'}
    # Freeze the reviewed profiles, with explicitly measured fixed-inference differences.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(model, indent=2, allow_nan=False)+'\n', encoding='utf8')
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(evidence, indent=2)+'\n', encoding='utf8')
    print(json.dumps(evidence, indent=2))


if __name__ == '__main__':
    main()
