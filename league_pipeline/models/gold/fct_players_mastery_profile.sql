{{ config(materialized='table', file_format='delta') }}

{% set max_favoured = var('favoured_champion_max_count', 10) %}
{% set gap_multiplier = var('favoured_champion_gap_multiplier', 1.5) %}
{% set min_log_gap = var('favoured_champion_min_log_gap', 0.69314718056) %}

with as_of as (

    select max(snapshot_date) as as_of_date
    from {{ ref('dim_players_current') }}

),

mastery as (

    select
        m.puuid as player_id,
        m.champion_key,
        c.name as champion_name,
        m.champion_points,
        m.last_play_time
    from {{ ref('fct_masteries_current') }} m
    left join {{ ref('dim_champions') }} c on m.champion_key = c.key
    where m.champion_points > 0

),

shares as (

    select
        *,
        {{ dbt_utils.safe_divide('champion_points', 'sum(champion_points) over (partition by player_id)') }} as champion_share,
        row_number() over (
            partition by player_id
            order by champion_points desc, champion_key
        ) as points_rank
    from mastery

),

top_candidates as (

    select
        *,
        lead(champion_points) over (
            partition by player_id order by points_rank
        ) as next_champion_points
    from shares
    where points_rank <= {{ max_favoured }}

),

gaps as (

    select
        player_id,
        points_rank,
        ln(cast(champion_points as double) / next_champion_points) as log_gap
    from top_candidates
    where next_champion_points > 0

),

gap_medians as (

    select
        player_id,
        percentile(log_gap, 0.5) as median_log_gap
    from gaps
    group by player_id

),

largest_gaps as (

    select player_id, points_rank, log_gap
    from gaps
    qualify row_number() over (
        partition by player_id order by log_gap desc, points_rank
    ) = 1

),

top_counts as (

    select player_id, count(*) as top_champion_count
    from top_candidates
    group by player_id

),

favoured_boundaries as (

    select
        t.player_id,
        case
            when t.top_champion_count = 1 then 1
            when g.log_gap >= {{ min_log_gap }}
                and (
                    t.top_champion_count = 2
                    or coalesce(m.median_log_gap, 0) = 0
                    or g.log_gap >= {{ gap_multiplier }} * m.median_log_gap
                ) then g.points_rank
            else t.top_champion_count
        end as mastery_favoured_champion_count,
        g.log_gap as mastery_favoured_log_gap
    from top_counts t
    left join gap_medians m on t.player_id = m.player_id
    left join largest_gaps g on t.player_id = g.player_id

),

favoured_pools as (

    select
        b.player_id,
        b.mastery_favoured_champion_count,
        b.mastery_favoured_log_gap,
        least(greatest(sum(s.champion_share), 0.0), 1.0) as mastery_favoured_champions_share
    from favoured_boundaries b
    join shares s
        on b.player_id = s.player_id
        and s.points_rank <= b.mastery_favoured_champion_count
    group by
        b.player_id,
        b.mastery_favoured_champion_count,
        b.mastery_favoured_log_gap

),

concentration as (

    select
        player_id,
        count(*) as champions_with_mastery,
        sum(champion_points) as total_mastery_points,
        max(case when points_rank = 1 then champion_key end) as top_champion_key,
        max(case when points_rank = 1 then champion_name end) as top_champion_name,
        max(champion_share) as mastery_top1_share,
        sum(pow(champion_share, 2)) as mastery_hhi,
        -sum(case when champion_share > 0 then champion_share * log2(champion_share) end) as mastery_entropy,
        max(case when last_play_time > timestamp '2009-01-01' then last_play_time end) as last_play_time
    from shares
    group by player_id

),

profile_metrics as (

    select
        c.*,
        f.mastery_favoured_champion_count,
        f.mastery_favoured_champions_share,
        f.mastery_favoured_log_gap,
        case
            when c.champions_with_mastery <= 1 then 0
            else least(greatest(
                {{ dbt_utils.safe_divide('c.mastery_entropy', 'log2(c.champions_with_mastery)') }},
                0.0
            ), 1.0)
        end as mastery_normalized_entropy
    from concentration c
    left join favoured_pools f on c.player_id = f.player_id

),

scored as (

    select
        *,
        {{ playstyle_score('specialist', 'mastery_top1_share', 'mastery_favoured_champions_share', 'mastery_hhi', 'mastery_normalized_entropy', 'mastery_favoured_champion_count') }} as mastery_specialist_score,
        {{ playstyle_score('multispecialist', 'mastery_top1_share', 'mastery_favoured_champions_share', 'mastery_hhi', 'mastery_normalized_entropy', 'mastery_favoured_champion_count') }} as mastery_multispecialist_score,
        {{ playstyle_score('versatile', 'mastery_top1_share', 'mastery_favoured_champions_share', 'mastery_hhi', 'mastery_normalized_entropy', 'mastery_favoured_champion_count') }} as mastery_versatile_score,
        {{ playstyle_score('generalist', 'mastery_top1_share', 'mastery_favoured_champions_share', 'mastery_hhi', 'mastery_normalized_entropy', 'mastery_favoured_champion_count') }} as mastery_generalist_score
    from profile_metrics

),

labeled as (

    select
        *,
        case greatest(
            mastery_specialist_score,
            mastery_multispecialist_score,
            mastery_versatile_score,
            mastery_generalist_score
        )
            when mastery_specialist_score then 'specialist'
            when mastery_multispecialist_score then 'multispecialist'
            when mastery_versatile_score then 'versatile'
            else 'generalist'
        end as mastery_playstyle
    from scored

),

accrual as (

    select
        player_id,
        sum(points_delta) as tracked_points_gained,
        min(previous_snapshot_date) as first_accrual_date,
        max(snapshot_date) as last_accrual_date
    from {{ ref('fct_players_champion_delta_history') }}
    group by player_id

),

tracking as (

    select
        puuid as player_id,
        count(distinct snapshot_date) as snapshot_count,
        datediff(max(snapshot_date), min(snapshot_date)) as days_tracked
    from {{ ref('dim_players_history') }}
    group by puuid

)

select
    p.puuid as player_id,
    ao.as_of_date,
    coalesce(c.champions_with_mastery, 0) as champions_with_mastery,
    coalesce(c.total_mastery_points, 0) as total_mastery_points,
    c.top_champion_key,
    c.top_champion_name,
    c.mastery_top1_share,
    c.mastery_favoured_champion_count,
    c.mastery_favoured_champions_share,
    c.mastery_favoured_log_gap,
    c.mastery_hhi,
    c.mastery_entropy,
    c.mastery_normalized_entropy,
    c.mastery_specialist_score,
    c.mastery_multispecialist_score,
    c.mastery_versatile_score,
    c.mastery_generalist_score,
    c.mastery_playstyle,
    c.last_play_time,
    datediff(ao.as_of_date, c.last_play_time) as days_since_last_play,
    coalesce(t.days_tracked, 0) as days_tracked,
    coalesce(t.snapshot_count, 0) as snapshot_count,
    {{ dbt_utils.safe_divide(
        'a.tracked_points_gained',
        'datediff(a.last_accrual_date, a.first_accrual_date)'
    ) }} as mastery_points_per_day
from {{ ref('dim_players_current') }} p
cross join as_of ao
left join labeled c on p.puuid = c.player_id
left join accrual a on p.puuid = a.player_id
left join tracking t on p.puuid = t.player_id
