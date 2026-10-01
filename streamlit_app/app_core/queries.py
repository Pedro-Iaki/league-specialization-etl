from __future__ import annotations

DATASET_QUERIES = {
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
    "champion_playstyles": """
        select * except(champion_playstyle_id)
        from league_pipeline.gold.mart_champion_playstyle_profile
    """,
    "cooccurrence": """
        select * except(champion_pair_id)
        from league_pipeline.gold.mart_champion_cooccurrence
    """,
    "rank_growth": """
        select
            region,
            queue,
            previous_tier,
            previous_division,
            previous_league_points,
            previous_rank_score,
            tier,
            division,
            league_points,
            rank_score,
            previous_snapshot_date,
            snapshot_date,
            period_in_days,
            wins_delta,
            losses_delta,
            games_delta,
            lp_delta,
            is_lp_growth_eligible,
            champion_count,
            mastery_points_gained,
            primary_champion_key,
            primary_champion_name,
            primary_champion_points,
            pool_top1_share,
            pool_favoured_champion_count,
            pool_favoured_champions_share,
            pool_hhi,
            pool_normalized_entropy,
            playstyle,
            tier_lp_per_game_baseline,
            lp_per_game,
            lp_per_day,
            period_win_rate,
            lp_per_game_lift_vs_tier
        from league_pipeline.gold.mart_player_delta_history
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
    "champion_growth_players": """
        select
            c.name as champion_name,
            s.champion_key,
            s.starting_tier,
            s.player_mean_champion_share as champion_commitment,
            s.player_mean_pool_hhi as specialization_hhi,
            s.player_mean_pool_top1_share as top_champion_share,
            s.median_lp_per_game_lift_vs_tier as climbing_efficiency,
            s.player_win_rate as win_rate,
            s.observed_period_count as period_count,
            s.attributed_games
        from league_pipeline.gold.fct_players_champion_growth_summary s
        inner join league_pipeline.silver.dim_champions c
            on s.champion_key = c.key
        where s.cohort_scope = 'champion_tier'
    """,
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
            current_player.main_role as current_main_role,
            p.climbing_efficiency,
            p.win_rate,
            p.period_count,
            p.games
        from player_cohorts p
        left join league_pipeline.gold.mart_player_profile current_player
            on p.player_id = current_player.player_id
    """,
    "champion_tier_growth": """
        select * except(champion_tier_growth_id)
        from league_pipeline.gold.mart_champion_tier_growth
    """,
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


REQUIRED_COLUMNS = {
    "players": {
        "as_of_date",
        "tier",
        "tier_order",
        "rank_score",
        "active_playstyle",
        "alltime_playstyle",
        "main_role",
        "lp_per_game_recent",
    },
    "champions": {
        "champion_key",
        "champion_name",
        "as_of_date",
        "active_play_rate",
        "primary_player_count",
        "observed_games",
    },
    "champion_playstyles": {
        "champion_key",
        "champion_name",
        "playstyle",
        "current_player_count",
        "observed_games",
    },
    "cooccurrence": {
        "champion_name_a",
        "champion_name_b",
        "pair_player_count",
        "lift",
        "npmi",
    },
    "rank_growth": {
        "previous_tier",
        "games_delta",
        "lp_delta",
        "wins_delta",
        "playstyle",
        "primary_champion_name",
    },
    "growth_players": {"starting_tier", "specialization_hhi", "climbing_efficiency", "period_count"},
    "growth_player_styles": {"starting_tier", "playstyle", "climbing_efficiency", "period_count"},
    "champion_growth_players": {
        "champion_name", "starting_tier", "champion_commitment", "climbing_efficiency", "period_count"
    },
    "champion_tier_growth": {
        "champion_name", "starting_tier", "cohort_scope", "climbing_efficiency", "observed_player_count"
    },
    "ranked_mastery_cohorts": {
        "window_name", "starting_tier", "current_main_role",
        "median_ranked_mastery_share", "period_count", "favoured_champions",
        "first_period_end", "last_period_end",
    },
}
