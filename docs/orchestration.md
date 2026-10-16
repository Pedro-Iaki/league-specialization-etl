# Python orchestration

Run from the repository root. Python performs collection, checks, compaction,
upload, ingestion confirmation, and a separate dbt build. The dashboard export
script is run manually after a successful build.

## Configuration

Fill in `config/EXTRACTION_CONFIG.env` using its example. Files are read directly;
explicit process environment values can override them. Pydantic validates the
extraction settings before collection, and the job settings before their use.
Credentials remain in local ignored files.

| File | What belongs here |
| --- | --- |
| `config/EXTRACTION_CONFIG.env` | Riot key, collection options, deployed ingestion/dbt job IDs and wait timeouts |
| `config/DATABRICKS_CONFIG.env` | Existing Databricks credentials and SQL warehouse connection settings |
| `.env.local` | `DATABASE_URL` for the Neon registry; `DATABASE_URL_UNPOOLED` for its one-time schema setup |

| Extraction setting | Meaning | Default |
| --- | --- | --- |
| `RIOT_API_KEY` | Riot API credential | Required |
| `REGION`, `QUEUE` | Scope for discovery, staleness and refresh | Required |
| `PLAYERS_FETCH_DEPTH` | Number of collection rounds per configured tier/division pair | Required |
| `MASTERY_TASK_LIMIT` | Maximum local missing-mastery work per round | Required |
| `TIERS` | Discovery tiers | Diamond through Iron |
| `DIVISIONS` | Discovery divisions | I, II, III, IV |
| `FRESHNESS_THRESHOLD_MINUTES` | Age at which a player becomes stale | 10080 (one week) |
| `MAX_REFRESH_SCALE` | Maximum refreshes per observed snapshot player; reaching it skips both snapshot fetchers | 4 |
| `RUNS_PER_LOAD` | Collection rounds between loads; leftovers also load | 10 |
| `FULL_VERIFICATION` | Also scan raw files before compaction; compacted checks always run | false |
| `INGEST_JOB_ID`, `DBT_JOB_ID` | Positive numeric IDs of the deployed jobs | Required; replace example zeros |
| `INGESTION_TIMEOUT_SECONDS` | Local ingestion wait | 900 |
| `DBT_TIMEOUT_SECONDS` | Local dbt wait | 1800 |

Claim expiry is a program constant of 30 minutes. Upload, ingestion, dbt and
transient compaction retries are capped at three attempts. Adaptive scheduling
uses the observed snapshot size and `MAX_REFRESH_SCALE`, with the runner's
205-player fallback only for skipped/empty snapshots. `STALENESS_INTENSITY=3`
controls the weighting described in the root README. There is no separate discovery
cutoff or fixed player-count cap. The existing Riot client controls rate limits.
There is no `VERSION`, fixed refresh-limit setting, or claim-timeout setting.
The former `FULL_VERIFICATION_POST` setting is now `FULL_VERIFICATION`.

With dependencies installed and jobs configured:

```powershell
$env:PYTHONPATH = "src"
python -m extract.run_pipeline
```

## State and failure behavior

- SQLite `data/database/extraction.db` records runs, tasks, files and load status.
- Neon `player_state_registry` and `rank_page_progress` coordinate freshness,
  inactivity, refresh claims and discovery cursors.
- Databricks `league_pipeline.raw` receives files; one dbt build produces the
  Bronze, Silver and Gold layers.
- An integrity failure prevents upload. Ingestion failure prevents load-success,
  freshness/inactivity and page-completion updates. Valid no-file outcomes can
  update immediately.
- Refresh heartbeats renew only claims still owned by that worker, at one third
  of the claim timeout (10 minutes with the current default). Existing
  expiry cleanup runs before refresh claiming. Lost claims do not invalidate files.
  Only fresh local collections awaiting rank ingestion, without a current failure,
  are excluded from refresh claims. Stale or failed work passes this local filter;
  the registry's normal freshness and claim rules still apply.
- Snapshot outcomes always have a result object. Refresh scheduling details stay
  inside `refresh_result`; top-level status/stage/error summarize the round for
  the operator. Detailed errors stay with their stage results.
- Request progress logs include rough ETAs and elapsed time, assuming 50 requests
  per minute at 95% efficiency. A rank/mastery refresh uses about two requests per
  player; these estimates do not measure throughput or change rate limiting.
- A dbt failure preserves confirmed ingestion status and local files. Retry the
  build with `python -m load.build_dbt`.
- A job timeout stops the local stage and logs its remote run ID when available.
  Inspect that run in Databricks before retrying; a timed-out remote run may still
  be running.
- Cleanup occurs only after required stages and recorded loads succeed.
  `job_results.json` is a report, not another source of execution state.

## Review feature by feature

All commands below run local tests without calling live Riot, Neon or Databricks:

```powershell
python -m pytest src/extract/tests/test_compaction_gate.py -q
python -m pytest src/extract/tests/test_adaptive_refresh.py src/load/tests/test_player_registry.py -q
python -m pytest src/extract/tests/test_refresh_tracking.py -q
python -m pytest src/extract/tests/test_pipeline_reporting.py -q
python -m pytest src/extract/tests/test_load_boundaries.py src/load/tests/test_confirm_ingestion.py src/load/tests/test_build_dbt.py -q
```

The tests use temporary SQLite databases/Parquet and mocked cloud calls. Registry
SQL conflict/weighting/claim behavior is exercised locally with SQLite adapters;
this does not replace running it against Postgres.

After code review, evaluate a real collection/load cycle. Inspect the ingestion
and dbt job results, SQLite load flags, Neon freshness/page changes, and
`data/logs/job_results.json`. Review failed-stage messages in the ordinary logs and
`compaction_integrity_check.json`. Live success and failure behavior still need
evaluation before bulk refinement. No new Neon schema migration is required by
these orchestration follow-ups.
