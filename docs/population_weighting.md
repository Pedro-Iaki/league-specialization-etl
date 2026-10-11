# Frozen tier distribution and population estimates

The extraction schedule balances rank-page depth across tiers. Pooled player
statistics therefore describe the collected sample unless corrected for the tier
mix. This implementation uses the manually supplied distribution in
`league_pipeline/seeds/rank_population_reference.csv`; it requires no scraping.
Bronze and silver jointly account for **37.97%** in this reference. All ten shares
sum to 100%. Receipt date is 2026-10-10; the observation date, region and queue of
the supplied estimate are unknown. Applying it to each dataset scope is an
explicit assumption.

## Analyst access

Run the app from the repository root:

```powershell
streamlit run streamlit_app/app.py
```

Open **Population Estimates**. It retains all available tiers, provides the
**Analysis denominator** selector, compares sample and weighted shares/means/
medians, and exposes effective sample size, reference coverage and downloads.
Filters preserve the precomputed weights. The same selector on **Population
Analysis** changes role composition and skew, mastery-band composition, pooled
mastery baselines, climber composition and active/lifetime cross-classification.
Within-tier box plots remain descriptive; in the current single-scope sample,
equal weights within a tier cancel. Mixing region/queue scopes can change a
tier's result because scope-specific weights can differ within that tier.

The ranked-activity view calibrates starting tier separately for the selected
observation window before champion filters or exploded champion membership.
Its denominator remains the selected cohort with completed ranked observations,
not all ranked players. A single starting-tier template cannot correct selection
into that cohort or resolve variation within tiers.

Generate a reproducible analyst bundle immediately from the existing anonymous
snapshot, without connecting to the warehouse:

```powershell
python streamlit_app/scripts/export_population_estimates.py
```

Outputs are under `data/population_estimates/`: a ZIP, anonymous weighted Parquet,
CSV estimates/diagnostics, input/reference-hash manifest and `ANALYST_HANDOFF.md`. Regenerate
after reference or snapshot changes. Dashboard downloads reflect the current
analyst selection; the CLI bundle contains the unfiltered snapshot.

## Weight definition and limitations

Within each available region/queue, let `n_t` be the unfiltered sample count in
tier `t`, `N` the count across tiers represented in the reference, `p_t` the
reference share and `C` the sum of reference shares for tiers with observations.
The relative player weight is:

```text
w_t = (p_t / C) / (n_t / N)
weighted_mean = sum(w_i * x_i) / sum(w_i)  # valid x and weights only
weighted_share = sum(w_i for matching players) / sum(w_i for eligible players)
effective_sample_size = sum(w_i)^2 / sum(w_i^2)
```

Weights average one in each calibration scope. A missing tier receives no
invented observations: diagnostics report full-reference coverage and results
are conditional on represented tiers. Unknown/unranked tiers receive undefined
weights and are excluded from weighted estimates and support counts. Before
filters, region/queue mixes retain supported-sample proportions because their
relative population sizes were not supplied; filtering can change that mix.
The gameplay Population Analysis view still displays Iron through Master; its
coverage diagnostics show excluded apex tiers. Population Estimates and the
analyst bundle preserve every tier available in the profile snapshot.

Calculate weights on the original calibration cohort, then filter by role,
champion, classification, mastery or tracked days. Recalibrating each filtered
subset would force its tier composition to match the full ladder and change the
meaning of the estimate. Side-by-side sample/weighted comparisons in estimate
mode use the same supported observations. Collected-sample mode can include
otherwise eligible unsupported-tier rows with equal weights. Player counts and
minimum support thresholds remain observed counts over eligible rows;
weighted mass is not an estimated real player count. Raw-count Wilson intervals
are omitted in weighted views. Effective sample size is diagnostic, not a
confidence interval or a measure of uncertainty in the manual reference.

Mastery bands retain sample-defined equal-frequency boundaries, with weighted
composition and weighted centers in estimate mode. The median-mastery
normalization remains a descriptive adjustment rather than full standardization.
The adjustment does not remove selection differences within tiers, establish
causality or make synthetic spending data real.

Overview, Champion Explorer and Cross Champion View now share the denominator
selector. Pooled trends, local medians, outcome summaries, correlations,
champion rankings, primary-player shares and rank statistics, mastery summaries,
ladder distributions and overlap probabilities retain tier weights before
filters. Quartiles in player box plots use the same weights. Observed counts
remain support counts; weighted mass is never displayed as a player count.

Historical comparisons calibrate the full observed player–tier cohort before
selecting champions, roles or playstyles. Ranked-share windows calibrate their
full player cohort independently. These estimate represented observations with
completed periods, rather than correcting selection into observation or claiming
outcomes for all ranked players. Champion population summaries pool player–tier
records, so a player observed in several tiers contributes once per tier.

The anonymous `champion_population_activity` and `champion_population_pairs`
exports retain tier, region and queue counts from existing gameplay models.
They supply weighted active-play rates, inferred role mixes and overlap
probabilities without changing those models. Old snapshots without the activity
export show an availability notice; old snapshots without the pair export retain
explicitly labeled sample overlap. Champion mastery means/medians at 15K or
above use the anonymous player-mastery export, rather than averaging tier
medians. Tier aggregate counts/means supply all-holder expert shares.

The experience-stratified check retains raw shares, equal-count sample bands and
Wilson intervals as requested. Synthetic business statistics retain their
scenario sample definition and are not real population spending estimates.

## Warehouse resources

The seed is configured for the reference schema; the view
`mart_player_population_weights` is configured for Gold and joins the existing
player profile mart without altering gameplay data. Activate it in the normal
configured dbt environment (from `league_pipeline`):

```powershell
dbt seed --select rank_population_reference
dbt test --select rank_population_reference
dbt run --select mart_player_population_weights
dbt test --select mart_player_population_weights
```

Analysts can join the view to `mart_player_profile` on `player_id`, `region` and
`queue` (use null-safe joins if any scope key is null). Use `population_weight`
for estimates, and retain `covered_population_share`, `reference_version` and
reference dates in reports. SQL uses the same scope normalization as Python.
The player query joins the weight mart while private join keys remain inside
the warehouse, exporting only weights and reference metadata. Dashboard
controls use supplied weights after validating them against the full snapshot
and frozen reference; stale weights are rejected. If the mart has not been
built, the exporter and live loader fall back to the full profile query and the
same local frozen-reference formula. Thus snapshot mode also works before
warehouse activation. Schema names follow the project's dbt schema macro.

### Reading the mart

The view has one row per current profile key (`player_id`, `region`, `queue`),
calibrated by current tier. It counts all unfiltered profiles in each scope/tier,
joins the manual reference, derives supported scope totals with window sums,
and attaches the resulting relative weight back to each profile. It uses actual
sample counts; extraction does not have to produce exactly equal tier counts.

| Quantity | SQL column | Current Gold example |
|---|---|---:|
| Tier sample count `n_t` | `tier_sample_players` | 4,998 |
| Supported scope count `N` | `scope_sample_players` | 37,172 |
| Actual sample share `n_t/N` | `sample_tier_share` | 13.4456% |
| Full reference share `p_t` | `estimated_population_share` | 23.53% |
| Represented reference mass `C` | `covered_population_share` | 99.94% |
| Supported target `p_t/C` | `supported_target_share` | 23.5441% |
| Relative weight | `population_weight` | 1.7511 |

Every current Gold player therefore receives the same weight in this scope. A
weight of 1.7511 increases that observation's influence relative to a weight of
one. It does not mean that the row represents exactly 1.7511 real people or
provide a real population count. Coverage is reference tier mass represented in
the sample, not the percentage of all real players collected.

The mart additionally exposes profile analytical/rank snapshot dates and seed
version/receipt/review dates. It preserves unsupported profile rows with null
weights and zero scope coverage when no reference tier is represented. Do not
replace null weights with one in an estimate.

Example warehouse estimate by role (current active HHI):

```sql
select
    p.main_role,
    count(*) as observed_players,
    sum(w.population_weight * p.active_hhi) / sum(w.population_weight) as estimated_hhi
from league_pipeline.gold.mart_player_profile p
join league_pipeline.gold.mart_player_population_weights w
    on p.player_id <=> w.player_id
   and p.region <=> w.region
   and p.queue <=> w.queue
where p.active_hhi is not null
  and p.main_role is not null
  and w.population_weight > 0
group by p.main_role
```

This query filters only after joining the unfiltered calibration. Compare or
report reference version, coverage and profile dates alongside the estimate.
The mart is a **live view**: a profile refresh changes counts and weights under
the same frozen reference version. Freeze joined profiles/weights together for
historical reporting; do not join today's weights to old periods. The offline
bundle freezes one snapshot and its exact reference instead.

## Manual freshness

Review is due after **2027-04-10**, or earlier after a rank-system change, a
material distribution shift or receipt of a better matching regional estimate.
The six-month review date is a maintenance reminder, not proof of stability or
an observation date. The dashboard warns when review is due and retains the
displayed version. There is no automatic external collection or replacement.

Update shares, source/scope, version and receipt/review dates together. Keep one
row per tier and positive shares summing to 1. Preserve the prior version in
version control; regenerate bundles, reseed and recreate the SQL view when
activating a new reference. If ranks are added or removed, update the validation
tier list, seed tests, tier macros and dashboard coverage deliberately before
using a revised estimate.

## Design and solution review — 2026-10-10

The separation is appropriate for this project: a manual reference supplies an
explicit assumption, current profiles supply observations, and a small Gold
view supplies relative analyst weights. The collector can retain balanced tier
coverage. Sample-defined champion aggregates remain separately labeled, because
an overall mean with discarded tier detail cannot always be corrected later.

The view/Python implementation intentionally calculates the same formula in two
execution environments. The dashboard uses its serving cohort; the warehouse
uses its current profile mart. Their results should agree only for matching
cohorts/reference content. Reseed the warehouse after a CSV change and compare
version and shares; the dashboard does not automatically deploy the seed.

| Reviewed concern | Resolution and evidence |
|---|---|
| Invalid/unsupported rows could inflate support or influence mastery-band boundaries | Shared helpers now exclude invalid weights before classification, bands, transitions, role support and ranked-activity counts; regression fixtures cover an unranked outlier |
| SQL/Python formulas could drift | A local regression executes the actual model's grouping/window/arithmetic logic, adapting only Jinja refs/config and null-safe equality to SQLite; fixtures cover uneven samples, missing scopes and absent tiers |
| Mean-one tests alone could miss duplicated joins | Added composite key, non-null player key and exact profile-cardinality tests; source dates/count/share diagnostics make the view auditable |
| An in-memory reference could bypass CSV validation | All reference callers now share one validator; seed metadata tests cover dates and provenance |
| A version label alone cannot identify changed shares | The offline manifest now fingerprints canonical reference content and the input snapshot, and carries the exact artifact list |
| ZIP could sweep unrelated output-folder files into the handoff | Only explicitly generated artifacts enter the archive; a regression leaves an unrelated file outside the bundle |
| Documentation described five pages and raw-count intervals in all modes | README/page guides, model catalog/lineage, engineering journey and analyst handoff now document six pages, weighting modes, unsupported rows and omitted weighted intervals |

The remaining limitations are scientific and operational: the reference's
original date/region/queue are unknown; division/page order and refresh policies
can select players within tiers; the 59 current Master profiles are selected
climbers; and completed-period outcomes are observed for a smaller cohort.
Post-stratification estimates require within-tier representativeness and a
reasonable reference for the chosen scope. These conditions are assumptions,
not established by the implementation. Effective sample size measures weight
dispersion, not uncertainty in those assumptions. Historical weighting needs
its own cohort/time definition; multiple-queue support also requires reviewing
upstream profile/period grains rather than only adding scopes to this view.

Local verification includes focused numeric/dashboard tests, SQL/Python parity,
artifact allowlist/fingerprint checks, Ruff and dbt parsing. This records local
implementation validation, not a Databricks seed/build/test execution. Run the
activation commands above to validate the deployed resources in the configured
warehouse. The analyst bundle is regenerated after the review changes.
