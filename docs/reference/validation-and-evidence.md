# Validation and evidence

[Project README](../../README.md) · [Documentation index](../README.md) · [Orchestration](orchestration.md) · [Data models](data-models.md)

This reference separates implemented checks, inspectable frozen artifacts, reviewed historical run records and behavior that has not been demonstrated live. Counts below describe a dated snapshot. They do not imply a fresh collection, warehouse build or export during the documentation rewrite.

Use [orchestration](orchestration.md) for execution-state semantics, [data models](data-models.md) for grains, [metrics and methods](metrics-and-methods.md) for calculations, and [population adjustment](population-adjustment.md) for coverage and weight diagnostics.

## Validation boundaries

| Boundary | What is checked | Evidence limit |
|---|---|---|
| Extraction configuration | Required fields, supported values and numeric constraints before work starts. | Valid settings do not prove credentials, service availability or a completed run. |
| Local files and ingestion | Required load/integrity checks, delivery and remote ingestion confirmation before dependent completion state advances. | Local timeout does not establish remote cancellation; mocked tests do not demonstrate live recovery. |
| dbt build | Declared schema/data tests and custom SQL checks across the selected graph. | A build validates its selected resources and data at that time. Merely having test definitions does not establish that they passed. |
| Generated transaction files | Arrow schemas, nonempty files, unique transaction IDs, known player/product/currency IDs, scenario/date consistency, nonnegative bounded amounts, cash separation, count/USD/history reconciliation and required acquisition history. | Consistency establishes a valid simulation, not realism or observed purchasing behavior. |
| Transaction warehouse and export | Cohort completion marker, unique scenario and players, transaction totals, fiat counts/USD and matching Gold summaries. | A missing/inconsistent cohort or stale Gold blocks serving; this is not a distributed transaction across every stage. |
| Serving export | Nonempty output, required columns and exclusion of operational identifiers; dataset and scenario metadata recorded in the manifest. | Anonymous datasets cannot reconstruct arbitrary cross-dataset player joins. Partial exports can retain older unselected files. |
| Local dashboard | Loading/contracts, analytical helpers and selected page rendering covered by Python tests. | Tests and local rendering do not establish hosting uptime or correctness of every visual interpretation. |

Inspect [configuration validation](../../src/pydantic_models.py), [dbt schema tests](../../league_pipeline/models/gold/schema.yml), [custom SQL tests](../../league_pipeline/tests), [transaction validation](../../src/sample/validation.py), [serving contracts](../../streamlit_app/app_core/contracts.py) and [snapshot contract tests](../../streamlit_app/tests/test_snapshot_contracts.py) for the actual gates. The spending source contract uses fixed two-decimal money fields and distinguishes fiat cash from in-game currency.

## Inspectable serving snapshot

The current [manifest](../../streamlit_app/data/manifest.json) records export time **October 10, 2026, 23:37:07 UTC**. Player profiles are as of **September 29, 2026**, with underlying player snapshots dated September 16–29. These are different dates with different meanings.

Parquet metadata was checked locally against all 13 manifest entries on October 19, 2026: row counts and column counts matched. The [data-model reference](data-models.md#serving-datasets) supplies the complete grain definitions.

| Dataset | Rows | Counting unit |
|---|---:|---|
| `players` | 37,172 | Current player profiles. |
| `champions` | 173 | Character summaries. |
| `cooccurrence` | 14,878 | Supported unordered character pairs. |
| `champion_player_mastery_share` | 1,139,520 | Player/character memberships, not unique people. |
| `champion_tier_mastery` | 22,350 | Character/rank/threshold summaries, including overlapping thresholds and rollups. |
| `growth_players` | 1,066 | Eligible player/starting-rank summaries. |
| `growth_player_styles` | 1,066 | Eligible player/starting-rank/period-classification summaries. |
| `champion_growth_players` | 4,089 | Attributed player/character/starting-rank summaries. |
| `champion_tier_growth` | 2,842 | Character/starting-rank/scope summaries. |
| `ranked_mastery_cohorts` | 4,296 | Player/window summaries; one person can appear in multiple windows. |
| `business_players` | 24,990 | Frozen real profiles joined to simulated commercial summaries. |
| `champion_population_activity` | 1,384 | Character/current-rank/scope summaries. |
| `champion_population_pairs` | 119,024 | Character-pair/current-rank/scope summaries. |

The manifest is an inventory, not a claim that all files were refreshed atomically. A selective export keeps existing entries for unselected datasets. Check per-dataset dates and scenario identity before combining results, and retain this dated table until an actual refreshed artifact has been inspected.

## Cohort counts branch by question

The reviewed analysis of this frozen export distinguishes the following cohorts. These counts are historical analytical findings, separate from the directly inspectable Parquet row inventory above; reproduce the corresponding filters before using them for a new release.

| Cohort | People | Interpretation |
|---|---:|---|
| Full profile cohort | 37,172 | Available current profiles. |
| Classified recent audience / complete core business cohort | 24,990 | Usable recent-pool classification and required frozen business features. |
| No recent pool | 12,182 | Missing recent classification; not evidence of zero activity or zero spending. |
| Recent classification with latest eligible LP outcome | 1,074 | Latest-outcome analysis cohort. |
| Growth scatter | 946 | Separately filtered for at least two games and usable outcome/concentration. |
| Classified historical outcome cohort | 1,066 | Eligible historical players, with one retained outcome period in this export. |

These are branches, not successive stages of one conversion funnel. The historical complete period on September 27 contained 3,373 players before outcome filtering, including 2,291 with zero games. The estimated ranked-mastery-share cohort also contained 1,074 people but differed from the latest LP-eligible cohort by eight people in each direction. Counts alone are insufficient evidence of shared membership, particularly after public identifiers are removed.

All frozen profiles had fewer than 30 tracked days, with maximum 13. Recent pools were gain-weighted for 3,374 players, equal-membership-weighted for 21,616, and absent for 12,182. This helps explain the current recent-activity measures; it does not describe the future behavior of the mature 30-day rule.

## Frozen transaction scenario

The manifest identifies generator **v1.2**, seed **42**, and a 24,990-profile cohort. It records **3,900,172 generated events**, including **447,282 fiat events**. These event totals are scenario metadata, not rows in the public player-level business extract.

Generated history runs from October 2, 2018 to September 29, 2026; its recent purchase window is August 1–September 29, 2026 inclusive. Real profile context and generated purchase history have separate provenance. Reproducibility depends on the frozen cohort, seed, configuration and generator version together, rather than the seed alone.

The [scenario tests](../../src/sample/tests/test_business_sample.py) exercise reproducibility, grain, cash separation and rejection of invalid/incomplete/stale inputs using small fixtures and mocked warehouse calls. Their success is not evidence of a fresh full-volume generation or live load.

## Historical warehouse records

The reviewed project record reports these completed builds:

| Date | Recorded scope and outcome | Recorded elapsed time |
|---|---|---|
| September 30, 2026 | 21 models and 129 tests; 150 successful resources. | Full refresh 146.58 s; subsequent incremental run 158.94 s. |
| October 18, 2026 | 25 models, three seeds and 167 tests; 195 successful resources, zero warnings, errors or skips. | dbt 126.69 s. |

The original cloud run outputs behind these reviewed historical records are not included in the public serving export, and these builds were not rerun for this documentation batch. The [job definition](../../resources/build_dbt.job.yml) describes configured work; it does not independently prove a successful execution. Times describe those runs and are not a sustained throughput benchmark or a guarantee for another environment.

## Local verification during the rewrite

On October 19, 2026, the preceding documentation stages verified:

- One selected root dashboard smoke test passed against local snapshots.
- 55 selected configuration, job-result and load/confirmation-boundary tests passed using temporary state and mocked remote boundaries.
- Archived originals remained byte-identical, and current documentation links resolved.

Run the analytical and snapshot checks from the repository root, using the project's Python environment with its existing test dependencies:

```powershell
python -B -m pytest streamlit_app/tests/test_metrics.py streamlit_app/tests/test_population.py streamlit_app/tests/test_population_standardization.py streamlit_app/tests/test_population_views.py streamlit_app/tests/test_experience.py streamlit_app/tests/test_ranked_share.py streamlit_app/tests/test_business_sample.py streamlit_app/tests/test_story.py streamlit_app/tests/test_snapshot_contracts.py src/sample/tests/test_business_sample.py -q
```

This selection passed **59 tests** on October 19, 2026, using the existing project virtual environment. It covers metrics, rank adjustment, direct standardization, experience intervals, ranked-activity estimates, commercial summaries, growth-story calculations, snapshot contracts and small generated-scenario fixtures. It does not represent the entire repository test suite. Live collection, a cloud build and a serving refresh are separate operations.

## Execution evidence still in progress

The local execution showcase is being packaged under ignored `data/evidence/`. The reviewed inspection found blank start/finish/result fields in the dated run-context record and a separate timing record with no start time and exit code 1. Console logs were present but were not authenticated as one complete successful representative run. These artifacts are not public proof of end-to-end success, and separate timing output must not be assigned to a dated folder without matching identity.

A live injected failure followed by successful retry has not been demonstrated; failure/retry behavior is covered by tests. This distinction does not create a requirement for a new collection campaign. Task-attempt counts are not exact HTTP request totals, and an ETA based on 50 requests per minute is an assumption rather than measured sustained performance.

Claims about successful service execution, recovery, request totals or performance should identify the matching dated outputs when available. Current evidence also does not establish real spending, causal rank improvement, a proven zero effect, exactly-once delivery, or an achieved 200,000-player deployment.
