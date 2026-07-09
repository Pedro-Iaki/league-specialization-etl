from os import listdir
from os.path import isfile, join
from pathlib import Path
import requests
import json
from datetime import datetime, timezone
# %%
#configs to target a set of data from a certain period, at certain parameters
region = "na1"
queue = "RANKED_SOLO_5x5"
tier= "DIAMOND"
date = "260707"
# %%
#get the raw files extracted from the api for players and their masteries
#and the raw data from riot about their champions to access their ids later
current_dir = Path.cwd().resolve()
base_dir = current_dir.parents[0]
data_dir = base_dir / "data" / "raw"
players_dir = data_dir / "players" / ("region="+region) / ("queue="+queue) / ("tier="+tier) / ("dt="+date)
masteries_dir = data_dir / "masteries" / ("region="+region) / ("queue="+queue) / ("tier="+tier) / ("dt="+date)

players_file_paths = [join(players_dir,f) for f in listdir(players_dir) if isfile(join(players_dir, f))]
players_payloads = []
for p in players_file_paths:
    with open(p) as f:
        players_payloads.append(json.load(f))

masteries_file_paths = [join(masteries_dir,f) for f in listdir(masteries_dir) if isfile(join(masteries_dir, f))]
masteries_payloads = []
for m in masteries_file_paths:
    with open(m) as f:
        masteries_payloads.append(json.load(f))
        
latest_patch = "https://ddragon.leagueoflegends.com/api/versions.json"
patch = requests.get(latest_patch).json()[0]
champions_url = f"https://ddragon.leagueoflegends.com/cdn/{patch}/data/en_US/champion.json"

champions_data_response = requests.get(champions_url)
champions_data = champions_data_response.json()
# %%
#Now we start transforming the data into flattened dumps

#turn champion data into a useful dictionary
champions_by_id = {c['id']:c['key'] for c in champions_data["data"].values()}

masteries_dump = [m['masteries'] for m in masteries_payloads]
all_masteries_list = []
for player_ms in masteries_dump:
    for champion_ms in player_ms:
        all_masteries_list.append(champion_ms)

all_players_list = []
for page in players_payloads:
    for player in page['players']:
        all_players_list.append(player)

payload = {
    "source": "riot-api",
    "fetched-at": datetime.now(timezone.utc).isoformat(),
    "champions": champions_by_id,
    "masteries": all_masteries_list,
    "players": all_players_list
    }

cleaned_data_dir = current_dir / "Cleaned_Data"
cleaned_data_dir.mkdir(parents=True, exist_ok=True)
output_path = cleaned_data_dir / f"fulldata_{datetime.now(timezone.utc).strftime('%y%m%d%H%M%S')}"
output_path.write_text(json.dumps(payload,indent = 2, ensure_ascii=True), encoding="utf-8")
