import json
from pathlib import Path
import tempfile

def get_partitioned_path(base_path: Path, partitions: list[tuple[str,str]], mock_save: bool = False) -> Path:
	final_path = Path(tempfile.mkdtemp()) if mock_save else base_path
	for key, value in partitions:
		partition_name = f"{key}={value}"
		final_path = final_path / partition_name
		final_path.mkdir(parents=True, exist_ok=True)
		
	return final_path

def write_json(payload: dict, output_path: Path):
	output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")