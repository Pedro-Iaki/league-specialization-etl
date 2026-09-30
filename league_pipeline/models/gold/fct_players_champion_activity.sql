{{ config(materialized='table', file_format='delta') }}

{% set activity_window_days = var('active_champion_activity_window_days', 60) %}
{% set min_absolute_points = var('active_champion_min_absolute_points', 3000) %}
{% set min_relative_pct = var('active_champion_min_relative_pct', 0.10) %}
{% set immature_window_fraction = var('active_champion_immature_window_fraction', 0.5) %}
{% set min_tracking_days = activity_window_days * immature_window_fraction %}

with as_of as (

    select max(snapshot_date) as as_of_date
    from {{ ref('dim_players_current') }}

),

recent_points as (

    select
        d.player_id,
        d.champion_key,
        sum(d.points_delta) as recent_champion_points
    from {{ ref('fct_players_champion_delta_history') }} d
    cross join as_of
    where d.snapshot_date > date_sub(as_of.as_of_date, {{ activity_window_days }})
      and d.points_delta > 0
    group by d.player_id, d.champion_key

),

player_totals as (

    select
        player_id,
        sum(recent_champion_points) as recent_total_points
    from recent_points
    group by player_id

),

tracking as (

    select
        puuid as player_id,
        datediff(max(snapshot_date), min(snapshot_date)) as days_tracked
    from {{ ref('dim_players_history') }}
    group by puuid

),

masteries as (

    select
        m.puuid as player_id,
        m.champion_key,
        c.name as champion_name,
        m.last_play_time
    from {{ ref('fct_masteries_current') }} m
    inner join {{ ref('dim_champions') }} c
        on m.champion_key = c.key

),

metrics as (

    select
        m.player_id,
        m.champion_key,
        m.champion_name,
        ao.as_of_date,
        coalesce(r.recent_champion_points, 0) as recent_champion_points,
        coalesce(p.recent_total_points, 0) as recent_total_points,
        coalesce(t.days_tracked, 0) as days_tracked,
        cast(datediff(ao.as_of_date, m.last_play_time) as int) as days_since_last_play
    from masteries m
    cross join as_of ao
    left join recent_points r
        on m.player_id = r.player_id
        and m.champion_key = r.champion_key
    left join player_totals p on m.player_id = p.player_id
    left join tracking t on m.player_id = t.player_id

)

select
    {{ dbt_utils.generate_surrogate_key(['player_id', 'champion_key']) }} as player_champion_activity_id,
    player_id,
    champion_key,
    champion_name,
    as_of_date,
    recent_champion_points,
    recent_total_points,
    {{ dbt_utils.safe_divide('recent_champion_points', 'recent_total_points') }} as recent_share,
    days_tracked,
    days_since_last_play,
    case
        when days_tracked >= {{ min_tracking_days }} then
            days_since_last_play between 0 and {{ activity_window_days }}
            and recent_champion_points > greatest(
                {{ min_absolute_points }} * least(days_tracked / {{ activity_window_days }}.0, 1),
                recent_total_points * {{ min_relative_pct }}
            )
        else days_since_last_play between 0 and {{ min_tracking_days }}
    end as is_active
from metrics
