{{ config(materialized='view') }}

-- absolute_lp is computed here rather than in the marts so that
-- dim_players_current (which is `select * except(valid_to)` off this view)
-- carries it for free. This is a view, so no backfill is needed: the column
-- appears on the next run with no --full-refresh of dim_players_history.

select
    *,
    {{ absolute_lp('tier', 'division', 'league_points') }} as absolute_lp,
    lead(snapshot_date) over (
        partition by puuid order by snapshot_date
    ) as valid_to
from {{ ref('dim_players_history') }}
