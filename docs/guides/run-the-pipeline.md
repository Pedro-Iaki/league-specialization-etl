# Run the pipeline

[Project README](../../README.md) · [Documentation index](../README.md) · [Architecture](../wiki/architecture.md) · [Configuration](../reference/configuration.md) · [Orchestration](../reference/orchestration.md)

This guide is for an operator running collection and delivery into a configured warehouse. It uses the Python coordinator, local SQLite ledger, shared Neon registry and separate Databricks ingestion/build jobs. It makes source requests, writes local state and files, updates shared collection state and writes warehouse data.

To inspect the output without operating those services, use [run the dashboard](run-the-dashboard.md). Cloud setup is partly manual; the repository supplies examples, schemas and job definitions rather than a one-command infrastructure deployment.

## 1. Prepare the environment and services

Run local commands from the repository root. Use an existing compatible virtual environment, or create `.venv` if it is absent:

```sh
python -m venv .venv
```

Install the root [requirements](../../requirements.txt). In PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PYTHONPATH = (Join-Path (Get-Location) "src")
```

On a POSIX shell:

```sh
.venv/bin/python -m pip install -r requirements.txt
export PYTHONPATH="$PWD/src"
```

Keep `src` on `PYTHONPATH` for the `extract`, `load` and `sample` module commands below. Local ledger/schema paths also depend on running from the repository root. Dependency installation alone does not provision any service.

Prepare these service boundaries:

| Service | Required setup |
|---|---|
| Riot | A valid API key and network access for collection and character-reference requests. |
| Neon Postgres | A database reachable by the collector, with the checked-in [registry schema](../../src/load/player_registry_schema.sql) applied through its SQL console or the operator's database client. It defines the player registry and discovery-page progress tables. |
| Databricks storage and SQL | A usable SQL warehouse and permissions for the project's catalog, schemas, Delta tables and landing volumes. |
| Databricks jobs | An ingestion notebook job and a separate dbt build job, with access to the configured repository revision and required compute. |

The source uses the `league_pipeline` catalog and fixed volume/table paths. Changing a connection's workspace does not remap those names. Before the first upload into a new workspace, provision the catalog, schemas and landing volumes declared at the start of the [ingestion notebook](../../src/load/ingest_players.ipynb):

```sql
CREATE CATALOG IF NOT EXISTS league_pipeline;
CREATE SCHEMA IF NOT EXISTS league_pipeline.landing_zone;
CREATE SCHEMA IF NOT EXISTS league_pipeline.raw;
CREATE SCHEMA IF NOT EXISTS league_pipeline.bronze;
CREATE VOLUME IF NOT EXISTS league_pipeline.landing_zone.players;
CREATE VOLUME IF NOT EXISTS league_pipeline.landing_zone.masteries;
CREATE VOLUME IF NOT EXISTS league_pipeline.landing_zone.checkpoints;
```

Execute this in the operator's Databricks environment with suitable permissions. The runner uploads before invoking ingestion, so a fresh workspace cannot rely on that later job to create the upload destinations for its first delivery. dbt also needs permission to create its remaining model/seed schemas and relations. Retain ingestion checkpoints during ordinary reruns.

## 2. Configure local connections and jobs

Create missing local configuration files from the examples. These PowerShell commands preserve existing configured files:

```powershell
if (-not (Test-Path -LiteralPath config/EXTRACTION_CONFIG.env)) {
    Copy-Item -LiteralPath config/EXTRACTION_CONFIG.env.example -Destination config/EXTRACTION_CONFIG.env
}
if (-not (Test-Path -LiteralPath config/DATABRICKS_CONFIG.env)) {
    Copy-Item -LiteralPath config/DATABRICKS_CONFIG.env.example -Destination config/DATABRICKS_CONFIG.env
}
```

On POSIX, use `cp -n` for each source/destination pair to preserve existing files. Fill in the local files and root `.env.local`:

| Location | Values to supply or review |
|---|---|
| `config/EXTRACTION_CONFIG.env` | Real `RIOT_API_KEY`, collection scope, depth/cadence and allocation settings; positive `INGEST_JOB_ID` and `DBT_JOB_ID`; job wait limits. |
| `config/DATABRICKS_CONFIG.env` | `HOST` as a workspace hostname without scheme/path, warehouse `HTTP_PATH`, and `TOKEN`. |
| `.env.local` | `DATABASE_URL`, or fallback `DATABASE_URL_UNPOOLED`, for the shared registry. A caller requesting a direct connection needs the unpooled value. |

Keep credentials in local configuration rather than documentation or committed files. Existing process environment values override file values. Omitted keys can select defaults; blank keys do not select defaults. The example job IDs are `0` placeholders that intentionally fail validation.

Use the [ingestion job](../../resources/ingest_players.job.yml) and [dbt job](../../resources/build_dbt.job.yml) definitions to configure the two deployed jobs. Replace the build task's warehouse selection with the operator's warehouse and put the resulting job IDs into extraction configuration. Check Git access and `git_source`: both templates execute branch `main`, so uncommitted local changes do not become remote job code.

The deployed dbt task supplies its own connection context. Python's Databricks configuration file does not configure a separate local dbt CLI profile. All settings, defaults and timeout distinctions are in [configuration](../reference/configuration.md).

## 3. Choose the first-build path

For an established environment with gameplay and sample raw tables already loaded, keep the build task's checked-in commands: `dbt deps`, then `dbt build`.

For a **fresh warehouse**, initially configure that task to run:

```sh
dbt deps
dbt build --exclude tag:business_sample
```

This creates the gameplay models without requiring a generated scenario that first needs Gold player profiles. The checked-in full build includes the business models, their fictional reference seeds and reconciliation test; it cannot create the two sample raw tables by itself. The exclusion is a bootstrap choice for the deployed job, not a new argument to the Python runner.

Use this gameplay-only task for the initial collection in step 4. Once that run has built eligible Gold profiles, step 6 completes the generated source and restores the full build. A gameplay-only operator can retain the exclusion, but should report the narrower build scope.

## 4. Validate settings and start collection

Before starting, review the amount of requested work. The example depth of 30 across seven tiers and four divisions means **840 rounds**, not 30 requests. Depth controls rounds over the shared cursor; it does not reset pagination. A short invocation still has discovery, adaptive refresh and a final delivery cycle. There is no dry-run flag.

You can validate extraction settings without connecting to the services. In PowerShell:

```powershell
.\.venv\Scripts\python.exe -c "from extract.config_helper import get_configs; from pydantic_models import ExtractionConfigManifest; ExtractionConfigManifest.model_validate(get_configs()); print('Extraction settings valid')"
```

This checks values and constraints, not credential validity, deployed permissions or remote job behavior. Once the environment and first-build choice are ready, launch:

```powershell
.\.venv\Scripts\python.exe -m extract.run_pipeline
$LASTEXITCODE
```

On POSIX:

```sh
.venv/bin/python -m extract.run_pipeline
echo $?
```

Exit code `0` means the coordinator returned success; `1` means it returned failure. Unhandled errors or interruption can also stop the process, so read its diagnostics alongside the exit status. The entrypoint reads `config/EXTRACTION_CONFIG.env`; it has no CLI config-path option.

For a fresh workspace, perform the initial collection with the gameplay-only build task described above. A new local ledger is initialized automatically. Existing ledger state is retained; a reset is a separate operation and is not part of normal startup.

## 5. Check completion and retain evidence

Expect collection and refresh rounds, with integrity checks, compaction, output verification, upload, confirmed ingestion and the separate build at load cadence and the final round. Successful cleanup clears completed raw/compacted files while retaining SQLite.

Inspect these outputs together:

| Output | What to inspect |
|---|---|
| Console/log output | Active stage, failure details and remote job/run identities. |
| `data/logs/job_results.json` | Per-round stage details, including failed, skipped or unstarted work. |
| Integrity reports in `data/logs` | `db_integrity_check.json`, optional `integrity_check.json`, and `compaction_integrity_check.json`. |
| `data/database/extraction.db` | Local runs, tasks, file lineage and compaction/load status. |
| Databricks job results | Confirm ingestion and build outcomes separately, for the recorded run identities and selected build scope. |

Fixed report paths can be overwritten by later invocations. Retain dated copies with the code revision and configuration context when preparing evidence, excluding secrets. Task attempts are not exact HTTP request totals. [Validation and evidence](../reference/validation-and-evidence.md) distinguishes local checks, historical cloud records and the execution package still in progress.

## 6. Complete a fresh warehouse's generated source

Skip this step for an established matching sample or a deliberately gameplay-only build. After the initial gameplay build has produced eligible Gold profiles, generate, validate and load the scenario. With the configuration and `PYTHONPATH` above, PowerShell commands are:

```powershell
.\.venv\Scripts\python.exe -m sample.generate_transactions
if ($LASTEXITCODE -ne 0) { throw "Scenario generation failed; stop before validation and loading." }
.\.venv\Scripts\python.exe -m load.load_business_sample --validate-only
if ($LASTEXITCODE -ne 0) { throw "Scenario validation failed; do not load it." }
.\.venv\Scripts\python.exe -m load.load_business_sample
if ($LASTEXITCODE -ne 0) { throw "Scenario load failed; stop before the full build." }
```

In a POSIX shell, run the same module commands with `.venv/bin/python` and stop after any nonzero exit status. The generator reuses `data/business_sample/cohort.parquet` when present; otherwise it freezes eligible Gold profiles. Do not use `--refresh-cohort` merely to retry generation: that explicitly replaces the cohort. The load replaces only the two dedicated sample raw tables, then checks their agreement.

Restore `dbt build` in the deployed build task and run that job to build the complete graph, including sample seeds and spending models. Inspect its outcome as in step 5. All purchases remain simulated. [Simulated transactions](../wiki/simulated-transactions.md) and the [manual-entrypoint reference](../reference/configuration.md#manual-entrypoints-and-options) explain the branch.

## 7. Inspect failures before retrying

| Situation | Operator action |
|---|---|
| Invalid settings | Correct the reported field or environment override before rerunning. |
| Collection, integrity or compaction failure | Inspect stage reports and ledger/file evidence. Resolve the fault while preserving successful and pending observations. |
| Upload or unconfirmed ingestion | Inspect the recorded upload and ingestion run. A file in a volume is not proof of successful ingestion. |
| Local job wait expired | Inspect that remote run before submitting another; timeout does not cancel it. |
| Ingestion succeeded but state updates failed | Check both shared registry and local ledger against the confirmed remote result before retrying. |
| dbt failed after confirmed ingestion | Inspect/fix the build, including missing sample inputs or wrong build scope. Confirmed ingestion remains recorded; the build job can be inspected and rerun separately. |

Use `Ctrl+C` to interrupt an active local invocation when necessary, then inspect its final diagnostics and any remote jobs. Do not treat file deletion, ledger reset or checkpoint removal as ordinary retry steps. There is no single repair command for every partial state; [failure and retry behavior](../reference/orchestration.md#failure-and-retry-behavior) defines the supported boundaries.

A successful collection/build invocation does not regenerate the commercial scenario, export serving files or update the dashboard. Follow [refresh dashboard data](refresh-dashboard-data.md) for those separate manual operations. The bundled [dashboard guide](run-the-dashboard.md) remains usable independently of this environment.
