{{ config(materialized='table', file_format='delta') }}

with pool_metrics as (

    select
        rank_period_id,
        count(*) as champion_count,
        sum(points_gained) as mastery_points_gained,
        max(case when points_rank = 1 then champion_key end) as primary_champion_key,
        max(case when points_rank = 1 then champion_name end) as primary_champion_name,
        max(case when points_rank = 1 then points_gained end) as primary_champion_points,
        max(champion_share) as top1_share,
        max(favoured_champion_count) as favoured_champion_count,
        least(greatest(sum(case when is_favoured then champion_share else 0 end), 0.0), 1.0)
            as favoured_champions_share,
        max(favoured_log_gap) as favoured_log_gap,
        sum(pow(champion_share, 2)) as hhi,
        -sum(champion_share * log2(champion_share)) as entropy
    from {{ ref('fct_players_period_champion_activity') }}
    group by rank_period_id

),

normalized as (

    select
        *,
        case
            when champion_count = 1 then 0
            else least(greatest(
                {{ dbt_utils.safe_divide('entropy', 'log2(champion_count)') }},
                0.0
            ), 1.0)
        end as normalized_entropy
    from pool_metrics

),

scored as (

    select
        *,
        {{ playstyle_score('specialist', 'top1_share', 'favoured_champions_share', 'hhi', 'normalized_entropy', 'favoured_champion_count') }} as specialist_score,
        {{ playstyle_score('multispecialist', 'top1_share', 'favoured_champions_share', 'hhi', 'normalized_entropy', 'favoured_champion_count') }} as multispecialist_score,
        {{ playstyle_score('versatile', 'top1_share', 'favoured_champions_share', 'hhi', 'normalized_entropy', 'favoured_champion_count') }} as versatile_score,
        {{ playstyle_score('generalist', 'top1_share', 'favoured_champions_share', 'hhi', 'normalized_entropy', 'favoured_champion_count') }} as generalist_score
    from normalized

)

select
    s.*,
    case greatest(
        s.specialist_score,
        s.multispecialist_score,
        s.versatile_score,
        s.generalist_score
    )
        when s.specialist_score then 'specialist'
        when s.multispecialist_score then 'multispecialist'
        when s.versatile_score then 'versatile'
        when s.generalist_score then 'generalist'
    end as playstyle
from scored s
