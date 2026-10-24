# Validation and evidence

[Project README](../../README.md) · [Documentation index](../README.md) · [Orchestration](orchestration.md) · [Data models](data-models.md)

This reference separates implemented checks, inspectable frozen artifacts, reviewed historical run records and behavior that has not been demonstrated live. Counts below describe dated snapshots. The October 20 refresh inspected existing successful warehouse jobs and exported their outputs; it did not start a new collection, warehouse build or transaction generation.

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

The current [manifest](../../streamlit_app/data/manifest.json) records the family-enriched export on **October 23, 2026, 11:06:08 UTC**. Its **38,403 profiles are as of October 20**, with retained player snapshots spanning September 17–October 20. The **24,990-customer scenario stays frozen at September 29**; its purchase window is August 1–September 29 inclusive. All customers were associated with current audience context by actual private player key and queue before anonymous projection. Later context is not evidence of purchase-date preference or prediction.

| Dataset | Rows | Columns |
|---|---:|---:|
| `champion_population_pairs` | 133,902 | 11 |
| `champion_population_activity` | 1,557 | 13 |
| `business_players` | 24,990 | 80 |
| `champion_player_mastery_share` | 1,168,633 | 7 |
| `champion_tier_mastery` | 22,567 | 13 |
| `players` | 38,403 | 87 |
| `champions` | 173 | 38 |
| `cooccurrence` | 14,878 | 14 |
| `growth_players` | 1,255 | 12 |
| `champion_growth_players` | 4,818 | 13 |
| `growth_player_styles` | 1,255 | 9 |
| `champion_tier_growth` | 3,110 | 16 |
| `ranked_mastery_cohorts` | 3,982 | 10 |

Only profiles and business summaries were replaced in this release. The other eleven datasets are retained byte for byte from the previous serving package; the manifest records that retention and their earlier export provenance. The new top-level export date does not refresh their observations. Row grains are defined in [data models](data-models.md#serving-datasets).

The installed [family definition](../../streamlit_app/definitions/champion-audience-families-v1.json) fixes 25 families, 173 characters and 251 overlapping memberships. Its SHA-256 is `fdb8f3eaca472fcf24b749a1d6af60ea74b0d908c1dbcfd831a5339a8029f781`. The [segment reference](../../streamlit_app/data/audience_segments_reference.json) pins complete-base bands, individual-tier calibration and source-profile identity. Behavioral calibration covers 99.98% of the saved rank reference; 0.02% is unsupported and 0.04% has sparse individual-tier support. Scored family pools cover 50.73% of adjusted profiles, including shared-top states; absent pools remain visible elsewhere.

The preserved scenario reconciles **6,790 cash purchasers, 18,200 nonbuyers and USD 283,693.66** in its 60-day purchase window, plus **USD 7,439,491.86** across generated history. Cash is counted once in integer cents. Purchaser rates include nonbuyers; per-purchaser cash uses purchasers only. No gameplay population weights enter these customer totals. These amounts are generated demonstration data, not actual revenue.

The October 23 integration checked all 13 public schemas, forbidden identifiers, manifest counts/sizes, unique within-file row keys, enriched file/metric hashes, frozen reference identity, scenario preservation, conditional audience totals and cash reconciliation before local promotion. A complete previous serving directory is retained locally for rollback. The six guided chapters render against this coherent package. A focused integrated run passed 75 tests; the new engineering tests passed all three cases after correcting a test assertion. Browser checks covered all six in EN/PT and both terminology modes, with 21 recorded cases at 1440, 1024 and 390 px, unchanged chart numbers across language/terminology and no rendering exceptions or horizontal overflow. The pre-existing explorer emitted one pandas categorical warning. These are local checks, not deployment or independent validation of families. See [run the dashboard](../guides/run-the-dashboard.md) for viewing and [refresh dashboard data](../guides/refresh-dashboard-data.md) for replacement/rollback boundaries.

The final October 23 acceptance exercised **437 dashboard test cases**. The complete run passed 436 and exposed one legacy test that hardcoded the older snapshot's band counts; that assertion was replaced with checks against the installed frozen reference and retained tiers. The final related audience/customer/translation run passed all 29 tests, followed by all 10 language checks after tablet spacing changes. The complete run retained 24 existing pandas categorical warnings. No analytical failure remained after those focused checks; the full suite was not repeated unchanged.

The final browser pass recorded **30 cases** at 1440, 1024 and a strict 390 px, complementing the earlier six-chapter EN/PT review. Checks included rank inversion and hour-label invariance, retained-history and ranked-volume selections, searchable family choice, primary versus affinity, optional focus/breadth, sparse estimates, customer refinements, independent language/terminology persistence and returning to the opening page. The final review corrected clipped customer-axis titles and tablet language/flow spacing. There were no page-level horizontal overflows or runtime errors in the accepted cases. Frozen serving/backup hashes and the adopted family definition stayed unchanged. Required serving references are explicitly allowed in Git; local experiments and private notes remain excluded. These checks establish local readiness, not hosted availability.

## Historical serving and chapter checks: October 20, 2026


The current [manifest](../../streamlit_app/data/manifest.json) records export time **October 20, 2026, 03:17:24 UTC**. Gameplay profiles are as of **October 19, 2026**, with latest-known player observations spanning September 17–October 19. The validated transaction scenario remains frozen at **September 29, 2026**; its provenance and generated events were preserved.

| Dataset | Rows | Counting unit |
|---|---:|---|
| `players` | 37,803 | Current player profiles, including the new active-pool Lifetime preference fields. |
| `champions` | 173 | Character summaries. |
| `cooccurrence` | 14,878 | Supported unordered character pairs. |
| `champion_player_mastery_share` | 1,168,633 | Player/character memberships. |
| `champion_tier_mastery` | 22,567 | Character/rank/threshold summaries. |
| `growth_players` | 1,255 | Eligible player/starting-rank summaries. |
| `growth_player_styles` | 1,255 | Eligible player/starting-rank/period-classification summaries. |
| `champion_growth_players` | 4,818 | Attributed player/character/starting-rank summaries. |
| `champion_tier_growth` | 3,110 | Character/starting-rank/scope summaries. |
| `ranked_mastery_cohorts` | 3,982 | Player/window summaries. |
| `business_players` | 24,990 | Preserved frozen scenario/player summaries. |
| `champion_population_activity` | 1,557 | Character/current-rank/scope summaries. |
| `champion_population_pairs` | 133,902 | Character-pair/current-rank/scope summaries. |

The full player extract contains **19,723 paired Recent/Lifetime classifications** and **18,080 profiles without a Recent classification**. Tracking spans 0–33 days; **3,602 profiles have at least 30 tracked days**, so the mature membership rule now applies to part of the sample. Active-pool Lifetime preferences have positive mastery support for **19,722 profiles**; one additional classified pool has zero Lifetime mastery and retains null preference fields. There are **18,629 profiles** whose leading active character has at least 15,000 Lifetime points. These counts cover the full extract. Legacy default views omit its one Grandmaster profile; the paired page-3 comparison includes it in Diamond+ and excludes the zero-total pool, yielding 19,722 comparable profiles. September cohort counts and descriptive findings below must not be carried forward without recalculation.

Read-only job checks before and after export found successful ingestion run `1011929478031051` and dbt run `85473963130053`, with no active runs or changes to their identities, profile count/dates or scenario metadata during export. The configured build scope was `dbt deps` and `dbt build`. Those run responses did not expose a resolved Git commit; the local exporter revision was `e72cd63`.

All 13 candidate datasets passed public contracts, privacy checks and manifest row/column/size checks. Additional checks covered active-pool membership counts, share denominators, HHI and scenario consistency. All six story pages plus specialization/rank, character, population-estimate and business explorer pages rendered against the candidate. Six snapshot/preference tests passed against the installed files. The previous serving package was backed up, and replacement files were verified by hash before the local preview restarted. A new analyst bundle records the refreshed snapshot and the unchanged rank reference; its generic reference-scope metadata remains an interpretation limit.

The subsequent page-3 alignment on October 20 passed **144 dashboard tests** and a final **13-test focused run**. Checks cover the paired cohort, apex inclusion, fixed value-based bands and score ties, medians/quartiles, chart transposition, audience-map reconciliation, stale-reference behavior, language/terminology invariance and existing snapshot/explorer behavior. Headless browser checks at 1440, 1024 and 390 px covered EN/PT, Plain/League, both axis orientations and quartile toggling without page overflow or rendering exceptions. Median ranges are distribution quartiles; Wilson intervals remain limited to historical category proportions. The full run emitted 24 categorical-compatibility warnings from the legacy composition helper in `analysis.py`; these were not suppressed or represented as test failures. All 13 serving-file hashes and the manifest remained unchanged during this page implementation.

The October 20 implementation of story pages 1, 2 and 4 passed **154 dashboard tests**, followed by **32 focused tests** against the final changes. Browser review at 1440, 1024 and 390 px covered the three chapters, English/Portuguese and both terminology modes. A final page-4 review also exercised the whole-history view and a leading-character selection, preserving the expected 663-profile Yasuo audience without overflow or rendering exceptions. The terminology-switch check caught and corrected a deferred widget-label mapping issue before completion. The full run retained the same 24 legacy categorical warnings described above.

The chapter checks reconcile page 2's distribution summaries and collapsed grid to page 3's rank facets, preserve the fixed cohort/bands after character filtering, retain missing-type profiles outside the type chart, and distinguish the 19,723-profile pair source from the 19,722-profile concentration reference. That historical chapter sequence placed transactions fifth and retained separate growth evidence in the final chapter; the October 23 audience story replaces that ending with engineering and evidence. All 13 dataset hashes, the manifest and the frozen audience reference remained unchanged. No warehouse models, transaction scenario or archetype assignments were regenerated.

## Historical serving snapshot: September 29, 2026

The previous manifest recorded export time **October 10, 2026, 23:37:07 UTC**. Player profiles were as of **September 29, 2026**, with underlying player snapshots dated September 16–29. These are different dates with different meanings.

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

The reviewed analysis of the September 29 export distinguishes the following cohorts. These counts are historical analytical findings; reproduce the corresponding filters against the current snapshot before using them for a new release.

| Cohort | People | Interpretation |
|---|---:|---|
| Full profile cohort | 37,172 | Available current profiles. |
| Classified recent audience / complete core business cohort | 24,990 | Usable recent-pool classification and required frozen business features. |
| No recent pool | 12,182 | Missing recent classification; not evidence of zero activity or zero spending. |
| Recent classification with latest eligible LP outcome | 1,074 | Latest-outcome analysis cohort. |
| Growth scatter | 946 | Separately filtered for at least two games and usable outcome/concentration. |
| Classified historical outcome cohort | 1,066 | Eligible historical players, with one retained outcome period in this export. |

These are branches, not successive stages of one conversion funnel. The historical complete period on September 27 contained 3,373 players before outcome filtering, including 2,291 with zero games. The estimated ranked-mastery-share cohort also contained 1,074 people but differed from the latest LP-eligible cohort by eight people in each direction. Counts alone are insufficient evidence of shared membership, particularly after public identifiers are removed.

All September 29 profiles had fewer than 30 tracked days, with maximum 13. Recent pools were gain-weighted for 3,374 players, equal-membership-weighted for 21,616, and absent for 12,182. This explains that historical snapshot's recent-activity measures, rather than the refreshed cohort's mixture of short-history and mature membership rules.

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
- Current documentation links resolved.

Run the analytical and snapshot checks from the repository root, using the project's Python environment with its existing test dependencies:

```powershell
python -B -m pytest streamlit_app/tests/test_metrics.py streamlit_app/tests/test_population.py streamlit_app/tests/test_population_standardization.py streamlit_app/tests/test_population_views.py streamlit_app/tests/test_experience.py streamlit_app/tests/test_ranked_share.py streamlit_app/tests/test_business_sample.py streamlit_app/tests/test_story.py streamlit_app/tests/test_snapshot_contracts.py src/sample/tests/test_business_sample.py -q
```

This selection passed **59 tests** on October 19, 2026, using the existing project virtual environment. It covers metrics, rank adjustment, direct standardization, experience intervals, ranked-activity estimates, commercial summaries, growth-story calculations, snapshot contracts and small generated-scenario fixtures. It does not represent the entire repository test suite. Live collection, a cloud build and a serving refresh are separate operations.

## Family workflow finalization checks

On October 23, 2026, `python -m pytest streamlit_app/tests -q` passed **331 tests**
in the existing project environment. This run includes the full and anchored family
helpers, cohort editing and selection, Compact objectives, experiment resume/export
boundaries, dashboard rendering and snapshot contracts. It completed with 24 pandas
categorical deprecation warnings from the existing analysis helper.

The accepted 87.5% family-cohort alternative was separately checked for its 173
champions, 25 families, 251 memberships, saved source identities, portable loading,
all review gates and frozen reference-pool checksum. Finalization renamed display
labels without changing selected memberships or source evidence. These are local
implementation and artifact checks; this step ran no new discovery/bootstrap,
cloud build or serving refresh.

## Execution evidence still in progress

The local execution showcase is being packaged under ignored `data/evidence/`. The reviewed inspection found blank start/finish/result fields in the dated run-context record and a separate timing record with no start time and exit code 1. Console logs were present but were not authenticated as one complete successful representative run. These artifacts are not public proof of end-to-end success, and separate timing output must not be assigned to a dated folder without matching identity.

A live injected failure followed by successful retry has not been demonstrated; failure/retry behavior is covered by tests. This distinction does not create a requirement for a new collection campaign. Task-attempt counts are not exact HTTP request totals, and an ETA based on 50 requests per minute is an assumption rather than measured sustained performance.

Claims about successful service execution, recovery, request totals or performance should identify the matching dated outputs when available. Current evidence also does not establish real spending, causal rank improvement, a proven zero effect, exactly-once delivery, or an achieved 200,000-player deployment.
