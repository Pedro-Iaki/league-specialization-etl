{{ config(materialized='table', file_format='delta') }}

{% set high_elo_min_tier_order = var('high_elo_min_tier_order', 7) %}
{% set low_elo_max_tier_order = var('low_elo_max_tier_order', 4) %}

-- Grain: one row per champion in dim_champions, built from the latest
-- as_of_date slice of mart_champion_tier_daily. This is the champion-level
-- join key for modelling; mart_champion_tier_daily stays the source of truth
-- for anything that needs a specific tier or a time series.
--
-- The per-tier play rates are pivoted into columns so a champion is one row.
-- High/low elo aggregates are pooled (sum of numerators over sum of
-- denominators), not averaged across tiers - averaging tier-level rates would
-- weight Challenger, with a few hundred players, the same as Gold with tens of
-- thousands.
--
-- tier_skew_ratio > 1 means the champion is picked more often in
-- {{ 'tier_order >= ' ~ high_elo_min_tier_order }} (DIAMOND+) than in
-- {{ 'tier_order <= ' ~ low_elo_max_tier_order }} (IRON-GOLD). The log ratio is
-- the one to feed a model: it is symmetric around 0, whereas the raw ratio
-- squashes "half as popular" into [0,1] and stretches "twice as popular" into
-- [1,inf).
--
-- CAVEAT: play_rate here is a share of ACTIVE POOLS, not of games played. A
-- champion that everybody owns and occasionally grinds looks popular even if
-- it is rarely picked. Without match-level data that gap cannot be closed.

with latest as (

    select max(as_of_date) as as_of_date
    from {{ ref('mart_champion_tier_daily') }}

),

tier_slice as (

    select d.*
    from {{ ref('mart_champion_tier_daily') }} d
    join latest l
        on d.as_of_date = l.as_of_date

),

rolled as (

    select
        champion_key,
        max(as_of_date) as as_of_date,
        count(distinct tier) as tiers_present,

        sum(active_player_count) as active_player_count,
        sum(active_pool_player_count) as active_pool_player_count,
        sum(mastery_player_count) as mastery_player_count,
        sum(expert_player_count) as expert_player_count,

        max(case when tier = 'IRON'        then play_rate end) as play_rate_iron,
        max(case when tier = 'BRONZE'      then play_rate end) as play_rate_bronze,
        max(case when tier = 'SILVER'      then play_rate end) as play_rate_silver,
        max(case when tier = 'GOLD'        then play_rate end) as play_rate_gold,
        max(case when tier = 'PLATINUM'    then play_rate end) as play_rate_platinum,
        max(case when tier = 'EMERALD'     then play_rate end) as play_rate_emerald,
        max(case when tier = 'DIAMOND'     then play_rate end) as play_rate_diamond,
        max(case when tier = 'MASTER'      then play_rate end) as play_rate_master,
        max(case when tier = 'GRANDMASTER' then play_rate end) as play_rate_grandmaster,
        max(case when tier = 'CHALLENGER'  then play_rate end) as play_rate_challenger,

        {{ dbt_utils.safe_divide(
            'sum(case when tier_order >= ' ~ high_elo_min_tier_order ~ ' then active_player_count end)',
            'sum(case when tier_order >= ' ~ high_elo_min_tier_order ~ ' then active_pool_player_count end)'
        ) }} as high_elo_play_rate,
        {{ dbt_utils.safe_divide(
            'sum(case when tier_order <= ' ~ low_elo_max_tier_order ~ ' then active_player_count end)',
            'sum(case when tier_order <= ' ~ low_elo_max_tier_order ~ ' then active_pool_player_count end)'
        ) }} as low_elo_play_rate,

        -- player-weighted so a 3-player tier row cannot swing the champion mean
        {{ dbt_utils.safe_divide(
            'sum(specialization_bias * active_player_count)',
            'sum(case when specialization_bias is not null then active_player_count end)'
        ) }} as specialization_bias,
        {{ dbt_utils.safe_divide(
            'sum(avg_lp_per_game * form_player_count)',
            'sum(case when avg_lp_per_game is not null then form_player_count end)'
        ) }} as avg_lp_per_game,
        {{ dbt_utils.safe_divide(
            'sum(avg_lp_per_game_lift * form_player_count)',
            'sum(case when avg_lp_per_game_lift is not null then form_player_count end)'
        ) }} as avg_lp_per_game_lift,
        {{ dbt_utils.safe_divide(
            'sum(avg_win_rate_lift * form_player_count)',
            'sum(case when avg_win_rate_lift is not null then form_player_count end)'
        ) }} as avg_win_rate_lift,
        {{ dbt_utils.safe_divide(
            'sum(avg_mastery * mastery_player_count)',
            'sum(case when avg_mastery is not null then mastery_player_count end)'
        ) }} as avg_mastery,
        sum(form_player_count) as form_player_count

    from tier_slice
    group by champion_key

)

select
    c.key as champion_key,
    c.name as champion_name,
    c.patch as champion_patch,
    c.expected_positions,
    r.as_of_date,
    r.tiers_present,

    -- exposure
    r.active_player_count,
    r.active_pool_player_count,
    r.mastery_player_count,
    r.expert_player_count,
    r.form_player_count,
    {{ dbt_utils.safe_divide('r.active_player_count', 'r.active_pool_player_count') }} as play_rate_overall,

    -- play rate by tier, side by side
    r.play_rate_iron,
    r.play_rate_bronze,
    r.play_rate_silver,
    r.play_rate_gold,
    r.play_rate_platinum,
    r.play_rate_emerald,
    r.play_rate_diamond,
    r.play_rate_master,
    r.play_rate_grandmaster,
    r.play_rate_challenger,

    -- tier skew
    r.high_elo_play_rate,
    r.low_elo_play_rate,
    {{ dbt_utils.safe_divide('r.high_elo_play_rate', 'nullif(r.low_elo_play_rate, 0)') }} as tier_skew_ratio,
    log2(nullif({{ dbt_utils.safe_divide('r.high_elo_play_rate', 'nullif(r.low_elo_play_rate, 0)') }}, 0)) as tier_skew_log_ratio,

    -- outcomes relative to the tier baselines the players actually sit in
    r.avg_lp_per_game,
    r.avg_lp_per_game_lift,
    r.avg_win_rate_lift,
    r.specialization_bias,

    -- mastery
    {{ dbt_utils.safe_divide('r.expert_player_count', 'r.mastery_player_count') }} as expert_population,
    r.avg_mastery,

    -- inferred role weights from the champion's playerbase
    w.player_count as role_sample_player_count,
    w.avg_top_pct as role_top_pct,
    w.avg_jungle_pct as role_jungle_pct,
    w.avg_middle_pct as role_middle_pct,
    w.avg_bottom_pct as role_bottom_pct,
    w.avg_support_pct as role_support_pct

from {{ ref('dim_champions') }} c
left join rolled r
    on c.key = r.champion_key
left join {{ ref('dim_champion_role_weights') }} w
    on c.key = w.champion_key
