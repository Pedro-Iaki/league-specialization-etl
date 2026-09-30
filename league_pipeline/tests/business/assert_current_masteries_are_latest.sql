-- Current mastery must contain exactly the latest observation for every
-- standard player/champion combination retained in mastery history.

with expected as (

    select
        puuid,
        champion_key,
        max(snapshot_date) as snapshot_date
    from {{ ref('fct_masteries_history') }}
    group by puuid, champion_key

),

actual as (

    select puuid, champion_key, snapshot_date
    from {{ ref('fct_masteries_current') }}

)

select
    coalesce(e.puuid, a.puuid) as puuid,
    coalesce(e.champion_key, a.champion_key) as champion_key,
    e.snapshot_date as expected_snapshot_date,
    a.snapshot_date as actual_snapshot_date
from expected e
full outer join actual a
    on e.puuid = a.puuid
    and e.champion_key = a.champion_key
where e.puuid is null
   or a.puuid is null
   or e.snapshot_date <> a.snapshot_date
