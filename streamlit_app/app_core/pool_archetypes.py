"""Pool archetypes: non-negative factorization of active-pool family affinities (local laboratory).

Affinities are overlapping 0-1 coverage scores, so rows do not sum to one. Roles are not features and the
local membership snapshot carries no player identity, so concentration is computed from the same pool.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from sklearn.cluster import KMeans
from sklearn.decomposition import NMF
from sklearn.metrics import adjusted_rand_score

from app_core.config import DATA_DIR, REPO_ROOT
from app_core.families import LOCAL_DIR, VECTORS_DIR, load_family_reference, load_membership
from app_core.population import WEIGHT, calibrate_population, effective_sample_size, weighted_mean, weighted_quantile

DEFINITION_PATH = REPO_ROOT / 'streamlit_app' / 'definitions' / 'champion-audience-families-v1.json'
CHAMPION_PROFILES_PATH = DATA_DIR / 'champion_profiles.parquet'
AFFINITY_PREFIX = 'mastery_coverage_'
CONCENTRATION_COLUMNS = ('top1_share', 'normalized_entropy')
ROLE_COLUMNS = {'Top': 'role_top', 'Jungle': 'role_jungle', 'Middle': 'role_middle',
                'Bottom': 'role_bottom', 'Support': 'role_support'}
STRONG_AFFINITY = 0.5
MAX_ITERATIONS = 300
HELD_OUT_FRACTION = 0.2
KINDS = ('Single', 'Blend', 'Diffuse')


@dataclass(frozen=True)
class ArchetypeSettings:
    components: int = 6
    sparsity: float = 0.0
    include_concentration: bool = False
    concentration_weight: float = 0.4
    minimum_pool: int = 3
    active_loading: float = 0.25
    family_weighting: float = 0.0
    seed: int = 42

    def __post_init__(self):
        if not 2 <= self.components <= 20 or not 0 <= self.sparsity <= 1:
            raise ValueError('Components must be 2-20 and sparsity 0-1.')
        if not 0 < self.concentration_weight <= 1 or not 0 < self.active_loading <= 1:
            raise ValueError('Concentration weight and the active loading must be in (0, 1].')
        if not 0 <= self.family_weighting <= 2:
            raise ValueError('Family weighting must be between 0 and 2.')
        if self.minimum_pool < 1 or not 0 <= self.seed <= 2**31 - 1:
            raise ValueError('Minimum pool must be positive and the seed a valid integer.')


def load_champion_roles(path: Path = CHAMPION_PROFILES_PATH) -> pd.DataFrame:
    """Observed role shares per champion (rows sum to one), indexed by champion key."""
    profiles = pd.read_parquet(path).set_index('champion_key')
    roles = profiles[[f'{column}_pct' for column in ROLE_COLUMNS.values()]].set_axis(list(ROLE_COLUMNS.values()), axis=1)
    return roles.div(roles.sum(axis=1).replace(0, np.nan), axis=0)


def load_pool_features(vectors_dir: Path = VECTORS_DIR, membership_dir: Path = LOCAL_DIR,
                       roles: pd.DataFrame | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Join mastery-coverage vectors with pool concentration, role mix and tier weights.

    Both vector and membership files must describe the same snapshot. Tier weights are calibrated on the whole
    snapshot, before any pool filtering, and are used only to describe archetypes, never to fit them.
    """
    metadata = json.loads((vectors_dir / 'metadata.json').read_text(encoding='utf-8'))
    members, manifest = load_membership(membership_dir)
    vectors = pd.read_parquet(vectors_dir / 'vectors.parquet')
    if manifest['sha256'] != metadata['snapshot_sha256'] or len(vectors) != len(members):
        raise ValueError('Family vectors were not built from the current membership snapshot.')
    if not np.array_equal(vectors.snapshot_row.to_numpy(), np.arange(len(vectors))):
        raise ValueError('Vector rows are not in snapshot order.')
    families = list(metadata['family_order'])
    pools = members.members.map(lambda pool: [] if pool is None else list(pool))
    if not np.array_equal(pools.map(len).to_numpy(), vectors.pool_size.to_numpy()):
        raise ValueError('Pool sizes differ between membership and vectors.')
    frame = pd.DataFrame(vectors[[AFFINITY_PREFIX + family for family in families]].to_numpy(),
                         columns=families, index=vectors.index)
    frame.insert(0, 'pool_size', vectors.pool_size.to_numpy())
    roles = load_champion_roles() if roles is None else roles
    concentration = pd.DataFrame([pool_concentration(pool) for pool in pools], index=vectors.index)
    role_mix = pd.DataFrame([pool_role_mix(pool, roles) for pool in pools], index=vectors.index)
    weighted, _ = calibrate_population(members[['region', 'queue', 'tier']], load_family_reference())
    descriptors = pd.DataFrame({'tier': members.tier.to_numpy(), WEIGHT: weighted[WEIGHT].to_numpy()}, index=vectors.index)
    return pd.concat([frame, concentration, role_mix, descriptors], axis=1), families


def _pool_shares(pool: list) -> np.ndarray:
    """Mastery weights; zero-total pools use equal weights like the vectors."""
    points = np.array([float(member['points']) for member in pool])
    if not len(points):
        return points
    return points / points.sum() if points.sum() > 0 else np.full(len(points), 1 / len(points))


def pool_role_mix(pool: list, roles: pd.DataFrame) -> dict:
    """Mastery-weighted mean of each champion's observed role shares; champions without role data are skipped."""
    keys = [int(member['key']) for member in pool]
    known = np.array([key in roles.index for key in keys], dtype=bool)
    shares = _pool_shares(pool)
    if not known.any() or shares[known].sum() <= 0:
        return {column: np.nan for column in ROLE_COLUMNS.values()}
    weights = shares[known] / shares[known].sum()
    mix = weights @ roles.loc[np.array(keys)[known]].to_numpy()
    return dict(zip(ROLE_COLUMNS.values(), mix))


def pool_concentration(pool: list) -> dict:
    """Champion-level concentration of mastery weights."""
    shares = _pool_shares(pool)
    if not len(shares):
        return {name: np.nan for name in CONCENTRATION_COLUMNS}
    positive = shares[shares > 0]
    entropy = -(positive * np.log2(positive)).sum()
    return {'top1_share': shares.max(),
            'normalized_entropy': entropy / np.log2(len(shares)) if len(shares) > 1 else 0.0}


def eligible_mask(frame: pd.DataFrame, families: list[str], minimum_pool: int) -> pd.Series:
    """Pools below the minimum and pools with no family coverage have no affinity to cluster."""
    return (frame.pool_size >= minimum_pool) & (frame[families].sum(axis=1) > 0)


def design_matrix(frame: pd.DataFrame, families: list[str], include_concentration: bool, weight: float) -> np.ndarray:
    matrix = frame[families].to_numpy(dtype=float)
    if include_concentration:
        matrix = np.hstack([matrix, weight * frame[list(CONCENTRATION_COLUMNS)].to_numpy(dtype=float)])
    return matrix


def family_weights(matrix: np.ndarray, strength: float, families: int) -> np.ndarray:
    """Column weights log(1 / mean affinity) ** strength, averaging one; concentration columns keep weight one.

    Ubiquitous families have high mean affinity and get a lower weight, so they stop dominating the
    factorization and rare families can anchor their own archetypes. Strength zero leaves the matrix unchanged.
    """
    weights = np.log(1 / np.maximum(matrix[:, :families].mean(axis=0), 1e-3)) ** strength
    return np.concatenate([weights / weights.mean(), np.ones(matrix.shape[1] - families)])


def _nmf(components: int, sparsity: float, seed: int) -> NMF:
    return NMF(n_components=components, init='nndsvda', solver='mu', beta_loss='kullback-leibler',
               alpha_W=sparsity, l1_ratio=1.0, max_iter=MAX_ITERATIONS, random_state=seed)


def fit_nmf(matrix: np.ndarray, components: int, sparsity: float, seed: int) -> tuple[np.ndarray, np.ndarray, float]:
    """KL-divergence NMF; rows of H are rescaled to a maximum of one so loadings carry the intensity."""
    model = _nmf(components, sparsity, seed)
    loadings = model.fit_transform(matrix)
    profiles = model.components_
    scale = np.maximum(profiles.max(axis=1), 1e-12)
    return loadings * scale, profiles / scale[:, None], float(model.reconstruction_err_)


def fit_archetypes(matrix: np.ndarray, settings: ArchetypeSettings, families: int) -> tuple[np.ndarray, np.ndarray, float]:
    """Fit on family-weighted columns, then express profiles in plain affinity units.

    Loadings are on the scale of the profile peak (affinity 0-1), so they are comparable across players.
    """
    weights = family_weights(matrix, settings.family_weighting, families)
    loadings, profiles, error = fit_nmf(matrix * weights, settings.components, settings.sparsity, settings.seed)
    profiles = profiles / weights
    scale = np.maximum(profiles.max(axis=1), 1e-12)
    return loadings * scale, profiles / scale[:, None], error


def assign_archetypes(loadings: np.ndarray, active_loading: float) -> pd.DataFrame:
    """Primary archetype plus how many archetypes the player expresses in absolute terms.

    A relative top share confuses breadth with mixing: a broad pool spreads thin affinity everywhere. Absolute
    loadings separate the cases. Single: one archetype reaches the active loading. Blend: two or more do.
    Diffuse: none does, so the primary archetype is only a weak best match.
    """
    totals = loadings.sum(axis=1, keepdims=True)
    shares = np.divide(loadings, totals, out=np.zeros_like(loadings), where=totals > 0)
    active = (loadings >= active_loading).sum(axis=1)
    kind = np.select([active == 0, active == 1], ['Diffuse', 'Single'], default='Blend')
    return pd.DataFrame({'archetype': loadings.argmax(axis=1), 'strength': loadings.max(axis=1),
                         'top_share': shares.max(axis=1), 'active_archetypes': active, 'kind': kind})


def profile_similarity(profiles: np.ndarray) -> np.ndarray:
    """Pairwise cosine between archetype profiles; high off-diagonal values mean redundant archetypes."""
    unit = profiles / np.maximum(np.linalg.norm(profiles, axis=1, keepdims=True), 1e-12)
    return unit @ unit.T


def _kl_per_row(observed: np.ndarray, fitted: np.ndarray) -> float:
    fitted = np.maximum(fitted, 1e-12)
    safe = np.maximum(observed, 1e-12)
    return float((observed * np.log(safe / fitted) - observed + fitted).sum() / len(observed))


def sweep_components(matrix: np.ndarray, candidates: list[int], sparsity: float, seed: int,
                     bootstraps: int = 4, sample: int = 4000) -> pd.DataFrame:
    """Held-out error and bootstrap stability (matched cosine of profiles) for each component count.

    Profiles are fitted on a training split; held-out rows are projected on them, so the error cannot be lowered
    just by adding components that memorize players.
    """
    rng = np.random.default_rng(seed)
    rows = matrix[rng.choice(len(matrix), min(sample, len(matrix)), replace=False)]
    split = int(len(rows) * (1 - HELD_OUT_FRACTION))
    train, test = rows[:split], rows[split:]
    results = []
    for components in candidates:
        model = _nmf(components, sparsity, seed)
        fitted = model.fit_transform(train)
        reference = model.components_
        held_out = _kl_per_row(test, model.transform(test) @ reference)
        scores = []
        for draw in range(bootstraps):
            resample = train[rng.integers(0, len(train), len(train))]
            _, other, _ = fit_nmf(resample, components, sparsity, seed + draw + 1)
            scores.append(_matched_cosine(reference, other))
        results.append({'components': components, 'train_error': _kl_per_row(train, fitted @ reference),
                        'held_out_error': held_out, 'stability': float(np.mean(scores)),
                        'worst_stability': float(np.min(scores))})
    return pd.DataFrame(results)


def _matched_cosine(reference: np.ndarray, other: np.ndarray) -> float:
    unit = lambda values: values / np.maximum(np.linalg.norm(values, axis=1, keepdims=True), 1e-12)
    similarity = unit(reference) @ unit(other).T
    rows, columns = linear_sum_assignment(-similarity)
    return float(similarity[rows, columns].mean())


def kmeans_agreement(matrix: np.ndarray, labels: np.ndarray, components: int, seed: int) -> float:
    """Adjusted Rand index between NMF dominant archetypes and k-means on the same matrix."""
    clusters = KMeans(n_clusters=components, n_init=10, random_state=seed).fit_predict(matrix)
    return float(adjusted_rand_score(labels, clusters))


def profile_archetypes(frame: pd.DataFrame, families: list[str], profiles: np.ndarray, assignment: pd.DataFrame,
                       titles: dict[str, str], weights: pd.Series | None = None) -> pd.DataFrame:
    """Describe archetypes after fitting using fields that may not have been features.

    Shares, medians and means use the supplied weights (tier calibration); player counts stay observed.
    Callers must remove rows without a valid weight first.
    """
    weights = pd.Series(1.0, index=frame.index) if weights is None else weights
    data = frame.assign(archetype=assignment.archetype.to_numpy(), kind=assignment.kind.to_numpy(),
                        strength=assignment.strength.to_numpy(), weight=weights.to_numpy())
    data['affinity_mass'] = data[families].sum(axis=1)
    data['strong_families'] = (data[families] >= STRONG_AFFINITY).sum(axis=1)
    medians = {'median_pool': 'pool_size', 'median_strength': 'strength', 'median_top1_share': 'top1_share',
               'median_entropy': 'normalized_entropy', 'median_strong_families': 'strong_families'}
    rows = {}
    for archetype, group in data.groupby('archetype'):
        w = group.weight
        rows[archetype] = {
            'players': len(group), 'share': w.sum() / data.weight.sum(), 'effective_players': effective_sample_size(w),
            **{label: weighted_quantile(group[column], w) for label, column in medians.items()},
            'mean_affinity_mass': weighted_mean(group.affinity_mass, w),
            **{f'{kind.lower()}_share': weighted_mean((group.kind == kind).astype(float), w) for kind in KINDS},
            **{role: weighted_mean(group[column], w) for role, column in ROLE_COLUMNS.items()},
        }
    summary = pd.DataFrame.from_dict(rows, orient='index')
    summary['top_families'] = [
        ', '.join(f'{families[i]} {profiles[a, i]:.2f}' for i in np.argsort(-profiles[a, :len(families)])[:3])
        for a in summary.index]
    summary['lead_family'] = [titles.get(families[int(np.argmax(profiles[a, :len(families)]))], '') for a in summary.index]
    return summary


def inspect_families(frame: pd.DataFrame, families: list[str], definitions: pd.DataFrame, members: np.ndarray,
                     threshold: float, weights: pd.Series, profile: np.ndarray | None = None) -> pd.DataFrame:
    """Per-family reach inside a player subset among players whose affinity reaches the threshold.

    `members` flags the inspected subset. Lift compares the subset's reach with every player's, so a family
    that is rare everywhere is not mistaken for a weak fit among its holders.
    """
    inside = frame.loc[members]
    inside_weights = weights.loc[members]
    rows = []
    for index, family in enumerate(families):
        passing = inside[family] >= threshold
        overall = weighted_mean((frame[family] >= threshold).astype(float), weights)
        reach = weighted_mean(passing.astype(float), inside_weights)
        rows.append({
            'family': family, 'players_passing': int(passing.sum()), 'reach': reach,
            'median_affinity': weighted_quantile(inside.loc[passing, family], inside_weights[passing]),
            'all_players_reach': overall, 'lift': reach / overall if overall > 0 else np.nan,
            'profile_weight': np.nan if profile is None else float(profile[index]),
        })
    result = pd.DataFrame(rows).set_index('family')
    return definitions.join(result, how='right').reset_index()


def tier_prevalence(tiers: pd.Series, members: np.ndarray, include: list[str] | None = None) -> pd.DataFrame:
    """Share of each tier's eligible players in the inspected subset, and its distance from the pooled share.

    The baseline is the subset's share across the included tiers only, so excluded tiers cannot move it.
    Observed and unweighted: within a tier every player counts once.
    """
    frame = pd.DataFrame({'tier': tiers.to_numpy(), 'inside': members})
    if include is not None:
        frame = frame[frame.tier.isin(include)]
    counts = frame.groupby('tier').inside.agg(['mean', 'size']).rename(columns={'mean': 'share_of_tier', 'size': 'players'})
    counts['baseline'] = frame.inside.mean()
    counts['over_under'] = counts.share_of_tier - counts.baseline
    return counts


def pool_size_bands(pool_size: pd.Series, bands: int = 5) -> pd.Categorical:
    """Equal-count bands of pool size labeled by their range, so breadth can be separated from archetype."""
    codes = pd.qcut(pool_size.rank(method='first'), bands, labels=False)
    ranges = pool_size.groupby(codes).agg(['min', 'max'])
    labels = [f'{low}-{high}' for low, high in ranges.itertuples(index=False)]
    return pd.Categorical.from_codes(codes.to_numpy(), labels, ordered=True)


def champion_presence(pools: pd.Series) -> tuple[pd.DataFrame, dict[int, str]]:
    """Boolean player-by-champion matrix (columns are champion keys) and a key-to-name map taken from the pools."""
    names = {int(member['key']): member['name'] for pool in pools for member in pool}
    keys = sorted(names)
    column = {key: position for position, key in enumerate(keys)}
    matrix = np.zeros((len(pools), len(keys)), dtype=bool)
    for row, pool in enumerate(pools):
        for member in pool:
            matrix[row, column[int(member['key'])]] = True
    return pd.DataFrame(matrix, index=pools.index, columns=keys), names


def load_pool_presence(membership_dir: Path = LOCAL_DIR) -> tuple[pd.DataFrame, dict[int, str]]:
    members, _ = load_membership(membership_dir)
    return champion_presence(members.members.map(lambda pool: [] if pool is None else list(pool)))


def champion_families(path: Path = DEFINITION_PATH) -> dict[int, frozenset[str]]:
    """Families each champion belongs to, by champion key; families overlap, so a champion can have several."""
    owners: dict[int, set[str]] = {}
    for family in json.loads(path.read_text(encoding='utf-8'))['families']:
        for member in family['members']:
            owners.setdefault(int(member['character_key']), set()).add(family['family_key'])
    return {key: frozenset(families) for key, families in owners.items()}


def group_prevalence(flags: pd.DataFrame, inside: np.ndarray) -> pd.DataFrame:
    """Share of players inside and outside a subset who have each flag, and the ratio between them."""
    inside_reach = flags[inside].mean()
    outside_reach = flags[~inside].mean()
    lift = (inside_reach / outside_reach.replace(0, np.nan)).rename('lift')
    return pd.concat([flags[inside].sum().rename('players'), inside_reach.rename('inside_reach'),
                      outside_reach.rename('outside_reach'), lift], axis=1)


def pair_lift(flags: pd.DataFrame, inside: np.ndarray, minimum_players: int,
              shared: dict | None = None) -> pd.DataFrame:
    """Flag pairs that co-occur more inside a subset than outside, with enough inside players to trust.

    Excess is the difference in co-occurrence share; it favours combinations that are both common and
    over-represented, where lift alone favours rare ones. `shared` maps a flag to its groups (for example the
    families of a champion) so same-group pairs can be told apart from pairs that bridge groups.
    """
    values = flags.to_numpy(dtype=np.float32)
    inside_rows, outside_rows = values[inside], values[~inside]
    together_in, together_out = inside_rows.T @ inside_rows, outside_rows.T @ outside_rows
    first, second = np.triu_indices(len(flags.columns), 1)
    players = together_in[first, second]
    keep = players >= minimum_players
    first, second, players = first[keep], second[keep], players[keep]
    inside_share = players / max(len(inside_rows), 1)
    outside_share = together_out[first, second] / max(len(outside_rows), 1)
    result = pd.DataFrame({
        'first': flags.columns[first], 'second': flags.columns[second], 'players': players.astype(int),
        'inside_share': inside_share, 'outside_share': outside_share, 'excess': inside_share - outside_share,
        'lift': np.divide(inside_share, outside_share, out=np.full(len(players), np.nan), where=outside_share > 0)})
    if shared is not None:
        result['shared'] = [', '.join(sorted(shared.get(a, frozenset()) & shared.get(b, frozenset())))
                            for a, b in zip(result['first'], result['second'])]
    return result.sort_values('excess', ascending=False).reset_index(drop=True)


def concentration_bands(frame: pd.DataFrame) -> pd.Series:
    """Tertiles of champion-level normalized entropy, labeled for cross-profiling against archetypes."""
    ranks = frame.normalized_entropy.rank(method='first')
    return pd.qcut(ranks, 3, labels=['Focused', 'Balanced', 'Broad']).astype(str)


def load_family_definitions(path: Path = DEFINITION_PATH, roles: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per family: title, size, every member champion and their mean observed role shares."""
    roles = load_champion_roles() if roles is None else roles
    rows = []
    for family in json.loads(path.read_text(encoding='utf-8'))['families']:
        keys = [member['character_key'] for member in family['members']]
        known = roles.reindex(keys).dropna()
        rows.append({'family': family['family_key'], 'title': family['title'], 'champion_count': len(keys),
                     'champions': ', '.join(sorted(member['character'] for member in family['members'])),
                     **dict(zip(ROLE_COLUMNS, known.mean().to_numpy() if len(known) else [np.nan] * len(ROLE_COLUMNS)))})
    return pd.DataFrame(rows).set_index('family')
