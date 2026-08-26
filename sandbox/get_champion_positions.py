
def run():
    from pathlib import Path
    import json
    import pandas as pd
    from lupa import LuaRuntime
    import requests
    
    # ============================================================
    # Paths
    # ============================================================
    
    wiki_api = "https://wiki.leagueoflegends.com/en-us/api.php"
    
    params = {
        "action": "parse",
        "page": "Module:ChampionData/data",
        "prop": "wikitext",
        "format": "json",
    }
    
    with requests.Session() as session:
        lua_source = session.get(wiki_api, params=params)
    
    lua_source = lua_source.json()["parse"]["wikitext"]["*"]
    lua_source = lua_source.removeprefix("-- <pre>\n")
    lua_source = lua_source.removesuffix("\n</pre>")
    
    # ============================================================
    # Load the Lua data
    # ============================================================
    
    lua = LuaRuntime(unpack_returned_tuples=True)
    
    # Your file is a Lua table, so wrap it in `return` if necessary.
    lua_table = lua.execute(lua_source)
    
    
    # ============================================================
    # Convert Lua tables recursively to normal Python objects
    # ============================================================
    
    def lua_to_python(value):
        """
        Recursively convert Lua tables into Python dicts/lists.
        """
    
        if not hasattr(value, "items"):
            return value
    
        items = list(value.items())
    
        # Empty Lua table
        if not items:
            return {}
    
        # Check whether this is an array-style Lua table:
        # { "Top", "Jungle", "Support" }
        keys = [key for key, _ in items]
    
        if all(isinstance(key, (int, float)) for key in keys):
            keys = sorted(keys)
    
            # Lua arrays are 1-indexed
            if keys == list(range(1, len(keys) + 1)):
                return [
                    lua_to_python(value[i])
                    for i in keys
                ]
    
        # Otherwise it's a dictionary/table
        return {
            lua_to_python(key): lua_to_python(val)
            for key, val in items
        }
    
    
    champion_data = lua_to_python(lua_table)
    
    
    # ============================================================
    # Build position lookup from the Lua data
    # ============================================================
    
    position_lookup = {}
    
    for info in champion_data.values():
        if not isinstance(info, dict):
            continue
    
        client_positions = info.get(
            "client_positions",
            []
        )
    
        external_positions = info.get(
            "external_positions",
            []
        )
    
        # Make sure these are lists
        if not isinstance(client_positions, list):
            client_positions = [client_positions]
    
        if not isinstance(external_positions, list):
            external_positions = [external_positions]
    
        position_lookup[str(info['id'])] = {
            "client_positions": client_positions,
            "external_positions": external_positions,
        }
    
    
    # ============================================================
    # Create rows using clean_data's champion list
    # ============================================================
    
    rows = []
    for c_id in position_lookup:
        positions = position_lookup.get(c_id, '')
    
        rows.append({
            "champion": c_id,
            "client_positions": ", ".join(
                positions["client_positions"]
            ),
            "external_positions": ", ".join(
                positions["external_positions"]
            ),
        })
    
    
    # ============================================================
    # Save CSV
    # ============================================================
    
    positions_df = pd.DataFrame(rows)
    
    return positions_df