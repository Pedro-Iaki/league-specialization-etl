import pandas as pd
from lupa import LuaRuntime
import requests

WIKI_API = "https://wiki.leagueoflegends.com/en-us/api.php"
REQUEST_PARAMS = {
    "action": "parse",
    "page": "Module:ChampionData/data",
    "prop": "wikitext",
    "format": "json",
}


def get_champion_positions() -> pd.DataFrame:
    lua = LuaRuntime(unpack_returned_tuples=True)
    # Get Champions as a parsed json, read to lua table, then convert to a python dict
    champion_data = dict_from_lua(lua.execute(get_champions_lua()))

    # Build a lookup table for champion positions based on the parsed champion data
    position_lookup = {}
    for info in champion_data.values():
        if not isinstance(info, dict):
            continue

        client_positions = info.get("client_positions", [])
        external_positions = info.get("external_positions", [])

        if not isinstance(client_positions, list):
            client_positions = [client_positions]
        if not isinstance(external_positions, list):
            external_positions = [external_positions]

        position_lookup[str(info["id"])] = {
            "client_positions": client_positions,
            "external_positions": external_positions,
        }

    return pd.DataFrame(
        [
            {
                "champion": c_id,
                "client_positions": ", ".join(positions["client_positions"]),
                "external_positions": ", ".join(positions["external_positions"]),
            }
            for c_id, positions in position_lookup.items()
        ]
    )


def get_champions_lua():
    with requests.Session() as session:
        lua_source = session.get(WIKI_API, params=REQUEST_PARAMS)

    lua_source = lua_source.json()["parse"]["wikitext"]["*"]
    lua_source = lua_source.removeprefix("-- <pre>\n")
    lua_source = lua_source.removesuffix("\n</pre>")
    return lua_source


def dict_from_lua(lua_table) -> dict:
    result = lua_to_python(lua_table)
    if not isinstance(result, dict):
        raise TypeError(f"Expected a dict, got {type(result)}")
    return result


def lua_to_python(value):
    """
    Recursively convert Lua tables into Python dicts/lists.
    Go through the table, then through each of its lists,
    and each value recursively to convert them into Python types.
    """
    # If its not a table or list, return the value as-is
    if not hasattr(value, "items"):
        return value
    items = list(value.items())

    # Empty Lua table
    if not items:
        return {}

    # Check whether this is an array table
    keys = [key for key, _ in items]
    if all(isinstance(key, (int, float)) for key in keys):
        keys = sorted(keys)
        if keys == list(range(1, len(keys) + 1)):
            return [lua_to_python(value[i]) for i in keys]

    # Otherwise it's a dictionary/table
    return {lua_to_python(key): lua_to_python(val) for key, val in items}


def get_champions_dataframe():
    """returns a df with name index, and columns: key, id, client_positions, external_positions"""
    # get the data from ddragon
    with requests.Session() as session:
        latest_patch = session.get("https://ddragon.leagueoflegends.com/api/versions.json").json()[0]
        champions_url = f"https://ddragon.leagueoflegends.com/cdn/{latest_patch}/data/en_US/champion.json"
        champions_data = session.get(champions_url).json()

    # create df from data
    champions_by_name = {c["key"]: {"name": c["name"], "id": c["id"]} for c in champions_data["data"].values()}
    champions_by_name_df = (
        pd.DataFrame.from_dict(champions_by_name, orient="index")
        .reset_index()
        .rename(columns={"index": "key"})
        .assign(key=lambda df: df["key"].astype(str))
        .assign(patch=latest_patch)
    )

    # get positions
    champions_positions = get_champion_positions()
    champions_positions["champion"] = champions_positions["champion"].astype(str)

    # merge them both
    champions_clean_data = champions_by_name_df.merge(
        champions_positions, left_on="key", right_on="champion", how="left"
    ).drop(columns=["champion"])

    return champions_clean_data


if __name__ == "__main__":
    print(get_champions_dataframe())
