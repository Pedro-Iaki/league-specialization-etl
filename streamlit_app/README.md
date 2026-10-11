# League Specialization Dashboard

A Streamlit dashboard built on the `league_pipeline.gold` dbt marts. It explores the association between champion-pool specialization and LP/game above a starting-tier baseline.

The default **Business Sample** opening page adds a small purchase reporting example. Purchases, spending patterns, ownership and customer types are synthetic; player traits come from a frozen real Riot API cohort. A prominent link leads into the real gameplay pages. No scenario relationship is presented as a real customer finding.

The app uses identifier-free Parquet snapshots by default; a public deployment is planned. Player identifiers and rank-interval identifiers are excluded from every exported dataset. An optional Databricks mode runs the same fixed, read-only queries against the live gold schema.

## Run with the included snapshot

```powershell
cd streamlit_app
..\.venv\Scripts\python.exe -m streamlit run app.py
```

Install the focused app dependencies first when needed:

```powershell
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

After updating a running dashboard, rerun or refresh the page. The app shell detects an older cached business-helper API (for example, one missing `CASH_DISCOUNT_COLUMNS`) and reloads that helper and its dependent query/data/chart/UI modules before importing the page. Current modules are left alone. If the server does not pick up source changes, stop it with Ctrl+C and start it again using the command above.

## Refresh the snapshot

The exporter reads the existing ignored `config/DATABRICKS_CONFIG.env` through the project's Databricks helper.

```powershell
cd streamlit_app
..\.venv\Scripts\python.exe scripts\export_data.py
```

For a single extract, pass `--dataset champion_tier_mastery`. The exporter preserves the other manifest entries and refreshes only that Parquet file.

For the business branch, first follow the [generation/load/tagged-build workflow](../README.md#generate-the-business-sample), then run `python scripts/export_data.py --dataset business_players` here. Its explicit column allowlist excludes player, event and SKU IDs. Metadata records scenario ID, seed/version, cohort/config fingerprints, frozen profile date, generated history range, recent window, counts and synthetic provenance. The exporter checks raw completion and Gold reconciliation before writing. A failed load or stale mart blocks this export; older snapshots without it still open the real gameplay pages. A full export skips the business dataset if its warehouse tables have never been created.

The included business snapshot was refreshed from the successfully built sample Gold mart on 2026-10-09: **24,990 players with complete core context**, 42 columns, 2,117,210 bytes. The three added columns summarize recent fiat-only discounts. It includes every eligible current ranked profile, without a row cap. Ranked share and recent games/day are optional; observed values are retained for 1,066 and 1,074 players, and missing values remain null. Actual profile dates span 2026-09-16 through 2026-09-29, frozen as of 2026-09-29, and the recent synthetic window is 2026-08-01 through 2026-09-29. The existing gameplay files and their dataset manifest entries were preserved. Snapshot and live mode both label spending as synthetic; live scenario metadata comes from the matching warehouse completion marker, not the local snapshot manifest.

The business page now implements four question-led comparisons:

| Question | View and denominator |
|---|---|
| How does spending vary across player traits? | Audience bubble map grouped by one selected trait: tier, role, playstyle, simulated account age or estimated total playtime. Share uses all players; USD per purchaser uses recent cash purchasers. Bubble size is audience size; zero-purchaser groups have an undefined conditional mean. Account-age bands use time since the first generated purchase. Relative playtime bands use cumulative mastery sum as a proxy, without converting it into hours; ties reduce the number of quantile bands. Plot labels and hovers call this estimated total playtime, with the calculation explained separately in a methodology expander. |
| Does spending vary with experience within comparable simulated tenure? | Recent USD/player, USD/cash purchaser or purchaser share over mastery quantile bands on a log axis, split by simulated tenure. Mastery is experience, not hours; tenure is derived from first fictional purchase. |
| Does pool concentration relate to cosmetic preference? | Top-one share or entropy versus mean player cosmetic share, grouped by playstyle. Each player receives equal weight. Shading shows the middle 50% of player shares, not uncertainty; cash top-ups are excluded from content mix. |
| Which audiences use cash discounts more often and how deep are they? | Recent discounted fiat-event share versus event-weighted mean conditional discount, by role, tier or playstyle. Size counts cash purchasers. RP/BE discounts are excluded; usage does not establish effectiveness or price sensitivity. |

Tier and inferred-role filters apply to all four business views. Champion-level comparisons and filters have been removed from the business page; the existing real gameplay pages retain their champion analyses. The default support minimum is three players; per-purchaser and conditional-discount outcomes additionally require their corresponding purchaser support. Sparse groups keep counts in hovers/support tables and can be revealed with the existing Show omitted control. Lines break at omitted groups. Every chart labels spending/patterns synthetic and player traits real; account age is explicitly simulated. Ranked-focus cadence remains a possible fifth view for the observed ranked-share subset; none of the four current views needs either optional period field. Older business snapshots without cash-discount columns still show the first three views with an availability notice.

To refresh only the spending-mart change and its reconciliation tests, run from `league_pipeline`: `dbt build --select mart_player_spending assert_business_sample_reconciles`, then run the business-only exporter above. The 2026-10-09 focused build passed all five resources (one table and four tests); live mode rendered all four charts against the matching warehouse scenario.

The optional `champion_player_mastery_share` extract powers the Cross Champion View mastery-share boxes. It contains one row per player and champion with at least 15K champion mastery points, with tier and mastery ratios but no player identifier. When absent from a snapshot, that chart explains which extract is needed.

Build the growth marts before refreshing the export. Each Parquet file is replaced atomically in `data/`, followed by a manifest recording row counts, file sizes, date coverage, and export time. The included snapshot contains historical growth extracts. Older snapshots without those extracts remain supported: the app identifies unavailable views and labels older champion estimates explicitly.

## Optional live mode

Set the data mode before starting Streamlit:

```powershell
$env:LEAGUE_DASHBOARD_DATA_MODE = "databricks"
..\.venv\Scripts\python.exe -m streamlit run app.py
```

Snapshot mode remains the recommended public deployment because it starts quickly, does not expose warehouse credentials, and does not depend on SQL warehouse availability.

## Language selection and translation catalogs

The **EN / PT** selector sits at the top of the dashboard. English is the default; PT uses Brazilian Portuguese. The choice persists across page navigation for the current session. All six pages use the shared catalogs for navigation, copy, controls, chart labels and table headings; strings not yet cataloged fall back to English. The switch preserves canonical filter values and numerical data; amounts remain USD.

Translations are centralized in [locales/en.json](locales/en.json) and [locales/pt.json](locales/pt.json). English source messages are stable keys; edit their values to change displayed copy without changing the internal choices used by filters. Add the same key to both catalogs. For dynamic sentences, keep the `{p0}`, `{p1}` placeholders intact; Plotly tokens such as `%{y:.1%}` must also remain unchanged. `_formats.long_date` controls the profile freshness date. Missing translations fall back to the English catalog, and catalog edits are reloaded on the next app rerun.

The explicit rendering adapter in [app_core/i18n.py](app_core/i18n.py) is imported as `st` by the pages and shared UI helpers. It delegates non-display operations to Streamlit, formats widget choices without translating their return values, and creates presentation copies of tables and Plotly figures. It does not patch Streamlit globally or translate cached datasets. Use stable explicit widget keys for persistent controls. For new standalone copy, `t(key, **parameters)` is also available. Champion names, model identifiers and technical version/patch strings stay unchanged.

Localization checks validate matching catalog keys and placeholders, unchanged numeric chart/table values, rendering of every page in PT, and EN→PT→EN switching with filter and navigation persistence:

```powershell
python -m pytest streamlit_app/tests/test_i18n.py
```

## Pages

- **Business Sample** — default opening: audience monetization, experience/tenure, cosmetic preference and fiat discount use. Shared audience filters, outcome/group selectors and support counts guide the four comparisons. USD comes from fiat events only. Every plot labels the synthetic patterns and real traits. First simulated purchase supplies the tenure proxy; it is not real account age. The project/author introduction and architecture explain the separate synthetic branch.

- **Overview** — the player-level specialization and growth relationship, plus the champion landscape. The historical charts use completed rank periods; current-pool previews are labeled separately.
- **Population Analysis** — playstyle composition, role skew, and ranked-mastery share by current inferred role, recent starting tier, or favoured champion. The denominator selector switches between the frozen tier estimate and equal player weights. Ranked-activity cells average one median per player within the selected observed window, using starting-tier weights in estimate mode.
- **Population Estimates** — analyst workspace comparing sample/weighted shares, means and medians. It retains every available profile tier, reports reference coverage/effective sample size, preserves weights through filters, and downloads diagnostics, reference, tables and anonymous weighted profiles.
- **Champion Explorer** — champion mastery share versus rank growth, a cycling correlation/slope/R² summary, signed differences for player mix, role, tier/playstyle outcomes, and ranked-mastery share, plus mastery depth and active-pool overlap.
- **Cross Champion View** — cross-champion rankings for outcomes, expert share, active play rate, mastery depth above 15K points, rank score, ranked share, and conditional active-pool overlap. A full-width champion outcome comparison sits above tier box plots of player-level champion mastery share when the optional extract is available. Its tier curves compare each champion's distribution of total mastery points across tiers with the sample's distribution, so a champion's overall mastery level does not shift its whole line upward.

Population Analysis includes observed cell counts and, only in collected-sample mode, Wilson interval widths for playstyle composition, active or lifetime pool distributions, log-scaled cumulative mastery by tier, and playstyle share across mastery bands. Its experience-stratified view uses five pooled equal-count bands, grouped tiers, raw all-time specialist shares and Wilson intervals in both denominator modes. Panels are the default; lines and Master exclusion are visible options. It shares the minimum-players-per-cell slider with ranked activity. Overview shows rank outcomes by observed playstyle. Champion Explorer adds a tier representation curve against the selected player baseline, primary-player rank-score summaries, player-count cards that start as percentages, and champion mastery by tier. Its mastery cards compare with the equal-weight average champion at the selected mastery threshold. The expert line can show percentage difference from the pooled expert share among champion mastery holders in each tier. Its player-mix comparison can use tier, 200-point rank-score bands, or inferred role. The refreshed `champion_tier_mastery.parquet` extract supports 0–90K mastery thresholds in 10K steps, a 15K mastery baseline for mean and median cards, and all-tier aggregates.

Overview, Population Analysis, Champion Explorer and Cross Champion View share the population/sample denominator selector. Population mode keeps the unfiltered cohort's weights through filters and uses weighted pooled means, medians, associations, mastery and primary-player summaries, ladder distributions and player box quartiles. Historical pooling estimates represented player–tier observations with completed periods; it does not correct selection into those periods. Anonymous tier-preserving activity and pair exports enable population active-play rates, role mixes and overlap probabilities. Counts and support thresholds remain observed. The experience-stratified view and synthetic Business Sample retain their requested sample definitions. See [population weighting](../docs/population_weighting.md) for the mart export, fallback formula and missing-export behavior.

The original gameplay views display tiers through Master in tier-specific views. Population Estimates and its CLI bundle retain all tiers available in the profile input. The business sample keeps every frozen player, including any higher-tier players, in its denominator. Champion-wide aggregate marts in older snapshots may still include players from higher tiers; excluding them from every gameplay aggregate requires rebuilding those marts and exporting a new snapshot.

Estimated ranked-mastery share uses players with completed ranked observation periods. Players who mainly play other modes are underrepresented, and Ranked Flex is not covered by the recorded queue. Treat this measure as a selected-cohort estimate rather than the population's ranked-play share.

Current mastery views offer an **Active (60 days)** or **All-time** control next to the chart. Historical growth charts use completed rank periods and the starting-tier baseline.

Population structure also offers **Active and observed**: active profiles restricted to players with a nonmissing recent LP delta, including positive, zero, and negative changes. Its normalization baseline uses that same observed cohort.

Population structure can normalize each observed playstyle share by the expected share at the tier or role's median total mastery. The baseline pools the selected classified players into sample-defined equal-frequency mastery bands and interpolates their playstyle shares at each group median. In estimate mode, shares and median centers use population weights. Ratios use a reference of 1; zero expected shares are undefined. This adjusts for median mastery, not the group's full mastery distribution. The support table retains observed counts, raw shares, relative weighted mass and effective group size; Wilson interval widths apply only in collected-sample mode.

The observed-climber plot includes players with positive net `lp_delta_recent` and positive `games_recent` in the latest completed observation period. Each classified player counts once, using the selected current active or lifetime playstyle and current tier or role. The tracked-days and minimum-total-mastery filters apply. Its independent normalization toggle uses the full selected population's mastery bands, evaluated at each climber group's median total mastery, with 1 indicating the expected playstyle share. Mastery and playstyle uses median total mastery on a log axis.

Below Ladder curves, Cross Champion View compares concentrated active mains with each champion's general tier distribution. Defaults are the same five champions, at least 300K total account mastery, and active main share ≥80% or active HHI ≥0.65; all thresholds and the concentration rule are configurable. Tier shares overlay the two player distributions; relative representation divides the one-trick tier share by the champion-holder tier share, with 1 indicating agreement. The baseline uses player counts at the zero champion-mastery threshold, includes one-tricks, and applies no concentration or account-mastery filter. Low-support points leave gaps without changing denominators. These are current ladder positions, not longitudinal career outcomes.
For players tracked less than 30 days, the active-pool model falls back to last-play recency without requiring the usual mastery-gain threshold. A one-off pick from another mode can therefore enter an active pool, especially in this short-history snapshot. See the [project README](../README.md) and [model reference](../league_pipeline/docs/model_reference.md) for the research design and exact rule.
The Overview defaults to the **Active (60 days)** specialization window. Its observed-period view filters to at least **35% estimated ranked share**, an activity proxy calculated from expected ranked mastery divided by total mastery gained during each period. Current-profile comparisons use unadjusted recent LP/game. The champion comparison on Cross Champion View has its own support threshold.

On Population Analysis, minimum tracked days applies only to the current-profile charts. The ranked-activity support threshold sits beside its section. Historical outcome rows on Overview are player–tier–playstyle summaries: an all-tier result is not a count of distinct players.
Growth outcomes exclude rank periods with absolute movement above the configured 50 LP per recorded game; raw period deltas remain in the mart for inspection. The current snapshot preview applies the same bound and defaults to at least two ranked games.

Champion Explorer's difference views use explicit baselines: current playstyle mix versus classified players in the same tier or role; historical playstyle outcomes versus the selected champion's average in the same starting tier; ranked-mastery share versus all observed players in that tier. Its role chart averages inferred player-role mixes among people who recently played the selected champion. It does **not** measure which lane the champion was played in; the equal 20% reference is a visual reference across five roles, not a population baseline. Share and win-rate differences are percentage points, while rank-growth differences are LP per game.

The dashboard uses a shared default minimum of **three players or player–tier observations per displayed group**. Support controls can raise or lower the threshold. Sparse heatmap cells are marked `n<3`; entirely unsupported groups are marked `—`. A measured zero remains zero when its parent group has sufficient support. Grouped bars and champion points below the threshold are omitted with an on-page warning. Counts appear in the relevant chart labels or hovers. Co-occurrence pairs have an upstream minimum of five shared players.

When a low-support result is available but hidden, the warning has a **Show omitted** button. It reveals that section's results with count labels or hovers; heatmaps additionally mark low-count cells with ⚠. **Hide omitted** restores the threshold. The button cannot recover records that were never exported or pairs excluded by the upstream co-occurrence model.

The scatter plots retain the mean within concentration bands. Bands with fewer than three observations are omitted from that line and flagged. An optional **smoothed local median** trace uses overlapping neighborhoods containing about 30% of the plotted observations, then smooths adjacent medians. It resists isolated extreme outcomes and is hidden in Plotly's legend by default. Neither trend line is a prediction or a confidence interval.

## Test

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest streamlit_app\tests
.\.venv\Scripts\python.exe -m ruff check streamlit_app
```

## Population weighting and analyst downloads

**Population Estimates** compares the anonymous profile sample with a frozen,
manually maintained ten-tier reference. It exposes reference version, supported
population coverage, effective sample size, filters and analyst downloads.
**Population Analysis** applies the same denominator choice to its player
composition analyses. Other pages' pooled aggregates retain sample definitions.

From the repository root, run
`python streamlit_app/scripts/export_population_estimates.py` to produce an
anonymous Parquet/CSV ZIP under `data/population_estimates/` without connecting
to Databricks. See [population weighting](../docs/population_weighting.md) for
the weighting formula, cohort definitions and manual reference updates.

The seed is loaded and validated on each dashboard rerun, so an invalid manual
reference blocks population estimates rather than silently producing new
weights. The denominator preference persists between the two population pages.
Profile weights are calibrated before tracked-days/mastery/role/champion/style
filters. Unsupported or invalid weights are excluded before both statistics and
support counts; collected-sample mode uses all otherwise eligible rows equally.

The archive contains only explicitly generated files, with an exact file list
and both snapshot and canonical reference hashes in its manifest. The warehouse
mart is a live view; source refreshes change weights under the same reference.
This CLI bundle freezes one snapshot and its reference together.

| Component | Behavior under the denominator selector |
|---|---|
| Role composition and skew | Weighted shares/role baseline in estimate mode |
| Mastery composition and normalization | Sample-defined bands, weighted shares and median centers |
| Climber composition | Original profile weights retained after selecting observed climbers |
| Active/lifetime cross-classification | Weighted row shares; support counts remain eligible observed players |
| Ranked activity | Starting-tier calibration for the selected observed window, before champion expansion/filtering |
| Tier box plots | Within-tier descriptions; in the current single-scope sample, tier weights cancel |
| Other pages and synthetic business views | Existing sample aggregates, explicitly labeled; no population correction implied |

The current snapshot represents 99.94% of the supplied reference's tier mass,
not 99.94% of all real players. It has no Grandmaster/Challenger observations.
Weights do not correct within-tier selection, including the selected Master
climbers, or selection into completed rank periods. Effective sample size is a
weight-dispersion diagnostic; no weighted confidence intervals are claimed.
See the [model reference](../league_pipeline/docs/model_reference.md#mart_player_population_weights)
for warehouse grain, join keys and SQL column definitions.

