
select * from (
    {{ champion_tier_growth() }}
) tiers
union all
select * from (
    {{ champion_tier_growth(true) }}
) styles
