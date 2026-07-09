# %%
from os import listdir
from os.path import isfile, join
from pathlib import Path
import json
import numpy
import pandas
# %%
#Load the latest clean data from our folder

current_dir = Path.cwd().resolve()
cdata_dir = current_dir / "Cleaned_Data"

cdata_candidates = [f for f in listdir(cdata_dir) if isfile(join(cdata_dir, f))]
latest_cdata_name = max(cdata_candidates, key=lambda f: f.split('_')[-1])
clean_data = json.loads(Path(join(cdata_dir, latest_cdata_name)).read_text(encoding="utf-8"))
del cdata_candidates
del cdata_dir
del current_dir
del latest_cdata_name
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

