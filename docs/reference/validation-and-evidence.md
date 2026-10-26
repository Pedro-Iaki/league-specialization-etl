# Validation and evidence

[Project overview](../../README.md) / [Documentation](../README.md)

This page distinguishes inspectable artifacts, recorded verification and claims that remain untested. Counts describe dated snapshots, not targets to impose on future exports. Start with the current result; historical checks below explain provenance without serving as a checklist of every development iteration.

## Inspectable serving snapshot

The [story manifest](../../streamlit_app/data/story/manifest.json) identifies the default dashboard's behavioral and customer snapshots. The accepted October 24 package contains:

| Measure | Recorded result |
|---|---:|
| Behavioral profiles, as of October 20 | 38,403 |
| Profiles scored against the frozen archetypes | 13,348 |
| Empty active pools | 17,765 |
| Nonempty pools below the four-character minimum | 7,290 |
| Frozen scenario members | 24,990 |
| Cash purchasers in the scenario window | 6,790 |
| Cash in that window | USD 283,693.66 |

Behavioral tracking spans 0-34 days; 5,669 profiles have at least 30 tracked days. The current snapshot therefore uses both short-history and mature active-membership rules. Missing archetype eligibility is retained in coverage, not silently removed from the base.

The app reads local files and sends aggregates to its bundled component. Viewing requires no warehouse, local laboratory directory or execution database. The [evidence manifest](../../streamlit_app/story_component/evidence-manifest.json) identifies sanitized family diagnostics, component explanations and run summaries. Private archives remain local. `legacy_app.py` retains the older package under `streamlit_app/data`; its [manifest](../../streamlit_app/data/manifest.json) is a separate inventory.

## Recorded local acceptance

These are dated results from the existing project environment, not tests rerun each time this page is read. Counts from overlapping suites must not be added into a single total.

| Scope | Recorded verification | Limit |
|---|---|---|
| October 25 Streamlit migration | 98 analytical/host/offline/legacy tests; final 12-test focused recheck. 90 actual browser states across desktop/mobile and terminology modes, covering comparisons, Apply/pending state, navigation, purchase carry and response handling. | Local acceptance, not hosted load testing. |
| October 25 language publication | All 450 messages supplied in English and Portuguese; 24 focused tests and 28 actual Portuguese chapter/width/terminology states. | Reviewed display copy, not independent professional translation review. |
| October 25 scrolling | Wheel/footer checks for seven chapters at two widths, plus PageDown and navigation reset. | The checked layouts and interactions, not every browser/device. |
| Frozen family selection | 173 characters, 25 families, 251 memberships, original source identities and all accepted review gates checked; portable cohort reloaded. | Reused selection evidence, not held-out validation. |
| Frozen archetype integration | Laboratory feature agreement and component-count reconciliation; fixed-inference differences measured, keyed profile/customer association and scenario preservation checked. | See the [archetype reference](player-pool-archetypes.md) for solver differences and eligibility. |

The migration also checked syntax, new Python lint, package hashes and absence of raw Parquet exposure over HTTP. Legacy checks retained known pandas categorical deprecation warnings. Later portability fixes in `36c89e5` made snapshot/model hash handling independent of checkout line endings and normalized packaged metadata; those changes are distinct from the October 25 acceptance record and are not a new collection or model fit.

[Run the dashboard](../guides/run-the-dashboard.md) describes local verification entrypoints. Hosted availability, clean-environment installation and live injected-failure recovery require their own evidence; the recorded local checks do not establish them.

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

## Frozen transaction scenario

The manifest identifies generator **v1.2**, seed **42**, and a 24,990-profile cohort. It records **3,900,172 generated events**, including **447,282 fiat events**. These event totals are scenario metadata, not rows in the public player-level business extract.

Generated history runs from October 2, 2018 to September 29, 2026; its recent purchase window is August 1–September 29, 2026 inclusive. Real profile context and generated purchase history have separate provenance. Reproducibility depends on the frozen cohort, seed, configuration and generator version together, rather than the seed alone.

The [scenario tests](../../src/sample/tests/test_business_sample.py) exercise reproducibility, grain, cash separation and rejection of invalid/incomplete/stale inputs using small fixtures and mocked warehouse calls. Their success is not evidence of a fresh full-volume generation or live load.

## Recorded execution evidence

Inspection on October 25 reconciled two separate local archives under ignored `data/evidence/`. The public story exposes sanitized timelines and one task/compaction/load lineage example from the October 19 SQLite ledger.

| Archive | Recorded execution | Timing evidence |
|---|---|---|
| October 19 | 12 completed rounds, four completed ingestion/build cycles; 12 successful round reports and 4,920 reported player-refresh operations. | Exit code 0; 16,520.49 seconds. The timer has no start timestamp. |
| October 20 | 12 completed rounds and four completed ingestion/build cycles. | Exit code 0; 16,725.88 seconds, aligned with console timestamps 03:05:49-07:44:35 UTC. |

These durations include collection, pacing and cloud waits; they are not extraction-throughput measurements. Task attempts are not exact HTTP request counts. The archives do not establish the initial backlog, historical environment overrides or cold/warm compute state, and the October 19 ledger must not be attributed to October 20. A copied context note was corrected against its matching captures, with the original preserved.

The records support successful execution within their captured scope, not lineage for every dashboard row. Selected failure/retry paths have automated tests; a live injected failure followed by recovery has not been demonstrated. Shared claims and delivery confirmation are implemented mechanisms, not proof of exactly-once delivery or a tested multi-machine deployment.

## Historical checkpoints

Earlier versions are useful for tracing development, but their profile counts, page numbering and UI checks do not describe today's story.

| Checkpoint | What it established |
|---|---|
| September 29 profiles, exported October 10 | 37,172 profiles; the original frozen commercial cohort and early outcome comparisons. |
| October 20 export | 37,803 profiles as of October 19; 3,602 had at least 30 tracked days. All 13 candidate datasets passed contracts; existing successful ingestion/build jobs were inspected, not rerun. |
| October 23 family-enriched legacy package | 38,403 profiles and unchanged 24,990 scenario members; keyed family integration, full-package checks and six-chapter browser acceptance. Eleven other datasets retained earlier export provenance. |
| September 30 / October 18 warehouse records | Reviewed records reported 150 / 195 successful resources respectively. Original cloud outputs are not included in the public serving export; these records are separate from the archived executions above. |

The [pre-consolidation evidence record](https://github.com/Pedro-Iaki/league-specialization-etl/blob/7dbb30d/docs/reference/validation-and-evidence.md) preserves detailed inventories and historical test runs. Its references to a "current" manifest belong to that documentation revision; use the matching historical artifact, not a replaced serving file, to reproduce an older result. Timings from individual runs are not throughput guarantees.

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
