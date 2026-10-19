# Population weighting

The dashboard and analyst export read
[`rank_population_reference.csv`](../league_pipeline/seeds/rank_population_reference.csv)
directly. The current estimate is `2026-10-10-v1`, received on 2026-10-10, with
review due after 2027-04-10. Its observation date, region and queue were not
supplied. It is an assumed distribution, not a verified regional ladder census.

## Relative tier weights

The shared Python helpers in `app_core.population` calculate weights for the
unfiltered calibration cohort within each region/queue scope. Cached weight
values are recalculated using the current CSV. No weight or standardization
mart is required. The optional dbt reference seed and its tests remain available.

For tier `t`, let `n_t` be its collected count, `N` the count in supported tiers,
`p_t` the reference share and `C` the reference share covered by represented
tiers. Each represented player gets weight `(p_t / C) / (n_t / N)`. Weights
average one across supported players. Within one tier and scope they cancel.

Calculate these weights before conditional subgroup filters, then retain them
for champion, role or style comparisons. A mean is `sum(w * x) / sum(w)` over
valid metrics and weights. A share divides matching weighted mass by eligible
weighted mass. Neither weighted mass nor a player's weight is a population count.

Unknown tiers receive null weights and are excluded from population estimates.
The reference must have one row per tier, all ten tiers, positive finite shares
summing to one and consistent version/provenance fields. The Python loader and
retained reference-seed tests enforce these conditions.

## Direct standardization

This answers a separate question: what would selected groups' metric means look
like at the same tier mix? Calculate each selected tier's mean, then combine it:

`sum(reference_share * tier_mean) / sum(supported_reference_share)`.

The Python helper requires five valid metric observations per tier by default.
It reports tier counts, missing tiers and covered reference share. Coverage
below 99% is flagged; these are reporting defaults, not statistical guarantees.
Support is metric-specific. Unsupported tiers receive no invented values, and
no supported tiers produces a null estimate.

This does not establish outcomes for unobserved players. Forcing a subgroup's
composition to the full ladder is not an estimate of its population prevalence.

## Dashboard and analyst exports

Population mode adjusts pooled plots using the frozen reference; collected-sample
mode remains available. Counts and minimum-support controls are actual collected
counts. Historical growth uses one player/champion/starting-tier observation,
optionally grouped by observed style; a player can appear in several such rows.
The saved tier/style SQL derives each grouping from periods, rather than merging
subgroup medians. Dashboard windows and defaults are unchanged in this pass.

Run the manual dashboard exporter after building the retained dbt models:

```powershell
python streamlit_app/scripts/export_data.py
```

It overwrites ordinary Parquet files and updates the existing manifest. The
optional anonymous analyst bundle is created with:

```powershell
python streamlit_app/scripts/export_population_estimates.py
```

It writes `data/population_estimates/`: weighted profiles, the exact reference,
diagnostics, metric/category comparisons, standardized means and a ZIP with an
analyst guide. This generated output is not an input to dbt or ingestion.

## Interpretation and maintenance

Tier weighting does not correct division/page-order selection, dropped profiles,
selected Master climbers or selection into ranked observation. The reference has
no division shares; region/queue proportions remain those of the sample. Role,
style and ranked-mastery share are inferred measures.

Report metric-specific support, reference coverage and effective sample size.
Effective size describes weight dispersion, not reference uncertainty or proof
of representativeness. Historical bundled-snapshot counts remain descriptions
of that export; they do not establish a new warehouse build.

Update shares, version, receipt/review dates and provenance together when a
better estimate arrives. Keep one active reference in the CSV and prior versions
in Git. Re-export the dashboard and analyst bundle after a change. The dashboard
warns when review is due; it does not fetch or replace the reference automatically.
