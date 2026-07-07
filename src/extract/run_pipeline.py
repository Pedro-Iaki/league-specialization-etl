from get_players import run as extract_players
from get_masteries import run as extract_masteries


def run_pipeline():
    """Run the placeholder pipeline."""
    players_manifest = extract_players()
    extract_masteries(players_manifest)


if __name__ == "__main__":
    run_pipeline()