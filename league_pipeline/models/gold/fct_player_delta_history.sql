{{
    config(
        materialized='incremental',
        unique_key=['player_id', 'snapshot_date'] 
    )
}}

WITH active_pool AS (
    SELECT * FROM {{ ref('dim_players_active_pool') }}
),

champion_activity AS (
    SELECT * FROM {{ ref('fct_players_champion_activity') }}
),

rank_delta AS (
    SELECT * FROM {{ ref('fct_players_rank_last_delta') }}
    {% if is_incremental() %}
    -- Ensure we only append deltas from new snapshots
    WHERE snapshot_date > (SELECT COALESCE(MAX(snapshot_date), '1900-01-01') FROM {{ this }})
    {% endif %}
)

SELECT
    r.player_id,
    r.snapshot_date, -- Essential for logging the history over time
    r.previous_snapshot_date,
    r.period_in_days,
    c.total_days_tracked,

    -- Rank Deltas & Win Rate
    r.tier,
    r.division,
    r.wins_delta,
    r.losses_delta,
    r.lp_delta,
    r.lp_velocity,
    {{ dbt_utils.safe_divide('r.wins_delta', '(r.wins_delta + r.losses_delta)') }} AS win_rate,
    
    -- Active Pool
    p.active_champion_ids,
    p.active_champion_count,
    p.recent_champion_ids,
    p.recent_champion_count,
    p.main_role,
    p.main_role_weight,
    
    -- Champion Activity & Mastery
    c.recent_total_points

FROM rank_delta r
LEFT JOIN active_pool p 
    ON r.player_id = p.player_id
LEFT JOIN champion_activity c 
    ON r.player_id = c.player_id