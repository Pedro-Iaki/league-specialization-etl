# Orchestration and execution state

[Project README](../../README.md) · [Documentation index](../README.md) · [Configuration](configuration.md) · [Data models](data-models.md) · [Validation and evidence](validation-and-evidence.md)

The Python [runner](../../src/extract/run_pipeline.py) owns stage ordering and work allocation. It coordinates collection and warehouse delivery; dashboard exports and simulated-source generation are separate manual operations.

## State ownership

| Store | Responsibility | Important boundary |
|---|---|---|
| SQLite, `data/database/extraction.db` | Runs, player/mastery tasks, file references, compaction and load status | Explains local execution and retained inputs. Task attempts are not a count of individual HTTP requests. |
| Neon Postgres | Tracked-player freshness/inactivity, refresh claims and discovery cursors | Durable collection coordination across runs. It does not store the analytical observation history. |
| Databricks | Landing files, raw Delta observations, ingestion checkpoints and analytical tables | Uploaded files, ingested observations and successfully built analytical models are separate outcomes. |
| JSON reports and logs | Diagnostics and summaries | Outputs for inspection; they do not replace the stores above as execution state. |

The [SQLite helper](../../src/extract/extraction_db_helper.py) owns local SQL and transactions. Coupled compaction-task and player-state updates are committed together there. A caller supplying a connection owns commit, rollback and close. PostgreSQL claims and warehouse jobs have their own boundaries; the workflow is not one transaction across services.

## Startup and round lifecycle

1. Read and validate extraction settings before collection. Create missing local storage without resetting an existing ledger.
2. Mark runs with no heartbeat for over one hour failed, cleaning up their unfinished task state while retaining successful task evidence.
3. Reconcile raw Parquet files against ledger references. Move unreferenced files into a timestamped quarantine tree. A reconciliation error stops startup before collection.
4. Create the API client and enter the configured number of rounds: fetch depth × tier count × division count.

Each round follows this sequence:

| Stage | Work and success condition |
|---|---|
| Staleness | Calculate weighted stale pressure for the configured region/queue and derive a capped refresh allocation. |
| Discovery | Unless paused at the refresh cap, claim one ranked page, collect eligible new observations and attempt pending mastery work. Any failed or unfinished extraction task fails that run. |
| Refresh | Claim stale known players, collect their rank and mastery observations and record per-player outcomes. A calculated limit of zero is a successful skip. |
| Integrity | At load cadence or the final round, require a valid ledger report with zero faulty records. When full verification is enabled, also require the raw-file scan to pass. |
| Compaction | Merge ledger-selected raw files, retaining source-file and task lineage. Complete the compaction task and affected record states together. |
| Compacted-output verification | Check the resulting files and ledger links. Missing diagnostics, task-level issues or records still awaiting compaction prevent upload. This gate always runs. |
| Load | Refresh character metadata, upload collected datasets, wait for ingestion confirmation, apply delivery-related collection state, then run the separate dbt build. |
| Cleanup | Only after delivery/build success and no incomplete local loads, clear the raw and compacted directories. Preserve SQLite and its diagnostics. |

A successful collection-only round can finish before its files have reached the warehouse. Delivery occurs at `RUNS_PER_LOAD` and at the final round. A successful overall invocation has passed its required delivery cycles; it does not automatically export or publish dashboard data.

## Discovery, refresh and claims

[Discovery](../../src/extract/get_players.py) reserves a page in `rank_page_progress`, scoped by region, queue, tier, division and patch. Transactional selection uses `FOR UPDATE SKIP LOCKED`; progress ties visit configured division order before tier order. The page's total observed size is recorded before freshness filtering.

Already fresh players are excluded using the shared registry. Recent local observations awaiting ingestion are also excluded, preventing their repeated collection while delivery is pending. A page that saved observations retains its claim token in SQLite until those observations are confirmed loaded. Empty pages reset their cursor to page one for a new traversal. A page containing only already-confirmed fresh players can advance without another load; one excluded because its data is still pending locally cannot use that shortcut. Failed requests release their claim without advancing the cursor.

[Refresh](../../src/extract/refresh_stale_players.py) uses registry player claims. Expired claims are reclaimable after 30 minutes, and a worker renews its claims on a cadence of one third of that timeout while iterating. It releases claims it still owns on exit. Losing a claim does not invalidate a genuine saved observation. Successful responses showing no entry for the tracked queue are handled separately from request failures and can update collection state without inventing a data file.

The API client synchronizes pacing within that client. Shared PostgreSQL claims do not create a global API-key rate limiter, and the local file workflow is not evidence of a tested multi-machine deployment.

### Adaptive allocation

For each tracked player, effective inactivity penalty is the inactive streak minus complete elapsed freshness periods, bounded below by zero. The contribution to stale pressure is `2 ** (-penalty)` when that player is stale and claimable. The denominator is **all tracked players in the selected region/queue**, not the sum of their weights. Inactivity is based on unchanged wins plus losses in that queue; request failures are not inactivity evidence.

Let `s` be that weighted stale fraction and `c` be `MAX_REFRESH_SCALE`:

```text
p = 3 * s
refresh_scale = c                         if p >= 1
refresh_scale = min(c, p / (1 - p))        otherwise
refresh_limit = ceil(snapshot_size * refresh_scale)
```

Use the observed page size when nonzero; otherwise the runner uses its explained fallback of 205. For `s = 0.20` and `c = 4`, the scale is `1.5` and the fallback allocation is 308 players. Eligibility and available claims can reduce actual work. At the cap, discovery and its mastery fetcher pause by default; configuration can keep them enabled without increasing the refresh cap.

## Upload, ingestion and build boundaries

The [loader](../../src/load/load_compacted_to_databricks.py) uploads player/mastery Parquet to timestamp-and-UUID paths under `/Volumes/league_pipeline/landing_zone`. Successful upload records `pending_load`; it does not establish raw-table ingestion.

The [ingestion notebook](../../src/load/ingest_players.ipynb) uses Auto Loader with persisted schema/checkpoint locations and `availableNow`, writes raw Delta tables with `_ingested_at`, and waits for each stream to terminate. Access or execution failures propagate to the job. Only a successful ingestion job result lets the loader update player freshness/inactivity, mark SQLite loads successful and complete linked discovery pages.

These post-ingestion writes span separate stores. If registry or ledger updates fail, the loader reports failure and retains inputs even though the remote ingestion already succeeded. Reapplying an observation is subject to the registry's freshness checks; there is no cross-service atomicity claim. An expired page claim can prevent cursor completion without invalidating ingested data.

The runner then submits the **separate** dbt job. A later build failure preserves previously confirmed ingestion and blocks normal file cleanup. If both compacted datasets are absent or empty, the loader skips the ingestion submission; the runner can still invoke dbt. Character-reference loading is separate SQL work: an empty metadata result is reported as zero rows, while an exception stops the load stage.

## Separate transaction and serving operations

The simulated branch freezes eligible real profiles, generates transaction files and validates them before its [sample-only loader](../../src/load/load_business_sample.py) connects. That loader writes only the two dedicated raw sample tables. It invalidates the cohort completion marker first, replaces transactions, writes the cohort last and reconciles the result. This is a completion convention across separate table replacements, not a multi-table transaction. Business dbt models and the serving export are subsequent operations.

The [dashboard exporter](../../streamlit_app/scripts/export_data.py) reads warehouse results manually. It checks public-column contracts and business reconciliation, replaces each Parquet file through a temporary file, then writes a manifest. A complete set of serving files is not published atomically. Pipeline cleanup, a successful dbt build or a new generated scenario does not by itself refresh the dashboard.

## Failure and retry behavior

| Failure or interruption | Recorded outcome and next inspection |
|---|---|
| Invalid extraction configuration | Return failure before collection. Correct the reported setting. |
| Collection or refresh failure | Stop the round. Preserve successful outputs and mark unfinished work failed; startup reconciliation can quarantine files that no longer have valid ledger references. |
| Raw or ledger integrity failure | Do not compact. Inspect the relevant report and its task/file records. |
| Compaction or output-verification failure | Do not upload. Keep inputs and compaction diagnostics. |
| Upload or unconfirmed ingestion | Do not apply the loader's delivery-related registry updates or normal cleanup. Inspect upload status and remote run identity. |
| Ingestion succeeded, state updates failed | Preserve local evidence and the confirmed remote result. Inspect both stores before retrying. |
| dbt failed after ingestion | Keep confirmed loads recorded and local files retained. Inspect the build independently of source delivery. |
| Local job wait expired | Return failure without cancelling the remote job or submitting another attempt from that call. Inspect the existing Databricks run first. |
| Operator interruption | Record the active stage and interruption, stop locally and avoid normal cleanup. Partial work still needs inspection. |

The [API client](../../src/extract/api_client.py) permits up to six attempts for rate-limit/server HTTP responses and connection/timeout errors, using bounded exponential backoff. Ordinary authorization failures do not meet that retry predicate. Compaction permits three attempts only for selected transient file/SQLite errors. Uploads permit three attempts. The [Jobs helper](../../src/load/databricks_helper.py) permits up to three submissions for non-timeout failures; a timeout stops immediately. These are implemented policies, not evidence that every remote failure is transient or automatically recoverable.

## Inspecting a run

Use SQLite's `runs`, `player_tasks`, `mastery_tasks`, `players_recorded` and `compaction_tasks` together. Collection task states are `pending`, `in_progress`, `success` and `failed`; per-dataset load state progresses through `pending_compaction`, `pending_load`, `load_success` or `load_failed`. Run heartbeat and task attempts describe local execution.

The runner writes per-round stage details to `data/logs/job_results.json`. Integrity checks write `db_integrity_check.json`, optional `integrity_check.json` and `compaction_integrity_check.json` in that directory. Remote job IDs and run IDs are logged for inspection. These fixed report paths can be overwritten by later invocations; retain a dated copy when packaging execution evidence.

Normal cleanup removes file contents, not the ledger or registry. Explicit reset utilities are separate operations and must not be treated as ordinary retry steps. The described boundaries come from source inspection and targeted local checks; they do not establish exactly-once processing, measured throughput or a completed live failure-and-retry exercise.
