-- The published playstyle must be the highest-scoring archetype. The CASE
-- order intentionally mirrors the deterministic tie-break used by the models.

with profiles as (

    select
        'lifetime_mastery' as profile_type,
        cast(player_id as string) as profile_id,
        mastery_playstyle as actual_playstyle,
        mastery_specialist_score as specialist_score,
        mastery_multispecialist_score as multispecialist_score,
        mastery_versatile_score as versatile_score,
        mastery_generalist_score as generalist_score
    from {{ ref('fct_players_mastery_profile') }}

    union all

    select
        'active_pool',
        cast(player_id as string),
        playstyle,
        specialist_score,
        multispecialist_score,
        versatile_score,
        generalist_score
    from {{ ref('dim_players_active_pool') }}

    union all

    select
        'rank_period',
        cast(rank_delta_id as string),
        playstyle,
        specialist_score,
        multispecialist_score,
        versatile_score,
        generalist_score
    from {{ ref('fct_players_period_pool_profile') }}

),

expected as (

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
        end as expected_playstyle
    from profiles
    where coalesce(
        specialist_score,
        multispecialist_score,
        versatile_score,
        generalist_score
    ) is not null

)

select
    profile_type,
    profile_id,
    actual_playstyle,
    expected_playstyle
from expected
where actual_playstyle is null
   or actual_playstyle <> expected_playstyle
