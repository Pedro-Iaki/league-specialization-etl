{{ config(materialized='table', file_format='delta') }}

-- Latest rank movement per (player_id, queue): the newest snapshot, kept only
-- if something moved. This is a thin filter over fct_players_rank_history and
-- returns the same rows the previous standalone version did, so
-- mart_champion_analysis is unaffected.
--
-- For trends or anything historical use fct_players_rank_history or
-- mart_player_delta_history instead.

select *
from {{ ref('fct_players_rank_history') }}
qualify snapshot_date = max(snapshot_date) over (partition by player_id, queue)
    and has_movement