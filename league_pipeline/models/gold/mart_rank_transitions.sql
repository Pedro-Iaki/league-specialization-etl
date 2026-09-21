{{ config(materialized='table', file_format='delta') }}

{% set lookback_days = var('rank_transition_lookback_days', 90) %}
{% set max_period_days = var('rank_transition_max_period_days', 7) %}

-- Grain: one row per (queue, from_tier, from_division, to_tier, to_division)
-- observed in the trailing {{ lookback_days }} days.
--
-- transition_probability is P(next observed state | current state), estimated
-- over consecutive snapshot pairs. Rows for every from-state sum to 1.0,
-- including the "held" row where nothing moved - that row is the bulk of the
-- mass and dropping it would turn this into "given that you moved, where to",
-- which is a different and much less useful question.
--
-- THREE FILTERS, AND WHY EACH ONE MATTERS:
--   period_in_days <= {{ max_period_days }}
--       a transition probability is only meaningful per unit of time. A pair
--       of snapshots 40 days apart and a pair 1 day apart are not the same
--       event, and mixing them makes the whole matrix uninterpretable. Rows
--       spanning a collection gap are dropped, not stretched.
--   not is_counter_reset
--       a season/split reset moves everyone at once for reasons that have
--       nothing to do with play. Those pairs would show up as a huge synthetic
--       demotion wave.
--   previous_tier / tier not null
--       a player appearing or disappearing is not a transition.
--
-- READ THE SAMPLE SIZE. With a short collection history most cells will have
-- single-digit from_state_observations and the probabilities will be garbage.
-- Filter on from_state_observations before plotting anything; a few weeks of
-- daily snapshots is roughly the minimum for the common tiers, and the tails
-- (Challenger, Iron IV) will stay thin much longer than that.

with as_of as (

    select max(snapshot_date) as as_of_date
    from {{ ref('fct_players_rank_history') }}

),

observations as (

    select r.*
    from {{ ref('fct_players_rank_history') }} r
    cross join as_of ao
    where r.snapshot_date > date_sub(ao.as_of_date, {{ lookback_days }})
      and r.period_in_days between 1 and {{ max_period_days }}
      and not r.is_counter_reset
      and r.previous_tier is not null
      and r.tier is not null
      and r.previous_state_order is not null
      and r.state_order is not null

),

from_totals as (

    select
        queue,
        previous_tier,
        previous_division,
        count(*) as from_state_observations,
        count(distinct player_id) as from_state_players,
        avg(period_in_days) as from_state_avg_period_in_days
    from observations
    group by queue, previous_tier, previous_division

),

transitions as (

    select
        queue,
        previous_tier,
        previous_division,
        tier,
        division,
        -- constant within the group; min() just carries it through
        min(previous_state_order) as from_state_order,
        min(state_order) as to_state_order,
        count(*) as transition_count,
        count(distinct player_id) as transition_players,
        avg(period_in_days) as avg_period_in_days,
        avg(lp_delta) as avg_lp_delta,
        avg(wins_delta + losses_delta) as avg_games,
        percentile(wins_delta + losses_delta, 0.5) as median_games,
        {{ dbt_utils.safe_divide('sum(wins_delta)', 'sum(wins_delta + losses_delta)') }} as win_rate
    from observations
    group by queue, previous_tier, previous_division, tier, division

)

select
    {{ dbt_utils.generate_surrogate_key([
        't.queue',
        't.previous_tier',
        't.previous_division',
        't.tier',
        't.division'
    ]) }} as rank_transition_id,

    ao.as_of_date,
    {{ lookback_days }} as lookback_days,
    {{ max_period_days }} as max_period_days,
    t.queue,

    t.previous_tier as from_tier,
    t.previous_division as from_division,
    t.from_state_order,
    t.tier as to_tier,
    t.division as to_division,
    t.to_state_order,

    t.to_state_order - t.from_state_order as division_steps,
    case
        when t.to_state_order > t.from_state_order then 'promotion'
        when t.to_state_order < t.from_state_order then 'demotion'
        else 'held'
    end as movement_type,
    (t.tier != t.previous_tier) as crossed_tier,

    f.from_state_observations,
    f.from_state_players,
    f.from_state_avg_period_in_days,
    t.transition_count,
    t.transition_players,
    {{ dbt_utils.safe_divide('t.transition_count', 'f.from_state_observations') }} as transition_probability,

    t.avg_period_in_days,
    t.avg_lp_delta,
    t.avg_games,
    t.median_games,
    t.win_rate

from transitions t
cross join as_of ao
join from_totals f
    on t.queue = f.queue
    and t.previous_tier = f.previous_tier
    -- null-safe: division should never be null for a ranked player, but if the
    -- API ever returns one the row should still find its denominator instead of
    -- silently vanishing from the matrix
    and t.previous_division <=> f.previous_division
