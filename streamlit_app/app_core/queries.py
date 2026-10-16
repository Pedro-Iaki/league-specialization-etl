from __future__ import annotations

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app_core.business import BUSINESS_PUBLIC_COLUMNS
from app_core.config import REPO_ROOT


def _analysis_query(name: str) -> str:
    """Render saved growth SQL directly from the same macro dbt uses."""
    relations = {
        "dim_champions": "league_pipeline.silver.dim_champions",
        "fct_players_period_champion_growth": "league_pipeline.gold.fct_players_period_champion_growth",
    }
    environment = Environment(
        loader=FileSystemLoader(REPO_ROOT / "league_pipeline"), undefined=StrictUndefined,
    )
    environment.globals["ref"] = lambda relation: relations[relation]
    macros = environment.get_template("macros/champion_player_growth.sql").module
    environment.globals.update(
        champion_player_growth=macros.champion_player_growth,
        champion_tier_growth=macros.champion_tier_growth,
    )
    return environment.get_template(f"analyses/{name}.sql").render().strip()


DATASET_QUERIES = {
    "champion_population_pairs": """
        with pool as (
            select distinct a.player_id, a.champion_key, p.region, p.queue, p.tier
            from league_pipeline.gold.fct_players_champion_activity a
            join league_pipeline.gold.mart_player_profile p on a.player_id = p.player_id
            where a.is_active
        ), population as (
            select region, queue, tier, count(distinct player_id) as pool_player_count
            from pool group by region, queue, tier
        ), totals as (
            select region, queue, tier, champion_key, count(*) as player_count
            from pool group by region, queue, tier, champion_key
        ), pairs as (
            select a.region, a.queue, a.tier, a.champion_key as champion_key_a,
                   b.champion_key as champion_key_b, count(*) as pair_player_count
            from pool a join pool b on a.player_id = b.player_id and a.champion_key < b.champion_key
                and a.region <=> b.region and a.queue <=> b.queue and a.tier <=> b.tier
            group by a.region, a.queue, a.tier, a.champion_key, b.champion_key
        )
        select r.champion_key_a, r.champion_name_a, r.champion_key_b, r.champion_name_b,
               p.region, p.queue, p.tier, p.pool_player_count,
               coalesce(a.player_count, 0) as player_count_a,
               coalesce(b.player_count, 0) as player_count_b,
               coalesce(j.pair_player_count, 0) as pair_player_count
        from league_pipeline.gold.mart_champion_cooccurrence r
        cross join population p
        left join totals a on r.champion_key_a = a.champion_key
            and p.region <=> a.region and p.queue <=> a.queue and p.tier <=> a.tier
        left join totals b on r.champion_key_b = b.champion_key
            and p.region <=> b.region and p.queue <=> b.queue and p.tier <=> b.tier
        left join pairs j on r.champion_key_a = j.champion_key_a and r.champion_key_b = j.champion_key_b
            and p.region <=> j.region and p.queue <=> j.queue and p.tier <=> j.tier
    """,
    "champion_population_activity": """
        with active as (
            select a.champion_key, p.region, p.queue, p.tier,
                   count(*) as active_player_count, avg(a.recent_share) as mean_active_share,
                   count(p.role_top_pct) as role_sample_player_count,
                   avg(p.role_top_pct) as role_top_pct, avg(p.role_jungle_pct) as role_jungle_pct,
                   avg(p.role_middle_pct) as role_middle_pct, avg(p.role_bottom_pct) as role_bottom_pct,
                   avg(p.role_support_pct) as role_support_pct
            from league_pipeline.gold.fct_players_champion_activity a
            join league_pipeline.gold.mart_player_profile p on a.player_id = p.player_id
            where a.is_active
            group by a.champion_key, p.region, p.queue, p.tier
        ), population as (
            select p.region, p.queue, p.tier, count(distinct p.player_id) as active_pool_player_count
            from league_pipeline.gold.mart_player_profile p
            join league_pipeline.gold.fct_players_champion_activity a on p.player_id = a.player_id
            where a.is_active
            group by p.region, p.queue, p.tier
        )
        select c.name as champion_name, p.region, p.queue, p.tier,
               coalesce(a.active_player_count, 0) as active_player_count,
               p.active_pool_player_count, a.mean_active_share,
               coalesce(a.role_sample_player_count, 0) as role_sample_player_count,
               a.role_top_pct, a.role_jungle_pct, a.role_middle_pct, a.role_bottom_pct, a.role_support_pct
        from league_pipeline.silver.dim_champions c
        cross join population p
        left join active a on c.key = a.champion_key
            and p.region <=> a.region and p.queue <=> a.queue and p.tier <=> a.tier
    """,
    "business_players": "select " + ", ".join(BUSINESS_PUBLIC_COLUMNS) + " from league_pipeline.gold.mart_player_spending",
    "champion_player_mastery_share": """
        select
            c.name as champion_name,
            p.region,
            p.queue,
            p.tier,
            m.champion_points,
            p.total_mastery_points,
            m.champion_points / p.total_mastery_points as mastery_share
        from league_pipeline.silver.fct_masteries_current m
        inner join league_pipeline.gold.mart_player_profile p on m.puuid = p.player_id
        inner join league_pipeline.silver.dim_champions c on m.champion_key = c.key
        where m.champion_points >= 15000
          and p.total_mastery_points > 0
          and p.tier in ('IRON', 'BRONZE', 'SILVER', 'GOLD', 'PLATINUM', 'EMERALD', 'DIAMOND', 'MASTER')
    """,
    "champion_tier_mastery": """
        with thresholds as (
            select explode(array_union(sequence(0, 100000, 10000), array(15000, 250000, 500000, 1000000))) as minimum_mastery
        ), observations as (
            select
            c.name as champion_name,
            p.tier,
            t.minimum_mastery,
            m.champion_points,
            p.rank_score
            from league_pipeline.silver.fct_masteries_current m
            join league_pipeline.gold.mart_player_profile p on m.puuid = p.player_id
            join league_pipeline.silver.dim_champions c on m.champion_key = c.key
            cross join thresholds t
            where m.champion_points >= t.minimum_mastery
              and p.tier in ('IRON', 'BRONZE', 'SILVER', 'GOLD', 'PLATINUM', 'EMERALD', 'DIAMOND', 'MASTER')
        )
        select
            champion_name,
            coalesce(tier, 'ALL') as tier,
            minimum_mastery,
            count(*) as player_count,
            count(case when champion_points >= 100000 then 1 end) as expert_player_count,
            avg(champion_points) as mean_mastery,
            percentile(champion_points, 0.25) as q1_mastery,
            percentile(champion_points, 0.5) as median_mastery,
            percentile(champion_points, 0.75) as q3_mastery,
            min(champion_points) as min_mastery,
            max(champion_points) as max_mastery,
            avg(rank_score) as mean_rank_score,
            percentile(rank_score, 0.5) as median_rank_score
        from observations
        group by champion_name, minimum_mastery, rollup(tier)
    """,
    "players": """
        select
            as_of_date,
            snapshot_date,
            region,
            queue,
            patch,
            tier,
            tier_order,
            division,
            league_points,
            rank_score,
            total_games,
            win_rate,
            form_window_days,
            games_recent,
            lp_delta_recent,
            win_rate_recent,
            lp_per_game_recent,
            lp_per_day_recent,
            games_per_day_recent,
            form_days_covered,
            role_top_pct,
            role_jungle_pct,
            role_middle_pct,
            role_bottom_pct,
            role_support_pct,
            role_purity,
            main_role,
            main_role_weight,
            role_champions_sampled_count,
            active_champion_count,
            recent_total_points,
            active_primary_champion_key,
            active_primary_champion_name,
            active_playstyle,
            active_top1_share,
            active_favoured_champion_count,
            active_favoured_champions_share,
            active_hhi,
            active_normalized_entropy,
            champions_with_mastery,
            total_mastery_points,
            top_champion_key,
            top_champion_name,
            alltime_top1_share,
            alltime_favoured_champion_count,
            alltime_favoured_champions_share,
            alltime_hhi,
            alltime_normalized_entropy,
            alltime_playstyle,
            alltime_points_per_day,
            days_since_last_play,
            days_tracked
        from league_pipeline.gold.mart_player_profile
    """,
    "champions": """
        select *
        from league_pipeline.gold.mart_champion_profile
    """,
    "cooccurrence": """
        select * except(champion_pair_id)
        from league_pipeline.gold.mart_champion_cooccurrence
    """,
    "growth_players": """
        with player_tiers as (
            select
                player_id,
                previous_tier as starting_tier,
                percentile(pool_hhi, 0.5) as specialization_hhi,
                percentile(pool_top1_share, 0.5) as top_champion_share,
                percentile(pool_normalized_entropy, 0.5) as normalized_entropy,
                percentile(estimated_ranked_mastery_share, 0.5) as estimated_ranked_mastery_share,
                percentile(lp_per_game_lift_vs_tier, 0.5) as climbing_efficiency,
                sum(wins_delta) / nullif(sum(games_delta), 0) as win_rate,
                count(*) as period_count,
                sum(games_delta) as games
            from league_pipeline.gold.mart_player_delta_history
            where is_lp_growth_eligible
              and playstyle is not null
              and pool_hhi is not null
              and lp_per_game_lift_vs_tier is not null
            group by player_id, previous_tier
        )
        select
            p.starting_tier,
            current_player.region,
            current_player.queue,
            current_player.main_role as current_main_role,
            p.specialization_hhi,
            p.top_champion_share,
            p.normalized_entropy,
            p.estimated_ranked_mastery_share,
            p.climbing_efficiency,
            p.win_rate,
            p.period_count,
            p.games
        from player_tiers p
        left join league_pipeline.gold.mart_player_profile current_player
            on p.player_id = current_player.player_id
    """,
    "champion_growth_players": _analysis_query("champion_growth_players"),
    "growth_player_styles": """
        with player_cohorts as (
            select
                player_id,
                previous_tier as starting_tier,
                playstyle,
                percentile(lp_per_game_lift_vs_tier, 0.5) as climbing_efficiency,
                sum(wins_delta) / nullif(sum(games_delta), 0) as win_rate,
                count(*) as period_count,
                sum(games_delta) as games
            from league_pipeline.gold.mart_player_delta_history
            where is_lp_growth_eligible
              and playstyle is not null
              and lp_per_game_lift_vs_tier is not null
            group by player_id, previous_tier, playstyle
        )
        select
            p.starting_tier,
            p.playstyle,
            current_player.region,
            current_player.queue,
            current_player.main_role as current_main_role,
            p.climbing_efficiency,
            p.win_rate,
            p.period_count,
            p.games
        from player_cohorts p
        left join league_pipeline.gold.mart_player_profile current_player
            on p.player_id = current_player.player_id
    """,
    "champion_tier_growth": _analysis_query("champion_tier_growth"),
    "ranked_mastery_cohorts": """
        with latest as (
            select max(period_bucket_end) as latest_period_end
            from league_pipeline.gold.mart_player_delta_history
            where estimated_ranked_mastery_share is not null
        ),
        windows as (
            select 'Latest completed period' as window_name, 0 as days_back
            union all select 'Last 30 days', 29
            union all select 'Last 60 days', 59
            union all select 'All observed periods', cast(null as int)
        ),
        eligible_periods as (
            select
                w.window_name,
                p.rank_period_id,
                p.player_id,
                p.previous_tier,
                p.period_bucket_end,
                p.estimated_ranked_mastery_share
            from league_pipeline.gold.mart_player_delta_history p
            cross join latest l
            cross join windows w
            where p.estimated_ranked_mastery_share is not null
              and (w.days_back is null
                   or p.period_bucket_end >= date_sub(l.latest_period_end, w.days_back))
        ),
        player_windows as (
            select
                window_name,
                player_id,
                max_by(previous_tier, period_bucket_end) as starting_tier,
                percentile(estimated_ranked_mastery_share, 0.5) as median_ranked_mastery_share,
                count(*) as period_count,
                min(period_bucket_end) as first_period_end,
                max(period_bucket_end) as last_period_end
            from eligible_periods
            group by window_name, player_id
        ),
        champions as (
            select
                p.window_name,
                p.player_id,
                sort_array(collect_set(a.champion_name)) as favoured_champions
            from eligible_periods p
            left join league_pipeline.gold.fct_players_period_champion_activity a
                on p.rank_period_id = a.rank_period_id
               and a.is_favoured
            group by p.window_name, p.player_id
        )
        select
            p.window_name,
            p.starting_tier,
            current_player.region,
            current_player.queue,
            current_player.main_role as current_main_role,
            p.median_ranked_mastery_share,
            p.period_count,
            p.first_period_end,
            p.last_period_end,
            c.favoured_champions
        from player_windows p
        left join champions c
            on p.window_name = c.window_name
           and p.player_id = c.player_id
        left join league_pipeline.gold.mart_player_profile current_player
            on p.player_id = current_player.player_id
    """,
}
