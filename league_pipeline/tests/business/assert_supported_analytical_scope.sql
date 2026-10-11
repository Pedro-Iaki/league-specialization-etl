-- Current player/profile/history grains are reviewed for one platform and solo queue.
select 'unsupported analytical scope' as failure
from {{ ref('mart_player_profile') }}
having count(distinct region) != 1
    or count(distinct queue) != 1
    or max(queue) != '{{ var("ranked_queue", "RANKED_SOLO_5x5") }}'
    or count(region) != count(*)
    or count(queue) != count(*)
