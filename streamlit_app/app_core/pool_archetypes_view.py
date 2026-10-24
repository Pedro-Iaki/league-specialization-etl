"""Pool archetype laboratory: soft family-affinity archetypes with post-hoc profiling and inspection."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from app_core import pool_archetypes
from app_core.families import VECTORS_DIR
from app_core.pool_archetypes import (
    KINDS,
    ROLE_COLUMNS,
    ArchetypeSettings,
    assign_archetypes,
    champion_families,
    concentration_bands,
    design_matrix,
    eligible_mask,
    family_weights,
    fit_archetypes,
    group_prevalence,
    inspect_families,
    kmeans_agreement,
    load_family_definitions,
    load_pool_features,
    load_pool_presence,
    pair_lift,
    pool_size_bands,
    profile_archetypes,
    profile_similarity,
    sweep_components,
    tier_prevalence,
)
from app_core.population import ALL_TIERS, WEIGHT
from app_core.ui import setup_page

ALL_PLAYERS = 'All eligible players'
EVEN_ROLE_SHARE = 1 / len(ROLE_COLUMNS)
PERCENT = st.column_config.NumberColumn(format='percent')


@st.cache_data(show_spinner=False)
def _features(modified: tuple[int, int]):
    return load_pool_features()


@st.cache_data(show_spinner=False)
def _definitions(modified: tuple[int, int]):
    return load_family_definitions()


@st.cache_data(show_spinner='Fitting archetypes')
def _fit(modified: tuple[int, int], settings: ArchetypeSettings):
    frame, families = _features(modified)
    data = frame[eligible_mask(frame, families, settings.minimum_pool)]
    matrix = design_matrix(data, families, settings.include_concentration, settings.concentration_weight)
    loadings, profiles, error = fit_archetypes(matrix, settings, len(families))
    assignment = assign_archetypes(loadings, settings.active_loading)
    weighted = matrix * family_weights(matrix, settings.family_weighting, len(families))
    agreement = kmeans_agreement(weighted, assignment.archetype.to_numpy(), settings.components, settings.seed)
    return data, matrix, profiles, assignment, error, agreement


@st.cache_data(show_spinner='Sweeping component counts')
def _sweep(modified: tuple[int, int], settings: ArchetypeSettings, candidates: tuple[int, ...]):
    frame, families = _features(modified)
    data = frame[eligible_mask(frame, families, settings.minimum_pool)]
    matrix = design_matrix(data, families, settings.include_concentration, settings.concentration_weight)
    weighted = matrix * family_weights(matrix, settings.family_weighting, len(families))
    return sweep_components(weighted, list(candidates), settings.sparsity, settings.seed)


@st.cache_data(show_spinner=False)
def _presence(modified: tuple[int, int]):
    return load_pool_presence()


def _render_diffuse(modified, data: pd.DataFrame, families: list[str], names: list[str], assigned: pd.DataFrame,
                    titles: dict[str, str]) -> None:
    """Show what Diffuse players have in common: affinity spread, family pairs, champions and champion pairs."""
    diffuse = (assigned.kind == 'Diffuse').to_numpy()
    st.markdown('#### Diffuse players')
    if diffuse.sum() < 30 or (~diffuse).sum() < 30:
        st.info('Too few Diffuse or clearly-expressing players to compare at these settings.')
        return
    left, right = st.columns(2)
    threshold = left.slider('Family counts as held at affinity', 0.05, 0.5, 0.1, 0.05, key='pa_diffuse_threshold',
                            help='Low by default: Diffuse players spread thin affinity, so a high bar hides their families.')
    minimum = right.slider('Minimum Diffuse players per combination', 10, 200, 30, 10, key='pa_diffuse_min')
    held = data[families] >= threshold
    columns = st.columns(4)
    columns[0].metric('Diffuse players', f'{int(diffuse.sum()):,}')
    columns[1].metric('Median pool size', f'{data.pool_size[diffuse].median():.0f}',
                      delta=f'{data.pool_size[diffuse].median() - data.pool_size[~diffuse].median():+.0f} vs others', delta_color='off')
    columns[2].metric('Median families held', f'{held[diffuse].sum(axis=1).median():.0f}',
                      delta=f'{held[diffuse].sum(axis=1).median() - held[~diffuse].sum(axis=1).median():+.0f} vs others', delta_color='off')
    columns[3].metric('Median top affinity', f'{data[families].max(axis=1)[diffuse].median():.2f}',
                      delta=f'{data[families].max(axis=1)[diffuse].median() - data[families].max(axis=1)[~diffuse].median():+.2f} vs others', delta_color='off')

    by_archetype = data[families][diffuse].groupby(assigned.archetype.to_numpy()[diffuse]).mean()
    by_archetype.index = [names[index] for index in by_archetype.index]
    figure = px.imshow(by_archetype.T, aspect='auto', color_continuous_scale='Viridis', height=720,
                       title='Mean family affinity of Diffuse players, by their best-matching archetype',
                       labels={'x': 'Best-matching archetype', 'y': 'Family', 'color': 'Mean affinity'})
    figure.update_yaxes(dtick=1)
    st.plotly_chart(figure, width='stretch')
    st.caption('Each column is the Diffuse players whose weak best match is that archetype. Compare it with the same '
               'archetype\'s profile above: a flat column means the pool covers many families a little.')

    spread = pd.DataFrame({'Diffuse': data[families][diffuse].mean(), 'Clear': data[families][~diffuse].mean()})
    relative = (spread.Diffuse / spread.Clear).rename('Diffuse vs clear').rename_axis('family').reset_index()
    relative['label'] = relative.family.map(lambda family: f'{family} {titles.get(family, "").split(":")[-1].strip()}')
    chart = px.bar(relative.sort_values('Diffuse vs clear'), x='Diffuse vs clear', y='label', orientation='h', height=720,
                   title='Mean affinity of Diffuse players relative to clearly-expressing players')
    chart.add_vline(x=1, line_color='#9aabc0')
    st.plotly_chart(chart, width='stretch')
    st.caption('Above 1 means Diffuse players hold that family more strongly than the others on average; below 1, less.')

    st.markdown('##### Family combinations')
    family_pairs = pair_lift(held, diffuse, minimum)
    st.dataframe(family_pairs.head(30), hide_index=True, width='stretch',
                 column_config={'inside_share': PERCENT, 'outside_share': PERCENT, 'excess': PERCENT,
                                'lift': st.column_config.NumberColumn(format='%.1f×')})
    st.caption('Share of Diffuse players holding both families, against the share of the other players. Excess is the '
               'difference; lift is the ratio. Sorted by excess so common combinations rank above rare ones.')

    presence, champion_names = _presence(modified)
    flags = presence.loc[data.index].rename(columns=champion_names)
    owners = {champion_names[key]: families_of for key, families_of in champion_families().items() if key in champion_names}
    st.markdown('##### Champions and champion combinations')
    champions = group_prevalence(flags, diffuse)
    champions = champions[champions.players >= minimum].sort_values('lift', ascending=False)
    champions['families'] = [', '.join(sorted(owners.get(name, ()))) for name in champions.index]
    pairs = pair_lift(flags, diffuse, minimum, owners)
    pairs['bridges families'] = pairs.shared == ''
    left, right = st.columns(2)
    left.markdown('Champions held more often by Diffuse players')
    left.dataframe(champions.head(30).rename_axis('champion').reset_index(), hide_index=True, width='stretch',
                   column_config={'inside_reach': PERCENT, 'outside_reach': PERCENT,
                                  'lift': st.column_config.NumberColumn(format='%.1f×')})
    right.markdown('Champion pairs most over-represented in Diffuse pools')
    right.dataframe(pairs.head(30), hide_index=True, width='stretch',
                    column_config={'inside_share': PERCENT, 'outside_share': PERCENT, 'excess': PERCENT,
                                   'lift': st.column_config.NumberColumn(format='%.1f×')})
    top = pairs.head(50)
    st.caption(f'{top["bridges families"].mean():.0%} of the 50 most over-represented pairs share no family, so these '
               'players combine champions from different families instead of deepening one. "shared" lists the families '
               'both champions belong to. Observed players; presence in the active pool, not mastery.')


def render_pool_archetypes() -> None:
    setup_page('Pool archetypes')
    st.subheader('Pool archetypes')
    st.write('Soft archetypes from overlapping family affinity: each player is a non-negative mixture of archetypes. '
             'Roles are never features; role mix is descriptive, taken from each champion\'s observed role shares. '
             'Concentration and pool size describe the result unless enabled as features.')
    try:
        # The module's own timestamp invalidates cached fits when the method changes under a running server.
        modified = ((VECTORS_DIR / 'vectors.parquet').stat().st_mtime_ns, Path(pool_archetypes.__file__).stat().st_mtime_ns)
        frame, families = _features(modified)
        definitions = _definitions(modified)
    except (ValueError, OSError, KeyError) as error:
        st.error(str(error))
        return
    titles = definitions.title.to_dict()

    left, middle, right = st.columns(3)
    components = left.slider('Archetypes', 2, 20, 6, key='pa_components')
    minimum_pool = middle.slider('Minimum pool size', 1, 20, 3, key='pa_min_pool',
                                 help='Small pools give extreme, noisy affinities.')
    sparsity = right.slider('Loading sparsity (L1)', 0.0, 1.0, 0.0, 0.05, key='pa_sparsity',
                            help='Higher values push players toward fewer archetypes.')
    left, middle, right = st.columns(3)
    weighting = left.slider('Rare-family weighting', 0.0, 2.0, 0.0, 0.25, key='pa_weighting',
                            help='Scales each family by log(1 / mean affinity) to this power before fitting, so common '
                                 'families stop dominating. Zero fits the raw affinities. Profiles are shown in plain affinity.')
    active = middle.slider('Active archetype loading', 0.1, 0.9, 0.25, 0.05, key='pa_active',
                           help='A player expresses an archetype when its loading (affinity scale, 0-1) reaches this value. '
                                'Single: one archetype. Blend: two or more. Diffuse: none.')
    include = right.checkbox('Use champion concentration as features', False, key='pa_include',
                             help='Adds top-champion share and normalized entropy, scaled to 0-1, to the affinity matrix.')
    weight = right.slider('Concentration weight', 0.05, 1.0, 0.4, 0.05, key='pa_weight', disabled=not include)
    settings = ArchetypeSettings(components, sparsity, include, weight, minimum_pool, active, weighting)
    calibrated = st.toggle('Tier-calibrated shares, medians and means', True, key='pa_calibrated',
                           help='Reweights collected players to the frozen rank-population reference. Archetypes are '
                                'always fitted on the collected players; weights only change how they are described.')

    eligible = eligible_mask(frame, families, minimum_pool)
    st.caption(f'{int(eligible.sum()):,} of {len(frame):,} profiles are used; {int((frame.pool_size == 0).sum()):,} have no '
               f'active pool and {int(((frame.pool_size > 0) & (frame.pool_size < minimum_pool)).sum()):,} fall below the '
               'minimum pool.')
    if not eligible.any():
        st.info('No profiles meet the minimum pool size.')
        return

    fitted, matrix, profiles, assignment, error, agreement = _fit(modified, settings)
    names = [f'A{index + 1}' for index in range(components)]
    supported = fitted[WEIGHT].notna() if calibrated else pd.Series(True, index=fitted.index)
    data = fitted[supported]
    assigned = assignment[supported.to_numpy()].reset_index(drop=True)
    weights = data[WEIGHT] if calibrated else pd.Series(1.0, index=data.index)
    summary = profile_archetypes(data, families, profiles, assigned, titles, weights)
    summary.index = names
    if calibrated:
        st.caption('Shares and medians are tier-calibrated to the frozen reference population, conditional on players '
                   f'with an eligible pool; {len(fitted) - len(data):,} players in unsupported tiers are excluded. '
                   'Eligibility itself varies by tier, so these are estimates, not population prevalence.')
    else:
        st.caption('Unweighted collected snapshot: higher tiers are over-represented relative to the player population.')

    heat = pd.DataFrame(profiles[:, :len(families)].T, index=families, columns=names)
    figure = px.imshow(heat, zmin=0, zmax=1, aspect='auto', color_continuous_scale='Viridis',
                       title='Archetype profile: relative affinity to each family', height=720)
    figure.update_yaxes(dtick=1)
    st.plotly_chart(figure, width='stretch')

    columns = st.columns(5)
    columns[0].metric('Reconstruction error (KL)', f'{error / len(fitted):.4f}', help='Per player; compare across settings.')
    columns[1].metric('k-means agreement (ARI)', f'{agreement:.2f}',
                      help='Adjusted Rand index between dominant archetype and k-means on the same matrix.')
    columns[2].metric('Blend players', f'{summary.blend_share.mul(summary.share).sum():.0%}',
                      help='Two or more archetypes reach the active loading.')
    columns[3].metric('Diffuse players', f'{summary.diffuse_share.mul(summary.share).sum():.0%}',
                      help='No archetype reaches the active loading: a weak best match, not a mixture.')
    columns[4].metric('Smallest archetype', f'{summary.share.min():.1%}')

    st.markdown('#### Archetype profile')
    role_config = {role: PERCENT for role in ROLE_COLUMNS}
    kind_config = {f'{kind.lower()}_share': PERCENT for kind in KINDS}
    st.dataframe(summary.rename(columns={'median_top1_share': 'median top-champion share',
                                         'median_entropy': 'median normalized entropy',
                                         'median_strong_families': 'median families ≥ 0.5',
                                         'median_strength': 'median strength'}),
                 column_config={'share': PERCENT, **kind_config, **role_config,
                                'median strength': st.column_config.NumberColumn(format='%.2f')}, width='stretch')
    similarity = pd.DataFrame(profile_similarity(profiles[:, :len(families)]), index=names, columns=names)
    off_diagonal = similarity.to_numpy()[~np.eye(len(names), dtype=bool)]
    st.caption(f'Most similar pair of archetype profiles: cosine {off_diagonal.max():.2f}. Values near 1 mean two '
               'archetypes describe the same pools and should be merged by lowering the count.')
    with st.expander('Profile similarity between archetypes'):
        similarity_chart = px.imshow(similarity, zmin=0, zmax=1, text_auto='.2f', color_continuous_scale='Viridis',
                                     aspect='auto', title='Cosine similarity of archetype profiles')
        st.plotly_chart(similarity_chart, width='stretch')

    st.markdown('#### Does pool size drive the result?')
    bands = pool_size_bands(data.pool_size)
    band_labels = pd.Series(bands, name='Pool size band')
    kinds = pd.crosstab(band_labels, assigned.kind.to_numpy(), normalize='index')[list(KINDS)]
    mix = pd.crosstab(band_labels, assigned.archetype.map(dict(enumerate(names))).to_numpy(), normalize='index')
    left, right = st.columns(2)
    left.plotly_chart(px.bar(kinds, barmode='stack', title='Single / Blend / Diffuse by pool size',
                             labels={'value': 'Share of band', 'variable': 'Kind'}), width='stretch')
    right.plotly_chart(px.bar(mix, barmode='stack', title='Primary archetype by pool size',
                              labels={'value': 'Share of band', 'variable': 'Archetype'}), width='stretch')
    st.caption('Observed players, equal-count bands. Single/Blend/Diffuse use absolute loadings, so a large pool that '
               'spreads thin affinity is Diffuse, not a blend. If one archetype swells with pool size it is describing '
               'breadth instead of taste; compare it with the Diffuse share.')

    _render_diffuse(modified, data, families, names, assigned, titles)
    roles = summary[list(ROLE_COLUMNS)].sub(EVEN_ROLE_SHARE).rename_axis('Archetype')
    role_chart = px.bar(roles, barmode='group', labels={'value': 'Over / under an even 20% split', 'variable': 'Role'},
                        title='Mean inferred role of the champions in each archetype\'s pools, relative to 20%')
    role_chart.add_hline(y=0, line_color='#9aabc0')
    role_chart.update_yaxes(tickformat='+.0%')
    st.plotly_chart(role_chart, width='stretch')
    st.caption('Each player\'s pool role mix is the mastery-weighted mean of its champions\' observed role shares; '
               'the chart averages that over the archetype\'s players and subtracts 20%, the share each of the five '
               'roles would have under an even split. Bars above zero are over-represented roles. Champion roles come '
               'from observed play, not from these players\' own matches.')

    st.markdown('#### Inspect an archetype')
    choice = st.selectbox('Archetype', [ALL_PLAYERS, *names], key='pa_inspect',
                          format_func=lambda name: name if name == ALL_PLAYERS else
                          f'{name} · {summary.lead_family[name]} · {summary.share[name]:.1%}')
    threshold = st.slider('Minimum family affinity', 0.05, 1.0, 0.5, 0.05, key='pa_threshold',
                          help='A player counts toward a family only when their affinity reaches this value.')
    clear_only = st.checkbox('Only players who clearly express this archetype', False, key='pa_clear',
                             disabled=choice == ALL_PLAYERS,
                             help='Drops Diffuse players, whose best match is below the active loading.')
    if choice == ALL_PLAYERS:
        members, profile = np.ones(len(data), dtype=bool), None
    else:
        index = names.index(choice)
        members, profile = (assigned.archetype == index).to_numpy(), profiles[index, :len(families)]
        if clear_only:
            members = members & (assigned.kind != 'Diffuse').to_numpy()
    table = inspect_families(data, families, definitions, members, threshold, weights, profile)
    st.caption(f'{int(members.sum()):,} players. Reach is the share of this group whose affinity to the family reaches '
               f'{threshold:.2f}; median affinity is over those players only. Lift is reach divided by every eligible '
               'player\'s reach, so families that are rare overall can still stand out. Role columns are the mean '
               'observed role share of the family\'s champions.')
    st.dataframe(table.sort_values('reach', ascending=False),
                 column_config={'reach': PERCENT, 'all_players_reach': PERCENT,
                                'median_affinity': st.column_config.NumberColumn(format='%.2f'),
                                'lift': st.column_config.NumberColumn(format='%.1f×'),
                                'profile_weight': st.column_config.NumberColumn('profile weight', format='%.2f'),
                                'champions': st.column_config.TextColumn('champions', width='large'), **role_config},
                 hide_index=True, width='stretch', height=700, key=f'pa_families_{choice}_{threshold}_{clear_only}')

    if choice != ALL_PLAYERS:
        tiers = ALL_TIERS[:ALL_TIERS.index('DIAMOND') + 1]
        prevalence = tier_prevalence(data.tier, members, tiers)
        prevalence = prevalence.reindex([tier for tier in tiers if tier in prevalence.index]).reset_index()
        chart = px.bar(prevalence, x='tier', y='over_under', hover_data={'share_of_tier': ':.1%', 'players': True},
                       title=f'{choice}: share of each tier vs the Iron–Diamond average ({prevalence.baseline.iloc[0]:.1%})')
        chart.add_hline(y=0, line_color='#9aabc0')
        chart.update_yaxes(tickformat='+.1%', title='Over / under the average')
        st.plotly_chart(chart, width='stretch')
        st.caption('Observed players only. Master and above are left out because their few players would dominate '
                   'the scale; the average is taken over the tiers shown.')

    bands = pd.crosstab(pd.Series(assigned.archetype.map(dict(enumerate(names))).to_numpy(), name='Archetype'),
                        concentration_bands(data).to_numpy(), normalize='index')
    st.markdown('#### Champion concentration inside each archetype')
    st.plotly_chart(px.bar(bands[['Focused', 'Balanced', 'Broad']], barmode='stack', labels={'value': 'Share of archetype',
                    'variable': 'Entropy tertile'}), width='stretch')
    st.caption('Focused/Balanced/Broad are tertiles of normalized champion entropy across eligible players (observed). '
               'A spread across bands means family affinity and champion concentration are separate signals.')

    with st.expander('Choose the number of archetypes'):
        top = st.slider('Sweep up to', 4, 20, 10, key='pa_sweep_top')
        if st.button('Run sweep', key='pa_sweep_run'):
            st.session_state['pa_sweep_v2'] = _sweep(modified, settings, tuple(range(2, top + 1)))
        sweep = st.session_state.get('pa_sweep_v2')
        if sweep is not None:
            st.plotly_chart(px.line(sweep, x='components', y=['stability', 'worst_stability'], markers=True,
                                    title='Bootstrap stability (matched profile cosine)'), width='stretch')
            st.plotly_chart(px.line(sweep, x='components', y=['train_error', 'held_out_error'], markers=True,
                                    title='Reconstruction error per player: training vs held-out'), width='stretch')
            st.caption('Uses a 4,000-player sample (80% fitted, 20% held out) and four bootstrap resamples, on the same '
                       'family-weighted matrix. Prefer the largest count before stability drops and held-out error '
                       'flattens; a widening gap to training error means extra archetypes are memorizing players. '
                       'Confirm that archetypes remain interpretable and that the profile similarity stays low.')
