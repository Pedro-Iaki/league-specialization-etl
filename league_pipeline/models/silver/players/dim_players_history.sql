{{ config(
    materialized='incremental',
    file_format='delta',
    incremental_strategy='merge',
    unique_key='player_history_id',
    on_schema_change='append_new_columns'
) }}

{% set mastery_freshness_days = var('mastery_freshness_days') %}
{% set late_arrival_lookback_days = var('late_arrival_lookback_days') %}
{% set dedup_days_range = var('dedup_days_range') %}

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
        _ingested_at,
        floor(datediff(DAY, '2009-01-01', snapshot_date) / {{ dedup_days_range }}) as _weekly_bucket
    from {{ ref('bronze_players') }} p
    where exists (
        select 1
        from {{ ref('bronze_masteries') }} m
        where m.puuid = p.puuid
          and abs(datediff(DAY,
              to_date(m.date, 'yyMMdd'),
              to_date(p.date, 'yyMMdd')
          )) <= {{ mastery_freshness_days }}
    )

    {% if is_incremental() %}
      and to_date(p.date, 'yyMMdd') >= (
                    select date_sub(max(snapshot_date), {{ late_arrival_lookback_days }})
          from {{ this }}
      )
    {% endif %}

    qualify row_number() over (
        partition by
            puuid,
            _weekly_bucket
        order by _ingested_at desc
    ) = 1

)

select
    {{ dbt_utils.generate_surrogate_key(['puuid', '_weekly_bucket']) }} as player_history_id,
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
    snapshot_date
from source