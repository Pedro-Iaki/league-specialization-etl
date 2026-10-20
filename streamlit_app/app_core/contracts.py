"""Column requirements shared by snapshot serving and manual exports."""

from app_core.business import BUSINESS_PUBLIC_COLUMNS, CASH_DISCOUNT_COLUMNS

# Required on new exports; older serving snapshots remain readable.
ACTIVE_POOL_LIFETIME_COLUMNS = {
    "active_pool_lifetime_champion_count",
    "active_pool_lifetime_mastery_points",
    "active_pool_lifetime_primary_champion_key",
    "active_pool_lifetime_primary_champion_name",
    "active_pool_lifetime_primary_champion_points",
    "active_pool_lifetime_top1_share",
    "active_pool_lifetime_hhi",
}

REQUIRED_COLUMNS = {
    "champion_population_pairs": {"champion_key_a", "champion_name_a", "champion_key_b", "champion_name_b", "region", "queue", "tier", "recent_pool_player_count", "player_count_a", "player_count_b", "pair_player_count"},
    "champion_population_activity": {"champion_name", "tier", "region", "queue", "recent_player_count", "recent_pool_player_count", "mean_recent_share", "role_sample_player_count", "role_top_pct", "role_jungle_pct", "role_middle_pct", "role_bottom_pct", "role_support_pct"},
    "business_players": set(BUSINESS_PUBLIC_COLUMNS) - CASH_DISCOUNT_COLUMNS,
    "champion_player_mastery_share": {"champion_name", "tier", "champion_points", "lifetime_mastery_points", "mastery_share"},
    "champion_tier_mastery": {"champion_name", "tier", "minimum_mastery", "player_count", "expert_player_count", "mean_mastery", "median_mastery", "mean_rank_score", "median_rank_score"},
    "players": {
        "as_of_date",
        "tier",
        "tier_order",
        "rank_score",
        "recent_playstyle",
        "lifetime_playstyle",
        "main_role",
        "latest_rank_period_lp_per_game",
    },
    "champions": {
        "champion_key",
        "champion_name",
        "as_of_date",
        "recent_pool_membership_rate",
        "recent_primary_player_count",
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
    "growth_player_styles": {"starting_tier", "rank_period_playstyle", "climbing_efficiency", "period_count"},
    "champion_growth_players": {
        "champion_name", "starting_tier", "champion_commitment", "climbing_efficiency", "period_count"
    },
    "champion_tier_growth": {
        "champion_name", "starting_tier", "cohort_scope", "climbing_efficiency", "observed_player_tier_count"
    },
    "ranked_mastery_cohorts": {
        "window_name", "starting_tier", "current_main_role",
        "median_ranked_mastery_share", "period_count", "favoured_champions",
        "first_period_end", "last_period_end",
    },
}
