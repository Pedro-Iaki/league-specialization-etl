{{ config(materialized='table', file_format='delta') }}

-- One row per player in dim_players_current: lifetime mastery shape plus
-- observed accrual rate and recency.
--
-- Two different distributions live here and they answer different questions:
--   * mastery_* columns describe the player's LIFETIME champion_points
--     distribution (every champion they have ever touched). This is a
--     career-shape feature and moves very slowly.
--   * dim_players_active_pool carries the equivalent pool_* columns over
--     RECENT points on active champions only. That is the "what are they
--     playing now" feature and moves week to week.
-- A one-trick who has been grinding a second champion for a month will have a
-- high mastery_hhi and a low pool_hhi at the same time; that gap is signal, so
-- both are kept.
--
-- total_mastery_points is a lifetime stock that mostly accrued before tracking
-- began, so it must NOT be divided by days_tracked. mastery_points_per_day is
-- instead derived from the observed delta history, which only spans periods we
-- actually watched.

with as_of as (

    select max(as_of_date) as as_of_date
    from {{ ref('fct_players_champion_activity') }}

),

mastery as (

    select
        puuid as player_id,
        champion_key,
        champion_points,
        last_play_time
    from {{ ref('fct_masteries_current') }}

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

concentration as (

    select
        player_id,
        count(*) as champions_with_mastery,
        sum(champion_points) as total_mastery_points,
        max(case when points_rank = 1 then champion_key end) as top_champion_key,
        max(champion_share) as mastery_top1_share,
        sum(case when points_rank <= 3 then champion_share end) as mastery_top3_share,
        sum(pow(champion_share, 2)) as mastery_hhi,
        -sum(case when champion_share > 0 then champion_share * log2(champion_share) end) as mastery_entropy,
        -- never-played rows carry an epoch-ish last_play_time; same guard as
        -- dim_players_naive_role_distribution uses
        max(case when last_play_time > timestamp '2009-01-01' then last_play_time end) as last_play_time
    from shares
    group by player_id

),

accrual as (

    select
        player_id,
        sum(points_delta) as tracked_points_gained,
        count(distinct champion_key) as tracked_champion_count,
        min(previous_snapshot_date) as first_accrual_date,
        max(snapshot_date) as last_accrual_date
    from {{ ref('fct_players_champion_delta_history') }}
    group by player_id

),

tracking as (

    select
        puuid as player_id,
        min(snapshot_date) as first_snapshot_date,
        max(snapshot_date) as last_snapshot_date,
        count(distinct snapshot_date) as snapshot_count,
        datediff(max(snapshot_date), min(snapshot_date)) as days_tracked
    from {{ ref('dim_players_history') }}
    group by puuid

)

select
    p.puuid as player_id,
    ao.as_of_date,

    -- lifetime shape
    coalesce(c.champions_with_mastery, 0) as champions_with_mastery,
    coalesce(c.total_mastery_points, 0) as total_mastery_points,
    ln(1 + coalesce(c.total_mastery_points, 0)) as log_total_mastery,
    c.top_champion_key,
    c.mastery_top1_share,
    c.mastery_top3_share,
    c.mastery_hhi,
    c.mastery_entropy,
    case
        when c.mastery_entropy is null then null
        when c.champions_with_mastery <= 1 then 0
        else {{ dbt_utils.safe_divide('c.mastery_entropy', 'log2(c.champions_with_mastery)') }}
    end as mastery_normalized_entropy,

    -- recency
    c.last_play_time,
    datediff(ao.as_of_date, c.last_play_time) as days_since_last_play,

    -- how much of this player we have actually observed
    coalesce(t.days_tracked, 0) as days_tracked,
    coalesce(t.snapshot_count, 0) as snapshot_count,
    t.first_snapshot_date,
    t.last_snapshot_date,

    -- observed accrual
    coalesce(a.tracked_points_gained, 0) as tracked_points_gained,
    coalesce(a.tracked_champion_count, 0) as tracked_champion_count,
    datediff(a.last_accrual_date, a.first_accrual_date) as tracked_span_days,
    {{ dbt_utils.safe_divide(
        'a.tracked_points_gained',
        'datediff(a.last_accrual_date, a.first_accrual_date)'
    ) }} as mastery_points_per_day

from {{ ref('dim_players_current') }} p
cross join as_of ao
left join concentration c on p.puuid = c.player_id
left join accrual a on p.puuid = a.player_id
left join tracking t on p.puuid = t.player_id
