{{ config(materialized='table', file_format='delta') }}

{% set max_favoured = var('favoured_champion_max_count', 10) %}
{% set gap_multiplier = var('favoured_champion_gap_multiplier', 1.5) %}
{% set min_log_gap = var('favoured_champion_min_log_gap', 0.69314718056) %}

with active_champions as (

    select
        a.player_id,
        a.champion_key,
        a.champion_name,
        case
            when a.recent_total_points > 0 then a.recent_champion_points
            else 1
        end as pool_points
    from {{ ref('fct_players_champion_activity') }} a
    where a.is_active

),

pool_shares as (

    select
        *,
        {{ dbt_utils.safe_divide(
            'pool_points',
            'sum(pool_points) over (partition by player_id)'
        ) }} as champion_share,
        row_number() over (
            partition by player_id
            order by pool_points desc, champion_key
        ) as points_rank
    from active_champions

),

top_candidates as (

    select
        *,
        lead(pool_points) over (
            partition by player_id order by points_rank
        ) as next_champion_points
    from pool_shares
    where points_rank <= {{ max_favoured }}

),

gaps as (

    select
        player_id,
        points_rank,
        ln(cast(pool_points as double) / next_champion_points) as log_gap
    from top_candidates
    where next_champion_points > 0

),

gap_summary as (

    select
        player_id,
        percentile(log_gap, 0.5) as median_log_gap
    from gaps
    group by player_id

),

largest_gap as (

    select player_id, points_rank, log_gap
    from gaps
    qualify row_number() over (
        partition by player_id
        order by log_gap desc, points_rank
    ) = 1

),

favoured_boundaries as (

    select
        t.player_id,
        case
            when count(*) = 1 then 1
            when max(g.log_gap) >= {{ min_log_gap }}
                and (
                    count(*) = 2
                    or coalesce(max(s.median_log_gap), 0) = 0
                    or max(g.log_gap) >= {{ gap_multiplier }} * max(s.median_log_gap)
                ) then max(g.points_rank)
            else count(*)
        end as pool_favoured_champion_count,
        max(g.log_gap) as pool_favoured_log_gap
    from top_candidates t
    left join largest_gap g on t.player_id = g.player_id
    left join gap_summary s on t.player_id = s.player_id
    group by t.player_id

),

pool_metrics as (

    select
        s.player_id,
        count(*) as active_champion_count,
        max(case when s.points_rank = 1 then s.champion_key end) as primary_champion_key,
        max(case when s.points_rank = 1 then s.champion_name end) as primary_champion_name,
        max(s.champion_share) as pool_top1_share,
        least(greatest(sum(
            case when s.points_rank <= b.pool_favoured_champion_count then s.champion_share else 0 end
        ), 0.0), 1.0) as pool_favoured_champions_share,
        max(b.pool_favoured_champion_count) as pool_favoured_champion_count,
        max(b.pool_favoured_log_gap) as pool_favoured_log_gap,
        sum(pow(s.champion_share, 2)) as pool_hhi,
        -sum(s.champion_share * log2(s.champion_share)) as pool_entropy
    from pool_shares s
    join favoured_boundaries b on s.player_id = b.player_id
    group by s.player_id

),

normalized as (

    select
        *,
        case
            when active_champion_count = 1 then 0
            else least(greatest(
                {{ dbt_utils.safe_divide('pool_entropy', 'log2(active_champion_count)') }},
                0.0
            ), 1.0)
        end as pool_normalized_entropy
    from pool_metrics

),

scored as (

    select
        *,
        {{ playstyle_score('specialist', 'pool_top1_share', 'pool_favoured_champions_share', 'pool_hhi', 'pool_normalized_entropy', 'pool_favoured_champion_count') }} as specialist_score,
        {{ playstyle_score('multispecialist', 'pool_top1_share', 'pool_favoured_champions_share', 'pool_hhi', 'pool_normalized_entropy', 'pool_favoured_champion_count') }} as multispecialist_score,
        {{ playstyle_score('versatile', 'pool_top1_share', 'pool_favoured_champions_share', 'pool_hhi', 'pool_normalized_entropy', 'pool_favoured_champion_count') }} as versatile_score,
        {{ playstyle_score('generalist', 'pool_top1_share', 'pool_favoured_champions_share', 'pool_hhi', 'pool_normalized_entropy', 'pool_favoured_champion_count') }} as generalist_score
    from normalized

),

labeled as (

    select
        *,
        case greatest(
            specialist_score,
            multispecialist_score,
            versatile_score,
            generalist_score
        )
            when specialist_score then 'specialist'
            when multispecialist_score then 'multispecialist'
            when versatile_score then 'versatile'
            else 'generalist'
        end as playstyle
    from scored

),

pool_lists as (

    select
        player_id,
        sort_array(collect_list(champion_name)) as active_champion_names
    from active_champions
    group by player_id

),

role_sums as (

    select
        a.player_id,
        sum(w.avg_top_pct * a.pool_points) as top_points,
        sum(w.avg_jungle_pct * a.pool_points) as jungle_points,
        sum(w.avg_middle_pct * a.pool_points) as middle_points,
        sum(w.avg_bottom_pct * a.pool_points) as bottom_points,
        sum(w.avg_support_pct * a.pool_points) as support_points
    from active_champions a
    inner join {{ ref('dim_champion_role_weights') }} w
        on a.champion_key = w.champion_key
    where w.avg_top_pct is not null
    group by a.player_id

),

role_totals as (

    select
        *,
        top_points + jungle_points + middle_points + bottom_points + support_points
            as total_role_points
    from role_sums

),

role_shares as (

    select
        player_id,
        {{ dbt_utils.safe_divide('top_points', 'total_role_points') }} as role_top_pct,
        {{ dbt_utils.safe_divide('jungle_points', 'total_role_points') }} as role_jungle_pct,
        {{ dbt_utils.safe_divide('middle_points', 'total_role_points') }} as role_middle_pct,
        {{ dbt_utils.safe_divide('bottom_points', 'total_role_points') }} as role_bottom_pct,
        {{ dbt_utils.safe_divide('support_points', 'total_role_points') }} as role_support_pct
    from role_totals

),

role_profile as (

    select
        *,
        pow(role_top_pct, 2)
            + pow(role_jungle_pct, 2)
            + pow(role_middle_pct, 2)
            + pow(role_bottom_pct, 2)
            + pow(role_support_pct, 2) as role_purity
    from role_shares

),

main_role as (

    select player_id, role as main_role, role_share as main_role_weight
    from (
        select player_id, 'Top' as role, role_top_pct as role_share from role_shares
        union all
        select player_id, 'Jungle', role_jungle_pct from role_shares
        union all
        select player_id, 'Middle', role_middle_pct from role_shares
        union all
        select player_id, 'Bottom', role_bottom_pct from role_shares
        union all
        select player_id, 'Support', role_support_pct from role_shares
    )
    qualify row_number() over (
        partition by player_id
        order by role_share desc, role
    ) = 1

),

player_activity as (

    select
        player_id,
        max(as_of_date) as as_of_date,
        max(days_tracked) as days_tracked,
        max(recent_total_points) as recent_total_points
    from {{ ref('fct_players_champion_activity') }}
    group by player_id

)

select
    p.puuid as player_id,
    a.as_of_date,
    coalesce(a.days_tracked, 0) as days_tracked,
    coalesce(a.recent_total_points, 0) as recent_total_points,
    coalesce(m.active_champion_count, 0) > 0 as is_active,
    coalesce(l.active_champion_names, array()) as active_champion_names,
    coalesce(m.active_champion_count, 0) as active_champion_count,
    m.primary_champion_key,
    m.primary_champion_name,
    m.pool_top1_share,
    m.pool_favoured_champion_count,
    m.pool_favoured_champions_share,
    m.pool_favoured_log_gap,
    m.pool_hhi,
    m.pool_entropy,
    m.pool_normalized_entropy,
    m.specialist_score,
    m.multispecialist_score,
    m.versatile_score,
    m.generalist_score,
    m.playstyle,
    r.role_top_pct,
    r.role_jungle_pct,
    r.role_middle_pct,
    r.role_bottom_pct,
    r.role_support_pct,
    r.role_purity,
    mr.main_role,
    mr.main_role_weight
from {{ ref('dim_players_current') }} p
left join player_activity a on p.puuid = a.player_id
left join labeled m on p.puuid = m.player_id
left join pool_lists l on p.puuid = l.player_id
left join role_profile r on p.puuid = r.player_id
left join main_role mr on p.puuid = mr.player_id
