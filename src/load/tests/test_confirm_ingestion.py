import json
import logging
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from databricks.sdk.service.jobs import Run, RunResultState, RunState

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
    assert databricks_helper.run_job(123, 900, "Ingestion") is expected
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
    assert databricks_helper.run_job(123, 900, "Ingestion")
    assert len(attempts) == 2


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
        exec(source, {"dbutils": SimpleNamespace(fs=SimpleNamespace(ls=inaccessible)), "logging": logging})  # noqa: S102 - trusted notebook regression test
