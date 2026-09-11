{{ config(materialized='table', file_format='delta') }}

with masteries as (

    select
        m.puuid,
        m.champion_key,
        m.champion_points,
        c.expected_positions
    from {{ ref('fct_masteries_current') }} m
    inner join {{ ref('dim_champions') }} c on m.champion_key = c.key
    where m.champion_points > 0

),

player_champs as (

    select
        puuid,
        sum(champion_points) as total_mastery,
        array_sort(
            collect_list(struct(champion_points, champion_key, expected_positions)),
            (a, b) -> case
                when a.champion_points > b.champion_points then -1
                when a.champion_points < b.champion_points then 1
                else 0
            end
        ) as sorted_champs
    from masteries
    group by puuid

),

top10 as (

    select
        puuid,
        total_mastery,
        sorted_champs,
        slice(sorted_champs, 1, 10) as top10_champs
    from player_champs

),

gaps as (

    select
        puuid,
        total_mastery,
        sorted_champs,
        top10_champs,
        size(top10_champs) as n_top10,
        zip_with(
            slice(transform(top10_champs, x -> x.champion_points), 1, size(top10_champs) - 1),
            slice(transform(top10_champs, x -> x.champion_points), 2, size(top10_champs) - 1),
            (a, b) -> ln(a / b)
        ) as log_gaps
    from top10

),

gap_stats as (

    select
        *,
        array_max(log_gaps) as largest_log_gap,
        array_position(log_gaps, array_max(log_gaps)) - 1 as largest_gap_idx,
        case
            when size(log_gaps) = 0 then null
            when size(log_gaps) % 2 = 1
                then element_at(array_sort(log_gaps), cast((size(log_gaps) + 1) / 2 as int))
            else (
                element_at(array_sort(log_gaps), cast(size(log_gaps) / 2 as int))
                + element_at(array_sort(log_gaps), cast(size(log_gaps) / 2 as int) + 1)
            ) / 2.0
        end as median_log_gap
    from gaps

),

pool_calc as (

    select
        *,
        case
            when n_top10 = 1 then 1
            when median_log_gap > 0 and largest_log_gap >= 1.5 * median_log_gap then largest_gap_idx + 1
            else 10
        end as pool_size,
        case when median_log_gap > 0 then largest_log_gap / median_log_gap else null end as pool_exclusivity
    from gap_stats

),

pool_members as (

    select
        *,
        slice(sorted_champs, 1, least(pool_size, n_top10)) as pool_champs_struct,
        aggregate(transform(top10_champs, x -> x.champion_points), cast(0 as double), (acc, x) -> acc + x) as top10_total
    from pool_calc

),

pool_metrics as (

    select
        puuid,
        total_mastery,
        pool_size,
        pool_exclusivity,
        top10_total,
        transform(pool_champs_struct, x -> x.champion_key) as pool_champions,
        transform(pool_champs_struct, x -> x.champion_points / top10_total) as pool_normalized,
        aggregate(transform(pool_champs_struct, x -> x.champion_points), cast(0 as double), (acc, x) -> acc + x) as pool_total,
        flatten(transform(
            pool_champs_struct,
            x -> coalesce(x.expected_positions, cast(array() as array<string>))
        )) as pool_role_tags
    from pool_members

),

with_role_counts as (

    select
        *,
        transform(
            array_distinct(pool_role_tags),
            r -> struct(r as role, size(filter(pool_role_tags, y -> y = r)) as role_count)
        ) as role_counts
    from pool_metrics

),

roles as (

    select
        *,
        array_max(transform(role_counts, x -> x.role_count)) as max_role_count
    from with_role_counts

)

select
    p.puuid,
    r.total_mastery,
    r.pool_size,
    r.pool_exclusivity,
    case
        when r.top10_total > 0
            then 1 - (array_max(r.pool_normalized) - array_min(r.pool_normalized))
    end as pool_bias,
    case
        when r.total_mastery > 0
            then r.pool_total / r.total_mastery
    end as pool_depth,
    array_sort(transform(filter(r.role_counts, x -> x.role_count = r.max_role_count), x -> x.role)) as main_role,
    array_sort(transform(filter(r.role_counts, x -> x.role_count / r.pool_size >= 0.4), x -> x.role)) as all_roles,
    r.pool_champions,
    cast(0.0 as double) as volatility
from {{ ref('dim_players_current') }} p
left join roles r on p.puuid = r.puuid
