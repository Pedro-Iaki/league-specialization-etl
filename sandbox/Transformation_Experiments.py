# %%
from pathlib import Path
import json
import pandas as pd
# %%
#Load the latest clean data from our folder

current_dir = Path.cwd().resolve()
cdata_dir = current_dir / "Cleaned_Data"

cdata_candidates = list(cdata_dir.glob("*.json"))
if not cdata_candidates:
    raise ValueError("No transformable data found in Cleaned_Data Folder!")
latest_cdata_path = max(cdata_candidates, key=lambda f: f.stat().st_mtime)
clean_data = json.loads(latest_cdata_path.read_text(encoding="utf-8"))
del cdata_candidates
del cdata_dir
del current_dir
del latest_cdata_path
# %%
#Now, we finally start transforming the clean data into a usable dataframe
#Our initial dataframe should utilize Puuid as the indexer
#Then join both the mastery and players dictionaries to form their variables
#as for the variables used, we want:
#index by puuid
#separate all masteries in their own variable, with the champion name as their name
#sum of all masteries
#wins and losses
#veteran, fresh-blood, and inactive
#rank and division

player_data = pd.DataFrame(clean_data['players'])

mastery_data = pd.DataFrame(clean_data['masteries'])
mastery_data['lastPlayTime'] = pd.to_datetime(mastery_data['lastPlayTime'], unit='ms')
inverted_champion_dict = {value:key for key, value in clean_data['champions'].items()}
mastery_data['championName'] = mastery_data['championId'].astype(str).map(inverted_champion_dict)

player_masteries_matrix = mastery_data.pivot(index='puuid', columns='championName', values='championPoints')

last_played_matrix = mastery_data.pivot(index='puuid', columns='championName', values='lastPlayTime')
last_played_matrix = last_played_matrix.add_suffix('_lastPlayed')
structured_data = pd.merge(player_masteries_matrix, last_played_matrix, how='outer', on='puuid')

structured_data = pd.merge(player_data, structured_data, how='right', on='puuid')
structured_data.set_index('puuid', inplace=True)
del mastery_data
del inverted_champion_dict
del player_data
del player_masteries_matrix
del last_played_matrix
# %%

