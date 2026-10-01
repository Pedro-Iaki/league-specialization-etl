{{ config(materialized='table', file_format='delta') }}

{% set max_favoured = var('favoured_champion_max_count', 10) %}
{% set gap_multiplier = var('favoured_champion_gap_multiplier', 1.5) %}
{% set min_log_gap = var('favoured_champion_min_log_gap', 0.69314718056) %}

with rank_periods as (

    select rank_period_id, player_id, previous_snapshot_date, snapshot_date
    from {{ ref('fct_players_rank_periods') }}

),

champion_points as (

    select
        r.rank_period_id,
        d.champion_key,
        max(d.champion_name) as champion_name,
        sum(d.points_delta) as points_gained
    from rank_periods r
    inner join {{ ref('fct_players_champion_delta_history') }} d
        on r.player_id = d.player_id
        and d.snapshot_date > r.previous_snapshot_date
        and d.snapshot_date <= r.snapshot_date
    where d.points_delta > 0
    group by r.rank_period_id, d.champion_key

),

shares as (

    select
        *,
        {{ dbt_utils.safe_divide(
            'points_gained',
            'sum(points_gained) over (partition by rank_period_id)'
        ) }} as champion_share,
        row_number() over (
            partition by rank_period_id
            order by points_gained desc, champion_key
        ) as points_rank
    from champion_points

),

top_candidates as (

    select
        *,
        lead(points_gained) over (
            partition by rank_period_id order by points_rank
        ) as next_champion_points
    from shares
    where points_rank <= {{ max_favoured }}

),

gaps as (

    select
        rank_period_id,
        points_rank,
        ln(cast(points_gained as double) / next_champion_points) as log_gap
    from top_candidates
    where next_champion_points > 0

),

gap_summary as (

    select rank_period_id, percentile(log_gap, 0.5) as median_log_gap
    from gaps
    group by rank_period_id

),

largest_gap as (

    select rank_period_id, points_rank, log_gap
    from gaps
    qualify row_number() over (
        partition by rank_period_id
        order by log_gap desc, points_rank
    ) = 1

),

favoured_boundaries as (

    select
        t.rank_period_id,
        case
            when count(*) = 1 then 1
            when max(g.log_gap) >= {{ min_log_gap }}
                and (
                    count(*) = 2
                    or coalesce(max(s.median_log_gap), 0) = 0
                    or max(g.log_gap) >= {{ gap_multiplier }} * max(s.median_log_gap)
                ) then max(g.points_rank)
            else count(*)
        end as favoured_champion_count,
        max(g.log_gap) as favoured_log_gap
    from top_candidates t
    left join largest_gap g on t.rank_period_id = g.rank_period_id
    left join gap_summary s on t.rank_period_id = s.rank_period_id
    group by t.rank_period_id

),

pool_metrics as (

    select
        s.rank_period_id,
        count(*) as champion_count,
        sum(s.points_gained) as mastery_points_gained,
        max(case when s.points_rank = 1 then s.champion_key end) as primary_champion_key,
        max(case when s.points_rank = 1 then s.champion_name end) as primary_champion_name,
        max(case when s.points_rank = 1 then s.points_gained end) as primary_champion_points,
        max(s.champion_share) as top1_share,
        max(b.favoured_champion_count) as favoured_champion_count,
        least(greatest(sum(
            case when s.points_rank <= b.favoured_champion_count then s.champion_share else 0 end
        ), 0.0), 1.0) as favoured_champions_share,
        max(b.favoured_log_gap) as favoured_log_gap,
        sum(pow(s.champion_share, 2)) as hhi,
        -sum(s.champion_share * log2(s.champion_share)) as entropy
    from shares s
    inner join favoured_boundaries b on s.rank_period_id = b.rank_period_id
    group by s.rank_period_id

),

normalized as (

    select
        *,
        case
            when champion_count = 1 then 0
            else least(greatest(
                {{ dbt_utils.safe_divide('entropy', 'log2(champion_count)') }},
                0.0
            ), 1.0)
        end as normalized_entropy
    from pool_metrics

),

scored as (

    select
        *,
        {{ playstyle_score('specialist', 'top1_share', 'favoured_champions_share', 'hhi', 'normalized_entropy', 'favoured_champion_count') }} as specialist_score,
        {{ playstyle_score('multispecialist', 'top1_share', 'favoured_champions_share', 'hhi', 'normalized_entropy', 'favoured_champion_count') }} as multispecialist_score,
        {{ playstyle_score('versatile', 'top1_share', 'favoured_champions_share', 'hhi', 'normalized_entropy', 'favoured_champion_count') }} as versatile_score,
        {{ playstyle_score('generalist', 'top1_share', 'favoured_champions_share', 'hhi', 'normalized_entropy', 'favoured_champion_count') }} as generalist_score
    from normalized

)

select
    s.rank_period_id,
    s.champion_count,
    s.mastery_points_gained,
    s.primary_champion_key,
    s.primary_champion_name,
    s.primary_champion_points,
    s.top1_share,
    s.favoured_champion_count,
    s.favoured_champions_share,
    s.favoured_log_gap,
    s.hhi,
    s.entropy,
    s.normalized_entropy,
    s.specialist_score,
    s.multispecialist_score,
    s.versatile_score,
    s.generalist_score,
    case greatest(
        s.specialist_score,
        s.multispecialist_score,
        s.versatile_score,
        s.generalist_score
    )
        when s.specialist_score then 'specialist'
        when s.multispecialist_score then 'multispecialist'
        when s.versatile_score then 'versatile'
        when s.generalist_score then 'generalist'
    end as playstyle
from scored s
