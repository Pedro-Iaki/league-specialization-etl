{{ config(materialized='table', file_format='delta') }}

with player_champions as (

    select
        player_id,
        explode(champions_sample) as champion_key,
        top_pct,
        jungle_pct,
        middle_pct,
        bottom_pct,
        support_pct
    from {{ ref('dim_players_naive_role_distribution') }}

),

role_weights as (

    select
        champion_key,
        count(distinct player_id) as player_count,
        avg(top_pct) as avg_top_pct,
        avg(jungle_pct) as avg_jungle_pct,
        avg(middle_pct) as avg_middle_pct,
        avg(bottom_pct) as avg_bottom_pct,
        avg(support_pct) as avg_support_pct
    from player_champions
    group by champion_key

)

select
    c.key as champion_key,
    c.name as champion_name,
    coalesce(r.player_count, 0) as player_count,
    r.avg_top_pct,
    r.avg_jungle_pct,
    r.avg_middle_pct,
    r.avg_bottom_pct,
    r.avg_support_pct
from {{ ref('dim_champions') }} c
left join role_weights r on c.key = r.champion_key
