from get_players import run as extract_players
from get_masteries import run as extract_masteries


def run_pipeline():
    """Run the placeholder pipeline."""
    count = 1000
    while count > 0:
        print(f"Starting new pipeline run. Remaining runs: {count}")
        players_manifest = extract_players()
        extract_masteries(players_manifest)
        count -= 1


if __name__ == "__main__":
    run_pipeline()