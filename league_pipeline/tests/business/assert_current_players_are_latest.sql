-- The current player dimension must contain exactly the latest observed row
-- for every player and queue in player history.

with expected as (

    select
        puuid,
        queue,
        max(snapshot_date) as snapshot_date
    from {{ ref('dim_players_history') }}
    group by puuid, queue

),

actual as (

    select puuid, queue, snapshot_date
    from {{ ref('dim_players_current') }}

)

select
    coalesce(e.puuid, a.puuid) as puuid,
    coalesce(e.queue, a.queue) as queue,
    e.snapshot_date as expected_snapshot_date,
    a.snapshot_date as actual_snapshot_date
from expected e
full outer join actual a
    on e.puuid = a.puuid
    and e.queue = a.queue
where e.puuid is null
   or a.puuid is null
   or e.snapshot_date <> a.snapshot_date
