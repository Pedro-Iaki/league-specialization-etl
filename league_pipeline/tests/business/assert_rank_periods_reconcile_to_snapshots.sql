with periods as (

    select *
    from {{ ref('fct_players_rank_periods') }}

)

select r.rank_period_id
from periods r
left join {{ ref('dim_players_history') }} current_snapshot
    on r.player_id = current_snapshot.puuid
    and r.queue = current_snapshot.queue
    and r.snapshot_date = current_snapshot.snapshot_date
left join {{ ref('dim_players_history') }} previous_snapshot
    on r.player_id = previous_snapshot.puuid
    and r.queue = previous_snapshot.queue
    and r.previous_snapshot_date = previous_snapshot.snapshot_date
where current_snapshot.puuid is null
   or previous_snapshot.puuid is null
   or datediff(r.period_bucket_start, date_sub(r.previous_snapshot_date,
       pmod(datediff(r.previous_snapshot_date, date('1970-01-05')), r.period_bucket_days)
   )) <> r.period_bucket_days
   or r.period_in_days < greatest(1, r.period_bucket_days - 1)
   or r.period_in_days > r.period_bucket_days + 1
   or r.snapshot_date > r.period_bucket_end
   or not (r.wins_delta <=> current_snapshot.wins - previous_snapshot.wins)
   or not (r.losses_delta <=> current_snapshot.losses - previous_snapshot.losses)
   or not (r.games_delta <=>
       current_snapshot.wins + current_snapshot.losses
       - previous_snapshot.wins - previous_snapshot.losses
   )
   or exists (
       select 1
       from {{ ref('fct_players_rank_history') }} h
       where h.player_id = r.player_id
         and h.queue = r.queue
         and h.snapshot_date > r.previous_snapshot_date
         and h.snapshot_date <= r.snapshot_date
         and h.is_counter_reset
   )
