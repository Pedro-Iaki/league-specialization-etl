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
Snapshot saved: 50 rank observations out of 205 observed; 100 fresh in Neon, 55 fresh locally awaiting ingestion. Elapsed: 0.8s.
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

Found **158 output sites**: 18 DEBUG, 52 ERROR, 5 ERROR + traceback, 40 INFO, 6 PROGRESS, 19 STDOUT, 16 WARNING, 2 WARNING (retry callback).

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
| [src/extract/compact_parquets.py:46](../src/extract/compact_parquets.py#L46) · `run` | ERROR + traceback | `Compaction run failed: {e}` |
| [src/extract/compact_parquets.py:48](../src/extract/compact_parquets.py#L48) · `run` | DEBUG | `Players compaction summary: {players_summary}` |
| [src/extract/compact_parquets.py:49](../src/extract/compact_parquets.py#L49) · `run` | DEBUG | `Masteries compaction summary: {masteries_summary}` |
| [src/extract/compact_parquets.py:68](../src/extract/compact_parquets.py#L68) · `compact_dataset` | WARNING (retry callback) | `Retrying {function} in {seconds} seconds as it raised {exception_type}: {exception}.` |
| [src/extract/compact_parquets.py:74](../src/extract/compact_parquets.py#L74) · `compact_dataset` | INFO | `Compacting {dataset}: {len(rows)} pending player records.` |
| [src/extract/compact_parquets.py:76](../src/extract/compact_parquets.py#L76) · `compact_dataset` | INFO | `No {dataset} records to compact.` |
| [src/extract/compact_parquets.py:82](../src/extract/compact_parquets.py#L82) · `compact_dataset` | WARNING | `Skipping player {row['player_id']}: no logged path for dataset {dataset}.` |
| [src/extract/compact_parquets.py:113](../src/extract/compact_parquets.py#L113) · `compact_dataset` | ERROR | `Failed to compact dataset {dataset}: {e}` |
| [src/extract/compact_parquets.py:121](../src/extract/compact_parquets.py#L121) · `compact_dataset` | INFO | `Compacted {dataset}: {len(result['compacted_files'])} files, {result['rows_written']} rows, {len(player_ids)} players.` |
| [src/extract/compact_parquets.py:125](../src/extract/compact_parquets.py#L125) · `compact_dataset` | DEBUG | `Compacted {dataset} output: {result['output_path']}` |
| [src/extract/compact_parquets.py:134](../src/extract/compact_parquets.py#L134) · `compact_files` | WARNING | `Skipping compaction source, file not found on disk: {missing}` |
| [src/extract/compact_parquets.py:176](../src/extract/compact_parquets.py#L176) · `_dedup_merged_table` | WARNING | `Skipping dedup for {dataset}: dedup keys not found in schema.` |
| [src/extract/compact_parquets.py:188](../src/extract/compact_parquets.py#L188) · `_dedup_merged_table` | DEBUG | `Dropped {dropped} duplicate row(s) for {dataset} during compaction.` |
| [src/extract/extraction_db_helper.py:32](../src/extract/extraction_db_helper.py#L32) · `is_active` | ERROR | `Database connection error: {e}` |
| [src/extract/extraction_db_helper.py:61](../src/extract/extraction_db_helper.py#L61) · `start_run` | ERROR | `Failed to start a new run for pipeline {pipeline_name}.` |
| [src/extract/extraction_db_helper.py:136](../src/extract/extraction_db_helper.py#L136) · `add_player_task` | ERROR | `Failed to add a new player task for run {run_id}.` |
| [src/extract/extraction_db_helper.py:245](../src/extract/extraction_db_helper.py#L245) · `add_mastery_task` | ERROR | `Failed to add a new mastery task for player {player_id}.` |
| [src/extract/extraction_db_helper.py:286](../src/extract/extraction_db_helper.py#L286) · `update_mastery_task` | ERROR | `No mastery task found with task_id {task_id}.` |
| [src/extract/extraction_db_helper.py:338](../src/extract/extraction_db_helper.py#L338) · `get_mastery_id_from_list` | ERROR | `No task ID found for player {puuid} in the provided task list.` |
| [src/extract/extraction_db_helper.py:651](../src/extract/extraction_db_helper.py#L651) · `add_compaction_task` | ERROR | `Failed to add a new compaction task for {dataset} output {output_path}.` |
| [src/extract/extraction_db_helper.py:907](../src/extract/extraction_db_helper.py#L907) · `cleanup_stale_runs` | WARNING | `Cleaning up {len(stalled_run_ids)} stalled runs.` |
| [src/extract/extraction_db_helper.py:909](../src/extract/extraction_db_helper.py#L909) · `cleanup_stale_runs` | DEBUG | `No stalled runs to clean up.` |
| [src/extract/extraction_db_helper.py:930](../src/extract/extraction_db_helper.py#L930) · `cleanup_failed_run` | DEBUG | `Cleaning up failed run {run_id}.` |
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
| [src/extract/get_players.py:99](../src/extract/get_players.py#L99) · `run` | INFO | `Snapshot skipped: {snapshot_size} observed; {len(fresh_player_ids)} fresh in Neon, {len(pending_player_ids)} fresh locally awaiting ingestion. Elapsed: {monotonic() - started_at:.1f}s.` |
| [src/extract/get_players.py:134](../src/extract/get_players.py#L134) · `run` | INFO | `Snapshot saved: {len(snapshot_viable_players)} rank observations out of {snapshot_size} observed; {len(fresh_player_ids)} fresh in Neon, {len(pending_player_ids)} fresh locally awaiting ingestion. Elapsed: {monotonic() - started_at:.1f}s.` |
| [src/extract/get_players.py:161](../src/extract/get_players.py#L161) · `fetch_players` | ERROR | `No API client provided. Please set the RIOT_API_KEY environment variable and provide a valid API client.` |
| [src/extract/get_players.py:173](../src/extract/get_players.py#L173) · `fetch_players` | ERROR | `Error fetching players for {region} {queue} {tier} {division}: {e}` |
| [src/extract/get_players.py:178](../src/extract/get_players.py#L178) · `fetch_players` | ERROR | `Error fetching players for {region} {queue} {tier} {division}: {response.status_code} - {response.text}` |
| [src/extract/get_players.py:192](../src/extract/get_players.py#L192) · `fetch_players` | DEBUG | `Empty page for {region} {queue} {tier} {division}; cursor reset.` |
| [src/extract/get_players.py:196](../src/extract/get_players.py#L196) · `fetch_players` | ERROR | `Error validating player data for {region} {queue} {tier} {division}: {e}` |
| [src/extract/init_extraction_db.py:44](../src/extract/init_extraction_db.py#L44) · `initialize_database` | INFO | `Local extraction database initialized.` |
| [src/extract/init_extraction_db.py:54](../src/extract/init_extraction_db.py#L54) · `reset_database` | INFO | `Database and raw directories reset successfully.` |
| [src/extract/init_extraction_db.py:76](../src/extract/init_extraction_db.py#L76) · `clear_directory_contents` | ERROR | `Failed to delete {entry.path}. Reason: {e}` |
| [src/extract/refresh_stale_players.py:42](../src/extract/refresh_stale_players.py#L42) · `run` | WARNING | `Reaped {released_expired} expired refresh claim(s).` |
| [src/extract/refresh_stale_players.py:50](../src/extract/refresh_stale_players.py#L50) · `run` | INFO | `No stale players to refresh.` |
| [src/extract/refresh_stale_players.py:55](../src/extract/refresh_stale_players.py#L55) · `run` | INFO | `Refreshing {goal} stale players and their masteries... Rough ETA: {get_eta_minutes(2 * goal):.1f} min (development-key estimate).` |
| [src/extract/refresh_stale_players.py:79](../src/extract/refresh_stale_players.py#L79) · `run` | INFO | `Refreshing player {players_attempted}/{goal}. Rough ETA: {get_eta_minutes(2 * remaining):.1f} min. Elapsed: {(monotonic() - started_at) / 60:.1f} min.` |
| [src/extract/refresh_stale_players.py:103](../src/extract/refresh_stale_players.py#L103) · `run` | WARNING | `Failed to refresh player, Failures: {failures}. Skipping.` |
| [src/extract/refresh_stale_players.py:126](../src/extract/refresh_stale_players.py#L126) · `run` | WARNING | `Failed to refresh mastery. Failures: {failures}` |
| [src/extract/refresh_stale_players.py:131](../src/extract/refresh_stale_players.py#L131) · `run` | INFO | `Refreshed ranks for {players_refreshed}/{goal} players and saved masteries for {masteries_refreshed}. Failed refreshes: {failures}. Elapsed: {(monotonic() - started_at) / 60:.1f} min.` |
| [src/extract/refresh_stale_players.py:152](../src/extract/refresh_stale_players.py#L152) · `handle_player_extraction` | ERROR | `Missing required player info: {info}` |
| [src/extract/refresh_stale_players.py:157](../src/extract/refresh_stale_players.py#L157) · `handle_player_extraction` | WARNING | `Failed to fetch rank for player {puuid} in {region} {queue}.` |
| [src/extract/refresh_stale_players.py:197](../src/extract/refresh_stale_players.py#L197) · `handle_mastery_extraction` | ERROR | `Missing required player info: {info}` |
| [src/extract/refresh_stale_players.py:208](../src/extract/refresh_stale_players.py#L208) · `handle_mastery_extraction` | WARNING | `Failed to fetch mastery data for player {puuid} in {region} {queue}.` |
| [src/extract/refresh_stale_players.py:227](../src/extract/refresh_stale_players.py#L227) · `handle_mastery_extraction` | ERROR | `Failed to save mastery data for player {puuid} in {region} {queue}.` |
| [src/extract/refresh_stale_players.py:241](../src/extract/refresh_stale_players.py#L241) · `fetch_player_rank` | ERROR | `No API client provided. Please set the RIOT_API_KEY environment variable and provide a valid API client.` |
| [src/extract/refresh_stale_players.py:250](../src/extract/refresh_stale_players.py#L250) · `fetch_player_rank` | ERROR | `Error fetching rank for player {puuid}: {e}` |
| [src/extract/refresh_stale_players.py:255](../src/extract/refresh_stale_players.py#L255) · `fetch_player_rank` | ERROR | `Error fetching rank for player {puuid}: {response.status_code} - {response.text}` |
| [src/extract/refresh_stale_players.py:262](../src/extract/refresh_stale_players.py#L262) · `fetch_player_rank` | WARNING | `No {queue} entry found for player {puuid}; may be unranked or removed.` |
| [src/extract/refresh_stale_players.py:269](../src/extract/refresh_stale_players.py#L269) · `fetch_player_rank` | ERROR | `Error validating rank data for player {puuid}: {e}` |
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
| [src/extract/verify_integrity.py:452](../src/extract/verify_integrity.py#L452) · `verify_compaction_integrity` | INFO | `Compaction check completed: {len(task_level_issues)} issues, {sum(pending.values())} player records awaiting compaction.` |
| [src/extract/verify_integrity.py:456](../src/extract/verify_integrity.py#L456) · `verify_compaction_integrity` | DEBUG | `Compaction check pending records by dataset: {pending}` |
| [src/load/databricks_helper.py:96](../src/load/databricks_helper.py#L96) · `run_job` | ERROR | `Cannot start {job_name} job {job_id}: {error}` |
| [src/load/databricks_helper.py:104](../src/load/databricks_helper.py#L104) · `run_job` | INFO | `{job_name} job started (attempt {attempt}/{MAX_JOB_ATTEMPTS}).` |
| [src/load/databricks_helper.py:105](../src/load/databricks_helper.py#L105) · `run_job` | DEBUG | `{job_name} job {job_id}, run {run_id}.` |
| [src/load/databricks_helper.py:109](../src/load/databricks_helper.py#L109) · `run_job` | INFO | `{job_name} job completed in {(monotonic() - started_at) / 60:.1f} min.` |
| [src/load/databricks_helper.py:112](../src/load/databricks_helper.py#L112) · `run_job` | ERROR | `{job_name} job {job_id}, run {run_id} timed out: {error}. Stopping this job check; check the run in Databricks before retrying.` |
| [src/load/databricks_helper.py:117](../src/load/databricks_helper.py#L117) · `run_job` | ERROR | `{job_name} job {job_id}, run {run_id}, attempt {attempt} failed: {error}` |
| [src/load/load_champions_to_databricks.py:18](../src/load/load_champions_to_databricks.py#L18) · `load_champions` | WARNING | `No champion data to load. Exiting.` |
| [src/load/load_champions_to_databricks.py:52](../src/load/load_champions_to_databricks.py#L52) · `load_champions` | INFO | `Loaded {len(records)} champion reference rows.` |
| [src/load/load_champions_to_databricks.py:53](../src/load/load_champions_to_databricks.py#L53) · `load_champions` | DEBUG | `Champion reference table: {CATALOG}.{SCHEMA}.{TABLE_NAME}.` |
| [src/load/load_compacted_to_databricks.py:31](../src/load/load_compacted_to_databricks.py#L31) · `load_compacted` | ERROR | `Upload failed; ingestion was not started. Retaining local files.` |
| [src/load/load_compacted_to_databricks.py:34](../src/load/load_compacted_to_databricks.py#L34) · `load_compacted` | INFO | `No collected files to ingest.` |
| [src/load/load_compacted_to_databricks.py:38](../src/load/load_compacted_to_databricks.py#L38) · `load_compacted` | ERROR | `Ingestion was not confirmed; retaining local files without applying the loader's Neon updates.` |
| [src/load/load_compacted_to_databricks.py:54](../src/load/load_compacted_to_databricks.py#L54) · `load_compacted` | ERROR | `Ingestion succeeded but registry/ledger updates failed: {error}. Retaining local files.` |
| [src/load/load_compacted_to_databricks.py:56](../src/load/load_compacted_to_databricks.py#L56) · `load_compacted` | INFO | `Ingestion confirmed; collection state updated.` |
| [src/load/load_compacted_to_databricks.py:63](../src/load/load_compacted_to_databricks.py#L63) · `load_dataset` | INFO | `No compacted file found for {dataset}, nothing to load.` |
| [src/load/load_compacted_to_databricks.py:68](../src/load/load_compacted_to_databricks.py#L68) · `load_dataset` | INFO | `No {dataset} rows to upload.` |
| [src/load/load_compacted_to_databricks.py:85](../src/load/load_compacted_to_databricks.py#L85) · `load_dataset` | ERROR | `Failed to extract players from {dataset}: {e}` |
| [src/load/load_compacted_to_databricks.py:92](../src/load/load_compacted_to_databricks.py#L92) · `load_dataset` | ERROR | `Failed to load {dataset} after {MAX_UPLOAD_ATTEMPTS} attempts, will retry on next run: {e}` |
| [src/load/load_compacted_to_databricks.py:97](../src/load/load_compacted_to_databricks.py#L97) · `load_dataset` | INFO | `Uploaded {dataset}: {table.num_rows} rows for {len(players)} players; awaiting ingestion.` |
| [src/load/load_compacted_to_databricks.py:98](../src/load/load_compacted_to_databricks.py#L98) · `load_dataset` | DEBUG | `{dataset} upload status: {status}; local input: {compacted_path}.` |
| [src/load/load_compacted_to_databricks.py:109](../src/load/load_compacted_to_databricks.py#L109) · `complete_loaded_rank_pages` | DEBUG | `Page claim for task {task['task_id']} expired or was already completed; keeping ingested data.` |
| [src/load/load_compacted_to_databricks.py:116](../src/load/load_compacted_to_databricks.py#L116) · `_upload` | WARNING (retry callback) | `Retrying {function} in {seconds} seconds as it raised {exception_type}: {exception}.` |
| [src/load/player_registry.py:234](../src/load/player_registry.py#L234) · `record_refresh_result` | WARNING | `Refresh claim no longer belongs to {claimed_by} for {region}/{queue}/{puuid}; result skipped.` |

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
| [src/extract/verify_integrity.py:349](../src/extract/verify_integrity.py#L349) · `verify_compaction_integrity` | PROGRESS | `Verifying compaction tasks (unit: task)` |

### Synthetic sample commands

| Source and context | Level | Message template |
| --- | --- | --- |
| [src/load/load_business_sample.py:21](../src/load/load_business_sample.py#L21) · `main` | STDOUT | `Validated {players.num_rows:,} players and {events.num_rows:,} transactions; no warehouse writes` |
| [src/load/load_business_sample.py:46](../src/load/load_business_sample.py#L46) · `load_sample` | STDOUT | `INCOMPLETE business sample load; dashboard export is blocked until both tables reconcile.` |
| [src/load/load_business_sample.py:48](../src/load/load_business_sample.py#L48) · `load_sample` | STDOUT | `Loaded {result['player_count']:,} sample players and {result['transaction_count']:,} sample transactions` |
| [src/sample/generate_transactions.py:62](../src/sample/generate_transactions.py#L62) · `main` | STDOUT | `Frozen {cohort.num_rows:,} complete real players at one as-of date` |
| [src/sample/generate_transactions.py:73](../src/sample/generate_transactions.py#L73) · `main` | STDOUT | `{manifest['scenario_id']}: {players.num_rows:,} players, {transactions.num_rows:,} transactions, USD {manifest['cash_spent_usd_alltime']} hypothetical source cash` |
| [src/sample/generate_transactions.py:113](../src/sample/generate_transactions.py#L113) · `fetch_cohort` | STDOUT | `Selected {complete.num_rows:,} complete players from {table.num_rows:,} current profiles; excluded {table.num_rows - complete.num_rows:,} incomplete/invalid profiles; no row cap` |

### Manual dashboard export output

| Source and context | Level | Message template |
| --- | --- | --- |
| [streamlit_app/scripts/export_data.py:45](../streamlit_app/scripts/export_data.py#L45) · `main` | STDOUT | `Export complete: {total_bytes / 1048576:.2f} MiB` |
| [streamlit_app/scripts/export_data.py:63](../streamlit_app/scripts/export_data.py#L63) · `export_snapshots` | STDOUT | `Exporting {name}...` |
| [streamlit_app/scripts/export_data.py:70](../streamlit_app/scripts/export_data.py#L70) · `export_snapshots` | STDOUT | `  Optional business sample is not built; skipping.` |
| [streamlit_app/scripts/export_data.py:89](../streamlit_app/scripts/export_data.py#L89) · `export_snapshots` | STDOUT | `  {len(frame):,} rows -> {destination.name}` |
| [streamlit_app/scripts/export_population_estimates.py:158](../streamlit_app/scripts/export_population_estimates.py#L158) · `module` | STDOUT | `<json.dumps(result, indent=2)>` |
| [streamlit_app/scripts/export_population_estimates.py:159](../streamlit_app/scripts/export_population_estimates.py#L159) · `module` | STDOUT | `Analyst bundle: {args.output_dir.resolve() / 'population_estimates.zip'}` |

### Test harness logs

| Source and context | Level | Message template |
| --- | --- | --- |
| [src/extract/tests/conftest.py:91](../src/extract/tests/conftest.py#L91) · `mock_db` | INFO | `Creating test database at: {db_path}` |
| [src/extract/tests/conftest.py:125](../src/extract/tests/conftest.py#L125) · `module` | INFO | `Seed: {SUITE_SEED}` |

### Databricks build output

`resources/build_dbt.job.yml` executes `dbt deps`, then `dbt build`. dbt emits its
own dependency, model/test progress, elapsed-time, warning/error and completion
output in the remote job logs. Python emits the job lifecycle messages listed
above and records the result in `job_results.json`. No custom dbt/Jinja logging
calls were found.

### Maintenance

When changing messages, update the illustrative run and affected inventory rows.
Coverage was checked by parsing every tracked `.py` file and Python `.ipynb` cell
for severity calls on `logger`/`logging`, `print`, `tqdm`, and `before_sleep_log`.
Sink setup/forwarding (`add`, `remove`, `handle`) does not introduce message
templates. Progress bars and retry callbacks can emit multiple times per site;
the count above represents call sites, not the number of lines in one run.
