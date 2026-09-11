{{ config(
    materialized='incremental',
    file_format='delta',
    incremental_strategy='merge',
    unique_key='player_history_id',
    on_schema_change='append_new_columns'
) }}

with source as (

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
        to_date(date, 'yyMMdd') as snapshot_date,
        wins,
        losses,
        wins + losses as total_games,
        {{ dbt_utils.safe_divide('wins', 'wins + losses') }} as win_rate,
        freshBlood as in_motion,
        _ingested_at
    from {{ ref('bronze_players') }}

    {% if is_incremental() %}
    where snapshot_date > (select max(valid_from) from {{ this }})
    {% endif %}

),

{% set dedup_days_range = 7 %}

deduped as (

    select *
    from source
    qualify row_number() over (
        partition by
            puuid,
            floor(datediff(DAY, '2009-01-01', snapshot_date) / {{ dedup_days_range }})
        order by _ingested_at desc
    ) = 1

)

select
    {{ dbt_utils.generate_surrogate_key(['puuid', 'snapshot_date']) }} as player_history_id,
    puuid,
    region,
    queue,
    tier,
    division,
    patch,
    wins,
    losses,
    total_games,
    win_rate,
    in_motion,
    snapshot_date as valid_from
from deduped