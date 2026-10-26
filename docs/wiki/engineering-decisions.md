# Engineering decisions

[Project README](../../README.md) · [Documentation index](../README.md) · [Architecture](architecture.md) · [Simulated transactions](simulated-transactions.md)

I built this project to demonstrate a data product I could explain from source constraints through to usable output. The decisions below shaped that implementation: what to collect, which history to retain, when state can advance, and how someone can inspect the result.

The implementation links show the current mechanisms. Development stories and motivations are my recollections; measured results have their own dated [evidence reference](../reference/validation-and-evidence.md).

## Spend requests on useful observations

Ranked listing pages and character-activity snapshots provide economical audience context under a personal API allowance. They support broader repeated coverage while giving up direct match-level detail. Character activity remains mixed-mode, and character-specific competitive results must be inferred.

The two main collection operations have different nominal costs:

| Operation | Core request calculation | Assumption |
|---|---|---|
| Discovery plus character activity | One listing request plus one activity request per player: `206 / 205`, approximately 1.005 requests per player. | A full page of 205 useful players. |
| Refresh a known player | Two requests: competitive status and character activity. | Normal individual refresh, before additional calls or retries. |

These calculations explain the source choice; they are not throughput measurements. Partial pages, freshness filtering, metadata lookups and retries change the actual cost. Cheap discovery alone also cannot establish how many people can be kept regularly refreshed.

The runner consequently balances discovery against stale-player refresh. Repeated inactivity reduces a player's contribution to refresh pressure, while elapsed freshness periods allow that priority to recover. Inactivity comes from unchanged competitive game counters; a failed request is not evidence that someone stopped playing. [Adaptive allocation](../reference/orchestration.md#adaptive-allocation) records the implemented rule.

## Let the analytical question determine the history

A static profile can describe accumulated activity but cannot distinguish an old favorite from a current interest. Repeated snapshots made recent-pool inference and period-aligned rank comparisons possible. That required modeling actual observation intervals, missing follow-up and counter changes, rather than simply adding more copies of a current-state row.

I chose weekly buckets as a practical compromise between observation capacity and useful behavioral intervals. The model still uses actual endpoints and eligibility checks; a nominal week does not establish seven fully observed days. Recent activity and Lifetime context remain separate views, and a player can be useful in one without qualifying for the other outcome comparisons.

Exploration in Python/Pandas helped expose those needs before I formalized the warehouse models. dbt then made SQL dependencies, grains and checks inspectable. Databricks brought storage, compute, jobs and execution inspection into one environment; learning that platform was also part of my aim. These were choices for this project, without a formal comparison proving one platform universally cheaper or better. The [data-model reference](../reference/data-models.md) shows the resulting contracts.

## Separate discovery from a reproducible audience definition

Early concentration rules described how narrowly people played, but did not explain which interests they shared. Character co-occurrence added that relationship. A single exclusive graph partition still forced every character into one group, even where audiences overlapped or placements depended on the neighborhood being considered.

Full-roster and anchored Leiden searches supplied alternative groups. Resampling matrices exposed stable cores and weak members, while collection review balanced coverage, overlap and individual fit. The accepted result is 25 overlapping champion families with frozen source identities and review gates. The [family reference](../reference/character-family-cohort.md) records that selection; its consistency scores reuse discovery evidence and are not held-out accuracy.

The next layer needed to describe players who use several families. NMF over family-affinity features supplies eight recurring profiles with nonnegative mixture strengths. K-means remained a diagnostic comparison, rather than the adopted exclusive assignment. Informal naming feedback helped make the components readable without being treated as statistical validation.

Freezing the fitted transformation, feature order and training weights makes routine export independent of whichever cohort is being served. Fixed inference was checked against the original laboratory fit, including small differences around the expression threshold. Player and business rows are enriched while private keys are available, then anonymized. This avoids refitting during viewing and prevents guessed associations between anonymous files.

The story uses these archetypes to compare audiences, not to rank interests by popularity: family size, overlap and character prevalence remain influential. The [archetype contract](../reference/player-pool-archetypes.md) owns the numerical details. The engineering result is a traceable path from exploratory evidence to a stable serving definition, with the uncertainty of the interpretation kept visible.

## Make collection progress durable

I remember the local ledger revealing that early collection kept returning to the same first-page records. That observation led to persistent discovery progress. I no longer have the original evidence for a before/after efficiency comparison, so this is a development recollection rather than a measured performance result.

The current responsibilities are explicit: SQLite links local work to files, compaction and load status; Neon owns shared freshness, claims and discovery cursors; Databricks retains analytical observations and history. Keeping those responsibilities separate avoids treating temporary task state as warehouse history or maintaining two competing page cursors.

Persistent pagination does not freeze a changing ranked ladder into a census. Shared claims also do not establish a tested deployment across multiple machines. The value is concrete coordination and inspectable state, with the [ownership boundaries](../reference/orchestration.md#state-ownership) stated plainly.

## Coordinate the request allowance within the client

Concurrent requests exposed timing problems that were not apparent in a simple single-worker loop. I recall rate-limit responses despite an apparently sufficient allowance; thread synchronization, token-bucket timing and a small margin helped address those cases.

The [API client](../../src/extract/api_client.py) owns synchronized pacing within that client, while workers receive their allocation from the runner. Shared database claims solve a different problem: who owns available work. They are not a global rate limiter across independent clients. This keeps request pacing, work ownership and orchestration from becoming interchangeable responsibilities.

## Confirm delivery before advancing dependent state

A successful API response, a valid local file, an uploaded object and ingested warehouse observations are different outcomes. Advancing freshness or page progress at upload time could move collection past observations that never reached raw tables.

The loader therefore waits for ingestion confirmation before applying delivery-related state updates. The dbt build is a separate job. If ingestion succeeds and dbt fails, confirmed delivery stays recorded and normal file cleanup is blocked. Local files and the ledger then help explain what succeeded and what remains unresolved.

These boundaries cross services and are not one distributed transaction. A local wait can expire while the remote job continues, so a retry decision needs its run identity. Tests exercise selected failure paths; a live injected failure followed by recovery has not been demonstrated. [Upload, ingestion and build boundaries](../reference/orchestration.md#upload-ingestion-and-build-boundaries) specify the behavior in detail.

## Keep orchestration and serving proportionate to this version

The implemented workflow is a bounded collection loop followed by a small set of ordered stages. I kept that coordination in Python rather than adding another deployed scheduling service. The difficult work was establishing state transitions, integrity gates and partial-failure behavior; a scheduler would not define those automatically.

That choice keeps execution operator-started and leaves inspection and recovery responsibilities explicit. It does not provide every managed scheduling, alerting or backfill capability. A changed operating context could justify a different choice, but Airflow, Docker, infrastructure as code and automatic publication are outside this version's scope.

The new story retains a local snapshot boundary while moving its approved controls
into a bundled Streamlit component. Python owns predicates and aggregate results;
JavaScript owns presentation and draft/applied state. This preserves the reviewed
interaction design without a separate production HTTP service or Node build.
The previous interface remains explicitly available as `legacy_app.py`.

Serving follows the same principle. A manual export gives Streamlit local Parquet files and a manifest, so reviewers can explore the output without pipeline credentials or warehouse availability. The cost is visible staleness and an explicit refresh operation. A successful warehouse build does not update the app, and individual file replacement does not create an atomic refresh of the whole snapshot.

## Demonstrate the missing commercial domain explicitly

The customer questions needed purchase history that was not available. I built a reproducible generated source around a frozen real cohort, with distinct cash semantics and reconciliation. This lets the integration be inspected while keeping commercial assumptions visible.

The [simulated-transactions chapter](simulated-transactions.md) explains that boundary. Its relationships illustrate possible analyses; they are not validated customer findings. The generated branch is a valid completion point, rather than a promise of eventual access to private financial data.

## Lessons from building the pipeline

Over several months, the lesson was how much remains after a rudimentary extract/load/transform path works. State, data quality, modeling, lineage and delivery took much longer than I initially expected. I deliberately built some parts by hand to understand them, which was a learning choice rather than a production recommendation.

I would start with a smaller scope and finish it more deliberately. Small reviewed changes help keep that scope manageable.

Continue with [Validation and evidence](../reference/validation-and-evidence.md) to inspect the current result, recorded runs and boundaries of those claims.
