# League Specialization Dashboard

A Streamlit dashboard built on the `league_pipeline.gold` dbt marts. It explores the association between champion-pool specialization and LP/game above a starting-tier baseline.

The public app uses anonymized Parquet snapshots by default. Player identifiers and rank-interval identifiers are excluded from every exported dataset. An optional Databricks mode runs the same fixed, read-only queries against the live gold schema.

## Run with the included snapshot

```powershell
cd streamlit_app
..\.venv\Scripts\python.exe -m streamlit run app.py
```

Install the focused app dependencies first when needed:

```powershell
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Refresh the snapshot

The exporter reads the existing ignored `config/DATABRICKS_CONFIG.env` through the project's Databricks helper.

```powershell
cd streamlit_app
..\.venv\Scripts\python.exe scripts\export_data.py
```

For a single extract, pass `--dataset champion_tier_mastery`. The exporter preserves the other manifest entries and refreshes only that Parquet file.

The optional `champion_player_mastery_share` extract powers the Cross Champion View mastery-share boxes. It contains one row per player and champion with at least 15K champion mastery points, with tier and mastery ratios but no player identifier. When absent from a snapshot, that chart explains which extract is needed.

Build the growth marts before refreshing the export. Each Parquet file is replaced atomically in `data/`, followed by a manifest recording row counts, file sizes, date coverage, and export time. The included snapshot contains historical growth extracts. Older snapshots without those extracts remain supported: the app identifies unavailable views and labels older champion estimates explicitly.

## Optional live mode

Set the data mode before starting Streamlit:

```powershell
$env:LEAGUE_DASHBOARD_DATA_MODE = "databricks"
..\.venv\Scripts\python.exe -m streamlit run app.py
```

Snapshot mode remains the recommended public deployment because it starts quickly, does not expose warehouse credentials, and does not depend on SQL warehouse availability.

## Pages

- **Overview** — the player-level specialization and growth relationship, plus the champion landscape. The historical charts use completed rank periods; current-pool previews are labeled separately.
- **Population Analysis** — playstyle composition, role skew, and ranked-mastery share by current inferred role, recent starting tier, or favoured champion. Each share cell averages one median per player within the selected rank-period window.
- **Champion Explorer** — champion mastery share versus rank growth, a cycling correlation/slope/R² summary, signed differences for player mix, role, tier/playstyle outcomes, and ranked-mastery share, plus mastery depth and active-pool overlap.
- **Cross Champion View** — cross-champion rankings for outcomes, expert share, active play rate, mastery depth above 15K points, rank score, ranked share, and conditional active-pool overlap. A full-width champion outcome comparison sits above tier box plots of player-level champion mastery share when the optional extract is available. Its tier curves compare each champion's distribution of total mastery points across tiers with the sample's distribution, so a champion's overall mastery level does not shift its whole line upward.

Population Analysis includes Wilson interval widths and cell counts for playstyle composition, active or lifetime pool distributions, log-scaled cumulative mastery by tier, and playstyle share across mastery bands. Overview shows rank outcomes by observed playstyle. Champion Explorer adds a tier representation curve against the tracked player baseline, primary-player rank-score summaries, player-count cards that start as percentages, and champion mastery by tier. Its mastery cards compare with the equal-weight average champion at the selected mastery threshold. The expert line can show percentage difference from the pooled expert share among champion mastery holders in each tier. Its player-mix comparison can use tier, 200-point rank-score bands, or inferred role. The refreshed `champion_tier_mastery.parquet` extract supports 0–90K mastery thresholds in 10K steps, a 15K mastery baseline for mean and median cards, and all-tier aggregates.

The dashboard displays tiers through Master in tier-specific views. Champion-wide aggregate marts in older snapshots may still include players from higher tiers; excluding them from every aggregate requires rebuilding those marts and exporting a new snapshot.

Estimated ranked-mastery share uses players with completed ranked observation periods. Players who mainly play other modes are underrepresented, and Ranked Flex is not covered by the recorded queue. Treat this measure as a selected-cohort estimate rather than the population's ranked-play share.

Current mastery views offer an **Active (60 days)** or **All-time** control next to the chart. Historical growth charts use completed rank periods and the starting-tier baseline.
The Overview defaults to the **Active (60 days)** specialization window. Its observed-period view filters to at least **35% estimated ranked share**, an activity proxy calculated from expected ranked mastery divided by total mastery gained during each period. Current-profile comparisons use unadjusted recent LP/game. The champion comparison on Cross Champion View has its own support threshold.

On Population Analysis, minimum tracked days applies only to the current-profile charts. The ranked-activity support threshold sits beside its section. Historical outcome rows on Overview are player–tier–playstyle summaries: an all-tier result is not a count of distinct players.
Growth outcomes exclude rank periods with absolute movement above the configured 50 LP per recorded game; raw period deltas remain in the mart for inspection. The current snapshot preview applies the same bound and defaults to at least two ranked games.

Champion Explorer's difference views use explicit baselines: current playstyle mix versus classified players in the same tier or role; historical playstyle outcomes versus the selected champion's average in the same starting tier; ranked-mastery share versus all observed players in that tier. Role mix uses an equal 20% reference across five roles. Share and win-rate differences are percentage points, while rank-growth differences are LP per game.

The dashboard uses a shared default minimum of **three players or player–tier observations per displayed group**. Support controls can raise or lower the threshold. Sparse heatmap cells are marked `n<3`; entirely unsupported groups are marked `—`. A measured zero remains zero when its parent group has sufficient support. Grouped bars and champion points below the threshold are omitted with an on-page warning. Counts appear in the relevant chart labels or hovers. Co-occurrence pairs have an upstream minimum of five shared players.

When a low-support result is available but hidden, the warning has a **Show omitted** button. It reveals that section's results with count labels or hovers; heatmaps additionally mark low-count cells with ⚠. **Hide omitted** restores the threshold. The button cannot recover records that were never exported or pairs excluded by the upstream co-occurrence model.

The scatter plots retain the mean within concentration bands. Bands with fewer than three observations are omitted from that line and flagged. An optional **smoothed local median** trace uses overlapping neighborhoods containing about 30% of the plotted observations, then smooths adjacent medians. It resists isolated extreme outcomes and is hidden in Plotly's legend by default. Neither trend line is a prediction or a confidence interval.

## Editorial review and proposed project page

See [dashboard review](docs/dashboard_review.md) for the findings and changes, and [About the project — page proposal](docs/project_page_proposal.md) for a layout, publishable draft, pipeline scope, and optional components. The proposal is documentation only; it does not register a new Streamlit page.

## Test

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest streamlit_app\tests
.\.venv\Scripts\python.exe -m ruff check streamlit_app
```

