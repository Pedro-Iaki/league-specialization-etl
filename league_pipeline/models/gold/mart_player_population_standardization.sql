{{ config(materialized='view', tags=['population_weighting']) }}

-- Direct standardization of metric means, separately for each region/queue.
-- Selection is explicit; valid metric counts determine support independently.
-- Current-tier recent outcomes describe observed profiles, not all ranked players.
{% set cohorts = {
    'all_profiles': '1 = 1',
    'active_classified': "active_playstyle in ('specialist', 'multispecialist', 'versatile', 'generalist')",
    'alltime_classified': "alltime_playstyle in ('specialist', 'multispecialist', 'versatile', 'generalist')"
} %}
{% set metrics = ['total_mastery_points', 'rank_score', 'active_hhi', 'alltime_hhi',
                  'lp_per_game_recent', 'win_rate_recent'] %}

with profiles as (
    select * from {{ ref('mart_player_profile') }}
), scopes as (
    select distinct region, queue from profiles
), cohort_values as (
    {% for cohort, predicate in cohorts.items() %}
        {% for metric in metrics %}
    select region, queue, tier, '{{ cohort }}' as cohort, '{{ metric }}' as metric,
        cast({{ metric }} as double) as metric_value
    from profiles where {{ predicate }}
            {% if not loop.last %}union all{% endif %}
        {% endfor %}
        {% if not loop.last %}union all{% endif %}
    {% endfor %}
), cohort_metrics as (
    select region, queue, tier, cohort, metric,
        case when abs(metric_value) <= 1.7976931348623157e308 then metric_value end as metric_value
    from cohort_values
), definitions as (
    {% for cohort in cohorts %}
        {% for metric in metrics %}
    select '{{ cohort }}' as cohort, '{{ metric }}' as metric
            {% if not loop.last %}union all{% endif %}
        {% endfor %}
        {% if not loop.last %}union all{% endif %}
    {% endfor %}
), tier_metrics as (
    select region, queue, cohort, metric, tier,
        count(*) as selected_players,
        count(metric_value) as metric_players,
        avg(metric_value) as tier_mean
    from cohort_metrics
    group by region, queue, cohort, metric, tier
), tier_grid as (
    select s.region, s.queue, d.cohort, d.metric, r.tier,
        r.population_share, r.reference_version,
        r.recorded_on as reference_recorded_on, r.review_after as reference_review_after,
        coalesce(t.selected_players, 0) as selected_players,
        coalesce(t.metric_players, 0) as metric_players,
        t.tier_mean,
        case when coalesce(t.metric_players, 0) >= {{ var('population_min_tier_players', 5) }}
            then 1 else 0 end as tier_supported
    from scopes s
    cross join definitions d
    cross join {{ ref('rank_population_reference') }} r
    left join tier_metrics t
        on s.region <=> t.region and s.queue <=> t.queue
       and d.cohort = t.cohort and d.metric = t.metric and r.tier = t.tier
), covered as (
    select *,
        sum(case when tier_supported = 1 then population_share else 0 end)
            over (partition by region, queue, cohort, metric) as covered_population_share,
        sum(case when tier_supported = 1 then population_share * tier_mean else 0 end)
            over (partition by region, queue, cohort, metric) as standardized_numerator
    from tier_grid
)
select region, queue, cohort, metric, tier,
    selected_players, metric_players, tier_mean, tier_supported,
    {{ var('population_min_tier_players', 5) }} as minimum_tier_players,
    population_share as estimated_population_share,
    case when tier_supported = 1 then
        population_share / nullif(covered_population_share, 0)
    end as supported_target_share,
    covered_population_share,
    standardized_numerator / nullif(covered_population_share, 0) as standardized_mean,
    case when covered_population_share = 0 then 'no_supported_tiers'
         when covered_population_share < {{ var('population_min_coverage', 0.99) }} then 'low_coverage'
         else 'adequate_coverage' end as coverage_status,
    reference_version, reference_recorded_on, reference_review_after
from covered
