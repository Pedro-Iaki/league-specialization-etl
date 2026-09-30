{{ config(materialized='table', file_format='delta') }}

{% set min_pair_players = var('cooccurrence_min_pair_players', 5) %}

with as_of as (

    select max(as_of_date) as as_of_date
    from {{ ref('fct_players_champion_activity') }}

),

pool as (

    select distinct
        player_id,
        champion_key
    from {{ ref('fct_players_champion_activity') }}
    where is_active

),

pool_total as (

    select count(distinct player_id) as pool_player_count
    from pool

),

champion_totals as (

    select
        champion_key,
        count(*) as player_count
    from pool
    group by champion_key

),

pairs as (

    select
        a.champion_key as champion_key_a,
        b.champion_key as champion_key_b,
        count(*) as pair_player_count
    from pool a
    join pool b
        on a.player_id = b.player_id
        and a.champion_key < b.champion_key
    group by a.champion_key, b.champion_key
    having count(*) >= {{ min_pair_players }}

),

metrics as (

    select
        p.champion_key_a,
        p.champion_key_b,
        p.pair_player_count,
        t.pool_player_count,
        ta.player_count as player_count_a,
        tb.player_count as player_count_b,
        {{ dbt_utils.safe_divide('cast(p.pair_player_count as double)', 't.pool_player_count') }} as support_pair,
        {{ dbt_utils.safe_divide(
            'cast(p.pair_player_count as double)',
            '(ta.player_count + tb.player_count - p.pair_player_count)'
        ) }} as jaccard,
        {{ dbt_utils.safe_divide('cast(p.pair_player_count as double)', 'ta.player_count') }} as prob_b_given_a,
        {{ dbt_utils.safe_divide('cast(p.pair_player_count as double)', 'tb.player_count') }} as prob_a_given_b,
        {{ dbt_utils.safe_divide(
            'cast(p.pair_player_count as double) * t.pool_player_count',
            'cast(ta.player_count as double) * tb.player_count'
        ) }} as lift
    from pairs p
    cross join pool_total t
    join champion_totals ta
        on p.champion_key_a = ta.champion_key
    join champion_totals tb
        on p.champion_key_b = tb.champion_key

)

select
    {{ dbt_utils.generate_surrogate_key(['m.champion_key_a', 'm.champion_key_b']) }} as champion_pair_id,
    ao.as_of_date,

    m.champion_key_a,
    ca.name as champion_name_a,
    m.champion_key_b,
    cb.name as champion_name_b,

    m.pool_player_count,
    m.player_count_a,
    m.player_count_b,
    m.pair_player_count,

    m.jaccard,
    m.prob_b_given_a,
    m.prob_a_given_b,
    m.lift,
    {{ dbt_utils.safe_divide(
        'log2(nullif(m.lift, 0))',
        '-log2(nullif(m.support_pair, 0))'
    ) }} as npmi

from metrics m
cross join as_of ao
left join {{ ref('dim_champions') }} ca
    on m.champion_key_a = ca.key
left join {{ ref('dim_champions') }} cb
    on m.champion_key_b = cb.key
