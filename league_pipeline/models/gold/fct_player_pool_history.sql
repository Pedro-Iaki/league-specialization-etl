{{ config(
    materialized='incremental',
    file_format='delta',
    incremental_strategy='append',
    on_schema_change='append_new_columns',
    full_refresh=false
) }}

-- Frozen, append-only history of dim_players_active_pool: one row per
-- (player_id, snapshot_date), written the first time a player's snapshot is
-- seen and never touched again ("first write wins"). This is what lets
-- pool / role / activity features be joined to a historical rank delta as they
-- were AT THAT TIME rather than as they are today.
--
-- Why append-only: activity and pool are dense and depend on a moving as-of
-- date, so a past date cannot be recomputed later. History starts on the first
-- run of this model and cannot be back-filled.
--
-- full_refresh=false stops `dbt run --full-refresh` from wiping the history.
-- To rebuild deliberately, drop the table by hand. Rows keep the definition
-- they were written with; if the pool logic changes, older rows will not be
-- updated.

select
    {{ dbt_utils.generate_surrogate_key(['s.player_id', 's.snapshot_date']) }} as player_pool_history_id,
    s.*
from {{ ref('dim_players_active_pool') }} s
{% if is_incremental() %}
where not exists (
    select 1
    from {{ this }} h
    where h.player_id = s.player_id
      and h.snapshot_date = s.snapshot_date
)
{% endif %}