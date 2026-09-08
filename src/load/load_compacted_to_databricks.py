import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.dataset as ds
import pyarrow.parquet as pq

from load.databricks_helper import upload_parquet

COMPACTED_DIR = Path("data/compacted")


def load_compacted():
    tmp_dir = Path(tempfile.mkdtemp(prefix="league_pipeline_"))
    try:
        for dataset in ("players", "masteries"):
            # further compress all compacted into a single .parquet
            src_dir = COMPACTED_DIR / dataset
            table = ds.dataset(src_dir, format="parquet", partitioning="hive").to_table()
            tmp_parquet_path = tmp_dir / f"{dataset}.parquet"
            pq.write_table(table, tmp_parquet_path)

            # upload parquet file to landing zone in databricks
            time = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
            parquet_name = f"{dataset}_{time}.parquet"
            upload_parquet(
                str(tmp_parquet_path), f"dbfs:/Volumes/league_pipeline/landing_zone/{dataset}/{parquet_name}"
            )

            print(f"Uploaded {dataset}: {table.num_rows} rows")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    load_compacted()
