"""Export one jointly anonymized local membership snapshot; leave public serving files untouched."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(APP_ROOT.parent))

from app_core.families import LOCAL_DIR, validate_membership
from scripts.export_data import fetch_frame
from src.load.databricks_helper import get_connection

MEMBERSHIP_QUERY = """with members as (
    select a.player_id,
        sort_array(collect_list(named_struct(
            'key', cast(a.champion_key as int), 'name', c.name,
            'points', cast(m.champion_points as bigint)
        ))) as members
    from league_pipeline.gold.fct_players_champion_activity a
    join league_pipeline.silver.fct_masteries_current m
      on a.player_id = m.puuid and a.champion_key = m.champion_key
    join league_pipeline.silver.dim_champions c on a.champion_key = c.key
    where a.is_recent_pool_champion
    group by a.player_id
)
select p.region, p.queue, p.tier, p.days_tracked, p.lifetime_mastery_points,
       p.total_games, p.as_of_date, p.snapshot_date, m.members
from league_pipeline.gold.mart_player_profile p
left join members m on p.player_id = m.player_id
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=LOCAL_DIR)
    args = parser.parse_args()
    connection = get_connection()
    cursor = connection.cursor()
    try:
        frame = fetch_frame(cursor, MEMBERSHIP_QUERY)
    finally:
        cursor.close()
        connection.close()
    # Array position links records only inside this single anonymous export.
    # No player identifiers or join tokens leave the warehouse.
    validate_membership(frame)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    temporary = args.output_dir / 'membership.parquet.tmp'
    destination = args.output_dir / 'membership.parquet'
    frame.to_parquet(temporary, index=False, compression='zstd')
    os.replace(temporary, destination)
    manifest = {
        'exported_at_utc': datetime.now(timezone.utc).isoformat(),
        'source': 'league_pipeline.gold.mart_player_profile + fct_players_champion_activity + silver.fct_masteries_current',
        'sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
        'profiles': len(frame),
        'membership_policy': 'Existing model active pool: short-history 30d; mature 60d/gain.',
        'privacy': 'Local jointly anonymized membership; no player IDs; independent of public profile row order.',
        'min_as_of_date': str(frame.as_of_date.min()),
        'max_as_of_date': str(frame.as_of_date.max()),
    }
    (args.output_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(f'Exported {len(frame):,} anonymous profiles to {destination}', flush=True)


if __name__ == '__main__':
    main()

