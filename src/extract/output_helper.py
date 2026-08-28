from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def get_partitioned_path(base_path: Path, partitions: list[tuple[str, str]]) -> Path:
    final_path = base_path
    for key, value in partitions:
        partition_name = f"{key}={value}"
        final_path = final_path / partition_name
        final_path.mkdir(parents=True, exist_ok=True)

    return final_path


def write_parquet(payload: list[dict], output_path: Path):
    if not payload:
        raise ValueError("Payload is empty")
    table = pa.Table.from_pylist(payload)
    pq.write_table(table, output_path)
