{{ config(tags=['population_weighting']) }}

-- Require a complete, positive, normalized, single-version manual reference.
select 'invalid population reference' as failure
from {{ ref('rank_population_reference') }}
having count(*) != 10
    or abs(sum(population_share) - 1.0) > 0.00000001
    or min(population_share) <= 0
    or count(distinct reference_version) != 1
    or count(distinct recorded_on) != 1
    or count(distinct review_after) != 1
    or count(distinct source) != 1
    or count(distinct reference_scope) != 1
    or min(review_after) <= max(recorded_on)
