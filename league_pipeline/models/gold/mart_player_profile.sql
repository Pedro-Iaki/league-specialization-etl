{{ config(materialized='table', file_format='delta') }}

{% set flex_threshold = var('flex_main_role_threshold', 0.5) %}

-- Grain: one row per player in dim_players_current. This is the wide feature
-- table - one row in, one row out, no filtering - so a model trained on it can
-- be scored on it without a join. Every player present upstream survives;
-- features that cannot be computed are null rather than zero, so an imputer
-- downstream can tell "no data" from "genuinely zero".
--
-- Feature families:
--   ladder      tier / division / absolute_lp / rank_state_order
--   outcomes    lifetime win rate, trailing-window win rate and LP rates
--   role        points-weighted lane mix, purity, flex flag
--   pool        active champion count and concentration (current behaviour)
--   mastery     lifetime totals, concentration, accrual rate, recency
--
-- Nothing here is a leak-free target by construction - lp_per_day and
-- win_rate_recent are computed from the same trailing window you would
-- probably want to predict. Pick a target and drop its window-mates before
-- fitting.

with as_of as (

    select max(as_of_date) as as_of_date
    from {{ ref('fct_players_champion_activity') }}

),

naive_roles as (

    select
        player_id,
        primary_roles,
        size(primary_roles) as primary_role_count,
        champions_sampled_count
    from {{ ref('dim_players_naive_role_distribution') }}

)

select
    p.puuid as player_id,
    ao.as_of_date,
    p.snapshot_date,
    p.region,
    p.queue,
    p.patch,

    -- ladder position
    p.tier,
    {{ tier_order('p.tier') }} as tier_order,
    p.division,
    p.league_points,
    p.absolute_lp,
    {{ rank_state_order('p.tier', 'p.division') }} as rank_state_order,

    -- lifetime outcomes
    p.wins,
    p.losses,
    p.total_games,
    p.win_rate,

    -- trailing-window form (fixed denominator, see fct_players_rank_recent_form)
    f.window_days as form_window_days,
    f.games as games_recent,
    f.wins as wins_recent,
    f.losses as losses_recent,
    f.lp_delta as lp_delta_recent,
    f.win_rate as win_rate_recent,
    f.lp_per_game,
    f.lp_per_day,
    f.games_per_day,
    f.days_covered as form_days_covered,

    -- most recent single movement (kept for continuity with the older marts;
    -- prefer lp_per_game above, which is not conditioned on the last snapshot
    -- happening to contain games)
    d.lp_velocity as last_lp_velocity,
    d.lp_delta as last_lp_delta,
    d.movement_type as last_movement_type,
    d.snapshot_date as last_movement_date,

    -- role mix (points-weighted, inferred from champion metadata)
    pool.role_top_pct,
    pool.role_jungle_pct,
    pool.role_middle_pct,
    pool.role_bottom_pct,
    pool.role_support_pct,
    pool.role_purity,
    pool.main_role,
    pool.main_role_weight,
    (pool.main_role_weight < {{ flex_threshold }}) as is_flex,
    nr.primary_roles,
    nr.primary_role_count,
    nr.champions_sampled_count,

    -- active pool
    pool.is_active,
    pool.active_champion_count,
    pool.recent_champion_count,
    pool.recent_total_points,
    pool.pool_top1_share,
    pool.pool_top3_share,
    pool.pool_hhi,
    pool.pool_entropy,
    pool.pool_normalized_entropy,
    pool.active_champion_ids,

    -- lifetime mastery
    m.champions_with_mastery,
    m.total_mastery_points,
    m.log_total_mastery,
    m.top_champion_key,
    m.mastery_top1_share,
    m.mastery_top3_share,
    m.mastery_hhi,
    m.mastery_entropy,
    m.mastery_normalized_entropy,
    m.mastery_points_per_day,
    m.days_since_last_play,
    m.days_tracked,
    m.snapshot_count

from {{ ref('dim_players_current') }} p
cross join as_of ao
left join {{ ref('dim_players_active_pool') }} pool
    on p.puuid = pool.player_id
left join {{ ref('fct_players_mastery_profile') }} m
    on p.puuid = m.player_id
left join naive_roles nr
    on p.puuid = nr.player_id
left join {{ ref('fct_players_rank_recent_form') }} f
    on p.puuid = f.player_id
    and p.queue = f.queue
left join {{ ref('fct_players_rank_last_delta') }} d
    on p.puuid = d.player_id
    and p.queue = d.queue
