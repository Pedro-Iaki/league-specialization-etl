{{ config(materialized='table', file_format='delta') }}

{% set lookback_days = var('active_champion_lookback_days', 60) %}
{% set min_absolute_points = var('active_champion_min_absolute_points', 3000) %}
{% set min_relative_pct = var('active_champion_min_relative_pct', 0.10) %}

-- "Activity" is judged against the most recent snapshot_date present in the
-- deltas table (not current_date()), so this table stays consistent even if
-- the pipeline runs against backfilled or delayed data.
with as_of as (

    select max(snapshot_date) as as_of_date
    from {{ ref('fct_players_champion_delta') }}

),

recent_deltas as (

    select
        d.puuid,
        d.champion_key,
        d.points_delta,
        d.snapshot_date
    from {{ ref('fct_players_champion_delta') }} d
    cross join as_of
    where d.snapshot_date > date_sub(as_of.as_of_date, {{ lookback_days }})

),

champion_recent_gain as (

    select
        puuid,
        champion_key,
        sum(points_delta) as recent_champion_gain,
        max(snapshot_date) as last_gain_date
    from recent_deltas
    group by puuid, champion_key

),

player_recent_total as (

    -- total mastery gained by a player, across all champions, within the
    -- lookback window. Denominator for the relative representation threshold.
    select
        puuid,
        sum(points_delta) as total_recent_gain
    from recent_deltas
    group by puuid

),

champion_universe as (

    -- every champion a player currently holds mastery points on, so champs
    -- with no recent activity still get a row (and correctly land as inactive)
    select distinct
        puuid,
        champion_key
    from {{ ref('fct_masteries_current') }}

),

joined as (

    select
        u.puuid,
        u.champion_key,
        coalesce(g.recent_champion_gain, 0) as recent_champion_gain,
        g.last_gain_date,
        coalesce(t.total_recent_gain, 0) as player_total_recent_gain
    from champion_universe u
    left join champion_recent_gain g
        on u.puuid = g.puuid
        and u.champion_key = g.champion_key
    left join player_recent_total t
        on u.puuid = t.puuid

),

flagged as (

    select
        *,
        cast({{ min_absolute_points }} as double) as min_absolute_points_threshold,
        player_total_recent_gain * {{ min_relative_pct }} as min_relative_points_threshold,
        greatest(
            cast({{ min_absolute_points }} as double),
            player_total_recent_gain * {{ min_relative_pct }}
        ) as decent_representation_threshold
    from joined

)

select

    {{ dbt_utils.generate_surrogate_key(['puuid', 'champion_key']) }} as player_champion_activity_id,
    puuid,
    champion_key,
    recent_champion_gain,
    player_total_recent_gain,
    min_absolute_points_threshold,
    min_relative_points_threshold,
    decent_representation_threshold,
    last_gain_date,
    last_gain_date is not null as has_gain_in_lookback_window,
    (
        last_gain_date is not null
        and recent_champion_gain > decent_representation_threshold
    ) as is_active_champion

from flagged