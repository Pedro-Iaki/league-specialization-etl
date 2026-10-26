# Population adjustment

[Project README](../../README.md) · [Documentation index](../README.md) · [Metrics and methods](metrics-and-methods.md) · [Validation and evidence](validation-and-evidence.md)

Rank adjustment changes how observed players contribute to a summary. It does not make this collection a random sample or supply outcomes for unobserved people. This reference distinguishes sample summaries, inherited weights after filtering and direct standardization after selection. [Metrics and methods](metrics-and-methods.md) defines the underlying outcomes; [validation and evidence](validation-and-evidence.md) owns the dated export inventory.

## Ownership and reference input

Shared [Python helpers](../../streamlit_app/app_core/population.py) own calibration, weighted summaries and direct standardization. There is no current dbt population-weight mart. Exporters can attach weights. Legacy population explorers use runtime `population_weights` to recalculate them from the maintained local [rank reference CSV](../../league_pipeline/seeds/rank_population_reference.csv), replacing cached values.

The CSV requires all ten recognized tiers exactly once, with positive finite shares summing to one within absolute tolerance `1e-8`. Each metadata column must contain one common nonmissing value: `reference_version`, `recorded_on`, `review_after`, `source` and `reference_scope`. The review date must follow the recorded date. A fingerprint is calculated from canonical sorted CSV content. Structural validation does not authenticate the external source.

The saved October 10, 2026 shares are accepted by the author, who corrects their source to [OP.GG tier statistics](https://op.gg/lol/statistics/tiers), with North America ranked solo/duo as the intended scope. On October 23 the metadata was aligned as version `2026-10-10-v2-provenance`, retaining every numeric share, the October 10 recorded date and April 10, 2027 review date. This changes the canonical fingerprint but not calibrated weights. The live page confirms the source location and NA selector; it is not an independently matched historical capture. No replacement values were scraped.

Legacy population views show reference metadata and warn when review is due; they do not automatically fetch a replacement or stop using the file at that date. The default story calibrates from the reference frozen in its matching `audience_segments_reference.json`; it does not fetch a new reference during viewing. Historical family-discovery files retain their original reference hashes; correcting provenance does not change the accepted champion memberships.

## Calibration before filtering

Within each available `(region, queue)` scope, let:

- `n_t` be the calibration cohort's observed count in recognized tier `t`;
- `N = sum(n_t)` across recognized tiers;
- `p_t` be the external reference share;
- `S` be tiers with at least one observed player;
- `C = sum(p_t for t in S)` be supported reference coverage.

The normalized target share is `p_t / C`, the observed share is `n_t / N`, and each supported player's weight is:

```text
w_t = (p_t / C) / (n_t / N)
```

Weights average one among recognized calibration rows within the scope. Their sum is that observed cohort's size, not an estimate of the number of people in North America. Unsupported tiers receive diagnostic rows but no invented players. Unknown tiers have missing weights and are excluded from weighted calculations.

Current-profile views calibrate using current rank before conditional audience filters. Historical growth and ranked-activity callers calibrate their eligible observed cohort using **starting rank**, with separate window scopes where required. Always name the calibration cohort and rank basis. Full-profile current-rank diagnostics do not describe every historical analysis.

Helpers preserve scope columns when mapping weights. Ambiguous mappings across scopes raise rather than silently attaching another scope's weight. A shared tier reference applied separately to several scopes still requires a substantive reason to use that target in each; it does not establish a global mixture of those regions or queues.

## Three questions, three estimands

| Method | What it answers | When the tier mix is set |
|---|---|---|
| Collected sample | What was observed among these selected people? | No adjustment; each eligible person contributes equally. |
| Inherited population weights | What is the selected audience's summary after adjusting the original calibration cohort's tier mix? | Calibrate before filtering, then retain each selected person's original weight. |
| Direct-standardized mean | What would selected-cohort tier means average to under a common supported reference mixture? | Select first; calculate valid tier means and mix them using reference shares. |

For inherited weights, a selected-cohort mean is `sum(w_i * y_i) / sum(w_i)` over rows with usable measures and positive valid weights. A category share similarly divides its weighted mass by the selected eligible total. The selected group's rank mix is allowed to differ from the reference: selection is part of the question.

For example, suppose a two-tier reference is 50/50 and the calibration sample has equal counts, so all weights are one. After filtering, five Bronze players remain with mean outcome 2, and ten Diamond players remain with mean 8. The inherited mean is `(5*2 + 10*8) / 15 = 6`. Both tiers pass the default five-observation minimum, so direct standardization gives `.5*2 + .5*8 = 5`. Different results follow from different questions.

Recalibrating weights after filtering would change the inherited-weight estimand. When all relevant support conditions agree, recalibration of the selected cohort can reproduce a directly standardized mean, but it must not be presented as retaining the original population weights.

## Direct standardization and coverage

`direct_standardized_means` operates separately by scope and metric. Within the selected cohort it keeps finite metric values, calculates each tier's count and mean, and retains tiers meeting the default **five valid observations**. Thus two metrics on the same selected rows can have different support.

```text
supported coverage C_m = sum(p_t for metric-supported tiers)
standardized mean     = sum((p_t / C_m) * tier_mean_t)
```

Outputs report selected players, valid metric players, supported tiers and reference coverage. Status is `no_supported_tiers` when no tier passes, `low_coverage` below .99, and `adequate_coverage` at or above .99. A result at low coverage describes the renormalized supported mixture; it does not impute the absent reference mass. These thresholds are current implementation defaults, not universal statistical guarantees.

Standardization is available in analytical tables/downloads. It has no calculated confidence interval. Do not average scope-specific standardized means into a claimed overall population mean without an explicit scope mixture. It is also distinct from the [median-mastery adjustment](metrics-and-methods.md#audience-comparisons), which interpolates a descriptive expected composition at each group's median experience.

## Weight diagnostics and denominators

Kish effective sample size is:

```text
n_eff = (sum(w))^2 / sum(w^2)
```

It describes concentration in the supplied weights. It is neither a population size nor a confidence interval, and it does not account for every source of dependence or sampling bias. Report it with the actual observed count, coverage, calibration cohort and weight range. A full-cohort effective size does not automatically apply to a selected metric with missing outcomes.

`row_weights` uses equal weights when no weight column exists. If a weight column exists, missing, nonfinite or nonpositive entries are invalid rather than silently replaced with one. Callers must also enforce metric eligibility. Categorical summaries retain raw counts alongside weighted mass, shares, percentage-point differences and group-specific effective sizes.

Weighted quantiles use ordinary pandas quantiles when weights are equal. With unequal weights they interpolate at cumulative mass midpoints, `(cumulative_weight - weight/2) / total_weight`. This convention matters when comparing medians with other software.

## Frozen profile example

These values belong to the October 10 serving export and its accepted numeric reference shares, not a promised future release. They use all 37,172 frozen profiles; historical or filtered cohorts require their own diagnostics.

| Tier | Reference share | Observed profiles | Weight |
|---|---:|---:|---:|
| Iron | .0406 | 5,405 | .279387466 |
| Bronze | .1660 | 5,687 | 1.085679014 |
| Silver | .2137 | 5,696 | 1.395439862 |
| Gold | .2353 | 4,998 | 1.751064965 |
| Platinum | .1763 | 4,843 | 1.353986788 |
| Emerald | .1234 | 5,184 | .885373971 |
| Diamond | .0368 | 5,300 | .258254877 |
| Master | .0073 | 59 | 4.602008663 |
| Grandmaster | .0004 | 0 | Unsupported |
| Challenger | .0002 | 0 | Unsupported |

Supported coverage is .9994, full-cohort Kish size is approximately 28,734.54, and the largest-to-smallest tier-weight ratio is approximately 17.82. High aggregate coverage does not remove the sensitivity of a small observed tier. Reproducing these historical values requires that October 10 profile artifact and its reference. The installed manifests now describe later snapshots; applying the same calculation to them produces a new result, not a reproduction of these figures.

## Interpretation and maintenance

The default story retains full-base individual-tier weights through behavioral filtering, including Combine. Purchases uses unweighted scenario customers. Legacy population views use their declared weighted estimator, while the legacy experience explorer retains its sample-based estimator. A dashboard-wide label must not be taken as evidence that every chart uses the same estimator.

Tier weighting cannot correct within-tier selection, division/page selection, refresh behavior, sparse Master collection, complete-profile requirements or selection into observable outcomes. It cannot establish that specialization causes rank improvement or that simulated spending reflects real customers. Reference coverage measures represented target mass, not freedom from bias.

When maintaining the reference, preserve the source capture and its date/scope, validate the ten-tier file, update version/review metadata, and inspect recalculated coverage and weight diagnostics for each relevant cohort. Confirm agreement between reference, export and presentation before replacing dated published numbers. No automatic update or new support/uncertainty policy is implemented by this documentation.
