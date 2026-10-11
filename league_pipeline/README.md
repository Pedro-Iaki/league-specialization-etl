# League Pipeline dbt Project

This dbt project turns player rank snapshots, champion mastery snapshots, and champion metadata into player- and champion-level analytical datasets.

The full model catalog is in [docs/model_reference.md](docs/model_reference.md). It documents each model's purpose, grain, upstream and downstream dependencies, columns, implementation details, and interpretation edge cases.

## Layers

- `bronze`: latest ingested copy of each raw snapshot.
- `silver`: normalized historical and current player, mastery, and champion records.
- `gold`: reusable activity, role, concentration, and rank facts plus analyst-facing marts.

## Main analytical outputs

- `mart_player_profile`
- `mart_player_population_weights` — live view of relative current-tier weights under a frozen population estimate.
- `mart_player_delta_history`
- `mart_champion_profile`
- `mart_champion_tier_growth`
- `mart_champion_playstyle_profile`
- `mart_champion_cooccurrence`
- `mart_player_spending` — optional synthetic spending scenario over frozen real profiles; separate from gameplay marts.

## Frozen population reference and weight view

`rank_population_reference` is a manually maintained ten-tier seed in
`reference`. `gold.mart_player_population_weights` is a view over this seed and
the unfiltered current profile mart. One row represents the profile key
(`player_id`, `region`, `queue`); it includes actual tier/scope counts, sample and
target shares, covered reference share, profile dates and the relative weight
`(p_t / C) / (n_t / N)`. Weights average one within supported region/queue scopes.
Use all three keys when joining to profiles, and keep weights when filtering.

The current reference is `2026-10-10-v1`, received on 2026-10-10 with review due
2027-04-10. Observation date and region/queue were not supplied. It is an assumed
distribution, not an API observation or a guarantee of fixed ladder shares.
Missing tiers are not imputed, and within-tier selection remains possible.
The view changes when profiles refresh even if the reference version stays fixed.

With the existing profile mart built, activate only the new resources:

```powershell
dbt seed --select rank_population_reference
dbt test --select rank_population_reference
dbt run --select mart_player_population_weights
dbt test --select mart_player_population_weights
```

The profile-grain test reads the existing profile mart for comparison but does
not rebuild it. `dbt build --select tag:population_weighting` is also available
once the upstream profile mart exists. Tests enforce reference completeness,
metadata, positive shares and normalization, weight key uniqueness/profile row
cardinality, positive weights and valid coverage. Local verification includes
dbt parsing and Python/SQL numerical parity with equivalent SQLite null-safe
joins; Databricks execution of these resources has not been claimed.

The dashboard and anonymous analyst exporter read the same repository seed and
compute the same formula on their own serving cohorts. They work before
warehouse activation; a seed update must still be applied to the warehouse for
SQL analysts. Compare both reference content and calibration cohort before
comparing Python/SQL results. Definitions, columns and lifecycle are in the
[model catalog](docs/model_reference.md#mart_player_population_weights); the
[method and review](../docs/population_weighting.md) documents maintenance,
analyst exports and scope limitations.

## Separate business sample

After running the generator and dedicated loader from the repository root (see the [sample workflow](../README.md#generate-the-business-sample)), build only its resources:

```powershell
dbt build --select tag:business_sample
```

This includes `sample_currencies` and `sample_products` in `sample_reference`, `bronze.transactions`, `silver.fct_transactions`, `gold.mart_player_spending` and their focused tests. A separate seed command is unnecessary; `dbt seed --select sample_currencies sample_products` remains available. All sample models are rebuilt tables. No gameplay model is an upstream `ref()` of this build: the frozen raw cohort preserves the original real context.

The two added raw sources contain generated events and frozen scenario players, not real Riot purchase data. One Gold row represents one frozen player, including those with no fiat purchases. All-history cash and recent 60-day cash reconcile to the hypothetical endpoint's `amount_usd` only for fiat events. RP and BE contribute to content mix and acquisition counts without cash valuation. Consistency measures gaps between distinct cash purchase dates, not gameplay activity. See [the sample model reference](docs/model_reference.md#synthetic-business-sample) for ratios, nulls and provenance.

The cohort includes every current ranked player with complete valid core profile inputs, without a row cap: classified role/playstyle, champion and mastery/pool context. Ranked-mastery share and recent games/day are optional and remain null when unobserved; missing ranked share uses a neutral generation offset. Individual snapshot dates may differ; all rows share one frozen as-of date. Generator version 1.2 records required/optional features, their coverage and the snapshot date range.

The sample loader clears the cohort completion marker before replacing transactions, then writes the cohort last. The exporter/live sample reader require matching raw/Gold scenario IDs, row counts and cash totals, so an interrupted load or stale build cannot publish a business snapshot. Existing gameplay snapshots and models remain independent.

### Verified sample run

The four-chart dashboard update on 2026-10-09 added recent fiat-only discounted-event count, discounted share and conditional mean to the spending mart. `dbt build --select mart_player_spending assert_business_sample_reconciles` passed **5/5 resources** (one sample table and four tests). Reconciliation now verifies cash-only discount counts/ratios/conditional means against facts for every player, including nulls for absent denominators. The business-only export still has 24,990 rows and now has 42 public columns. Real gameplay models and raw tables were not modified.

The current **core-profile refresh, generator 1.2 (2026-10-09)** includes 24,990 players and 3,900,172 generated events. Ranked share/recent games-day observations are optional and present for 1,066/1,074 players; all other required core context is complete. The sample-only build passed 19/19 resources and the anonymous export contains 24,990 rows. Source fiat USD reconciles to 7,439,491.86 across generated history and 283,693.66 in the recent window. Of 37,172 available profiles, 12,182 lack required core/active context. Prior runs below record earlier selection policies.

The intermediate **2026-10-09 strict complete-data refresh** selected all 1,066 eligible players from 37,172 current profiles. Every requested real feature is observed; snapshot dates span 2026-09-23 through 2026-09-28 with common as-of 2026-09-29. Bronze/Silver contained 200,827 events, and Gold/public export each contain 1,066 players. The targeted build again passed 19/19 resources. Source fiat USD totals reconcile to 315,627.90 across generated history and 11,870.10 in the recent window. Generated history begins on 2018-10-04. The remaining 36,106 profiles failed complete-data eligibility; there is no row cap.

On 2026-10-08, the sample-only Databricks build passed **19/19 resources**: two seeds (5 currencies, 11 SKUs), three Delta models and 14 data tests, with no warnings or errors. Bronze/Silver each contain 143,557 events; Gold contains 1,000 frozen real players. Source fiat totals reconcile to USD 294,103.85 across generated history and USD 11,167.67 in the inclusive recent window, including 280 players with no fiat purchases. The real profile snapshot/as-of date is 2026-09-29. Repeat loading preserved logical row counts and totals; read-only checks showed unchanged versions of real `raw.players`, `raw.masteries` and `raw.champions`.

The 2026-10-08 figures record the initial capped run, separate from the complete-data refresh and earlier full gameplay build below. No gameplay models were rebuilt. That initial generated history begins on 2018-10-07; it is fictional history, not historical Riot evidence. The previous business exports had 39 columns; the current export adds three fiat-only discount summaries. All omit player/event/SKU IDs.

## Validation and build

Run commands from this directory with a configured `league_pipeline` dbt profile:

```powershell
dbt parse --no-partial-parse
dbt build
```

Use `dbt build --full-refresh` after changing the grain, unique key, or schema of an incremental bronze or silver history model.

### Last verified build

Validated against Databricks on 2026-09-30 using dbt Core 1.12.3 and dbt-databricks 1.12.5 with six threads.

| Build | Result | Resources | Duration | Purpose |
|---|---:|---:|---:|---|
| `dbt build --profiles-dir $HOME/.dbt --full-refresh` | Passed | 150/150 | 2m 27s | Rebuilt all models from the raw sources and validated the complete DAG. |
| `dbt build --profiles-dir $HOME/.dbt` | Passed | 150/150 | 2m 39s | Verified the normal incremental execution path after the rebuild. |

Each run covered 21 models and 129 data tests across the bronze, silver, and gold layers, with `WARN=0`, `ERROR=0`, and `SKIP=0`. This includes source constraints, uniqueness and grain checks, accepted-value and range checks, the silver mastery-to-champion relationship test, and nine end-to-end business-rule tests under `tests/business`.

These results record a successful validation at the commit where they were produced; they are not a substitute for rerunning `dbt build` after future model or source-contract changes.
