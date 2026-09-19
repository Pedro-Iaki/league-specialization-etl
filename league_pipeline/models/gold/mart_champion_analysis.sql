_{{ config(materialized='table', file_format='delta') }}

{% set expert_threshold = var('expert_mastery_threshold', 100000) %}

-- Grain: one row per (tier, champion). Every tier that has at least one
-- player is crossed with every champion in dim_champions, so champions nobody
-- in a tier plays still get a row (play_rate = 0, mastery columns null).
--
-- Tier is always the player's current tier (dim_players_current), so every
-- metric is bucketed the same way.
--
-- Two different champion populations are used on purpose:
--   * active pool (fct_players_champion_activity.is_active):
--       play_rate, specialization_bias, avg_lp_velocity
--   * anyone with mastery on the champion (fct_masteries_current):
--       expert_population, avg_mastery, median_mastery
--
-- All rates are fractions in [0, 1], same convention as the *_pct columns
-- elsewhere in gold. Multiply by 100 for display.

with players as (

    select
        puuid,
        queue,
        tier
    from {{ ref('dim_players_current') }}
    where tier is not null

),

-- Per-tier denominators. play_rate divides by players who actually have an
-- active pool, so players with an empty pool (new / inactive) don't deflate it.
tier_population as (

    select
        p.tier,
        count(distinct p.puuid) as tier_player_count,
        count(distinct case when ap.player_id is not null then p.puuid end) as active_pool_player_count
    from players p
    left join (
        select distinct player_id
        from {{ ref('fct_players_champion_activity') }}
        where is_active
    ) ap
        on p.puuid = ap.player_id
    group by p.tier

),

rank_velocity as (

    -- Note: fct_players_rank_last_delta drops snapshots where nothing moved,
    -- so avg_lp_velocity only reflects players who had movement.
    select
        puuid,
        queue,
        lp_velocity
    from {{ ref('fct_players_rank_last_delta') }}

),

-- One row per (tier, champion) over players with the champion in their active pool.
-- Each player counts once per champion, so a player with 5 active champions
-- contributes once to each of those 5 champions' averages.
active_metrics as (

    select
        p.tier,
        cast(a.champion_key as string) as champion_key,
        count(distinct a.player_id) as active_player_count,
        -- avg() skips nulls (recent_pct_of_total is null when the player's
        -- recent_total_points = 0), so those players don't drag it toward zero
        avg(a.recent_pct_of_total) as specialization_bias,
        avg(r.lp_velocity) as avg_lp_velocity
    from {{ ref('fct_players_champion_activity') }} a
    inner join players p
        on a.player_id = p.puuid
    left join rank_velocity r
        on p.puuid = r.puuid
        and p.queue = r.queue
    where a.is_active
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
        on m.puuid = p.puuid
    group by p.tier, cast(m.champion_key as string)

)

select
    {{ dbt_utils.generate_surrogate_key(['t.tier', 'c.key']) }} as tier_champion_id,

    t.tier,
    case t.tier
        when 'IRON' then 1
        when 'BRONZE' then 2
        when 'SILVER' then 3
        when 'GOLD' then 4
        when 'PLATINUM' then 5
        when 'EMERALD' then 6
        when 'DIAMOND' then 7
        when 'MASTER' then 8
        when 'GRANDMASTER' then 9
        when 'CHALLENGER' then 10
    end as tier_order,
    c.key as champion_key,
    c.name as champion_name,

    -- sample sizes, so thin rows (e.g. Challenger) can be discounted
    t.tier_player_count,
    t.active_pool_player_count,
    coalesce(a.active_player_count, 0) as active_player_count,
    coalesce(m.mastery_player_count, 0) as mastery_player_count,
    coalesce(m.expert_player_count, 0) as expert_player_count,

    -- active-pool metrics
    {{ dbt_utils.safe_divide('coalesce(a.active_player_count, 0)', 't.active_pool_player_count') }} as play_rate,
    a.specialization_bias,
    a.avg_lp_velocity,

    -- mastery metrics
    {{ dbt_utils.safe_divide('m.expert_player_count', 'm.mastery_player_count') }} as expert_population,
    m.avg_mastery,
    m.median_mastery

from tier_population t
cross join {{ ref('dim_champions') }} c
left join active_metrics a
    on t.tier = a.tier
    and cast(c.key as string) = a.champion_key
left join mastery_metrics m
    on t.tier = m.tier
    and cast(c.key as string) = m.champion_key