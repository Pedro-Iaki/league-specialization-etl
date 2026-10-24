"""Engineering decisions, inspectable evidence and limits of the guided audience story."""
from __future__ import annotations

from html import escape

import pandas as pd

from app_core.audience_segments import rank_context
from app_core.audience_story import PAGE_CSS, story_segments
from app_core.data import load_manifest
from app_core.i18n import st, t, terminology_selector
from app_core.story import REPOSITORY, resource_links, story_card, story_footer, story_prose, story_section, story_start

DECISIONS = [
    (
        'Collection: spend requests on dated coverage',
        'Riot API limits make collection selective. A Python coordinator allocates discovery and refresh work; SQLite records local tasks while shared coordination tracks freshness and claims.',
        'The repository contains configuration validation, task transitions and isolated failure-path tests. Those checks do not demonstrate live recovery or eliminate collection bias.',
        'docs/wiki/architecture.md',
    ),
    (
        'History: keep observations and outcomes at their own grains',
        'Bronze resolves repeated source observations, Silver retains history and current state, and Gold derives profiles and eligible periods. A current profile is different from a measured period outcome.',
        'Profile, purchase-window and retained-snapshot dates remain separate in serving metadata. The oldest retained positive-mastery play marker is a history lower bound, not an account creation date.',
        'docs/reference/data-models.md',
    ),
    (
        'Families: preserve overlap without ambiguous reporting totals',
        'Use lifetime mastery restricted to model-active membership. Each qualifying character contributes fully to every containing family; all active mastery remains in the denominator. A unique maximum supplies the primary label; ties remain Shared top.',
        'The definition fixes 25 families and 173 characters. Scoring and loader checks cover cutoff, ties, null evidence, coordinate order and definition hashes. Affinity coordinates can sum above one; exclusive primary categories support additive customer reporting.',
        'docs/reference/character-family-cohort.md',
    ),
    (
        'Comparisons: freeze bands and weights before filtering',
        'Behavioral audience views calibrate individual rank tiers to the saved NA solo/duo reference, then preserve those weights and fixed ranges. Each map labels its own joint, conditional or scored-pool denominator.',
        'Checks reconcile conditional totals, axis inversion, sparse-cell masks and scoring coverage. The saved OP.GG values are dated historical inputs; unsupported tiers and within-tier selection bias remain limitations.',
        'docs/reference/audience-segments.md',
    ),
    (
        'Identity: associate privately, then serve anonymous rows',
        'Family vectors are calculated while real player keys are available. The frozen business cohort is associated by player and queue before identifiers are removed. Streamlit reads local snapshots and needs no warehouse credentials.',
        'The manifest pins enriched profile and business hashes, metric metadata, source dates and scenario identity. Validation rejects incompatible files and operational identifiers. Anonymous row order is never a cross-file join key.',
        'docs/guides/refresh-dashboard-data.md',
    ),
    (
        'Money: keep simulation and cash semantics explicit',
        'Preserve the seeded transaction scenario and count fiat USD once. Nonbuyers stay in purchaser-share denominators; exclusive family labels partition cash. Customer reporting uses scenario rows rather than gameplay population weights.',
        'Integer-cent totals and purchaser counts reconcile to the preserved scenario. Generator assumptions create related spending patterns. Later audience observations do not establish purchase-date preferences, real demand or causal effects.',
        'docs/wiki/simulated-transactions.md',
    ),
]


def findings_page() -> None:
    terminology_selector()
    players = story_start(
        6, 'Inspect the decisions behind the audience.',
        'The dashboard connects observed behavior, versioned audience definitions and a synthetic customer demonstration. Its engineering keeps identities, dates, denominators and evidence limits inspectable.',
    )
    st.markdown(PAGE_CSS, unsafe_allow_html=True)
    story_section('01 · A traceable delivery', 'From observations to a reproducible local view')
    stages = [
        ('API and task state', 'Dated observations, request budgets and explicit delivery state.'),
        ('Bronze, Silver and Gold', 'Source resolution, retained history, current profiles and eligible periods.'),
        ('Private audience export', 'Versioned family scores and real-key customer association before anonymization.'),
        ('Local reporting', 'Manifest-checked Parquet, fixed audience ranges and explicit synthetic customer charts.'),
    ]
    items = ''.join(f'<li><strong>{escape(t(title))}</strong><span>{escape(t(body))}</span></li>' for title, body in stages)
    st.markdown(f'<ol class="audience-flow">{items}</ol>', unsafe_allow_html=True)
    story_prose('Activity, recorded ranked volume and rank describe different audience dimensions. Family interests add recognizable content context; inferred type complements them. The customer chapter shows how the same definitions can organize reporting questions.')
    story_section('02 · Decisions and checks', 'Open the boundary you want to inspect')
    for title, decision, evidence, document in DECISIONS:
        with st.expander(title):
            st.markdown(decision)
            st.caption(evidence)
            st.link_button('Read the maintained contract', f'{REPOSITORY}/blob/main/{document}')
    story_section('03 · Reading limits', 'Coverage and meaning remain part of the result')
    prepared = story_segments(players)
    if prepared is not None:
        base, reference = prepared
        context = rank_context(reference)
        total = base.population_weight.sum()
        scored = base.loc[base.family_state.isin(['primary', 'shared_top']), 'population_weight'].sum() / total
        typed = base.loc[base.character_type.ne('Unavailable'), 'population_weight'].sum() / total
        left, right = st.columns(2)
        with left:
            story_card('Rank coverage', 'Adjustment has a boundary', t(
                'Observed tiers cover {p0} of the saved reference; {p1} is unsupported and {p2} has sparse individual-tier support. Calibration does not correct selection within a tier or turn cross-sections into climbing trajectories.',
                p0=f'{context.supported_share.sum():.2%}', p1=f'{context.unsupported_share.sum():.2%}', p2=f'{context.sparse_tier_share.sum():.2%}'))
        with right:
            story_card('Trait coverage', 'Unavailable evidence stays visible', t(
                'Scored family pools cover {p0} of the adjusted audience; known inferred type covers {p1}. Tied, empty and unavailable states remain explicit. A current interest proxy is not a recent match-share measure or an independent psychological persona.',
                p0=f'{scored:.1%}', p1=f'{typed:.1%}'))
    story_prose('Activity-based hour equivalents use an illustrative points-to-time conversion. Retained play timestamps are not verified account tenure. Synthetic purchase differences demonstrate reporting structure; actual demand, intervention effects and rank progression need different evidence.')
    with st.expander('Snapshot dates and verification scope'):
        manifest = load_manifest()
        inventory = []
        for name, item in manifest.get('datasets', {}).items():
            inventory.append({'Dataset': name, 'Rows': item['rows'],
                              'As-of cutoff': item.get('max_as_of_date', 'Not recorded'),
                              'Latest retained snapshot': item.get('max_snapshot_date', 'Not recorded')})
        st.dataframe(pd.DataFrame(inventory), hide_index=True, width='stretch')
        st.caption(t('Export recorded: {p0}. Export time does not make older observations current. Retained analytical datasets keep their original dates.', p0=manifest.get('exported_at_utc', t('Not recorded'))))
        st.markdown('Checks cover family scoring, ties and missing states, schema/privacy contracts, map denominators, synthetic cash reconciliation and actual browser controls. They verify the implementation and frozen files; they do not establish independent family validity, realistic customer behavior, live recovery or hosted availability.')
        st.markdown('The observed behavioral audience and the frozen customer cohort are different scopes. Current audience traits and older synthetic purchases have separate dates. Competitive-growth extracts remain available through the explorers; they do not establish a general benefit from specialization.')
        st.link_button('Review dated validation evidence', f'{REPOSITORY}/blob/main/docs/reference/validation-and-evidence.md')
    story_prose('The result is an inspectable audience definition and a working reporting path. Use the explorers for a narrower question, or return to the start to follow the argument again.', css='story-prose story-note')
    resource_links(contact=True)
    story_footer(6, 'pages/1_Overall_Analysis.py', 'Open the data explorers')
