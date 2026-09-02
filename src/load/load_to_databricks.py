import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.dataset as ds
import pyarrow.parquet as pq

COMPACTED_DIR = Path("data/compacted")
TMP_DIR = Path("tmp_staging")
TMP_DIR.mkdir(exist_ok=True)

for dataset in ("players", "masteries"):
    src_dir = COMPACTED_DIR / dataset
    table = ds.dataset(
        src_dir, format="parquet", partitioning="hive"
    ).to_table()  # Read all parquets for each dataset and compact into a table

    out_path = TMP_DIR / f"{dataset}.parquet"  # merge into a single file
    pq.write_table(table, out_path)  # write it temporarily to the staging directory

    time = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
    out_path_name = f"{dataset}_{time}.parquet"

    subprocess.run(
        [
            "databricks",
            "fs",
            "cp",
            str(out_path),
            f"dbfs:/Volumes/league_pipeline/raw/parquets/{out_path_name}",
            "--overwrite",
        ],
        check=True,
    )

    print(f"Uploaded {dataset}: {table.num_rows} rows")

print(
    "\nfiles in dbfs:/Volumes/league_pipeline/raw/parquets/:\n"
    + subprocess.run(
        ["databricks", "fs", "ls", "dbfs:/Volumes/league_pipeline/raw/parquets/"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
)
