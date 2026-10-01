{{ config(materialized='table', file_format='delta') }}

{% set max_favoured = var('favoured_champion_max_count', 10) %}
{% set gap_multiplier = var('favoured_champion_gap_multiplier', 1.5) %}
{% set min_log_gap = var('favoured_champion_min_log_gap', 0.69314718056) %}

with champion_points as (

    select
        r.rank_period_id,
        d.champion_key,
        max(d.champion_name) as champion_name,
        sum(d.points_delta) as points_gained
    from {{ ref('fct_players_rank_periods') }} r
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

)

select
    s.rank_period_id,
    s.champion_key,
    s.champion_name,
    s.points_gained,
    s.champion_share,
    s.points_rank,
    b.favoured_champion_count,
    b.favoured_log_gap,
    s.points_rank <= b.favoured_champion_count as is_favoured
from shares s
inner join favoured_boundaries b on s.rank_period_id = b.rank_period_id
