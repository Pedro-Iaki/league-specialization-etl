{{ config(
    materialized='table',
    file_format='delta',
    alias='players',
    on_schema_change='append_new_columns'
) }}

with latest_player_snapshot as (
    select *, to_date(date, 'yyMMdd') as fetch_date
    from {{ source('bronze', 'players') }}
    qualify row_number() over (
        partition by puuid
        order by fetch_date desc, _ingested_at desc
    ) = 1
),

select
    puuid,
    region,
    queueType as queue,
    tier,
    case upper(trim(`rank`))
        when 'I' then 1
        when 'II' then 2
        when 'III' then 3
        when 'IV' then 4
        else null
    end as division,
    patch,
    wins,
    losses,
    wins + losses as total_games,
    {{ dbt_utils.safe_divide('wins', 'wins + losses') }} as win_rate,
    freshBlood as recently_climbed
from latest_player_snapshot

