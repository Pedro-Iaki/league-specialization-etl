"""Column requirements shared by snapshot serving and manual exports."""

from app_core.business import BUSINESS_PUBLIC_COLUMNS, CASH_DISCOUNT_COLUMNS

REQUIRED_COLUMNS = {
    "champion_population_pairs": {"champion_key_a", "champion_name_a", "champion_key_b", "champion_name_b", "region", "queue", "tier", "pool_player_count", "player_count_a", "player_count_b", "pair_player_count"},
    "champion_population_activity": {"champion_name", "tier", "region", "queue", "active_player_count", "active_pool_player_count", "mean_active_share", "role_sample_player_count", "role_top_pct", "role_jungle_pct", "role_middle_pct", "role_bottom_pct", "role_support_pct"},
    "business_players": set(BUSINESS_PUBLIC_COLUMNS) - CASH_DISCOUNT_COLUMNS,
    "champion_player_mastery_share": {"champion_name", "tier", "champion_points", "total_mastery_points", "mastery_share"},
    "champion_tier_mastery": {"champion_name", "tier", "minimum_mastery", "player_count", "expert_player_count", "mean_mastery", "median_mastery", "mean_rank_score", "median_rank_score"},
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
    "cooccurrence": {
        "champion_name_a",
        "champion_name_b",
        "pair_player_count",
        "lift",
        "npmi",
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
