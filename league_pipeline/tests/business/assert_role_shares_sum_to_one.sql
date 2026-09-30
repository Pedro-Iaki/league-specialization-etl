-- A populated role distribution must contain all five roles, keep every share
-- in [0, 1], and allocate exactly one whole player distribution.

select
    player_id,
    top_pct,
    jungle_pct,
    middle_pct,
    bottom_pct,
    support_pct
from {{ ref('dim_players_naive_role_distribution') }}
where coalesce(top_pct, jungle_pct, middle_pct, bottom_pct, support_pct) is not null
  and (
      top_pct is null
      or jungle_pct is null
      or middle_pct is null
      or bottom_pct is null
      or support_pct is null
      or top_pct not between 0 and 1
      or jungle_pct not between 0 and 1
      or middle_pct not between 0 and 1
      or bottom_pct not between 0 and 1
      or support_pct not between 0 and 1
      or abs(top_pct + jungle_pct + middle_pct + bottom_pct + support_pct - 1.0) > 1e-9
  )
