import argparse

from loguru import logger

from extract.get_champions import get_champions_dataframe
from load.databricks_helper import get_connection, use_catalog_and_schema, infer_sql_schema

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

    logger.info(f"Fetched {len(df)} champions from get_champions_dataframe().")

    with get_connection() as connection, connection.cursor() as cursor:
        create_table_if_not_exists(cursor, df)
        cursor.execute(f"TRUNCATE TABLE {CATALOG}.{SCHEMA}.{TABLE_NAME}")

        records = list(df.itertuples(index=False, name=None))
        insert_query = f"""
                INSERT INTO {CATALOG}.{SCHEMA}.{TABLE_NAME}
                VALUES ({", ".join(["?"] * len(df.columns))})
            """

        for record in records:
            cursor.execute(insert_query, record)

    logger.info(f"Successfully loaded {len(records)} rows into {CATALOG}.{SCHEMA}.{TABLE_NAME}.")
    return len(records)


if __name__ == "__main__":
    load_champions()
