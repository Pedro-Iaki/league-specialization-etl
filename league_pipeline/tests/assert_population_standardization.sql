{{ config(tags=['population_weighting']) }}

select region, queue, cohort, metric
from {{ ref('mart_player_population_standardization') }}
group by region, queue, cohort, metric
having count(*) != 10
    or min(covered_population_share) < 0
    or max(covered_population_share) > 1.00000001
    or abs(sum(coalesce(supported_target_share, 0))
        - case when max(covered_population_share) > 0 then 1.0 else 0.0 end) > 0.00000001
    or sum(case when tier_supported = 1 and metric_players < minimum_tier_players then 1 else 0 end) > 0
    or sum(case when tier_supported = 0 and supported_target_share is not null then 1 else 0 end) > 0
    or sum(case when covered_population_share = 0 and standardized_mean is not null then 1 else 0 end) > 0
    or sum(case when covered_population_share > 0 and standardized_mean is null then 1 else 0 end) > 0
    or abs(max(standardized_mean) - sum(coalesce(supported_target_share * tier_mean, 0))) > 0.00000001
