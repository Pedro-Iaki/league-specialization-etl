# Log inventory

This lists every explicit log call, `print` call, retry logging callback and
`tqdm` label found in all tracked Python files and executable Python notebook
cells after the logging refinement on `ai-review`. Test and exploratory output
appear separately. Templates show runtime expressions in braces; angle brackets
identify values printed directly. Notebook locations use one-based cell numbers
and cell-local line numbers. Source locations refer to this version of the code.

## Ordinary console view

Loguru's default sink includes DEBUG. For normal progress and completion messages,
plus warnings and errors, set the level **before starting Python**:

```powershell
$env:PYTHONPATH = "src"
$env:LOGURU_LEVEL = "INFO"
python -m extract.run_pipeline
```

`LOGURU_LEVEL` is a process environment variable, not an extraction-file setting.
It accepts Loguru severity names, defaults to `DEBUG`, and `INFO` suppresses
lower-severity messages. DEBUG includes paths, rate-limit headers, job/run IDs,
deduplication counts and compaction summaries. Warnings/errors keep diagnostic
details; `logger.exception` also emits the active traceback. Notebook diagnostics
use Python logging, controlled by the Databricks Python logging configuration;
ordinary notebook progress uses stdout.

Long mastery/refresh loops report the first attempt and every 25 attempted players,
then actual saved counts at completion. ETAs assume 50 requests/minute at 95%
efficiency and two requests per refreshed player. They do not change rate limits.

SDK, Spark, Auto Loader and dbt messages and unhandled Python tracebacks depend
on library versions and runtime results. They are outside the finite set of
repository-authored templates below.

## Illustrative successful round

These fictional values illustrate final INFO message text; they do not represent
a live run. Loguru also prefixes timestamps, severity and source locations. A real
invocation has depth × tier count × division count rounds. Integrity/load stages
appear at `RUNS_PER_LOAD` intervals and for final leftovers.

```text
Starting round 1/1.
Fetching player snapshot... Rough ETA: under 1 minute.
Player snapshot saved: 50 new or stale players out of 205 observed. Elapsed: 0.8s.
Fetching masteries for up to 50 players... Rough ETA: 1.1 min (development-key estimate).
Fetching mastery 1/50. Rough ETA: 1.1 min. Elapsed: 0.0 min.
Fetching mastery 25/50. Rough ETA: 0.5 min. Elapsed: 0.5 min.
Fetching mastery 50/50. Rough ETA: 0.0 min. Elapsed: 1.0 min.
Masteries saved for 50/50 players. Elapsed: 1.1 min.
Refreshing 25 stale players and their masteries... Rough ETA: 1.1 min (development-key estimate).
Refreshing player 1/25. Rough ETA: 1.1 min. Elapsed: 0.0 min.
Refreshing player 25/25. Rough ETA: 0.0 min. Elapsed: 1.0 min.
Refreshed ranks for 25/25 players and saved masteries for 25. Failed refreshes: 0. Elapsed: 1.1 min.
Checking collected data (raw-file scan: off).
Integrity check completed: 75 player records, 0 faulty or incomplete. Reports: data/logs.
Compacting players: 75 pending player records.
Compacted players: 26 files, 75 rows, 75 players.
Compacting masteries: 75 pending player records.
Compacted masteries: 75 files, 1500 rows, 75 players.
Compaction check completed: 0 issues, 0 player records awaiting compaction.
Loading champion reference data...
Loaded 170 champion reference rows.
Uploading and loading collected player files...
Uploaded players: 75 rows for 75 players; awaiting ingestion.
Uploaded masteries: 1500 rows for 75 players; awaiting ingestion.
Ingestion job started (attempt 1/3).
Ingestion job completed in 0.5 min.
Ingestion confirmed; collection state updated.
Building analytical tables...
dbt job started (attempt 1/3).
dbt job completed in 1.5 min.
Load and build stages completed.
Extraction state reset after successful load.
Round 1 completed.
```

Verification also displays the `tqdm` bars listed below. Full verification adds a
compaction check before compaction. Small collection loops may show only the
first attempt and completion. No-work alternatives cover unavailable snapshots,
fresh/awaiting-load players, no masteries, no stale players, a zero refresh
allocation and absent/empty compacted inputs. Reaching the refresh cap skips
discovery and its mastery loop while retaining stale-player refresh.

## Failures and detailed reports

- Configuration errors stop before collection. API, validation, save, compaction,
  upload and job failures keep their warning/error details listed below.
- Collection failures stop the round, whose error names the failing stage and
  retained files. Unexpected exceptions also produce tracebacks. Refresh failures
  are warnings/errors, never ordinary INFO progress.
- Failed uploads do not print successful upload messages. Uploaded data awaits
  ingestion; confirmation follows successful ingestion and registry/ledger updates.
  A no-file load skips ingestion and can still proceed to dbt.
- Jobs retry up to three attempts. Timeout errors identify the remote run ID when
  known and stop the local wait without cancelling that run. A dbt failure keeps
  the earlier confirmed ingestion state.
- The dynamic `error` message in `run_snapshot_fetchers` is `One or more extraction
  tasks failed or did not finish.`; in `run_stale_refresh` it is `One or more player
  refreshes failed.` Other exception details vary with the failing operation.

Existing reports keep detailed diagnostics available:

| Report | Contents |
| --- | --- |
| `data/logs/job_results.json` | Every attempted round, status, failing stage, error and stage-specific results; rewritten as rounds finish. |
| `data/logs/db_integrity_check.json` | Ledger checks, faulty records and task/duplicate statistics. |
| `data/logs/integrity_check.json` | Optional raw-file scan: unreadable/missing files, player/mastery coverage and duplicate diagnostics. |
| `data/logs/compaction_integrity_check.json` | Compaction task/output checks, pending records and raw-file diagnostics. |

## Complete source inventory

Found **245 output sites**: 18 DEBUG, 52 ERROR, 5 ERROR + traceback, 40 INFO, 6 PROGRESS, 106 STDOUT, 16 WARNING, 2 WARNING (retry callback).

### Pipeline Python logs

| Source and context | Level | Message template |
| --- | --- | --- |
| [src/extract/api_client.py:16](../src/extract/api_client.py#L16) · `_log_retry` | WARNING | `Retrying request after attempt {retry_state.attempt_number}: {exception}` |
| [src/extract/api_client.py:45](../src/extract/api_client.py#L45) · `get_patch` | ERROR | `Failed to fetch the latest patch version.` |
| [src/extract/api_client.py:64](../src/extract/api_client.py#L64) · `get` | WARNING | `429 Too Many Requests received, rate limited` |
| [src/extract/api_client.py:67](../src/extract/api_client.py#L67) · `get` | ERROR | `401 Unauthorized received, invalid API key. Please check your RIOT_API_KEY environment variable.` |
| [src/extract/api_client.py:81](../src/extract/api_client.py#L81) · `_initialize_buckets_from_response` | WARNING | `API response did not contain X-App-Rate-Limit. ` |
| [src/extract/api_client.py:95](../src/extract/api_client.py#L95) · `_initialize_buckets_from_response` | WARNING | `Couldn't consume initial token in rate-limit bucket: {bucket}` |
| [src/extract/api_client.py:97](../src/extract/api_client.py#L97) · `_initialize_buckets_from_response` | DEBUG | `Initialized Riot rate limits: {rate_limit_header}` |
| [src/extract/compact_parquets.py:55](../src/extract/compact_parquets.py#L55) · `compact_files` | WARNING | `Skipping compaction source, file not found on disk: {missing}` |
| [src/extract/compact_parquets.py:107](../src/extract/compact_parquets.py#L107) · `compact_dataset` | WARNING (retry callback) | `Retrying {function} in {seconds} seconds as it raised {exception_type}: {exception}.` |
| [src/extract/compact_parquets.py:113](../src/extract/compact_parquets.py#L113) · `compact_dataset` | INFO | `Compacting {dataset}: {len(rows)} pending player records.` |
| [src/extract/compact_parquets.py:115](../src/extract/compact_parquets.py#L115) · `compact_dataset` | INFO | `No {dataset} records to compact.` |
| [src/extract/compact_parquets.py:121](../src/extract/compact_parquets.py#L121) · `compact_dataset` | WARNING | `Skipping player {row['player_id']}: no logged path for dataset {dataset}.` |
| [src/extract/compact_parquets.py:152](../src/extract/compact_parquets.py#L152) · `compact_dataset` | ERROR | `Failed to compact dataset {dataset}: {e}` |
| [src/extract/compact_parquets.py:160](../src/extract/compact_parquets.py#L160) · `compact_dataset` | INFO | `Compacted {dataset}: {len(result['compacted_files'])} files, {result['rows_written']} rows, {len(player_ids)} players.` |
| [src/extract/compact_parquets.py:164](../src/extract/compact_parquets.py#L164) · `compact_dataset` | DEBUG | `Compacted {dataset} output: {result['output_path']}` |
| [src/extract/compact_parquets.py:175](../src/extract/compact_parquets.py#L175) · `_dedup_merged_table` | WARNING | `Skipping dedup for {dataset}: dedup keys not found in schema.` |
| [src/extract/compact_parquets.py:187](../src/extract/compact_parquets.py#L187) · `_dedup_merged_table` | DEBUG | `Dropped {dropped} duplicate row(s) for {dataset} during compaction.` |
| [src/extract/compact_parquets.py:197](../src/extract/compact_parquets.py#L197) · `run` | ERROR + traceback | `Compaction run failed: {e}` |
| [src/extract/compact_parquets.py:199](../src/extract/compact_parquets.py#L199) · `run` | DEBUG | `Players compaction summary: {players_summary}` |
| [src/extract/compact_parquets.py:200](../src/extract/compact_parquets.py#L200) · `run` | DEBUG | `Masteries compaction summary: {masteries_summary}` |
| [src/extract/extraction_db_helper.py:24](../src/extract/extraction_db_helper.py#L24) · `is_active` | ERROR | `Database connection error: {e}` |
| [src/extract/extraction_db_helper.py:61](../src/extract/extraction_db_helper.py#L61) · `start_run` | ERROR | `Failed to start a new run for pipeline {pipeline_name}.` |
| [src/extract/extraction_db_helper.py:116](../src/extract/extraction_db_helper.py#L116) · `add_player_task` | ERROR | `Failed to add a new player task for run {run_id}.` |
| [src/extract/extraction_db_helper.py:326](../src/extract/extraction_db_helper.py#L326) · `add_mastery_task` | ERROR | `Failed to add a new mastery task for player {player_id}.` |
| [src/extract/extraction_db_helper.py:367](../src/extract/extraction_db_helper.py#L367) · `update_mastery_task` | ERROR | `No mastery task found with task_id {task_id}.` |
| [src/extract/extraction_db_helper.py:419](../src/extract/extraction_db_helper.py#L419) · `get_mastery_id_from_list` | ERROR | `No task ID found for player {puuid} in the provided task list.` |
| [src/extract/extraction_db_helper.py:447](../src/extract/extraction_db_helper.py#L447) · `cleanup_stale_runs` | WARNING | `Cleaning up {len(stalled_run_ids)} stalled runs.` |
| [src/extract/extraction_db_helper.py:449](../src/extract/extraction_db_helper.py#L449) · `cleanup_stale_runs` | DEBUG | `No stalled runs to clean up.` |
| [src/extract/extraction_db_helper.py:470](../src/extract/extraction_db_helper.py#L470) · `cleanup_failed_run` | DEBUG | `Cleaning up failed run {run_id}.` |
| [src/extract/extraction_db_helper.py:727](../src/extract/extraction_db_helper.py#L727) · `add_compaction_task` | ERROR | `Failed to add a new compaction task for {dataset} output {output_path}.` |
| [src/extract/get_masteries.py:23](../src/extract/get_masteries.py#L23) · `run` | INFO | `No player masteries to fetch.` |
| [src/extract/get_masteries.py:26](../src/extract/get_masteries.py#L26) · `run` | INFO | `Fetching masteries for up to {goal} players... Rough ETA: {get_eta_minutes(goal):.1f} min (development-key estimate).` |
| [src/extract/get_masteries.py:41](../src/extract/get_masteries.py#L41) · `run` | INFO | `Fetching mastery {player_number}/{goal}. Rough ETA: {get_eta_minutes(remaining):.1f} min. Elapsed: {(monotonic() - started_at) / 60:.1f} min.` |
| [src/extract/get_masteries.py:48](../src/extract/get_masteries.py#L48) · `run` | ERROR | `No task ID found for player {puuid}. Skipping.` |
| [src/extract/get_masteries.py:59](../src/extract/get_masteries.py#L59) · `run` | ERROR | `No mastery data found for player {puuid}.` |
| [src/extract/get_masteries.py:67](../src/extract/get_masteries.py#L67) · `run` | ERROR | `Failed to save mastery data for player {puuid}.` |
| [src/extract/get_masteries.py:74](../src/extract/get_masteries.py#L74) · `run` | INFO | `Masteries saved for {processed}/{goal} players. Elapsed: {(monotonic() - started_at) / 60:.1f} min.` |
| [src/extract/get_masteries.py:82](../src/extract/get_masteries.py#L82) · `get_player_info` | ERROR | `No player info found for {puuid}.` |
| [src/extract/get_masteries.py:91](../src/extract/get_masteries.py#L91) · `get_player_info` | ERROR | `Missing required information for player {puuid}: region={region}, queue={queue}, tier={tier}, division={division}, date={date}` |
| [src/extract/get_masteries.py:108](../src/extract/get_masteries.py#L108) · `fetch_player_masteries` | ERROR | `No API client provided. Please set the RIOT_API_KEY environment variable and provide a valid API client.` |
| [src/extract/get_masteries.py:119](../src/extract/get_masteries.py#L119) · `fetch_player_masteries` | ERROR | `Error fetching mastery data for player {puuid}: {e}` |
| [src/extract/get_masteries.py:137](../src/extract/get_masteries.py#L137) · `fetch_player_masteries` | ERROR | `Error validating mastery data for player {puuid}: {e}` |
| [src/extract/get_masteries.py:152](../src/extract/get_masteries.py#L152) · `save_masteries` | ERROR | `Missing required information for saving masteries: region={region}, queue={queue}, date={date}, division={division}, puuid={puuid}, tier={tier}` |
| [src/extract/get_players.py:36](../src/extract/get_players.py#L36) · `run` | ERROR | `Player extractor not supplied with vital parameters, make sure to assign it.` |
| [src/extract/get_players.py:39](../src/extract/get_players.py#L39) · `run` | ERROR | `Invalid run id supplied to player extractor, cancelling operation.` |
| [src/extract/get_players.py:43](../src/extract/get_players.py#L43) · `run` | INFO | `Fetching player snapshot... Rough ETA: under 1 minute.` |
| [src/extract/get_players.py:53](../src/extract/get_players.py#L53) · `run` | INFO | `No player snapshot available for {region} {queue}.` |
| [src/extract/get_players.py:95](../src/extract/get_players.py#L95) · `run` | INFO | `Snapshot contains {snapshot_size} players; no new files needed. Elapsed: {monotonic() - started_at:.1f}s.` |
| [src/extract/get_players.py:105](../src/extract/get_players.py#L105) · `run` | INFO | `Snapshot contains {snapshot_size} players already awaiting load. Elapsed: {monotonic() - started_at:.1f}s.` |
| [src/extract/get_players.py:140](../src/extract/get_players.py#L140) · `run` | INFO | `Player snapshot saved: {len(snapshot_viable_players)} new or stale players out of {snapshot_size} observed. Elapsed: {monotonic() - started_at:.1f}s.` |
| [src/extract/get_players.py:161](../src/extract/get_players.py#L161) · `fetch_players` | ERROR | `No API client provided. Please set the RIOT_API_KEY environment variable and provide a valid API client.` |
| [src/extract/get_players.py:173](../src/extract/get_players.py#L173) · `fetch_players` | ERROR | `Error fetching players for {region} {queue} {tier} {division}: {e}` |
| [src/extract/get_players.py:178](../src/extract/get_players.py#L178) · `fetch_players` | ERROR | `Error fetching players for {region} {queue} {tier} {division}: {response.status_code} - {response.text}` |
| [src/extract/get_players.py:192](../src/extract/get_players.py#L192) · `fetch_players` | DEBUG | `Empty page for {region} {queue} {tier} {division}; cursor reset.` |
| [src/extract/get_players.py:196](../src/extract/get_players.py#L196) · `fetch_players` | ERROR | `Error validating player data for {region} {queue} {tier} {division}: {e}` |
| [src/extract/init_extraction_db.py:41](../src/extract/init_extraction_db.py#L41) · `clear_directory_contents` | ERROR | `Failed to delete {entry.path}. Reason: {e}` |
| [src/extract/init_extraction_db.py:66](../src/extract/init_extraction_db.py#L66) · `initialize_database` | INFO | `Local extraction database initialized.` |
| [src/extract/init_extraction_db.py:76](../src/extract/init_extraction_db.py#L76) · `reset_database` | INFO | `Database and raw directories reset successfully.` |
| [src/extract/refresh_stale_players.py:42](../src/extract/refresh_stale_players.py#L42) · `run` | WARNING | `Reaped {released_expired} expired refresh claim(s).` |
| [src/extract/refresh_stale_players.py:50](../src/extract/refresh_stale_players.py#L50) · `run` | INFO | `No stale players to refresh.` |
| [src/extract/refresh_stale_players.py:55](../src/extract/refresh_stale_players.py#L55) · `run` | INFO | `Refreshing {goal} stale players and their masteries... Rough ETA: {get_eta_minutes(2 * goal):.1f} min (development-key estimate).` |
| [src/extract/refresh_stale_players.py:79](../src/extract/refresh_stale_players.py#L79) · `run` | INFO | `Refreshing player {players_attempted}/{goal}. Rough ETA: {get_eta_minutes(2 * remaining):.1f} min. Elapsed: {(monotonic() - started_at) / 60:.1f} min.` |
| [src/extract/refresh_stale_players.py:103](../src/extract/refresh_stale_players.py#L103) · `run` | WARNING | `Failed to refresh player, Failures: {failures}. Skipping.` |
| [src/extract/refresh_stale_players.py:126](../src/extract/refresh_stale_players.py#L126) · `run` | WARNING | `Failed to refresh mastery. Failures: {failures}` |
| [src/extract/refresh_stale_players.py:131](../src/extract/refresh_stale_players.py#L131) · `run` | INFO | `Refreshed ranks for {players_refreshed}/{goal} players and saved masteries for {masteries_refreshed}. Failed refreshes: {failures}. Elapsed: {(monotonic() - started_at) / 60:.1f} min.` |
| [src/extract/refresh_stale_players.py:153](../src/extract/refresh_stale_players.py#L153) · `fetch_player_rank` | ERROR | `No API client provided. Please set the RIOT_API_KEY environment variable and provide a valid API client.` |
| [src/extract/refresh_stale_players.py:162](../src/extract/refresh_stale_players.py#L162) · `fetch_player_rank` | ERROR | `Error fetching rank for player {puuid}: {e}` |
| [src/extract/refresh_stale_players.py:167](../src/extract/refresh_stale_players.py#L167) · `fetch_player_rank` | ERROR | `Error fetching rank for player {puuid}: {response.status_code} - {response.text}` |
| [src/extract/refresh_stale_players.py:174](../src/extract/refresh_stale_players.py#L174) · `fetch_player_rank` | WARNING | `No {queue} entry found for player {puuid}; may be unranked or removed.` |
| [src/extract/refresh_stale_players.py:181](../src/extract/refresh_stale_players.py#L181) · `fetch_player_rank` | ERROR | `Error validating rank data for player {puuid}: {e}` |
| [src/extract/refresh_stale_players.py:194](../src/extract/refresh_stale_players.py#L194) · `handle_player_extraction` | ERROR | `Missing required player info: {info}` |
| [src/extract/refresh_stale_players.py:199](../src/extract/refresh_stale_players.py#L199) · `handle_player_extraction` | WARNING | `Failed to fetch rank for player {puuid} in {region} {queue}.` |
| [src/extract/refresh_stale_players.py:239](../src/extract/refresh_stale_players.py#L239) · `handle_mastery_extraction` | ERROR | `Missing required player info: {info}` |
| [src/extract/refresh_stale_players.py:250](../src/extract/refresh_stale_players.py#L250) · `handle_mastery_extraction` | WARNING | `Failed to fetch mastery data for player {puuid} in {region} {queue}.` |
| [src/extract/refresh_stale_players.py:269](../src/extract/refresh_stale_players.py#L269) · `handle_mastery_extraction` | ERROR | `Failed to save mastery data for player {puuid} in {region} {queue}.` |
| [src/extract/reset_extraction_state.py:8](../src/extract/reset_extraction_state.py#L8) · `reset_local_data` | INFO | `Extraction state reset after successful load.` |
| [src/extract/run_pipeline.py:57](../src/extract/run_pipeline.py#L57) · `run_pipeline` | ERROR | `Invalid configuration: {e}` |
| [src/extract/run_pipeline.py:65](../src/extract/run_pipeline.py#L65) · `run_pipeline` | ERROR | `Cannot connect to database. Ensure init_db has been run and the database is accessible in the correct folder.` |
| [src/extract/run_pipeline.py:91](../src/extract/run_pipeline.py#L91) · `extraction_loop` | INFO | `Starting round {run_n + 1}/{runs_remaining}.` |
| [src/extract/run_pipeline.py:113](../src/extract/run_pipeline.py#L113) · `extraction_loop` | DEBUG | `Using fallback snapshot size {snapshot_size} for refresh allocation.` |
| [src/extract/run_pipeline.py:119](../src/extract/run_pipeline.py#L119) · `extraction_loop` | INFO | `Skipping new-player collection to refresh previously collected players.` |
| [src/extract/run_pipeline.py:173](../src/extract/run_pipeline.py#L173) · `extraction_loop` | ERROR + traceback | `Round {run_n + 1} failed at {result.stage}.` |
| [src/extract/run_pipeline.py:177](../src/extract/run_pipeline.py#L177) · `extraction_loop` | ERROR | `Round {run_n + 1} stopped at {result.stage}: {result.error}` |
| [src/extract/run_pipeline.py:179](../src/extract/run_pipeline.py#L179) · `extraction_loop` | INFO | `Round {run_n + 1} completed.` |
| [src/extract/run_pipeline.py:190](../src/extract/run_pipeline.py#L190) · `run_snapshot_fetchers` | DEBUG | `Starting snapshot run {run_id}.` |
| [src/extract/run_pipeline.py:214](../src/extract/run_pipeline.py#L214) · `run_snapshot_fetchers` | ERROR | `<error>` |
| [src/extract/run_pipeline.py:219](../src/extract/run_pipeline.py#L219) · `run_snapshot_fetchers` | ERROR + traceback | `An error occurred during the pipeline run: {err}` |
| [src/extract/run_pipeline.py:229](../src/extract/run_pipeline.py#L229) · `run_stale_refresh` | INFO | `Refresh skipped: the calculated player limit is zero.` |
| [src/extract/run_pipeline.py:232](../src/extract/run_pipeline.py#L232) · `run_stale_refresh` | DEBUG | `Starting refresh run {run_id} with a limit of {limit} players.` |
| [src/extract/run_pipeline.py:246](../src/extract/run_pipeline.py#L246) · `run_stale_refresh` | ERROR | `<error>` |
| [src/extract/run_pipeline.py:251](../src/extract/run_pipeline.py#L251) · `run_stale_refresh` | ERROR + traceback | `Stale-player refresh run failed: {e}` |
| [src/extract/run_pipeline.py:267](../src/extract/run_pipeline.py#L267) · `run_load` | INFO | `Loading champion reference data...` |
| [src/extract/run_pipeline.py:269](../src/extract/run_pipeline.py#L269) · `run_load` | INFO | `Uploading and loading collected player files...` |
| [src/extract/run_pipeline.py:272](../src/extract/run_pipeline.py#L272) · `run_load` | INFO | `Building analytical tables...` |
| [src/extract/run_pipeline.py:278](../src/extract/run_pipeline.py#L278) · `run_load` | INFO | `Load and build stages completed.` |
| [src/extract/run_pipeline.py:281](../src/extract/run_pipeline.py#L281) · `run_load` | ERROR + traceback | `Load or dbt build failed: {e}` |
| [src/extract/verify_integrity.py:25](../src/extract/verify_integrity.py#L25) · `run_integrity_check` | INFO | `Checking collected data (raw-file scan: {'on' if full else 'off'}).` |
| [src/extract/verify_integrity.py:33](../src/extract/verify_integrity.py#L33) · `run_integrity_check` | INFO | `Integrity check completed: {database_log.get('total_player_records', 0)} player records, {database_log.get('faulty_records_count', 0)} faulty or incomplete. Reports: data/logs.` |
| [src/extract/verify_integrity.py:47](../src/extract/verify_integrity.py#L47) · `is_compaction_ready` | ERROR | `Database integrity check failed: faulty record count {database.get('faulty_records_count')}.` |
| [src/extract/verify_integrity.py:54](../src/extract/verify_integrity.py#L54) · `is_compaction_ready` | ERROR | `Raw file integrity check failed: {total_errors} error(s).` |
| [src/extract/verify_integrity.py:67](../src/extract/verify_integrity.py#L67) · `is_load_ready` | ERROR | `Compaction integrity check failed: issues {issues}, uncompacted records {pending}.` |
| [src/extract/verify_integrity.py:96](../src/extract/verify_integrity.py#L96) · `verify_files_integrity` | ERROR | `Failed to read player file {player_file}: {e}` |
| [src/extract/verify_integrity.py:113](../src/extract/verify_integrity.py#L113) · `verify_files_integrity` | ERROR | `Failed to read mastery file {mastery_file}: {e}` |
| [src/extract/verify_integrity.py:457](../src/extract/verify_integrity.py#L457) · `verify_compaction_integrity` | INFO | `Compaction check completed: {len(task_level_issues)} issues, {sum(pending.values())} player records awaiting compaction.` |
| [src/extract/verify_integrity.py:461](../src/extract/verify_integrity.py#L461) · `verify_compaction_integrity` | DEBUG | `Compaction check pending records by dataset: {pending}` |
| [src/load/databricks_helper.py:64](../src/load/databricks_helper.py#L64) · `run_job` | ERROR | `Cannot start {job_name} job {job_id}: {error}` |
| [src/load/databricks_helper.py:72](../src/load/databricks_helper.py#L72) · `run_job` | INFO | `{job_name} job started (attempt {attempt}/{MAX_JOB_ATTEMPTS}).` |
| [src/load/databricks_helper.py:73](../src/load/databricks_helper.py#L73) · `run_job` | DEBUG | `{job_name} job {job_id}, run {run_id}.` |
| [src/load/databricks_helper.py:77](../src/load/databricks_helper.py#L77) · `run_job` | INFO | `{job_name} job completed in {(monotonic() - started_at) / 60:.1f} min.` |
| [src/load/databricks_helper.py:80](../src/load/databricks_helper.py#L80) · `run_job` | ERROR | `{job_name} job {job_id}, run {run_id} timed out: {error}. Stopping this job check; check the run in Databricks before retrying.` |
| [src/load/databricks_helper.py:85](../src/load/databricks_helper.py#L85) · `run_job` | ERROR | `{job_name} job {job_id}, run {run_id}, attempt {attempt} failed: {error}` |
| [src/load/load_champions_to_databricks.py:31](../src/load/load_champions_to_databricks.py#L31) · `load_champions` | WARNING | `No champion data to load. Exiting.` |
| [src/load/load_champions_to_databricks.py:65](../src/load/load_champions_to_databricks.py#L65) · `load_champions` | INFO | `Loaded {len(records)} champion reference rows.` |
| [src/load/load_champions_to_databricks.py:66](../src/load/load_champions_to_databricks.py#L66) · `load_champions` | DEBUG | `Champion reference table: {CATALOG}.{SCHEMA}.{TABLE_NAME}.` |
| [src/load/load_compacted_to_databricks.py:30](../src/load/load_compacted_to_databricks.py#L30) · `_upload` | WARNING (retry callback) | `Retrying {function} in {seconds} seconds as it raised {exception_type}: {exception}.` |
| [src/load/load_compacted_to_databricks.py:42](../src/load/load_compacted_to_databricks.py#L42) · `load_dataset` | INFO | `No compacted file found for {dataset}, nothing to load.` |
| [src/load/load_compacted_to_databricks.py:47](../src/load/load_compacted_to_databricks.py#L47) · `load_dataset` | INFO | `No {dataset} rows to upload.` |
| [src/load/load_compacted_to_databricks.py:64](../src/load/load_compacted_to_databricks.py#L64) · `load_dataset` | ERROR | `Failed to extract players from {dataset}: {e}` |
| [src/load/load_compacted_to_databricks.py:71](../src/load/load_compacted_to_databricks.py#L71) · `load_dataset` | ERROR | `Failed to load {dataset} after {MAX_UPLOAD_ATTEMPTS} attempts, will retry on next run: {e}` |
| [src/load/load_compacted_to_databricks.py:76](../src/load/load_compacted_to_databricks.py#L76) · `load_dataset` | INFO | `Uploaded {dataset}: {table.num_rows} rows for {len(players)} players; awaiting ingestion.` |
| [src/load/load_compacted_to_databricks.py:77](../src/load/load_compacted_to_databricks.py#L77) · `load_dataset` | DEBUG | `{dataset} upload status: {status}; local input: {compacted_path}.` |
| [src/load/load_compacted_to_databricks.py:88](../src/load/load_compacted_to_databricks.py#L88) · `complete_loaded_rank_pages` | DEBUG | `Page claim for task {task['task_id']} expired or was already completed; keeping ingested data.` |
| [src/load/load_compacted_to_databricks.py:96](../src/load/load_compacted_to_databricks.py#L96) · `load_compacted` | ERROR | `Upload failed; ingestion was not started. Retaining local files.` |
| [src/load/load_compacted_to_databricks.py:99](../src/load/load_compacted_to_databricks.py#L99) · `load_compacted` | INFO | `No collected files to ingest.` |
| [src/load/load_compacted_to_databricks.py:103](../src/load/load_compacted_to_databricks.py#L103) · `load_compacted` | ERROR | `Ingestion was not confirmed; retaining local files without applying the loader's Neon updates.` |
| [src/load/load_compacted_to_databricks.py:119](../src/load/load_compacted_to_databricks.py#L119) · `load_compacted` | ERROR | `Ingestion succeeded but registry/ledger updates failed: {error}. Retaining local files.` |
| [src/load/load_compacted_to_databricks.py:121](../src/load/load_compacted_to_databricks.py#L121) · `load_compacted` | INFO | `Ingestion confirmed; collection state updated.` |
| [src/load/player_registry.py:121](../src/load/player_registry.py#L121) · `record_refresh_result` | WARNING | `Refresh claim no longer belongs to {claimed_by} for {region}/{queue}/{puuid}; result skipped.` |

### Databricks ingestion notebook

| Source and context | Level | Message template |
| --- | --- | --- |
| [src/load/ingest_players.ipynb:cell 4, line 14](../src/load/ingest_players.ipynb) · `module` | STDOUT | `Schema refreshed from {path}` |
| [src/load/ingest_players.ipynb:cell 4, line 16](../src/load/ingest_players.ipynb) · `module` | STDOUT | `No files in landing zone for {subdir} — reusing existing schema.` |
| [src/load/ingest_players.ipynb:cell 4, line 19](../src/load/ingest_players.ipynb) · `module` | DEBUG | `Schema for {subdir}: {new_schema_json}` |
| [src/load/ingest_players.ipynb:cell 6, line 14](../src/load/ingest_players.ipynb) · `module` | ERROR | `Error accessing landing path {landing_path} for {subdir}: {e}` |
| [src/load/ingest_players.ipynb:cell 6, line 18](../src/load/ingest_players.ipynb) · `module` | STDOUT | `No files in landing zone for {subdir}; skipping ingestion.` |
| [src/load/ingest_players.ipynb:cell 6, line 22](../src/load/ingest_players.ipynb) · `module` | DEBUG | `Raw table {raw_table} found: {table_exists}` |
| [src/load/ingest_players.ipynb:cell 6, line 37](../src/load/ingest_players.ipynb) · `module` | STDOUT | `Created schema metadata for {subdir} from landing files.` |
| [src/load/ingest_players.ipynb:cell 6, line 61](../src/load/ingest_players.ipynb) · `module` | STDOUT | `Streaming ingestion completed for {raw_table}.` |

### Other pipeline console output

| Source and context | Level | Message template |
| --- | --- | --- |
| [src/extract/get_champions.py:111](../src/extract/get_champions.py#L111) · `module` | STDOUT | `<get_champions_dataframe()>` |
| [src/extract/get_champions.py:112](../src/extract/get_champions.py#L112) · `module` | STDOUT | `<get_champions_dataframe().info()>` |
| [src/extract/verify_integrity.py:84](../src/extract/verify_integrity.py#L84) · `verify_files_integrity` | PROGRESS | `Verifying player files (unit: file)` |
| [src/extract/verify_integrity.py:101](../src/extract/verify_integrity.py#L101) · `verify_files_integrity` | PROGRESS | `Verifying mastery files (unit: file)` |
| [src/extract/verify_integrity.py:117](../src/extract/verify_integrity.py#L117) · `verify_files_integrity` | PROGRESS | `Verifying mastery records (unit: record)` |
| [src/extract/verify_integrity.py:127](../src/extract/verify_integrity.py#L127) · `verify_files_integrity` | PROGRESS | `Verifying player records (unit: record)` |
| [src/extract/verify_integrity.py:222](../src/extract/verify_integrity.py#L222) · `verify_db_integrity` | PROGRESS | `Verifying database records (unit: record)` |
| [src/extract/verify_integrity.py:354](../src/extract/verify_integrity.py#L354) · `verify_compaction_integrity` | PROGRESS | `Verifying compaction tasks (unit: task)` |
| [src/load/migrate_player_registry.py:19](../src/load/migrate_player_registry.py#L19) · `main` | STDOUT | `Player registry schema is ready` |

### Synthetic sample commands

| Source and context | Level | Message template |
| --- | --- | --- |
| [src/load/load_business_sample.py:51](../src/load/load_business_sample.py#L51) · `load_sample` | STDOUT | `INCOMPLETE business sample load; dashboard export is blocked until both tables reconcile.` |
| [src/load/load_business_sample.py:53](../src/load/load_business_sample.py#L53) · `load_sample` | STDOUT | `Loaded {result['player_count']:,} sample players and {result['transaction_count']:,} sample transactions` |
| [src/load/load_business_sample.py:64](../src/load/load_business_sample.py#L64) · `main` | STDOUT | `Validated {players.num_rows:,} players and {events.num_rows:,} transactions; no warehouse writes` |
| [src/sample/generate_transactions.py:121](../src/sample/generate_transactions.py#L121) · `fetch_cohort` | STDOUT | `Selected {complete.num_rows:,} complete players from {table.num_rows:,} current profiles; excluded {table.num_rows - complete.num_rows:,} incomplete/invalid profiles; no row cap` |
| [src/sample/generate_transactions.py:300](../src/sample/generate_transactions.py#L300) · `main` | STDOUT | `Frozen {cohort.num_rows:,} complete real players at one as-of date` |
| [src/sample/generate_transactions.py:311](../src/sample/generate_transactions.py#L311) · `main` | STDOUT | `{manifest['scenario_id']}: {players.num_rows:,} players, {transactions.num_rows:,} transactions, USD {manifest['cash_spent_usd_alltime']} hypothetical source cash` |

### Manual dashboard export output

| Source and context | Level | Message template |
| --- | --- | --- |
| [streamlit_app/scripts/export_data.py:114](../streamlit_app/scripts/export_data.py#L114) · `export_snapshots` | STDOUT | `Exporting {name}...` |
| [streamlit_app/scripts/export_data.py:121](../streamlit_app/scripts/export_data.py#L121) · `export_snapshots` | STDOUT | `  Optional business sample is not built; skipping.` |
| [streamlit_app/scripts/export_data.py:140](../streamlit_app/scripts/export_data.py#L140) · `export_snapshots` | STDOUT | `  {len(frame):,} rows -> {destination.name}` |
| [streamlit_app/scripts/export_data.py:153](../streamlit_app/scripts/export_data.py#L153) · `main` | STDOUT | `Export complete: {total_bytes / 1048576:.2f} MiB` |
| [streamlit_app/scripts/export_population_estimates.py:158](../streamlit_app/scripts/export_population_estimates.py#L158) · `module` | STDOUT | `<json.dumps(result, indent=2)>` |
| [streamlit_app/scripts/export_population_estimates.py:159](../streamlit_app/scripts/export_population_estimates.py#L159) · `module` | STDOUT | `Analyst bundle: {args.output_dir.resolve() / 'population_estimates.zip'}` |

### Test harness logs

| Source and context | Level | Message template |
| --- | --- | --- |
| [src/extract/tests/conftest.py:91](../src/extract/tests/conftest.py#L91) · `mock_db` | INFO | `Creating test database at: {db_path}` |
| [src/extract/tests/conftest.py:125](../src/extract/tests/conftest.py#L125) · `module` | INFO | `Seed: {SUITE_SEED}` |

### Exploratory script output

| Source and context | Level | Message template |
| --- | --- | --- |
| [sandbox/get_clean_data.py:62](../sandbox/get_clean_data.py#L62) · `module` | STDOUT | `Collected {len(all_players_list)} players` |
| [sandbox/get_clean_data.py:93](../sandbox/get_clean_data.py#L93) · `module` | STDOUT | `Collected {len(all_masteries_list)} mastery entries` |
| [sandbox/get_clean_data.py:162](../sandbox/get_clean_data.py#L162) · `module` | STDOUT | `Saved players_{timestamp}.parquet, masteries_{timestamp}.parquet, champions_{timestamp}.json` |
| [sandbox/transform_and_plot.py:223](../sandbox/transform_and_plot.py#L223) · `module` | STDOUT | `\n=== PLAYER MASTERY POOL PROFILE ===` |
| [sandbox/transform_and_plot.py:224](../sandbox/transform_and_plot.py#L224) · `module` | STDOUT | `<players_df[profile_cols].describe()>` |
| [sandbox/transform_and_plot.py:226](../sandbox/transform_and_plot.py#L226) · `module` | STDOUT | `\nExample player mastery pool profiles:` |
| [sandbox/transform_and_plot.py:227](../sandbox/transform_and_plot.py#L227) · `module` | STDOUT | `<players_df[profile_cols].head(10)>` |
| [sandbox/transform_and_plot.py:232](../sandbox/transform_and_plot.py#L232) · `module` | STDOUT | `=== DATA DIAGNOSTICS ===` |
| [sandbox/transform_and_plot.py:233](../sandbox/transform_and_plot.py#L233) · `module` | STDOUT | `Number of players: {len(players_df)}` |
| [sandbox/transform_and_plot.py:234](../sandbox/transform_and_plot.py#L234) · `module` | STDOUT | `Number of mastery entries: {len(masteries_df)}` |
| [sandbox/transform_and_plot.py:235](../sandbox/transform_and_plot.py#L235) · `module` | STDOUT | `\nPlayers DataFrame columns:` |
| [sandbox/transform_and_plot.py:236](../sandbox/transform_and_plot.py#L236) · `module` | STDOUT | `<players_df.columns.tolist()>` |
| [sandbox/transform_and_plot.py:237](../sandbox/transform_and_plot.py#L237) · `module` | STDOUT | `\nMasteries DataFrame columns:` |
| [sandbox/transform_and_plot.py:238](../sandbox/transform_and_plot.py#L238) · `module` | STDOUT | `<masteries_df.columns.tolist()>` |
| [sandbox/transform_and_plot.py:239](../sandbox/transform_and_plot.py#L239) · `module` | STDOUT | `\nFirst 5 rows of players_df:` |
| [sandbox/transform_and_plot.py:240](../sandbox/transform_and_plot.py#L240) · `module` | STDOUT | `<players_df.head()>` |
| [sandbox/transform_and_plot.py:241](../sandbox/transform_and_plot.py#L241) · `module` | STDOUT | `\nFirst 5 rows of masteries_df:` |
| [sandbox/transform_and_plot.py:242](../sandbox/transform_and_plot.py#L242) · `module` | STDOUT | `<masteries_df.head()>` |
| [sandbox/transform_and_plot.py:245](../sandbox/transform_and_plot.py#L245) · `module` | STDOUT | `\nUnique values in 'tier' column:` |
| [sandbox/transform_and_plot.py:246](../sandbox/transform_and_plot.py#L246) · `module` | STDOUT | `<players_df['tier'].unique()>` |
| [sandbox/transform_and_plot.py:247](../sandbox/transform_and_plot.py#L247) · `module` | STDOUT | `\nValue counts:` |
| [sandbox/transform_and_plot.py:248](../sandbox/transform_and_plot.py#L248) · `module` | STDOUT | `<players_df['tier'].value_counts(dropna=False)>` |
| [sandbox/transform_and_plot.py:255](../sandbox/transform_and_plot.py#L255) · `module` | STDOUT | `\nPlayers with mastery_sum:` |
| [sandbox/transform_and_plot.py:256](../sandbox/transform_and_plot.py#L256) · `module` | STDOUT | `<players_df[['mastery_sum']].head()>` |
| [sandbox/transform_and_plot.py:257](../sandbox/transform_and_plot.py#L257) · `module` | STDOUT | `\nMastery sum statistics:` |
| [sandbox/transform_and_plot.py:258](../sandbox/transform_and_plot.py#L258) · `module` | STDOUT | `<players_df['mastery_sum'].describe()>` |
| [sandbox/transform_and_plot.py:282](../sandbox/transform_and_plot.py#L282) · `module` | STDOUT | `\nTop {top_n} champions by total mastery points:` |
| [sandbox/transform_and_plot.py:283](../sandbox/transform_and_plot.py#L283) · `module` | STDOUT | `<champion_totals>` |
| [sandbox/transform_and_plot.py:326](../sandbox/transform_and_plot.py#L326) · `module` | STDOUT | `\nChampions of interest availability:` |
| [sandbox/transform_and_plot.py:329](../sandbox/transform_and_plot.py#L329) · `module` | STDOUT | `  {id_to_name.get(champ, champ)}: {'✓ Found' if exists else '✗ Not found'}` |
| [sandbox/transform_and_plot.py:335](../sandbox/transform_and_plot.py#L335) · `module` | STDOUT | `\nNumber of mastery entries for selected champions: {len(filtered_masteries)}` |
| [sandbox/transform_and_plot.py:347](../sandbox/transform_and_plot.py#L347) · `module` | STDOUT | `Rows after dropping missing ranks: {len(merged_data_clean)}` |
| [sandbox/transform_and_plot.py:355](../sandbox/transform_and_plot.py#L355) · `module` | STDOUT | `\nAverage mastery points by tier and champion:` |
| [sandbox/transform_and_plot.py:356](../sandbox/transform_and_plot.py#L356) · `module` | STDOUT | `<avg_mastery_by_rank.rename(columns=id_to_name)>` |
| [sandbox/transform_and_plot.py:391](../sandbox/transform_and_plot.py#L391) · `module` | STDOUT | `\nAverage mastery sum by tier:` |
| [sandbox/transform_and_plot.py:392](../sandbox/transform_and_plot.py#L392) · `module` | STDOUT | `<avg_mastery_sum_by_rank>` |
| [sandbox/transform_and_plot.py:427](../sandbox/transform_and_plot.py#L427) · `module` | STDOUT | `\nNormalized average mastery (percentage of overall average mastery sum):` |
| [sandbox/transform_and_plot.py:428](../sandbox/transform_and_plot.py#L428) · `module` | STDOUT | `<normalized_mastery.rename(columns=id_to_name)>` |
| [sandbox/transform_and_plot.py:453](../sandbox/transform_and_plot.py#L453) · `module` | STDOUT | `\n=== SUMMARY STATISTICS ===` |
| [sandbox/transform_and_plot.py:454](../sandbox/transform_and_plot.py#L454) · `module` | STDOUT | `\nTop 10 players by total mastery:` |
| [sandbox/transform_and_plot.py:456](../sandbox/transform_and_plot.py#L456) · `module` | STDOUT | `<top_players>` |
| [sandbox/transform_and_plot.py:458](../sandbox/transform_and_plot.py#L458) · `module` | STDOUT | `\nMastery distribution by champion (top 10):` |
| [sandbox/transform_and_plot.py:461](../sandbox/transform_and_plot.py#L461) · `module` | STDOUT | `<champion_stats>` |
| [sandbox/transform_and_plot.py:463](../sandbox/transform_and_plot.py#L463) · `module` | STDOUT | `\nRank distribution:` |
| [sandbox/transform_and_plot.py:465](../sandbox/transform_and_plot.py#L465) · `module` | STDOUT | `<tier_dist>` |
| [sandbox/transform_and_plot.py:654](../sandbox/transform_and_plot.py#L654) · `module` | STDOUT | `<players_df['freshBlood'].value_counts(dropna=False)>` |
| [sandbox/transform_and_plot.py:670](../sandbox/transform_and_plot.py#L670) · `module` | STDOUT | `\nSummary statistics by freshBlood status:` |
| [sandbox/transform_and_plot.py:671](../sandbox/transform_and_plot.py#L671) · `module` | STDOUT | `<summary>` |
| [sandbox/transform_and_plot.py:677](../sandbox/transform_and_plot.py#L677) · `module` | STDOUT | `\nMann-Whitney U test: U={u_stat:.1f}, p={p_val:.4g}` |
| [sandbox/transform_and_plot.py:689](../sandbox/transform_and_plot.py#L689) · `module` | STDOUT | `Pearson correlation (total_games vs mastery_sum): {corr_pearson:.3f}` |
| [sandbox/transform_and_plot.py:1067](../sandbox/transform_and_plot.py#L1067) · `module` | STDOUT | `Pool-only mastery entries: {len(masteries_pool_only)}` |
| [sandbox/transform_and_plot.py:1088](../sandbox/transform_and_plot.py#L1088) · `module` | STDOUT | `\nRobust {CELL_AGG} pool-champion mastery per entry, by tier:` |
| [sandbox/transform_and_plot.py:1089](../sandbox/transform_and_plot.py#L1089) · `module` | STDOUT | `<avg_champion_mastery_by_tier>` |
| [sandbox/transform_and_plot.py:1199](../sandbox/transform_and_plot.py#L1199) · `module` | STDOUT | `\n{CELL_AGG.capitalize()} log2 fold-change by role and tier (0 = no change, +1 = doubled, -1 = halved):` |
| [sandbox/transform_and_plot.py:1200](../sandbox/transform_and_plot.py#L1200) · `module` | STDOUT | `<pd.DataFrame(role_summary).reindex(index=rank_order)>` |
| [sandbox/transform_and_plot.py:1271](../sandbox/transform_and_plot.py#L1271) · `module` | STDOUT | `Global specialist threshold: {global_threshold:.0f} mastery points` |
| [sandbox/transform_and_plot.py:1378](../sandbox/transform_and_plot.py#L1378) · `module` | STDOUT | `Players used for clustering: {len(clustering_data)} (out of {len(players_df)})` |
| [sandbox/transform_and_plot.py:1436](../sandbox/transform_and_plot.py#L1436) · `module` | STDOUT | `\nCluster centroids (original units):` |
| [sandbox/transform_and_plot.py:1437](../sandbox/transform_and_plot.py#L1437) · `module` | STDOUT | `<cluster_centers_original>` |
| [sandbox/transform_and_plot.py:1438](../sandbox/transform_and_plot.py#L1438) · `module` | STDOUT | `\nNumber of players per archetype:` |
| [sandbox/transform_and_plot.py:1439](../sandbox/transform_and_plot.py#L1439) · `module` | STDOUT | `<cluster_counts>` |
| [sandbox/transform_and_plot.py:1555](../sandbox/transform_and_plot.py#L1555) · `module` | STDOUT | `Plotting archetype proportions per tier for champion: {champ_name} (ID {champion_to_plot})` |
| [sandbox/transform_and_plot.py:1566](../sandbox/transform_and_plot.py#L1566) · `module` | STDOUT | `Tiers retained (≥{MIN_PLAYERS} players): {list(valid_tiers)}` |
| [sandbox/transform_and_plot.py:1734](../sandbox/transform_and_plot.py#L1734) · `module` | STDOUT | `Players used: <len(model_df)>` |
| [sandbox/transform_and_plot.py:1735](../sandbox/transform_and_plot.py#L1735) · `module` | STDOUT | `Archetypes: <all_archetypes>` |
| [sandbox/transform_and_plot.py:1736](../sandbox/transform_and_plot.py#L1736) · `module` | STDOUT | `Tiers: <all_tiers>` |
| [sandbox/transform_and_plot.py:1896](../sandbox/transform_and_plot.py#L1896) · `archetype_effects_for_champion` | STDOUT | `Could not fit champion {champion_id}: {e}` |
| [sandbox/transform_and_plot.py:2013](../sandbox/transform_and_plot.py#L2013) · `module` | STDOUT | `[{i:2d}/{len(top_champions)}] Champion {champ_id}` |
| [sandbox/transform_and_plot.py:2040](../sandbox/transform_and_plot.py#L2040) · `module` | STDOUT | `<effects_df>` |
| [sandbox/transform_and_plot.py:2059](../sandbox/transform_and_plot.py#L2059) · `module` | STDOUT | `<effects_df.round(2)>` |
| [sandbox/transform_and_plot.py:2281](../sandbox/transform_and_plot.py#L2281) · `module` | STDOUT | `Players: {len(model_df):,}` |
| [sandbox/transform_and_plot.py:2285](../sandbox/transform_and_plot.py#L2285) · `module` | STDOUT | `Champions: {player_pool_long['championId'].nunique():,}` |
| [sandbox/transform_and_plot.py:2290](../sandbox/transform_and_plot.py#L2290) · `module` | STDOUT | `Archetypes: {all_archetypes}` |
| [sandbox/transform_and_plot.py:2294](../sandbox/transform_and_plot.py#L2294) · `module` | STDOUT | `Tiers: {all_tiers}` |
| [sandbox/transform_and_plot.py:2298](../sandbox/transform_and_plot.py#L2298) · `module` | STDOUT | `Reference archetype: {reference_archetype}` |
| [sandbox/transform_and_plot.py:2500](../sandbox/transform_and_plot.py#L2500) · `fit_champion_model` | STDOUT | `Failed champion {champion_id}: {e}` |
| [sandbox/transform_and_plot.py:2699](../sandbox/transform_and_plot.py#L2699) · `module` | STDOUT | `\nRunning weighted regression for {len(all_champions):,} champions...` |
| [sandbox/transform_and_plot.py:2737](../sandbox/transform_and_plot.py#L2737) · `module` | STDOUT | `{i:,}/{len(all_champions):,}` |
| [sandbox/transform_and_plot.py:2793](../sandbox/transform_and_plot.py#L2793) · `module` | STDOUT | `\nResults:` |
| [sandbox/transform_and_plot.py:2797](../sandbox/transform_and_plot.py#L2797) · `module` | STDOUT | `<effects_df.head()>` |
| [sandbox/transform_and_plot.py:2893](../sandbox/transform_and_plot.py#L2893) · `module` | STDOUT | `\nHeatmap:\n{heatmap_path}` |
| [sandbox/transform_and_plot.py:3077](../sandbox/transform_and_plot.py#L3077) · `module` | STDOUT | `<'\n' + '=' * 70>` |
| [sandbox/transform_and_plot.py:3081](../sandbox/transform_and_plot.py#L3081) · `module` | STDOUT | `INDIVIDUAL CHAMPION: {get_champion_name(champion_id)} ({champion_id})` |
| [sandbox/transform_and_plot.py:3087](../sandbox/transform_and_plot.py#L3087) · `module` | STDOUT | `<'=' * 70>` |
| [sandbox/transform_and_plot.py:3106](../sandbox/transform_and_plot.py#L3106) · `module` | STDOUT | `Champion {champion_id} does not meet MIN_PLAYERS={MIN_PLAYERS}` |
| [sandbox/transform_and_plot.py:3140](../sandbox/transform_and_plot.py#L3140) · `module` | STDOUT | `<result_table.round(2)>` |

### Databricks build output

`resources/build_dbt.job.yml` executes `dbt deps`, then `dbt build`. dbt emits its
own dependency, model/test progress, elapsed-time, warning/error and completion
output in the remote job logs. Python emits the job lifecycle messages listed
above and records the result in `job_results.json`. The older paused
`resources/ingest_clean_transform.job.yml` also declares dbt commands; their
output likewise comes from dbt. No custom dbt/Jinja logging calls were found.

### Maintenance

When changing messages, update the illustrative run and affected inventory rows.
Coverage was checked by parsing every tracked `.py` file and Python `.ipynb` cell
for severity calls on `logger`/`logging`, `print`, `tqdm`, and `before_sleep_log`.
Sink setup/forwarding (`add`, `remove`, `handle`) does not introduce message
templates. Progress bars and retry callbacks can emit multiple times per site;
the count above represents call sites, not the number of lines in one run.
