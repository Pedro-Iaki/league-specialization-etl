# Python orchestration

Run from the repository root. Python performs collection, checks, compaction,
upload, ingestion confirmation, and a separate dbt build. The dashboard export
script is run manually after a successful build.

## Configuration

Fill in `config/EXTRACTION_CONFIG.env` using its example. Files are read directly;
explicit process environment values can override them. Pydantic validates the
extraction and job settings together before collection.
Credentials remain in local ignored files.

The [configuration reference](../README.md#work-on-the-pipeline) covers every
setting's units, defaults, bounds and workflow effects. The linked examples
include those details beside each value.

| File | What belongs here |
| --- | --- |
| `config/EXTRACTION_CONFIG.env` | Riot key, collection options, deployed ingestion/dbt job IDs and wait timeouts |
| `config/DATABRICKS_CONFIG.env` | Existing Databricks credentials and SQL warehouse connection settings |
| `.env.local` | Registry connection URL: prefer `DATABASE_URL`, fall back to `DATABASE_URL_UNPOOLED`; at least one is required |

Before the first collection against a new registry database, execute the full
[registry schema](../src/load/player_registry_schema.sql) in that database's
Neon SQL editor, using the `public` schema. It creates both registry tables and
their indexes. Existing registries with the current schema need no repeated
setup, and normal collection does not run schema migrations.

| Extraction setting | Meaning | Default |
| --- | --- | --- |
| `RIOT_API_KEY` | Riot API credential | Required |
| `REGION`, `QUEUE` | Scope for discovery, staleness and refresh | Required |
| `PLAYERS_FETCH_DEPTH` | Number of collection rounds per configured tier/division pair | Required |
| `MASTERY_TASK_LIMIT` | Maximum local missing-mastery work per round | Required |
| `TIERS` | Discovery tiers | Diamond through Iron |
| `DIVISIONS` | Discovery divisions | I, II, III, IV |
| `FRESHNESS_THRESHOLD_MINUTES` | Age at which a player becomes stale | 10080 (one week) |
| `MAX_REFRESH_SCALE` | Maximum refreshes per observed snapshot player; reaching it skips both snapshot fetchers by default | 4 |
| `PAUSE_DISCOVERY_AT_REFRESH_CAP` | Pause discovery and missing-mastery fetching at the cap; false keeps discovery enabled without changing stale-player eligibility | true |
| `RUNS_PER_LOAD` | Collection rounds between loads; leftovers also load | 10 |
| `FULL_VERIFICATION` | Also scan raw files before compaction; compacted checks always run | false |
| `INGEST_JOB_ID`, `DBT_JOB_ID` | Positive numeric IDs of the deployed jobs | Required; replace example zeros |
| `INGESTION_TIMEOUT_SECONDS` | Local ingestion wait | 900 |
| `DBT_TIMEOUT_SECONDS` | Local dbt wait | 1800 |

Python reads `config/EXTRACTION_CONFIG.env` and validates collection and job
settings together before starting work. Each stage receives those validated
settings; it does not reread the file. The standalone load command uses
the same complete configuration through the shared reader. Explicit process
environment values still take precedence over file values.

Claim expiry is a program constant of 30 minutes. Upload, ingestion, dbt and
transient compaction retries are capped at three attempts. Adaptive scheduling
uses the observed snapshot size and `MAX_REFRESH_SCALE`, with the runner's
205-player fallback only for skipped/empty snapshots. `STALENESS_INTENSITY=3`
controls the weighting described in the root README. There is no separate discovery
cutoff or fixed player-count cap. `PAUSE_DISCOVERY_AT_REFRESH_CAP=false` keeps
discovery enabled when refresh allocation is capped; it does not permit refreshing
fresh players. The existing Riot client controls rate limits.
There is no `VERSION`, fixed refresh-limit setting, or claim-timeout setting.
The former `FULL_VERIFICATION_POST` setting is now `FULL_VERIFICATION`.

With dependencies installed and jobs configured:

```powershell
$env:PYTHONPATH = "src"
python -m extract.run_pipeline
```

## State and failure behavior

- SQLite `data/database/extraction.db` records runs, tasks, files and load status.
  Ordinary startup creates missing storage without resetting existing work.
  New runs have an initial heartbeat; stale cleanup also handles older null
  heartbeats. Explicit development reset remains a separate destructive action.
- Before collection, startup compares raw Parquet paths with all SQLite task,
  player-record and compaction-source references. Unreferenced files move to
  `data/quarantine/<UTC timestamp>/players/` or `masteries/`, retaining their
  partition layout. No age cutoff or Parquet parsing is needed; corrupt orphan
  files can be moved too. Quarantined files are retained outside normal cleanup.
  Referenced files stay in place, including failed-task inputs; existing integrity
  checks still handle missing or corrupt referenced data. Startup stops if the
  ledger cannot be read, a move fails, or a local run is still marked running.
  Run startup without another local collector starting against the same folders;
  this check is not a filesystem lock. Pending loads keep their configured cadence.
- Neon `player_state_registry` and `rank_page_progress` coordinate freshness,
  inactivity, refresh claims and discovery cursors.
- Databricks `league_pipeline.raw` receives files; one dbt build produces the
  Bronze, Silver and Gold layers. Upload filenames include a unique suffix so
  collectors uploading within the same second retain separate files.
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
- Snapshot success requires all extraction tasks in that SQLite run to succeed.
  Refresh success requires no failed rank/mastery requests. Failed or unfinished
  collection stops the round and retains successful files; empty snapshots,
  missing queue entries and no work to refresh remain valid outcomes.
- Request progress logs include rough ETAs and elapsed time, assuming 50 requests
  per minute at 95% efficiency. A rank/mastery refresh uses about two requests per
  player; these estimates do not measure throughput or change rate limiting.
  Progress appears on the first attempt and every 25 players, plus final saved
  counts. See the [complete log inventory](log_inventory.md) for every message,
  severity, source location, notebook output and progress label. Set the process
  environment variable `LOGURU_LEVEL=INFO` before Python starts for concise output;
  `DEBUG` includes diagnostic paths, IDs and compaction summaries.
- Pending and stale mastery work share the configured task limit. Patch lookup
  happens before claiming, so a lookup failure leaves that work available.
- A dbt failure preserves confirmed ingestion status and local files.
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
python -m pytest src/extract/tests/test_fetch_status.py src/extract/tests/test_cleanup_behavior.py src/extract/tests/test_startup_state.py src/extract/tests/test_mastery_claim_limits.py -q
python -m pytest src/extract/tests/test_pipeline_reporting.py -q
python -m pytest src/extract/tests/test_load_boundaries.py src/load/tests/test_confirm_ingestion.py -q
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
