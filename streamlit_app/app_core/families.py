"""Local character-family discovery, diagnostics and portable review scenarios."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd

from app_core.config import REPO_ROOT
from app_core.population import ALL_TIERS, calibrate_population, load_reference, reference_fingerprint

LOCAL_DIR = REPO_ROOT / 'data' / 'character_families'


@dataclass(frozen=True)
class FamilySettings:
    minimum_mastery: int = 15000
    minimum_players: int = 30
    minimum_shared: int = 10
    minimum_similarity: float = 0.03
    neighbors: int = 10
    mutual_neighbors: bool = False
    resolution: float = 1.0
    minimum_family_size: int = 3
    maximum_family_size: int = 0
    seed: int = 42
    association: str = 'jaccard'
    population_weighted: bool = True

    def __post_init__(self):
        if not 0 <= self.minimum_mastery <= 10_000_000:
            raise ValueError('Mastery cutoff must be between 0 and 10,000,000.')
        if self.minimum_players < 1 or self.minimum_shared < 1:
            raise ValueError('Support thresholds must be positive.')
        if not 0 <= self.minimum_similarity <= 1 or not 1 <= self.neighbors <= 172:
            raise ValueError('Similarity must be 0–1 and neighbors 1–172.')
        if not 0.05 <= self.resolution <= 5 or not 2 <= self.minimum_family_size <= 173:
            raise ValueError('Resolution must be 0.05–5 and minimum family size 2–173.')
        if self.maximum_family_size and not self.minimum_family_size <= self.maximum_family_size <= 173:
            raise ValueError('Maximum family size must be zero (unlimited) or at least the minimum.')
        if not 0 <= self.seed <= 2**31 - 1 or self.association not in {'jaccard', 'breadth_adjusted'}:
            raise ValueError('Invalid seed or association method.')


def validate_membership(frame: pd.DataFrame) -> None:
    required = {'region', 'queue', 'tier', 'days_tracked', 'members', 'as_of_date'}
    if not required.issubset(frame.columns) or frame.empty:
        raise ValueError('Membership snapshot is empty or lacks required fields.')
    if {'player_id', 'puuid'}.intersection(frame.columns):
        raise ValueError('Local membership must exclude player identifiers.')
    names = {}
    for members in frame.members:
        seen = set()
        for member in members if members is not None else []:
            key, name, points = int(member['key']), str(member['name']), float(member['points'])
            if key in seen or not np.isfinite(points) or points < 0 or not name:
                raise ValueError('Invalid or duplicate character membership.')
            if key in names and names[key] != name:
                raise ValueError('Character key/name mapping is inconsistent.')
            names[key] = name
            seen.add(key)


def load_membership(directory: Path = LOCAL_DIR) -> tuple[pd.DataFrame, dict]:
    path = directory / 'membership.parquet'
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    if hashlib.sha256(path.read_bytes()).hexdigest() != manifest['sha256']:
        raise ValueError('Membership snapshot does not match its manifest. Export it again.')
    frame = pd.read_parquet(path)
    validate_membership(frame)
    return frame, manifest


def prepare_membership(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray, dict]:
    """Freeze base-cohort tier weights before any laboratory filtering."""
    base = frame.loc[frame.tier.isin(ALL_TIERS)].copy().reset_index(drop=True)
    base, diagnostics = calibrate_population(base)
    records = {int(m['key']): str(m['name']) for pool in base.members for m in (pool if pool is not None else [])}
    characters = pd.DataFrame(sorted(records.items()), columns=['character_key', 'character'])
    positions = {key: i for i, key in enumerate(characters.character_key)}
    points = np.zeros((len(base), len(characters)), dtype=np.float64)
    for row, pool in enumerate(base.members):
        for member in pool if pool is not None else []:
            points[row, positions[int(member['key'])]] = float(member['points'])
    reference = load_reference()
    provenance = {
        'reference_sha256': reference_fingerprint(reference),
        'reference_version': reference.reference_version.iloc[0],
        'reference_covered_share': float(diagnostics.covered_population_share.min()),
        'excluded_unknown_tier': len(frame) - len(base),
    }
    return base.drop(columns='members'), characters, points, provenance


def pair_statistics(points: np.ndarray, weights: np.ndarray, settings: FamilySettings) -> dict:
    membership = ((points >= settings.minimum_mastery) & (points > 0)).astype(np.float64)
    raw = membership.T @ membership
    shared = membership.T @ (membership * weights[:, None])
    audience = np.diag(shared).copy()
    union = audience[:, None] + audience[None, :] - shared
    jaccard = np.divide(shared, union, out=np.zeros_like(shared), where=union > 0)
    direction = np.divide(shared, audience[:, None], out=np.zeros_like(shared), where=audience[:, None] > 0)
    breadth = membership.sum(axis=1).astype(int)
    expected = np.zeros_like(shared)
    # Singletons supply coverage/marginals but cannot supply pair relationships.
    for low, high in [(2, 2), (3, 5), (6, 10), (11, 20), (21, 50), (51, 100000)]:
        mask = (breadth >= low) & (breadth <= high)
        mass = weights[mask].sum()
        if mass > 0:
            margins = membership[mask].T @ weights[mask]
            expected += np.outer(margins, margins) / mass
    ratio = np.divide(shared, expected, out=np.ones_like(shared), where=expected > 0)
    adjusted = np.maximum(0, np.log2(np.maximum(ratio, 1e-12)))
    np.fill_diagonal(jaccard, 0)
    np.fill_diagonal(adjusted, 0)
    return dict(raw=raw, shared=shared, audience=audience, jaccard=jaccard, direction=direction,
                adjusted=adjusted, breadth=breadth, membership=membership, expected=expected)


def discover_families(points: np.ndarray, characters: pd.DataFrame, weights: np.ndarray,
                      settings: FamilySettings, excluded: tuple[int, ...] = ()) -> dict:
    if len(points) != len(weights) or len(points) == 0 or not np.isfinite(weights).all() or (weights <= 0).any():
        raise ValueError('Select profiles with valid positive weights.')
    stats = pair_statistics(points, weights, settings)
    keys = characters.character_key.to_numpy(dtype=int)
    names = characters.character.to_numpy()
    graph, edge_weights, supported = _family_graph(stats, keys, settings, excluded)
    membership = _partition_families(graph, edge_weights, keys, settings, settings.seed)
    assignments = characters.copy()
    assignments['family'] = [f'AR{x + 1:02d}' if x >= 0 else 'Unassigned' for x in membership]
    assignments['support'] = np.diag(stats['raw']).astype(int)
    assignments['weighted_audience'] = stats['audience']
    assignments['degree'] = graph.degree()
    assignments['status'] = np.where(~supported, 'Below support / excluded',
                                     np.where(membership < 0, 'No accepted family', 'Candidate'))
    edges = pd.DataFrame([
        {'character_a': names[i], 'character_b': names[j], 'key_a': int(keys[i]), 'key_b': int(keys[j]),
         'shared_profiles': int(stats['raw'][i, j]), 'jaccard': float(stats['jaccard'][i, j]),
         'a_to_b': float(stats['direction'][i, j]), 'b_to_a': float(stats['direction'][j, i]),
         'breadth_log2_ratio': float(stats['adjusted'][i, j]), 'edge_weight': weight}
        for (i, j), weight in zip(graph.get_edgelist(), edge_weights, strict=True)
    ], columns=['character_a', 'character_b', 'key_a', 'key_b', 'shared_profiles', 'jaccard',
                'a_to_b', 'b_to_a', 'breadth_log2_ratio', 'edge_weight'])
    return {'assignments': assignments, 'edges': edges, 'stats': stats,
            'graph': graph, 'edge_weights': edge_weights}


def _family_graph(stats: dict, keys: np.ndarray, settings: FamilySettings, excluded: tuple[int, ...]):
    import igraph as ig

    n = len(keys)
    supported = np.diag(stats['raw']) >= settings.minimum_players
    supported &= ~np.isin(keys, excluded)
    valid = ((stats['raw'] >= settings.minimum_shared) & (stats['jaccard'] >= settings.minimum_similarity)
             & supported[:, None] & supported[None, :])
    np.fill_diagonal(valid, False)
    scores = stats['jaccard'] if settings.association == 'jaccard' else stats['adjusted']
    valid &= scores > 0
    nearest = np.zeros((n, n), dtype=bool)
    for i in range(n):
        candidates = np.flatnonzero(valid[i])
        # Preserve score-descending/key-ascending ordering, including exact ties.
        ranked = candidates[np.lexsort((keys[candidates], -scores[i, candidates]))]
        nearest[i, ranked[:settings.neighbors]] = True
    connected = nearest & nearest.T if settings.mutual_neighbors else nearest | nearest.T
    edge_indices = list(zip(*np.where(np.triu(connected, 1)), strict=True))
    graph = ig.Graph(n=n, edges=edge_indices, directed=False)
    edge_weights = [float(scores[i, j]) for i, j in edge_indices]
    return graph, edge_weights, supported


def _partition_families(graph, edge_weights: list[float], keys: np.ndarray,
                        settings: FamilySettings, seed: int) -> np.ndarray:
    import leidenalg as la

    membership = np.full(len(keys), -1, dtype=int)
    if graph.ecount():
        partition = la.find_partition(graph, la.RBConfigurationVertexPartition, weights=edge_weights,
                                     resolution_parameter=settings.resolution, seed=seed,
                                     n_iterations=-1, max_comm_size=settings.maximum_family_size)
        degrees = np.asarray(graph.degree())
        accepted = [sorted(group) for group in partition
                    if len(group) >= settings.minimum_family_size and (degrees[group] > 0).any()]
        accepted.sort(key=lambda group: (-len(group), int(keys[group].min())))
        for index, group in enumerate(accepted):
            membership[group] = index
    return membership


def family_affinities(points: np.ndarray, assignments: pd.DataFrame, minimum_mastery: int) -> pd.DataFrame:
    total = points.sum(axis=1)
    eligible = (points >= minimum_mastery) & (points > 0)
    result = {}
    for family in sorted(set(assignments.family) - {'Unassigned'}):
        result[family] = np.where(eligible[:, assignments.family.eq(family)],
                                  points[:, assignments.family.eq(family)], 0).sum(axis=1)
    result['Below cutoff'] = np.where(~eligible, points, 0).sum(axis=1)
    result['Unmapped'] = np.where(eligible[:, assignments.family.eq('Unassigned')],
                                 points[:, assignments.family.eq('Unassigned')], 0).sum(axis=1)
    return pd.DataFrame({name: np.divide(values, total, out=np.full(len(total), np.nan), where=total > 0)
                         for name, values in result.items()})


def stability_check(points: np.ndarray, characters: pd.DataFrame, weights: np.ndarray, settings: FamilySettings,
                    baseline: pd.DataFrame, excluded: tuple[int, ...], repetitions: int, bootstrap: bool,
                    *, discovery: dict | None = None) -> pd.DataFrame:
    """Reuse the fixed graph for seeds; resample whole profiles for bootstrap."""
    if not 2 <= repetitions <= 50:
        raise ValueError('Use 2?50 stability repetitions.')
    rng = np.random.default_rng(settings.seed)
    scores = np.zeros(len(characters))
    assigned = np.zeros(len(characters))
    together = np.zeros((len(characters), len(characters)), dtype=int)
    original_labels = baseline.family.to_numpy()
    original_members = [set(np.flatnonzero(original_labels == family)) - {i}
                        if family != 'Unassigned' else None for i, family in enumerate(original_labels)]
    keys = characters.character_key.to_numpy(dtype=int)
    if not bootstrap:
        if discovery is not None:
            graph, edge_weights = discovery['graph'], discovery['edge_weights']
        else:
            stats = pair_statistics(points, weights, settings)
            graph, edge_weights, _ = _family_graph(stats, keys, settings, excluded)
    for repeat in range(repetitions):
        if bootstrap:
            sample = rng.integers(0, len(points), len(points))
            stats = pair_statistics(points[sample], weights[sample], settings)
            graph, edge_weights, _ = _family_graph(stats, keys, settings, excluded)
        membership = _partition_families(graph, edge_weights, keys, settings,
                                         (settings.seed + repeat + 1) % 2**31)
        assigned += membership >= 0
        together += (membership[:, None] == membership[None, :]) & (membership[:, None] >= 0)
        groups = {family: set(np.flatnonzero(membership == family))
                  for family in np.unique(membership) if family >= 0}
        for i, original in enumerate(original_members):
            if original is None:
                scores[i] = np.nan
                continue
            comparison = groups.get(membership[i], set()) - {i}
            scores[i] += len(original & comparison) / len(original | comparison) if original | comparison else 0
    report = characters.assign(mean_comember_jaccard=scores / repetitions, assigned_rate=assigned / repetitions)
    report.attrs['co_membership'] = {'character_keys': keys.tolist(), 'rates': (together / repetitions).tolist()}
    return report


def family_consistency(co_membership: dict, baseline: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    """Compare repeat pair frequencies against fixed original groups, excluding self."""
    keys = co_membership['character_keys']
    rates = np.asarray(co_membership['rates'], dtype=float)
    if (len(set(keys)) != len(keys) or set(keys) != set(baseline.character_key)
            or rates.shape != (len(keys), len(keys)) or not np.isfinite(rates).all()
            or (rates < 0).any() or (rates > 1).any() or not np.allclose(rates, rates.T)):
        raise ValueError('Co-membership must be a symmetric probability matrix matching the original characters.')
    positions = {key: i for i, key in enumerate(keys)}
    order = [positions[key] for key in baseline.character_key]
    rates = rates[np.ix_(order, order)]
    labels = baseline.family.to_numpy()
    families = sorted(set(labels) - {'Unassigned'})
    averages = np.full((len(labels), len(families)), np.nan)
    for column, family in enumerate(families):
        members = labels == family
        denominator = members.sum() - members.astype(int)
        totals = rates[:, members].sum(axis=1) - np.diag(rates) * members
        averages[:, column] = np.divide(totals, denominator, out=np.full(len(labels), np.nan), where=denominator > 0)
    rows = []
    for i, family in enumerate(labels):
        own = averages[i, families.index(family)] if family in families else np.nan
        alternatives = [(name, averages[i, column]) for column, name in enumerate(families) if name != family]
        alternative, strength = max(alternatives, key=lambda item: item[1], default=(None, np.nan))
        rows.append({'own_consistency': own, 'alternative_family': alternative,
                     'alternative_consistency': strength, 'separation': own - strength,
                     'assigned_rate': rates[i, i]})
    return pd.concat([baseline[['character_key', 'character', 'family']].reset_index(drop=True), pd.DataFrame(rows)], axis=1), rates


def split_weakest_members(group: pd.DataFrame, trim_fraction: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return the retained and removed original members using the review's fixed rule."""
    if not 0 <= trim_fraction <= .4:
        raise ValueError('Weakest-member removal must be between 0 and 40%.')
    ranked = group.sort_values(['own_consistency', 'character_key'], na_position='first')
    count = min(int(np.ceil(len(group) * trim_fraction)), max(0, len(group) - 2))
    return ranked.iloc[count:], ranked.iloc[:count]


def summarize_family_consistency(co_membership: dict, baseline: pd.DataFrame, target: float = .8,
                                 trim_fraction: float = .2, separation_target: float = .2) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Keep full-group evidence visible beside sensitivity to removing weakest members."""
    if not 0 <= target <= 1 or not 0 <= trim_fraction <= .4 or not 0 <= separation_target <= 1:
        raise ValueError('Invalid family review target or removal fraction (0–40%).')
    characters, rates = family_consistency(co_membership, baseline)
    families = []
    for family, group in characters.loc[characters.family.ne('Unassigned')].groupby('family', sort=True):
        kept, removed = split_weakest_members(group, trim_fraction)
        removed_count = len(removed)
        retained = kept.index.to_numpy()
        submatrix = rates[np.ix_(retained, retained)]
        retained_cohesion = ((submatrix.sum() - np.trace(submatrix)) / (len(retained) * (len(retained) - 1))
                             if len(retained) >= 2 else np.nan)
        mean = group.own_consistency.mean()
        median_gap = group.separation.median() if group.separation.notna().any() else np.nan
        weak = group.own_consistency.lt(target)
        if pd.isna(mean):
            pattern = 'No original peers'
        elif pd.notna(median_gap) and median_gap < separation_target:
            pattern = 'Overlaps alternatives'
        elif mean >= target:
            pattern = 'Cohesive with loose members' if weak.any() else 'Cohesive throughout'
        elif retained_cohesion >= target and removed_count:
            pattern = 'Sensitive to weakest members'
        else:
            pattern = 'Loose or possible subgroups'
        families.append({'family': family, 'characters': len(group), 'mean_consistency': mean,
                         'median_consistency': group.own_consistency.median(),
                         'p10_consistency': group.own_consistency.quantile(.1),
                         'weak_members': int(weak.sum()), 'weak_share': float(weak.mean()),
                         'median_separation': median_gap, 'retained_consistency': retained_cohesion,
                         'uplift_pp': (retained_cohesion - mean) * 100,
                         'removed_count': removed_count, 'retained_count': len(retained),
                         'removed_members': ', '.join(removed.character), 'pattern': pattern})
    return pd.DataFrame(families, columns=['family', 'characters', 'mean_consistency', 'median_consistency',
                         'p10_consistency', 'weak_members', 'weak_share', 'median_separation', 'retained_consistency',
                         'uplift_pp', 'removed_count', 'retained_count', 'removed_members', 'pattern']), characters


def refine_memberships(consistency: pd.DataFrame, single_threshold: float = .8,
                       shared_threshold: float = .4) -> pd.DataFrame:
    """Derive at most two memberships using frozen original groups; do not refit."""
    if not 0 <= shared_threshold <= single_threshold <= 1:
        raise ValueError('Thresholds must satisfy 0 ≤ shared ≤ single ≤ 100%.')
    rows = []
    for row in consistency.itertuples():
        own_valid = row.family != 'Unassigned' and pd.notna(row.own_consistency) and row.own_consistency > 0
        alt_valid = pd.notna(row.alternative_family) and pd.notna(row.alternative_consistency) and row.alternative_consistency > 0
        primary = secondary = None
        if own_valid and alt_valid and min(row.own_consistency, row.alternative_consistency) >= shared_threshold:
            state = 'Both'
            primary, secondary = ((row.family, row.alternative_family) if row.own_consistency >= row.alternative_consistency
                                  else (row.alternative_family, row.family))
        elif own_valid and row.own_consistency >= single_threshold:
            state, primary = 'Primary only', row.family
        elif alt_valid and row.alternative_consistency >= single_threshold:
            state, primary = 'Secondary only', row.alternative_family
        else:
            state = 'Indecisive'
        rows.append({'character_key': row.character_key, 'character': row.character,
                     'original_family': row.family, 'alternative_family': row.alternative_family,
                     'own_consistency': row.own_consistency, 'alternative_consistency': row.alternative_consistency,
                     'assigned_rate': row.assigned_rate, 'state': state,
                     'final_primary': primary, 'final_secondary': secondary})
    return pd.DataFrame(rows, columns=['character_key', 'character', 'original_family', 'alternative_family',
                                      'own_consistency', 'alternative_consistency', 'assigned_rate', 'state',
                                      'final_primary', 'final_secondary'])


def summarize_stability(report: pd.DataFrame, baseline: pd.DataFrame, target: float = 0.8) -> dict:
    """Equal-character summaries; undefined co-membership never becomes zero."""
    if not 0 <= target <= 1:
        raise ValueError('Stability review target must be between zero and one.')
    required = {'character_key', 'mean_comember_jaccard', 'assigned_rate'}
    if not required.issubset(report) or not {'character_key', 'family'}.issubset(baseline):
        raise ValueError('Stability report lacks required character or assignment fields.')
    rows = baseline[['character_key', 'family']].merge(report, on='character_key', validate='one_to_one', how='left')
    if len(rows) != len(report) or not set(report.character_key) == set(baseline.character_key):
        raise ValueError('Stability report and baseline must contain the same characters.')
    for column in ['mean_comember_jaccard', 'assigned_rate']:
        values = pd.to_numeric(rows[column], errors='raise')
        if (values.notna() & (~np.isfinite(values) | values.lt(0) | values.gt(1))).any():
            raise ValueError('Stability values must be missing or between zero and one.')
        rows[column] = values
    initially_assigned = rows.family.ne('Unassigned')
    scored = rows.loc[initially_assigned & rows.mean_comember_jaccard.notna()]
    values = scored.mean_comember_jaccard
    rates = rows.loc[initially_assigned, 'assigned_rate']
    summaries = []
    for family, group in rows.loc[initially_assigned].groupby('family', sort=True):
        scores = group.mean_comember_jaccard.dropna()
        summaries.append({'family': family, 'characters': len(group), 'scored_characters': len(scores),
                          'mean_comember_jaccard': float(scores.mean()) if len(scores) else None,
                          'below_target_share': float(scores.lt(target).mean()) if len(scores) else None,
                          'mean_assigned_rate': float(group.assigned_rate.mean()) if group.assigned_rate.notna().any() else None})
    return {
        'total_characters': len(rows), 'initially_assigned': int(initially_assigned.sum()),
        'scored_characters': len(values), 'below_target': int(values.lt(target).sum()), 'target': target,
        'mean_jaccard': float(values.mean()) if len(values) else None,
        'median_jaccard': float(values.median()) if len(values) else None,
        'p10_jaccard': float(values.quantile(0.1)) if len(values) else None,
        'below_target_share': float(values.lt(target).mean()) if len(values) else None,
        'mean_assigned_rate': float(rates.mean()) if rates.notna().any() else None,
        'assignment_scored_characters': int(rates.notna().sum()),
        'initial_coverage': float(initially_assigned.mean()) if len(rows) else None,
        'rows': rows, 'families': pd.DataFrame(summaries),
    }


def scenario_payload(settings: FamilySettings, context: dict, assignments: pd.DataFrame,
                     titles: dict, notes: str, stability: dict | None = None) -> dict:
    return {'schema_version': 1, 'status': 'Exploratory, manually reviewed candidate',
            'saved_at_utc': datetime.now(timezone.utc).isoformat(), 'settings': asdict(settings),
            'source': context, 'software': {name: version(name) for name in ['leidenalg', 'igraph', 'numpy', 'pandas']},
            'families': titles, 'notes': notes, 'stability': stability,
            'assignments': assignments[['character_key', 'character', 'family']].to_dict('records')}


def validate_scenario(payload: dict, characters: pd.DataFrame, source_hash: str) -> None:
    if not isinstance(payload, dict):
        raise ValueError('Scenario must be a JSON object.')
    refinement = payload.get('refinement')
    if refinement is not None:
        if (not isinstance(refinement, dict) or not isinstance(refinement.get('rules'), dict)
                or not isinstance(refinement.get('source'), str)):
            raise ValueError('Invalid saved refinement definition.')
        rules = refinement['rules']
        single, shared = rules.get('single_threshold'), rules.get('shared_threshold')
        if (not isinstance(single, (int, float)) or not isinstance(shared, (int, float))
                or not 0 <= shared <= single <= 1):
            raise ValueError('Invalid saved refinement thresholds.')
    source = payload.get('source')
    if (payload.get('schema_version') != 1 or not isinstance(source, dict)
            or source.get('membership_sha256') != source_hash):
        raise ValueError('Scenario belongs to a different membership snapshot or schema.')
    FamilySettings(**payload['settings'])
    if source.get('reference_sha256') != reference_fingerprint(load_reference()):
        raise ValueError('Scenario uses a different population reference.')
    if (not isinstance(source.get('tiers'), list) or not set(source['tiers']).issubset(ALL_TIERS)
            or source.get('maturity') not in {'All', 'Under 30 days', '30 days or more'}
            or not isinstance(source.get('excluded_keys'), list)):
        raise ValueError('Scenario audience filters are invalid.')
    assignments = pd.DataFrame(payload['assignments'])
    expected = characters[['character_key', 'character']].sort_values('character_key').reset_index(drop=True)
    actual = assignments[['character_key', 'character']].sort_values('character_key').reset_index(drop=True)
    if not actual.equals(expected) or assignments.character_key.duplicated().any():
        raise ValueError('Scenario character keys/names do not match this snapshot.')
    if not assignments.family.map(lambda x: isinstance(x, str) and 0 < len(x) <= 80).all():
        raise ValueError('Family IDs must be nonempty strings of at most 80 characters.')
    families = set(assignments.family) - {'Unassigned'}
    if not isinstance(payload.get('families'), dict) or not families.issubset(payload['families']):
        raise ValueError('Every assigned family requires a title.')
    for family in families:
        label = payload['families'][family]
        if not isinstance(label, dict) or not isinstance(label.get('title'), str) or not label['title'].strip():
            raise ValueError('Family titles must be nonempty strings.')
