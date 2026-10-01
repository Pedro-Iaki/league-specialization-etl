from __future__ import annotations

import pandas as pd
from app_core.analysis import ranked_share_by_dimensions


def test_ranked_share_counts_players_once_per_cell() -> None:
    players = pd.DataFrame(
        {
            "starting_tier": ["GOLD", "GOLD", "SILVER"],
            "current_main_role": ["Middle", "Middle", "Top"],
            "median_ranked_mastery_share": [0.2, 0.8, 0.5],
            "favoured_champions": [["Ahri", "Ezreal"], ["Ahri"], ["Ezreal"]],
        }
    )
    role_tier = ranked_share_by_dimensions(players, "Tier", "Role")
    gold_middle = role_tier.loc[
        (role_tier["Tier"] == "GOLD") & (role_tier["Role"] == "Middle")
    ].iloc[0]
    assert gold_middle["player_count"] == 2
    assert gold_middle["mean_share"] == 0.5

    champion_role = ranked_share_by_dimensions(players, "Champion", "Role")
    ezreal_middle = champion_role.loc[
        (champion_role["Champion"] == "Ezreal") & (champion_role["Role"] == "Middle")
    ].iloc[0]
    assert ezreal_middle["player_count"] == 1
    assert ezreal_middle["mean_share"] == 0.2
