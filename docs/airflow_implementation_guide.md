# Airflow implementation: junior portfolio guide

Schedule the existing pipeline, show its stages in Airflow, demonstrate a retry, and publish the dashboard. Reuse the current extraction, SQLite, Neon, Databricks/dbt, and export code.

A **batch** is one complete operation: several internal **runs**, each with extraction **tasks**, followed by one final load. One Airflow DAG run owns one batch and one SQLite database. A retry continues that batch.

This guide defines the portfolio release. The broader [Airflow plan](../AIRFLOW_PLAN.md) contains follow-up improvements.

## 1. Use simple defaults

| Setting | First version |
| --- | --- |
| Runtime | One host, Docker Compose, LocalExecutor |
| Concurrency | One collector; `max_active_runs=1`, `max_active_tasks=1` |
| Schedule | Daily, `0 6 * * *` UTC; `catchup=False`; explicit UTC start date |
| Batch size | Up to `RUNS_PER_LOAD` internal runs, then one load |
| Collection | Each player once per batch; resume missing work on retry |
| Claims | Existing timeout configuration and release/expiry behavior |
| Success boundary | Completed Databricks ingestion/dbt job reports success |
| Recovery | Three retries with five-minute delay, then manual intervention |

Persist SQLite, raw/compacted files, Airflow logs, and the metadata database. Keep batches below a day. Existing date partitions and compaction are sufficient when each player is collected once per batch.

## 2. Start Airflow locally

Create `airflow/docker-compose.yaml`, `airflow/Dockerfile`, `airflow/requirements.txt`, and `dags/league_collection.py`.

Adapt the [official Compose example](https://airflow.apache.org/docs/apache-airflow/stable/howto/docker-compose/): select LocalExecutor, remove Redis/Celery worker services and their dependencies, and retain Postgres, scheduler, API server, DAG processor, and initialization. Use Linux containers on Windows.

Start with `apache/airflow:3.3.2-python3.12` and `apache-airflow-providers-databricks==7.21.0`. Install extraction/load/export dependencies and `boto3` using Airflow's constraints. Include `lupa`; omit the editable Git dependency from the root requirements file.

Mount the repo at `/opt/project`, use that working directory for pipeline tasks, and set `PYTHONPATH=/opt/project/src:/opt/project/streamlit_app`. Mount DAGs/logs at their Airflow paths. Reuse environment-based credentials; add a `databricks_default` Connection. Keep secrets out of Git and XCom.

```powershell
docker compose -f airflow/docker-compose.yaml build
docker compose -f airflow/docker-compose.yaml up airflow-init
docker compose -f airflow/docker-compose.yaml up -d
```

**Checkpoint:** localhost UI works, the DAG appears paused, and project modules import.

## 3. Expose one bounded batch

Add `src/extract/airflow_steps.py` with thin wrappers around existing functions. Make `collect_batch()` execute at most `RUNS_PER_LOAD` internal runs and return. Remove periodic loading/cleanup from this collection path: Airflow loads once afterward, including a partially filled batch.

Derive a stable batch ID from the Airflow DAG run ID. Initialize `data/database/extraction.db` once, reuse it on retries, and archive it at completion. A small local marker containing batch ID and completion status prevents initialization from wiping unfinished work. Airflow already tracks stage success.

Keep these necessary extraction fixes:

- Skip completed SQLite work on retry; resume missing mastery rather than recollecting rank.
- Filter discovery results against players already handled by this batch, across tiers; exclude those players from refresh claims too.
- Use task-based raw player filenames, such as `players_<task_id>.parquet`, to prevent overwrites.
- Raise exceptions for required failures rather than returning a success-looking summary.

Keep current rank-page advancement and inactivity update timing. An abandoned batch can leave those updates ahead of warehouse data; document that accepted limitation. Retrying retained work is the usual recovery path. Avoid changing configuration during an active batch.

## 4. Keep adaptive scheduling in one function

Before each internal run, query the configured region/queue. Exclude claimed players and players already handled by the batch from both numerator and denominator; use staleness zero if no eligible population remains.

```text
penalty = max(0, inactive_streak - floor(elapsed / freshness_period))
staleness = sum(2 ** -penalty for eligible stale players) / eligible population
proportion = 3 * staleness
```

If `STALE_REFRESH_LIMIT` is zero, disable refresh. Otherwise, when the proportion is at least 1, refresh only. Below 1, calculate `floor(205 * proportion / (1 - proportion))`. If this reaches `STALE_REFRESH_LIMIT`, refresh only up to that limit; otherwise request one discovery page plus the calculated refresh count. This uses the configured count instead of the fixed `0.8` cutoff.

Reuse the API rate limiter and log the decision/counts. No per-player Airflow tasks are needed.

## 5. Wire the stages

```text
collect_batch → validate_and_compact → upload
    → Databricks ingestion + dbt job
    → commit_export_publish → cleanup
```

Use TaskFlow wrappers for Python stages:

- **Validate/compact:** reuse full database/raw-file checks, compaction, and the existing post-compaction report. Missing required reports or reported errors fail. Check readable outputs; no new validation framework.
- **Upload:** use stable destinations such as `players/<batch_id>.parquet` and `masteries/<batch_id>.parquet`. Retry the same content. Reuse `load_champions()` here, require a positive returned row count, and propagate exceptions. Move final SQLite load marking and the upload-triggered Neon upsert out of this stage.
- **Warehouse:** use `DatabricksRunNowOperator` to trigger the existing job and wait for final success. Reuse its built-in run recovery with the pinned versions instead of writing a poller. See [operator documentation](https://airflow.apache.org/docs/apache-airflow-providers-databricks/stable/operators/run_now.html).
- **Commit/export/publish:** after job success, apply the existing upload-related Neon upsert and SQLite load marking, then export/publish. These upserts/assignments may repeat on retry; do not increment inactivity again.
- **Cleanup:** archive the ledger and remove batch working files only after success.

In `ingest_players.ipynb`, raise caught ingestion errors instead of logging/continuing. Keep Auto Loader/checkpoints. Trust completed job success: no source-file column, receipt table, row-count reconciliation, or raw-table migration.

Use normal success dependencies, finite task timeouts sized for the batch, and small XCom values. Import pipeline modules inside running tasks. For no-data batches, mark them complete inside collection and use a short-circuit guard to skip downstream work. No custom branch/join design is needed.

## 6. Publish with the existing exporter

Run a full export into `data/exports/<batch_id>` without `--dataset`. Keep its existing validation. Upload to `snapshots/<batch_id>/`, then replace the stable manifest last. Successful S3 API responses suffice; extra checksums/object verification are optional. Keep the previous version for manual rollback and reuse a completed staged export on publication retry.

Add public-URL loading in `streamlit_app/app_core/data.py`, retain local mode, and cache by manifest version. Use one manifest version per app rerun. Configure S3 manually when ready and deploy Streamlit with the public URL. This can follow the first collection-to-warehouse demo.

## 7. Demonstrate and enable

Run existing Python tests and one manual DAG with one or two internal runs and a low refresh limit. Check unique filenames, once-per-batch collection, and policy rounding. Demonstrate a successful batch, a no-data run, and a failed stage followed by retry. Confirm failures preserve local files and the previous public manifest.

After retries are exhausted, pause the DAG and repair/clear only the failed stage. The marker rejects a new batch while one is unfinished; `max_active_runs=1` alone does not enforce that after failure. To discard an old batch, stop its remote job, archive its ledger, release claims, and reset local work manually. Leave remote checkpoints intact and do not rerun the abandoned DAG run.

Stop the legacy runner, pause the Databricks file-arrival trigger, and enable the daily DAG. Add Graph/Grid and retry screenshots and the public dashboard link to the README.

## Optional after the demo

Per-file ingestion receipts, delayed page/inactivity commits, champion staging/patch-aware refresh, automatic stale-batch disposal, additional integrity contracts, object checksums, and a full failure-injection suite can wait. The first release proves scheduling, dependencies, retries, persistent batch work, and dashboard refresh.
