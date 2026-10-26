# Configuration

[Project README](../../README.md) · [Documentation index](../README.md) · [Orchestration](orchestration.md) · [Data models](data-models.md) · [Metrics and methods](metrics-and-methods.md)

This reference describes the settings consumed by the checked-in pipeline, analytical models and manual exporters. Viewing the bundled dashboard needs only its [app dependencies](../../streamlit_app/requirements.txt); collection and exports need the service configuration below. Follow [run the dashboard](../guides/run-the-dashboard.md), [run the pipeline](../guides/run-the-pipeline.md) or [refresh dashboard data](../guides/refresh-dashboard-data.md) for operating steps.

## Configuration sources and precedence

| Consumer | Configuration source | Precedence and validation |
|---|---|---|
| Python collection runner | `config/EXTRACTION_CONFIG.env`, based on the [example](../../config/EXTRACTION_CONFIG.env.example) | Process environment overrides file values. The runner validates once with `ExtractionConfigManifest` before starting collection and passes the resulting settings to its stages. |
| Shared collection registry | Root `.env.local` | Existing process environment values take precedence. Connections use `DATABASE_URL`, falling back to `DATABASE_URL_UNPOOLED`; a caller explicitly requesting a direct connection requires `DATABASE_URL_UNPOOLED`. |
| Python Databricks operations | `config/DATABRICKS_CONFIG.env`, based on the [example](../../config/DATABRICKS_CONFIG.env.example) | Existing environment values take precedence. SQL connections require `HOST`, `HTTP_PATH` and `TOKEN`; uploads and Jobs API calls use the workspace host and token. |
| dbt | [dbt_project.yml](../../league_pipeline/dbt_project.yml), with explicit dbt variable overrides when needed | Uses the `league_pipeline` profile. Local dbt credentials belong in the operator's untracked profile; the deployed dbt task uses its job configuration. Python's connection file does not itself configure a dbt profile. |
| Scenario generation and exports | Command-line options and checked-in source constants | These are manual entrypoints. They do not inherit every extraction setting. |

An omitted extraction key can select a model default. A present but blank key does not mean “use the default” and can fail validation. The example's `FULL_VERIFICATION=True` opts into a scan even though the model default is false. Its job IDs are deliberately `0` placeholders and must be replaced.

Authoritative implementations: [configuration reader](../../src/extract/config_helper.py), [validation model](../../src/pydantic_models.py), [registry connection](../../src/load/player_registry.py) and [Databricks helper](../../src/load/databricks_helper.py).

## Extraction settings

Defaults below apply when the key is omitted. “Required” means there is no model default.

| Environment key | Default | Meaning and boundary |
|---|---|---|
| `RIOT_API_KEY` | Required | Nonempty credential for Riot requests. |
| `REGION` | Required | Nonempty platform routing code, such as `na1`. Also scopes registry lookups. Supported Riot platforms are not enumerated by the validation model. |
| `QUEUE` | Required | Nonempty queue identifier. The example uses `RANKED_SOLO_5x5`; the model does not validate supported queue names. Keep it aligned with dbt's `ranked_queue`. |
| `PLAYERS_FETCH_DEPTH` | Required | Integer `1..1000`. Total rounds are depth × number of configured tiers × number of divisions. A round uses the shared page cursor; depth does not reset the page number. |
| `MASTERY_TASK_LIMIT` | Required | Integer `1..1000`. Maximum missing-mastery players attempted by the discovery-side fetcher in a round. Does not cap the separate stale-player refresh allocation. |
| `TIERS` | `DIAMOND,EMERALD,PLATINUM,GOLD,SILVER,BRONZE,IRON` | Nonempty comma-separated selection from these seven uppercase names. Restricts discovery, not the rank of previously tracked players eligible for refresh. |
| `DIVISIONS` | `I,II,III,IV` | Nonempty comma-separated selection from these four names. At equal cursor progress, division order breaks ties before tier order. |
| `FRESHNESS_THRESHOLD_MINUTES` | `10080` | Integer minutes, at least `1`; seven days by default. Used by registry freshness and local pending-observation filters. Inactivity can defer stale-player refresh further. |
| `MAX_REFRESH_SCALE` | `4` | Finite number greater than `0`. Caps the refresh-to-snapshot allocation multiplier. |
| `PAUSE_DISCOVERY_AT_REFRESH_CAP` | `true` | At the cap, skip both discovery and its missing-mastery fetcher. Setting false keeps discovery enabled while retaining the refresh cap. |
| `RUNS_PER_LOAD` | `10` | Integer rounds, at least `1`, between verification/compaction/load/build cycles. The final round also delivers outstanding work. |
| `FULL_VERIFICATION` | `false` | Also scan raw files before compaction. Ledger checks and verification of the actual compacted output still run when false. |
| `INGEST_JOB_ID` | Required | Positive integer ID of the deployed ingestion-only job. |
| `INGESTION_TIMEOUT_SECONDS` | `900` | Positive integer seconds to wait for each ingestion job attempt. Local timeout does not cancel the remote run. |
| `DBT_JOB_ID` | Required | Positive integer ID of the separate deployed dbt build job. |
| `DBT_TIMEOUT_SECONDS` | `1800` | Positive integer seconds to wait for each dbt attempt. Confirmed ingestion remains recorded if this stage fails. |

There is no configured upper bound on freshness, load cadence or job wait times beyond the stated validation. Values accepted as text by the model still need to be valid for the external service.

## Service configuration and job definitions

For Python Databricks operations, `HOST` is the workspace hostname without a scheme or path, `HTTP_PATH` selects the SQL warehouse, and `TOKEN` authenticates the calls. None has a project default. The shared registry uses PostgreSQL connection URLs; no service credentials are needed by the dashboard reader.

The [ingestion job](../../resources/ingest_players.job.yml) runs `src/load/ingest_players`; the [dbt job](../../resources/build_dbt.job.yml) runs `dbt deps` and `dbt build` in `league_pipeline`. Both definitions select Git branch `main`, queue requests and allow one concurrent run per job. Their remote job timeouts are respectively **1800** and **3600 seconds**, separate from the shorter default local waits above. Workspace job IDs and the build task's warehouse selection must match the operator's deployment.

Catalog, schema and volume paths such as `league_pipeline.raw` and `/Volumes/league_pipeline/landing_zone` are currently specified in source and job definitions. There is no environment setting that remaps the whole project to another catalog.

## Analytical settings

These defaults come from [dbt_project.yml](../../league_pipeline/dbt_project.yml). Changing an analytical assumption can alter cohort membership or metric meaning; it is separate from tuning collection.

| dbt variable | Default | Purpose |
|---|---|---|
| `ranked_queue` | `RANKED_SOLO_5x5` | Queue retained in player history. |
| `report_as_of_date` | `null` | Optional `YYYY-MM-DD` cutoff for consumers of `report_cutoff()`, including completed rank buckets. With null, that macro uses the maximum current player snapshot date. This override does not turn every latest-state model into a historical snapshot. |
| `late_arrival_lookback_days` | `5` | Source-date lookback in incremental Silver history models. Older corrections can require a deliberate rebuild; Bronze currently reconsiders its raw source when merging. |
| `mastery_freshness_days` | `2` | Maximum absolute date difference used to retain a player snapshot with nearby mastery evidence. |
| `rank_period_days` | `7` | Rank bucket length; must be positive. Endpoint eligibility uses actual dates. |
| `max_abs_lp_per_game_for_growth` | `50` | Absolute ranking-points-per-game eligibility ceiling. |
| `estimated_ranked_mastery_points_per_win` | `1000` | Assumed activity-score contribution used by the competitive-activity estimate. |
| `estimated_ranked_mastery_points_per_loss` | `300` | Corresponding assumed contribution for a loss. |
| `recent_champion_activity_window_days` | `60` | Recent activity window. |
| `recent_champion_min_absolute_points` | `3000` | Absolute activity-gain threshold input. |
| `recent_champion_min_relative_pct` | `0.10` | Relative activity-gain threshold input. |
| `recent_champion_immature_window_fraction` | `0.5` | Short-history boundary as a fraction of the recent window. |
| `role_profile_recent_champion_count` | `15` | Recently used characters considered for the initial role profile. |
| `divisions_per_tier`, `lp_per_division` | `4`, `100` | Rank-score mapping assumptions. |
| `expert_mastery_threshold` | `100000` | Activity-score threshold in character summary measures. |
| `cooccurrence_min_pair_players` | `5` | Minimum shared-player support for a warehouse character-pair row. |
| `favoured_champion_max_count` | `10` | Upper bound used by preferred-character selection and classification. |
| `favoured_champion_gap_multiplier`, `favoured_champion_min_log_gap` | `1.5`, `0.69314718056` | Gap-rule inputs for preferred-character selection. |
| `playstyle_feature_weights`, `playstyle_profiles` | Mappings in the project file | Feature weights and archetype targets for deterministic classification. They are not a trained model. |

The mathematical definitions belong in [metrics and methods](metrics-and-methods.md); this table identifies their configuration owner and units. A changed queue or scope needs a review of existing keys and history as well as a new setting; see [data-model scope](data-models.md#identities-and-scope).

## Manual entrypoints and options

For modules named `extract`, `load` or `sample`, run from the repository root with `src` on `PYTHONPATH`. Some local ledger paths are relative to that working directory.

| Entrypoint | Controls |
|---|---|
| `python -m streamlit run streamlit_app/app.py` | Default seven-chapter audience story. Reads `streamlit_app/data/story`; the bundled component uses Streamlit's aggregate request bridge. Brazilian Portuguese by default, selectable English, and independent Plain/Precise terminology. |
| `python -m streamlit run streamlit_app/legacy_app.py` | Previous six-chapter story, explorers and optional laboratories. Reads the original `streamlit_app/data` package; existing language controls are preserved. |
| `python streamlit_app/scripts/prepare_story_evidence.py` | Offline publication from the reviewed local research/run archives into sanitized component evidence and its checksum manifest. Not called during rendering. |
| `python -m extract.run_pipeline` | Uses the default extraction file. Python callers can supply a different path to `run_pipeline(config_path)`; this entrypoint has no command-line config-path flag. |
| `python -m sample.generate_transactions` | `--cohort PATH` reuses an existing cohort offline; `--refresh-cohort` explicitly replaces it from Gold. These options are mutually exclusive. Defaults: `--output-dir data/business_sample`, `--seed 42`, `--queue RANKED_SOLO_5x5`. |
| `python -m load.load_business_sample` | `--input-dir` defaults to `data/business_sample`. `--validate-only` checks local files without connecting or writing to the warehouse. |
| `python streamlit_app/scripts/export_data.py` | `--output-dir` defaults to `streamlit_app/data`. Repeatable `--dataset` selects names in `DATASET_QUERIES`; omission exports the configured set, skipping an absent optional business sample. `--family-audience` enables keyed family enrichment; `--pool-archetypes` also applies the frozen archetype model and implies family enrichment. |
| `python streamlit_app/scripts/export_audience_reference.py` | `--audience-segments --snapshot PATH --output PATH` freezes the wider audience reference for the matching candidate. See the [refresh guide](../guides/refresh-dashboard-data.md) for package validation. |
| `python streamlit_app/scripts/export_population_estimates.py` | Local bundle calculation. `--snapshot` defaults to `streamlit_app/data/player_profiles.parquet`; `--output-dir` defaults to `data/population_estimates`. |

With no explicit cohort option, generation reuses `cohort.parquet` in its output directory when present, otherwise fetching and freezing a new cohort. Scenario assumptions live in [scenario.py](../../src/sample/scenario.py); identity includes configuration, seed, cohort and generator version.

## Paths and fixed operational policy

The default story's locale publication settings are in
`streamlit_app/story_component/locales/manifest.json`. Brazilian Portuguese is the
published default; English is also published and remains the permanent fallback.
The header language selector switches display copy and locale formatting without
changing audience predicates or converting USD amounts. See the
[translation handoff](../../streamlit_app/story_component/locales/README.md).

The local ledger is `data/database/extraction.db`; raw observations are under `data/raw/players` and `data/raw/masteries`; compacted files are `data/compacted/players_compacted.parquet` and `masteries_compacted.parquet`. Diagnostics go to `data/logs`, and startup reconciliation quarantines unreferenced raw files under `data/quarantine`. Normal successful cleanup retains the ledger.

Refresh intensity `3`, fallback page size `205`, claim expiry `30 minutes`, API retry policy and compaction/upload retry limits are source constants, not extraction environment options. Their effects are documented in [orchestration](orchestration.md). The dashboard's dataset paths and support default are in [app configuration](../../streamlit_app/app_core/config.py); it has no live-warehouse mode.
