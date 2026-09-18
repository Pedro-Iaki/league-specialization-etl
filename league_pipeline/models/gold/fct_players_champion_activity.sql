{{ config(materialized='table', file_format='delta') }}

{% set activity_window_days = var('active_champion_activity_window_days', 60) %}
{% set min_absolute_points = var('active_champion_min_absolute_points', 3000) %}
{% set min_relative_pct = var('active_champion_min_relative_pct', 0.10) %}
{% set immature_window_fraction = var('active_champion_immature_window_fraction', 0.5) %}
{% set min_tracking_days = ({{ activity_window_days }} * {{ immature_window_fraction }}) %}

-- "Now" is pinned to the most recent snapshot_date present in the deltas
-- table (not current_date()), so this table stays consistent even if the
-- pipeline runs against backfilled or delayed data.
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
    where d.snapshot_date > date_sub(as_of.as_of_date, {{ activity_window_days }})

),

champion_recent_points as (

    select
        puuid,
        champion_key,
        sum(points_delta) as recent_champ_points
    from recent_deltas
    group by puuid, champion_key

),

player_recent_points as (

    -- total mastery gained by a player, across all champions, within the
    -- activity window. Denominator for relative_threshold.
    select
        puuid,
        sum(points_delta) as recent_total_points
    from recent_deltas
    group by puuid

),

champion_tracking as (

    -- Full observation span for this specific player/champion combination:
    -- first snapshot on record vs the latest, uncapped by the activity
    -- window (the window only bounds the *ratio* used to prorate
    -- absolute_threshold below, not this raw span). A champion only enters
    -- the mastery pull once it has nonzero points, so this differs
    -- meaningfully across a player's champions.
    select
        puuid,
        datediff(max(snapshot_date), min(snapshot_date)) as days_tracked
    from {{ ref('dim_players_history') }}
    group by puuid, champion_key

),

champion_last_played as (

    select
        puuid,
        champion_key,
        last_play_time
    from {{ ref('fct_masteries_current') }}

),

-- Dense player x champion universe: every champion gets a row for every
-- player, including ones never played. A never-played combo simply has no
-- rows in champion_tracking / champion_recent_points / champion_last_played,
-- so it resolves to an explicit 0/inactive below rather than being absent.
champion_universe as (

    select
        p.puuid,
        c.key as champion_key
    from {{ ref('dim_players_current') }} p
    cross join {{ ref('dim_champions') }} c

),

joined as (

    select
        u.puuid,
        u.champion_key,
        ao.as_of_date,
        coalesce(cr.recent_champ_points, 0) as recent_champ_points,
        coalesce(pr.recent_total_points, 0) as recent_total_points,
        coalesce(ct.days_tracked, 0) as days_tracked,
        lp.last_play_time
    from champion_universe u
    cross join as_of ao
    left join champion_recent_points cr
        on u.puuid = cr.puuid
        and u.champion_key = cr.champion_key
    left join player_recent_points pr
        on u.puuid = pr.puuid
    left join champion_tracking ct
        on u.puuid = ct.puuid
    left join champion_last_played lp
        on u.puuid = lp.puuid
        and u.champion_key = lp.champion_key

),

flagged as (

    select
        *,
        cast(datediff(as_of_date, last_play_time) as int) as last_played_at,
        cast({{ min_absolute_points }} as double)
            * least(days_tracked / {{ activity_window_days }}.0, 1) as absolute_threshold,
        recent_total_points * {{ min_relative_pct }} as relative_threshold
    from joined

)

select

    {{ dbt_utils.generate_surrogate_key(['puuid', 'champion_key']) }} as player_champion_activity_id,
    puuid as player_id,
    champion_key,
    recent_champ_points,
    recent_total_points,
    days_tracked,
    absolute_threshold,
    relative_threshold,
    last_played_at,
    case
        -- enough history to trust a delta trend: require both recency and
        -- representation
        when days_tracked >= {{ min_tracking_days }} then
            last_played_at is not null
            and last_played_at <= {{ activity_window_days }}
            and recent_champ_points > greatest(absolute_threshold, relative_threshold)
        -- not enough history for a delta to mean anything: fall back to
        -- last-played-time alone, at a tighter window
        else
            last_played_at is not null
            and last_played_at <= {{ min_tracking_days }}
    end as is_active

from flagged