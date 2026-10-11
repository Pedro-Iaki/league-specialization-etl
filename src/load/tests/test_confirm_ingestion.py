import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from databricks.sdk.service.jobs import Run, RunResultState, RunState
from pydantic import ValidationError

from load import confirm_ingestion as ingestion
from load import databricks_helper


@pytest.mark.parametrize(
    "outcome,expected,attempts",
    [
        ("success", True, 1),
        ("failure", False, 3),
        ("timeout", False, 1),
    ],
)
def test_job_result_controls_success_and_retry_limit(monkeypatch, outcome, expected, attempts):
    submissions = []

    def result(timeout):
        assert timeout == timedelta(seconds=900)
        if outcome == "timeout":
            raise TimeoutError("job still running")
        state = RunResultState.SUCCESS if outcome == "success" else RunResultState.FAILED
        return Run(run_id=42, state=RunState(result_state=state))

    def submit(**kwargs):
        submissions.append(kwargs)
        return SimpleNamespace(run_id=42, result=result)

    workspace = SimpleNamespace(jobs=SimpleNamespace(run_now=submit))
    monkeypatch.setattr(databricks_helper, "get_workspace_client", lambda: workspace)
    assert ingestion.run_ingestion(123, 900) is expected
    assert submissions == [{"job_id": 123}] * attempts


def test_transient_job_failure_can_be_retried(monkeypatch):
    attempts = []

    def submit(**kwargs):
        attempts.append(True)
        if len(attempts) == 1:
            raise RuntimeError("job failed")
        return SimpleNamespace(
            run_id=43, result=lambda **kwargs: Run(run_id=43, state=RunState(result_state=RunResultState.SUCCESS))
        )

    monkeypatch.setattr(
        databricks_helper, "get_workspace_client", lambda: SimpleNamespace(jobs=SimpleNamespace(run_now=submit))
    )
    assert ingestion.run_ingestion(123, 900)
    assert len(attempts) == 2


def test_job_settings_load_from_the_local_config_file(tmp_path, monkeypatch):
    for key in ("INGEST_JOB_ID", "INGESTION_TIMEOUT_SECONDS"):
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / "extraction.env"
    path.write_text("INGEST_JOB_ID=123\nINGESTION_TIMEOUT_SECONDS=600\n")
    monkeypatch.setattr(ingestion, "CONFIG_PATH", path)
    config = ingestion.get_ingestion_config()
    assert config.ingest_job_id == 123
    assert config.ingestion_timeout_seconds == 600
    path.write_text("INGEST_JOB_ID=0\n")
    with pytest.raises(ValidationError):
        ingestion.get_ingestion_config()


def test_notebook_landing_access_failure_is_not_swallowed():
    path = Path(__file__).resolve().parents[3] / "src/load/ingest_players.ipynb"
    cells = json.loads(path.read_text())["cells"]
    source = next(
        "".join(cell["source"]) for cell in cells if "query.awaitTermination()" in "".join(cell.get("source", []))
    )
    source = source[source.index('for subdir in ["players", "masteries"]:') :]

    def inaccessible(path):
        raise PermissionError("landing volume inaccessible")

    with pytest.raises(PermissionError, match="landing volume inaccessible"):
        exec(source, {"dbutils": SimpleNamespace(fs=SimpleNamespace(ls=inaccessible))})  # noqa: S102 - trusted notebook regression test
