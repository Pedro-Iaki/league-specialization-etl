import argparse
import json

from loguru import logger

from extract.get_champions import get_champions_dataframe
from load.databricks_helper import _is_list_like_column, get_connection, infer_sql_schema, use_catalog_and_schema

CATALOG = "league_pipeline"
SCHEMA = "raw"
VOLUME = "champions"
TABLE_NAME = "champions"


def create_table_if_not_exists(cursor, df):
    use_catalog_and_schema(cursor, CATALOG, SCHEMA)
    sql_columns = infer_sql_schema(df)
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {CATALOG}.{SCHEMA}.{TABLE_NAME} (
            {sql_columns}
        )
        USING DELTA
        """
    )


def load_champions():
    df = get_champions_dataframe()

    if df is None or df.empty:
        logger.warning("No champion data to load. Exiting.")
        return 0

    # Identify which columns are lists
    list_cols = [col for col in df.columns if _is_list_like_column(df[col])]

    # Build SQL placeholders: from_json(?, 'ARRAY<STRING>') for lists, ? for standard values
    placeholders = []
    for col in df.columns:
        if col in list_cols:
            placeholders.append("from_json(?, 'ARRAY<STRING>')")
        else:
            placeholders.append("?")

    # Convert Python lists in records to JSON strings for parameter binding
    records = []
    for row in df.itertuples(index=False):
        row_values = []
        for col_name, val in zip(df.columns, row):
            if col_name in list_cols and isinstance(val, (list, tuple)):
                row_values.append(json.dumps(val))
            else:
                row_values.append(val)
        records.append(tuple(row_values))

    with get_connection() as connection, connection.cursor() as cursor:
        create_table_if_not_exists(cursor, df)
        cursor.execute(f"TRUNCATE TABLE {CATALOG}.{SCHEMA}.{TABLE_NAME}")

        insert_query = f"""
            INSERT INTO {CATALOG}.{SCHEMA}.{TABLE_NAME}
            VALUES ({", ".join(placeholders)})
        """

        cursor.executemany(insert_query, records)

    logger.info(f"Successfully loaded {len(records)} rows into {CATALOG}.{SCHEMA}.{TABLE_NAME}.")
    return len(records)


if __name__ == "__main__":
    load_champions()
