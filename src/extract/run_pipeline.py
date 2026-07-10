from get_players import run as extract_players
from get_masteries import run as extract_masteries
import pipeline_db as db
import os


def run_pipeline():
    """Run the local pipeline."""
    db.cleanup_stale_runs()
    
    try:
        version = os.getenv("VERSION")
        count = 1000
        while count > 0:
            run_id = db.start_run(f"local_{count}_{version}")
            print(f"Starting new pipeline run. Remaining runs: {count}")
            players_manifest = extract_players(run_id)
            if players_manifest:
                extract_masteries(players_manifest, run_id)
                db.finish_run(run_id, "success")
            else:
                db.finish_run(run_id, "failed", error_message="No players manifest returned.")
            count -= 1
    except:
        db.cleanup_stale_runs()
        raise ValueError("Something went wrong during that run, aborting.")



if __name__ == "__main__":
    run_pipeline()