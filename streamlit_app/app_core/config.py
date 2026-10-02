from __future__ import annotations

from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
MIN_SUPPORT_PLAYERS = 3
REPO_ROOT = APP_ROOT.parent
DATA_DIR = APP_ROOT / "data"
MANIFEST_PATH = DATA_DIR / "manifest.json"

TIER_ORDER = [
    "IRON",
    "BRONZE",
    "SILVER",
    "GOLD",
    "PLATINUM",
    "EMERALD",
    "DIAMOND",
    "MASTER",
]
TIER_ORDER_HIGH_TO_LOW = list(reversed(TIER_ORDER))

PLAYSTYLE_ORDER = ["specialist", "multispecialist", "versatile", "generalist"]
PLAYSTYLE_LABELS = {
    "specialist": "Specialist",
    "multispecialist": "Multi-specialist",
    "versatile": "Versatile",
    "generalist": "Generalist",
    "insufficient activity": "Insufficient activity",
}
PLAYSTYLE_COLORS = {
    "specialist": "#D8A52D",
    "multispecialist": "#2EC4B6",
    "versatile": "#4EA5D9",
    "generalist": "#9B7EDE",
    "insufficient activity": "#65758B",
}

ROLE_ORDER = ["Top", "Jungle", "Middle", "Bottom", "Support"]
ROLE_COLORS = {
    "Top": "#D98E32",
    "Jungle": "#47B36B",
    "Middle": "#5CA8D8",
    "Bottom": "#D85F76",
    "Support": "#9B7EDE",
}

BACKGROUND = "#07111F"
PANEL = "#0E1B2B"
TEXT = "#E8EEF6"
MUTED = "#9AABC0"
GOLD = "#D8A52D"
BLUE = "#4EA5D9"
GRID = "rgba(154,171,192,0.14)"

DATASET_FILES = {
    "players": "player_profiles.parquet",
    "champions": "champion_profiles.parquet",
    "champion_playstyles": "champion_playstyle_profiles.parquet",
    "cooccurrence": "champion_cooccurrence.parquet",
    "rank_growth": "rank_growth.parquet",
    "growth_players": "growth_players.parquet",
    "growth_player_styles": "growth_player_styles.parquet",
    "champion_growth_players": "champion_growth_players.parquet",
    "champion_tier_growth": "champion_tier_growth.parquet",
    "ranked_mastery_cohorts": "ranked_mastery_cohorts.parquet",
    "champion_tier_mastery": "champion_tier_mastery.parquet",
    "champion_player_mastery_share": "champion_player_mastery_share.parquet",
}

DATASET_LABELS = {
    "players": "Player profiles",
    "champions": "Champion profiles",
    "champion_playstyles": "Champion × playstyle profiles",
    "cooccurrence": "Champion co-occurrence",
    "rank_growth": "Rank-growth intervals",
    "growth_players": "Player growth by starting tier",
    "growth_player_styles": "Player growth by starting tier and observed playstyle",
    "champion_growth_players": "Player and champion growth by starting tier",
    "champion_tier_growth": "Champion growth by starting tier",
    "ranked_mastery_cohorts": "Player ranked-mastery share by observation window",
    "champion_player_mastery_share": "Player champion mastery shares by current tier",
    "champion_tier_mastery": "Champion mastery by current tier and threshold",
}
