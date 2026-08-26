from pathlib import Path
import os
import json
import requests
from datetime import datetime, timezone
import pandas as pd

# ================= CONFIGURATION =================
region = "na1"
queue = "RANKED_SOLO_5x5"
tiers = ["DIAMOND", "EMERALD", "PLATINUM", "GOLD", "SILVER", "BRONZE", "IRON"]
date = "260722"
patch = "16.14.1"

# Optional limit for testing
MAX_PLAYERS = None          # set to 1000 to limit total players

current_dir = Path.cwd().resolve()
base_dir = current_dir.parent
data_dir = base_dir / "data" / "raw"
cleaned_data_dir = current_dir / "Cleaned_Data"
cleaned_data_dir.mkdir(parents=True, exist_ok=True)
# =================================================

all_players_list = []
selected_puuids = set()

# ------------------------------------------------------------
# 1. Read players (stop early if MAX_PLAYERS reached)
# ------------------------------------------------------------
for tier in tiers:
    players_dir = (
        data_dir / "players"
        / f"region={region}"
        / f"queue={queue}"
        / f"tier={tier}"
        / f"patch={patch}"
        / f"date={date}"
    )

    if not players_dir.exists():
        continue

    with os.scandir(players_dir) as entries:
        for entry in entries:
            if not entry.is_file():
                continue
            with open(entry.path, encoding="utf-8") as f:
                data = json.load(f)
            for p in data.get("players", []):
                if not isinstance(p, dict):
                    continue
                all_players_list.append(p)
                selected_puuids.add(p["puuid"])
                if MAX_PLAYERS and len(all_players_list) >= MAX_PLAYERS:
                    break
            if MAX_PLAYERS and len(all_players_list) >= MAX_PLAYERS:
                break
    if MAX_PLAYERS and len(all_players_list) >= MAX_PLAYERS:
        break

print(f"Collected {len(all_players_list)} players")

# ------------------------------------------------------------
# 2. Read masteries, filtered to selected players if limit set
# ------------------------------------------------------------
all_masteries_list = []
for tier in tiers:
    masteries_dir = (
        data_dir / "masteries"
        / f"region={region}"
        / f"queue={queue}"
        / f"tier={tier}"
        / f"dt={date}"
    )

    if not masteries_dir.exists():
        continue

    with os.scandir(masteries_dir) as entries:
        for entry in entries:
            if not entry.is_file():
                continue
            with open(entry.path, encoding="utf-8") as f:
                data = json.load(f)
            for m in data.get("masteries", []):
                if not isinstance(m, dict):
                    continue
                if MAX_PLAYERS and m["puuid"] not in selected_puuids:
                    continue
                all_masteries_list.append(m)

print(f"Collected {len(all_masteries_list)} mastery entries")

# ------------------------------------------------------------
# 3. Save to Parquet files
# ------------------------------------------------------------
now = datetime.now(timezone.utc)
timestamp = now.strftime('%y%m%d%H%M%S')

players_df = pd.DataFrame(all_players_list)
masteries_df = pd.DataFrame(all_masteries_list)

players_df.to_parquet(cleaned_data_dir / f"players_{timestamp}.parquet", index=False)
masteries_df.to_parquet(cleaned_data_dir / f"masteries_{timestamp}.parquet", index=False)

# ------------------------------------------------------------
# 4. Fetch champion mapping (name -> ID, as expected by analysis)
# ------------------------------------------------------------
with requests.Session() as session:
    latest_patch = session.get(
        "https://ddragon.leagueoflegends.com/api/versions.json"
    ).json()[0]
    champions_url = (
        f"https://ddragon.leagueoflegends.com/cdn/{latest_patch}/data/en_US/champion.json"
    )
    champions_data = session.get(champions_url).json()


# Build dict: champion name -> numeric ID
champions_by_name = {
    c["name"]: {'key': c["key"], 'id': c['id']} for c in champions_data["data"].values()
}

# ------------------------------------------------------------
# 4b. Merge name/id mapping with position data into one dataframe
# ------------------------------------------------------------

import get_champion_positions as cp

champions_positions = cp.run()

champions_by_name_df = (
    pd.DataFrame.from_dict(champions_by_name, orient="index")
    .reset_index()
    .rename(columns={"index": "name"})
)
# champions_by_name_df columns: name, key, id

champions_by_name_df["key"] = champions_by_name_df["key"].astype(str)
champions_positions["champion"] = champions_positions["champion"].astype(str)

champions_clean_data = champions_by_name_df.merge(
    champions_positions,
    left_on="key",
    right_on="champion",
    how="left"
).drop(columns=["champion"]
).set_index("name")

# ------------------------------------------------------------
# 4c. Save to json
# ------------------------------------------------------------

champions_clean_data.to_json(
    cleaned_data_dir / f"champions_{timestamp}.json",
    orient="index",       # <-- preserves the index as keys
    indent=2,
    force_ascii=False,
)

print(f"Saved players_{timestamp}.parquet, masteries_{timestamp}.parquet, champions_{timestamp}.json")