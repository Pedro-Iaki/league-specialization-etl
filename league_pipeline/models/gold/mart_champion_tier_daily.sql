{{ config(
    materialized='incremental',
    file_format='delta',
    incremental_strategy='merge',
    unique_key='tier_champion_date_id',
    on_schema_change='append_new_columns',
    full_refresh=false
) }}

{% set expert_threshold = var('expert_mastery_threshold', 100000) %}

-- Renamed from mart_champion_analysis, and now actually carries the date its
-- surrogate key was already built on. The old model hashed as_of_date into
-- tier_champion_date_id but never selected it, so the table accumulated one
-- opaque row set per day with no way to slice by day, order by day, or plot a
-- trend - which was the entire point of keying it that way.
--
-- Grain: one row per (tier, champion, as_of_date). Every tier with at least one
-- player is crossed with every champion in dim_champions, so champions nobody
-- plays in a tier still appear (play_rate = 0, mastery columns null).
--
-- Rates are fractions in [0, 1].
--
-- Two different champion populations are used on purpose:
--   * active pool (fct_players_champion_activity.is_active):
--       play_rate, specialization_bias, avg_lp_per_game
--   * anyone with mastery on the champion (fct_masteries_current):
--       expert_population, avg_mastery, median_mastery
--
-- LP rates now come from fct_players_rank_recent_form (whole trailing window)
-- instead of fct_players_rank_last_delta (latest snapshot, only if it moved).
-- The old denominator quietly excluded anyone whose most recent observation
-- contained no games, which biased the metric toward bursty players.
-- avg_lp_per_game_lift is the champion's rate minus its own tier's baseline,
-- which is what you want for cross-tier comparison: +0.4 LP/game in IRON and
-- +0.4 LP/game in DIAMOND mean the same thing, while raw rates do not.

with players as (

    select
        puuid as player_id,
        queue,
        tier,
        patch
    from {{ ref('dim_players_current') }}
    where tier is not null

),

as_of as (

    select max(as_of_date) as as_of_date
    from {{ ref('fct_players_champion_activity') }}

),

active_pool_players as (

    select distinct player_id
    from {{ ref('fct_players_champion_activity') }}
    where is_active
      and recent_total_points > 0

),

-- Per-tier denominators. play_rate divides by players who actually have an
-- active pool, so players with an empty pool (new / inactive) don't deflate it.
tier_population as (

    select
        p.tier,
        count(distinct p.player_id) as tier_player_count,
        count(distinct ap.player_id) as active_pool_player_count
    from players p
    left join active_pool_players ap
        on p.player_id = ap.player_id
    group by p.tier

),

-- Modal patch per tier. Not max(), because patch strings sort badly:
-- '15.9' > '15.10' lexically.
tier_patch as (

    select tier, patch
    from (
        select tier, patch, count(*) as patch_player_count
        from players
        where patch is not null
        group by tier, patch
    )
    qualify row_number() over (
        partition by tier
        order by patch_player_count desc, patch desc
    ) = 1

),

player_form as (

    select
        player_id,
        queue,
        lp_per_game,
        lp_per_day,
        win_rate
    from {{ ref('fct_players_rank_recent_form') }}
    where games > 0

),

tier_baseline as (

    select
        p.tier,
        count(f.lp_per_game) as tier_form_player_count,
        avg(f.lp_per_game) as tier_avg_lp_per_game,
        percentile(f.lp_per_game, 0.5) as tier_median_lp_per_game,
        avg(f.win_rate) as tier_avg_win_rate
    from players p
    join player_form f
        on p.player_id = f.player_id
        and p.queue = f.queue
    group by p.tier

),

-- One row per (tier, champion) over players with the champion in their active
-- pool. Each player counts once per champion, so a player with 5 active
-- champions contributes once to each of those 5 champions' averages.
active_metrics as (

    select
        p.tier,
        cast(a.champion_key as string) as champion_key,
        count(distinct a.player_id) as active_player_count,
        -- avg() skips nulls (recent_pct_of_total is null when the player's
        -- recent_total_points = 0), so those players don't drag it toward zero
        avg(a.recent_pct_of_total) as specialization_bias,
        avg(f.lp_per_game) as avg_lp_per_game,
        avg(f.lp_per_day) as avg_lp_per_day,
        avg(f.win_rate) as avg_win_rate,
        count(f.lp_per_game) as form_player_count
    from {{ ref('fct_players_champion_activity') }} a
    inner join players p
        on a.player_id = p.player_id
    left join player_form f
        on p.player_id = f.player_id
        and p.queue = f.queue
    where a.is_active and a.recent_total_points > 0
    group by p.tier, cast(a.champion_key as string)

),

-- One row per (tier, champion) over every player in the tier with mastery on it.
mastery_metrics as (

    select
        p.tier,
        cast(m.champion_key as string) as champion_key,
        count(*) as mastery_player_count,
        sum(case when m.champion_points > {{ expert_threshold }} then 1 else 0 end) as expert_player_count,
        avg(m.champion_points) as avg_mastery,
        percentile(m.champion_points, 0.5) as median_mastery
    from {{ ref('fct_masteries_current') }} m
    inner join players p
        on m.puuid = p.player_id
    group by p.tier, cast(m.champion_key as string)

)

select
    {{ dbt_utils.generate_surrogate_key(['t.tier', 'c.key', 'ao.as_of_date']) }} as tier_champion_date_id,

    ao.as_of_date,
    tp.patch,
    t.tier,
    {{ tier_order('t.tier') }} as tier_order,
    c.key as champion_key,
    c.name as champion_name,

    -- sample sizes, so thin rows (e.g. Challenger) can be discounted
    t.tier_player_count,
    t.active_pool_player_count,
    coalesce(a.active_player_count, 0) as active_player_count,
    coalesce(a.form_player_count, 0) as form_player_count,
    coalesce(m.mastery_player_count, 0) as mastery_player_count,
    coalesce(m.expert_player_count, 0) as expert_player_count,

    -- active-pool metrics
    {{ dbt_utils.safe_divide('coalesce(a.active_player_count, 0)', 't.active_pool_player_count') }} as play_rate,
    a.specialization_bias,
    a.avg_lp_per_game,
    a.avg_lp_per_day,
    a.avg_win_rate,

    -- tier baselines and lifts
    b.tier_form_player_count,
    b.tier_avg_lp_per_game,
    b.tier_median_lp_per_game,
    b.tier_avg_win_rate,
    a.avg_lp_per_game - b.tier_avg_lp_per_game as avg_lp_per_game_lift,
    a.avg_win_rate - b.tier_avg_win_rate as avg_win_rate_lift,

    -- mastery metrics
    {{ dbt_utils.safe_divide('m.expert_player_count', 'm.mastery_player_count') }} as expert_population,
    m.avg_mastery,
    m.median_mastery

from tier_population t
cross join as_of ao
cross join {{ ref('dim_champions') }} c
left join tier_patch tp
    on t.tier = tp.tier
left join tier_baseline b
    on t.tier = b.tier
left join active_metrics a
    on t.tier = a.tier
    and cast(c.key as string) = a.champion_key
left join mastery_metrics m
    on t.tier = m.tier
    and cast(c.key as string) = m.champion_key

where t.active_pool_player_count > 0
