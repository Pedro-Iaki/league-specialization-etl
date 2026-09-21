{{ config(materialized='table', file_format='delta') }}

-- One row per player in dim_players_current.
--
-- Everything the previous version emitted is still here, unchanged. Added:
--   * role_top_pct ... role_support_pct - the points-weighted lane mix that
--     main_role was already being picked from. It was computed and then thrown
--     away, so downstream had a winner with no runner-up and no way to tell
--     "70/30 mid-jungle" from "35/32 mid-jungle". The five columns are
--     normalised to sum to 1 per player.
--   * role_purity - HHI over those five shares. 0.2 = perfectly spread across
--     all five lanes, 1.0 = single lane. This is the "purity" feature and it
--     behaves better than main_role_weight alone because it responds to the
--     shape of the whole distribution, not just its peak.
--   * pool_* - concentration of RECENT mastery points across the active
--     champions (top-1 / top-3 share, HHI, entropy). One-trick vs generalist,
--     measured on current behaviour rather than career totals.
--
-- These are added here rather than in a mart on purpose: fct_player_pool_history
-- freezes this model with `s.*`, so putting them here is what makes them
-- available as-of-date in mart_player_delta_history. A mart-level calculation
-- could never be backfilled onto past snapshots.
--
-- main_role remains an INFERRED affinity (champion metadata smoothed through
-- co-play), not an observed lane. See the note in CHANGES.md about how much
-- independent information it really carries.

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

pool_shares as (

    select
        player_id,
        champion_key,
        recent_champ_points,
        {{ dbt_utils.safe_divide(
            'recent_champ_points',
            'sum(recent_champ_points) over (partition by player_id)'
        ) }} as champion_share,
        row_number() over (
            partition by player_id
            order by recent_champ_points desc, champion_key
        ) as points_rank
    from active_champions

),

pool_concentration as (

    -- champion_share is null for a player whose active champions all gained
    -- zero recent points, so every metric here stays null for them rather than
    -- collapsing to a fake 1.0 concentration.
    select
        player_id,
        count(*) as pool_champion_count,
        max(champion_share) as pool_top1_share,
        sum(case when points_rank <= 3 then champion_share end) as pool_top3_share,
        sum(pow(champion_share, 2)) as pool_hhi,
        -sum(case when champion_share > 0 then champion_share * log2(champion_share) end) as pool_entropy
    from pool_shares
    group by player_id

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
        sum(cr.avg_support_pct * ac.role_weight_factor) as sum_support
    from active_champions ac
    join {{ ref('dim_champion_role_weights') }} cr
        on ac.champion_key = cr.champion_key
    -- a champion nobody has sampled has all five averages null (they are
    -- null all-or-nothing, since they share a denominator upstream). Drop it
    -- instead of letting its weight sit in the normalisation denominator.
    where cr.avg_top_pct is not null
    group by ac.player_id

),

role_totals as (

    select
        *,
        coalesce(sum_top, 0) + coalesce(sum_jungle, 0) + coalesce(sum_middle, 0)
            + coalesce(sum_bottom, 0) + coalesce(sum_support, 0) as role_weight_total
    from player_role_sums

),

role_shares as (

    select
        player_id,
        {{ dbt_utils.safe_divide('sum_top',     'role_weight_total') }} as role_top_pct,
        {{ dbt_utils.safe_divide('sum_jungle',  'role_weight_total') }} as role_jungle_pct,
        {{ dbt_utils.safe_divide('sum_middle',  'role_weight_total') }} as role_middle_pct,
        {{ dbt_utils.safe_divide('sum_bottom',  'role_weight_total') }} as role_bottom_pct,
        {{ dbt_utils.safe_divide('sum_support', 'role_weight_total') }} as role_support_pct
    from role_totals

),

role_profile as (

    select
        *,
        case
            when role_top_pct is null then null
            else
                pow(coalesce(role_top_pct, 0), 2)
                + pow(coalesce(role_jungle_pct, 0), 2)
                + pow(coalesce(role_middle_pct, 0), 2)
                + pow(coalesce(role_bottom_pct, 0), 2)
                + pow(coalesce(role_support_pct, 0), 2)
        end as role_purity
    from role_shares

),

main_role as (

    select
        player_id,
        role_name,
        role_weight
    from (
        select player_id, 'Top'     as role_name, role_top_pct     as role_weight from role_shares
        union all
        select player_id, 'Jungle'  as role_name, role_jungle_pct  as role_weight from role_shares
        union all
        select player_id, 'Middle'  as role_name, role_middle_pct  as role_weight from role_shares
        union all
        select player_id, 'Bottom'  as role_name, role_bottom_pct  as role_weight from role_shares
        union all
        select player_id, 'Support' as role_name, role_support_pct as role_weight from role_shares
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

    -- pool concentration over recent points on the active champions
    pc.pool_top1_share,
    pc.pool_top3_share,
    pc.pool_hhi,
    pc.pool_entropy,
    case
        when pc.pool_entropy is null then null
        when pc.pool_champion_count <= 1 then 0
        else {{ dbt_utils.safe_divide('pc.pool_entropy', 'log2(pc.pool_champion_count)') }}
    end as pool_normalized_entropy,

    -- points-weighted lane mix
    rp.role_top_pct,
    rp.role_jungle_pct,
    rp.role_middle_pct,
    rp.role_bottom_pct,
    rp.role_support_pct,
    rp.role_purity,

    m.role_name as main_role,
    m.role_weight as main_role_weight
from {{ ref('dim_players_current') }} p
left join aggregated a
    on p.puuid = a.player_id
left join main_role m
    on p.puuid = m.player_id
left join player_level pl
    on p.puuid = pl.player_id
left join pool_concentration pc
    on p.puuid = pc.player_id
left join role_profile rp
    on p.puuid = rp.player_id
