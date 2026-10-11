from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from load import build_dbt


@pytest.mark.parametrize("succeeded", [False, True])
def test_build_uses_local_job_settings_and_reports_its_own_result(tmp_path, monkeypatch, succeeded):
    for key in ("DBT_JOB_ID", "DBT_TIMEOUT_SECONDS"):
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / "extraction.env"
    path.write_text("DBT_JOB_ID=456\nDBT_TIMEOUT_SECONDS=1200\n")
    monkeypatch.setattr(build_dbt, "CONFIG_PATH", path)
    calls = []
    monkeypatch.setattr(build_dbt, "run_job", lambda *args: calls.append(args) or succeeded)
    assert build_dbt.run_dbt() is succeeded
    assert calls == [(456, 1200, "dbt")]
    path.write_text("DBT_JOB_ID=0\n")
    with pytest.raises(ValidationError):
        build_dbt.run_dbt()
    assert len(calls) == 1


def test_dbt_job_builds_the_graph_in_one_task_without_a_file_trigger():
    path = Path(__file__).resolve().parents[3] / "resources/build_dbt.job.yml"
    job = yaml.safe_load(path.read_text())["resources"]["jobs"]["build_dbt"]
    assert len(job["tasks"]) == 1
    assert job["tasks"][0]["dbt_task"]["commands"] == ["dbt deps", "dbt build"]
    assert "trigger" not in job and "schedule" not in job
