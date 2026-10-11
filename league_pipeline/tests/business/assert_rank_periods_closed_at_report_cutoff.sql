select rank_period_id
from {{ ref('fct_players_rank_periods') }}
where date_add(period_bucket_start, period_bucket_days) > {{ report_cutoff() }}
