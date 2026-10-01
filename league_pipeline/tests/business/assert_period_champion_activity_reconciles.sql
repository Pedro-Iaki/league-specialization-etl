with activity as (

    select
        rank_period_id,
        count(*) as champion_count,
        sum(champion_share) as total_share,
        sum(case when is_favoured then 1 else 0 end) as favoured_count,
        sum(case when is_favoured then champion_share else 0 end) as favoured_share
    from {{ ref('fct_players_period_champion_activity') }}
    group by rank_period_id

)

select a.rank_period_id
from activity a
left join {{ ref('fct_players_period_pool_profile') }} p
    on a.rank_period_id = p.rank_period_id
where p.rank_period_id is null
   or a.champion_count <> p.champion_count
   or a.favoured_count <> p.favoured_champion_count
   or abs(a.total_share - 1.0) > 0.000001
   or abs(a.favoured_share - p.favoured_champions_share) > 0.000001
