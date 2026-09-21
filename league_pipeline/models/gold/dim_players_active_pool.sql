{{ config(materialized='table', file_format='delta') }}

-- One row per player in dim_players_current.
--
-- Changes vs the previous version:
--   * role labels are Title-case (Top/Jungle/Middle/Bottom/Support) to match
--     dim_champions and primary_roles in dim_players_naive_role_distribution
--   * main_role is weighted by recent mastery gained on each active champion
--     (was: every active champion counted equally). main_role_weight is now a
--     weighted-average lane share in [0, 1] instead of a raw sum
--   * carries as_of_date, patch, tier, queue, total_days_tracked and
--     recent_total_points so fct_player_pool_history can freeze a complete
--     player-level record per snapshot
--
-- main_role is an INFERRED affinity (champion metadata smoothed through
-- co-play), not an observed lane.

with active_champions as (

    select
        player_id,
        champion_name,
        champion_key,
        snapshot_date,
        last_played_at,
        recent_champ_points,
        -- weight each champion by the mastery the player is actually gaining on
        -- it, so one grinded champion outweighs several one-off games. If none
        -- of the active champions gained points (immature players are active on
        -- recency alone), fall back to equal weights.
        case
            when sum(recent_champ_points) over (partition by player_id) > 0
                then recent_champ_points
            else 1
        end as role_weight_factor
    from {{ ref('fct_players_champion_activity') }}
    where is_active

),

aggregated as (

    select
        player_id,
        max(snapshot_date) as snapshot_date,

        sort_array(collect_list(cast(champion_name as string))) as active_champion_names,
        sort_array(collect_list(cast(champion_key as string))) as active_champion_ids,
        count(champion_key) as active_champion_count,

        sort_array(collect_list(
            case
                when last_played_at <= 1
                then cast(champion_name as string)
            end
        )) as recent_champion_names,
        sort_array(collect_list(
            case
                when last_played_at <= 1
                then cast(champion_key as string)
            end
        )) as recent_champion_ids,
        count(
            case
                when last_played_at <= 1
                then champion_key
            end
        ) as recent_champion_count

    from active_champions
    group by player_id

),

-- These columns are constant per player in the dense activity table
player_level as (

    select
        player_id,
        max(as_of_date) as as_of_date,
        max(total_days_tracked) as total_days_tracked,
        max(recent_total_points) as recent_total_points
    from {{ ref('fct_players_champion_activity') }}
    group by player_id

),

player_role_sums as (

    select
        ac.player_id,
        sum(cr.avg_top_pct     * ac.role_weight_factor) as sum_top,
        sum(cr.avg_jungle_pct  * ac.role_weight_factor) as sum_jungle,
        sum(cr.avg_middle_pct  * ac.role_weight_factor) as sum_middle,
        sum(cr.avg_bottom_pct  * ac.role_weight_factor) as sum_bottom,
        sum(cr.avg_support_pct * ac.role_weight_factor) as sum_support,
        -- only count champions that actually have role data, so champions
        -- nobody has sampled yet don't drag the weighted average down
        sum(case when cr.avg_top_pct is not null then ac.role_weight_factor end) as total_weight
    from active_champions ac
    join {{ ref('dim_champion_role_weights') }} cr
        on ac.champion_key = cr.champion_key
    group by ac.player_id

),

main_role as (

    select
        player_id,
        role_name,
        role_weight
    from (
        select player_id, 'Top'     as role_name, {{ dbt_utils.safe_divide('sum_top',     'total_weight') }} as role_weight from player_role_sums
        union all
        select player_id, 'Jungle'  as role_name, {{ dbt_utils.safe_divide('sum_jungle',  'total_weight') }} as role_weight from player_role_sums
        union all
        select player_id, 'Middle'  as role_name, {{ dbt_utils.safe_divide('sum_middle',  'total_weight') }} as role_weight from player_role_sums
        union all
        select player_id, 'Bottom'  as role_name, {{ dbt_utils.safe_divide('sum_bottom',  'total_weight') }} as role_weight from player_role_sums
        union all
        select player_id, 'Support' as role_name, {{ dbt_utils.safe_divide('sum_support', 'total_weight') }} as role_weight from player_role_sums
    )
    -- no role data -> null main_role, rather than an arbitrary alphabetical winner
    where role_weight is not null

    qualify row_number() over (
        partition by player_id
        order by role_weight desc, role_name asc
    ) = 1

)

select
    p.puuid as player_id,
    p.snapshot_date,
    pl.as_of_date,
    p.patch,
    p.tier,
    p.queue,
    pl.total_days_tracked,
    pl.recent_total_points,
    coalesce(a.active_champion_count, 0) > 0 as is_active,
    coalesce(a.active_champion_names, array()) as active_champion_names,
    coalesce(a.active_champion_ids, array()) as active_champion_ids,
    coalesce(a.active_champion_count, 0) as active_champion_count,
    coalesce(a.recent_champion_names, array()) as recent_champion_names,
    coalesce(a.recent_champion_ids, array()) as recent_champion_ids,
    coalesce(a.recent_champion_count, 0) as recent_champion_count,
    m.role_name as main_role,
    m.role_weight as main_role_weight
from {{ ref('dim_players_current') }} p
left join aggregated a
    on p.puuid = a.player_id
left join main_role m
    on p.puuid = m.player_id
left join player_level pl
    on p.puuid = pl.player_id