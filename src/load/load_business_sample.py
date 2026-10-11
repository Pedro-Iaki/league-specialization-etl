"""Load only the two dedicated business sample raw tables, without a gameplay ingestion job."""
from __future__ import annotations

import argparse
from pathlib import Path

from load.databricks_helper import get_connection, upload_parquet
from sample.contract import PLAYER_SCHEMA, SAMPLE_DIR, SAMPLE_TABLES, TRANSACTION_SCHEMA, sql_schema
from sample.validation import validate_files, warehouse_metadata

VOLUME = "/Volumes/league_pipeline/landing_zone/business_sample"


def replace_sample_table(cursor, table_name: str, schema, file_path: str | None = None) -> None:
    if table_name not in SAMPLE_TABLES.values():
        raise ValueError(f"Refusing to write a non-sample table: {table_name}")
    ddl = sql_schema(schema)
    statement = f"CREATE OR REPLACE TABLE {table_name} ({ddl}) USING DELTA"
    if file_path is not None:
        if not file_path.startswith(VOLUME + "/") or "'" in file_path:
            raise ValueError("Only the dedicated business_sample volume can be read")
        columns = ", ".join(f"`{field.name}`" for field in schema)
        # Databricks RTAS takes its types from the statically declared reader schema,
        # and prohibits a separate table column declaration in the same statement.
        statement = (f"CREATE OR REPLACE TABLE {table_name} USING DELTA AS SELECT {columns} "
                     f"FROM read_files('{file_path}', format => 'parquet', "
                     f"schema => '{ddl}', schemaEvolutionMode => 'none')")
    cursor.execute(statement)


def load_sample(directory: Path) -> dict:
    _, _, manifest = validate_files(directory)  # finish all local checks before connecting or uploading
    # Generated scenario IDs are hex-based; no user-selected table/catalog/path interpolation.
    scenario = manifest["scenario_id"]
    if not scenario.startswith("business-") or any(character not in "0123456789abcdef" for character in scenario[9:]):
        raise ValueError("Invalid scenario ID")
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("CREATE VOLUME IF NOT EXISTS league_pipeline.landing_zone.business_sample")
        paths = {}
        for name in SAMPLE_TABLES:
            path = f"{VOLUME}/{scenario}/{name}.parquet"
            upload_parquet(str(directory / f"{name}.parquet"), path)
            paths[name] = path
        # Invalidate completion first, including on a same-scenario retry. The cohort is committed last.
        replace_sample_table(cursor, SAMPLE_TABLES["business_sample_players"], PLAYER_SCHEMA)
        try:
            replace_sample_table(cursor, SAMPLE_TABLES["transactions"], TRANSACTION_SCHEMA, paths["transactions"])
            replace_sample_table(cursor, SAMPLE_TABLES["business_sample_players"], PLAYER_SCHEMA, paths["business_sample_players"])
            result = warehouse_metadata(cursor, require_gold=False)
        except Exception:
            print("INCOMPLETE business sample load; dashboard export is blocked until both tables reconcile.")
            raise
    print(f"Loaded {result['player_count']:,} sample players and {result['transaction_count']:,} sample transactions")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=SAMPLE_DIR)
    parser.add_argument("--validate-only", action="store_true", help="Check private files without connecting or writing")
    args = parser.parse_args()
    if args.validate_only:
        players, events, _ = validate_files(args.input_dir)
        print(f"Validated {players.num_rows:,} players and {events.num_rows:,} transactions; no warehouse writes")
    else:
        load_sample(args.input_dir)


if __name__ == "__main__":
    main()
