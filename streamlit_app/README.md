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
- **Overall Analysis** — playstyle composition, role skew, historical climbing outcomes, and ranked-mastery share by current inferred role, recent starting tier, or favoured champion. Each share cell averages one median per player within the selected rank-period window.
- **Champion Explorer** — champion mastery share versus rank growth, a cycling correlation/slope/R² summary, signed differences for player mix, role, tier/playstyle outcomes, and ranked-mastery share, plus mastery depth and active-pool overlap.

Current mastery views offer an **Active (60 days)** or **All-time** control next to the chart. Historical growth charts use completed rank periods and the starting-tier baseline.
The Overview can filter historical player–tier observations by their median estimated ranked mastery share, an activity proxy calculated from expected ranked mastery divided by total mastery gained during each period. Current-profile comparisons use unadjusted recent LP/game and label the tier as current. The champion comparison has its own support threshold.

On Overall Analysis, minimum tracked days applies only to the current-profile charts. Historical outcome and ranked-activity support thresholds sit beside their respective sections. Historical outcome rows are player–tier–playstyle summaries: an all-tier result is not a count of distinct players.
Growth outcomes exclude rank periods with absolute movement above the configured 50 LP per recorded game; raw period deltas remain in the mart for inspection. The current snapshot preview applies the same bound and defaults to at least two ranked games.

Champion Explorer's difference views use explicit baselines: current playstyle mix versus classified players in the same tier or role; historical playstyle outcomes versus the selected champion's average in the same starting tier; ranked-mastery share versus all observed players in that tier. Role mix uses an equal 20% reference across five roles. Share and win-rate differences are percentage points, while rank-growth differences are LP per game.

## Editorial review and proposed project page

See [dashboard review](docs/dashboard_review.md) for the findings and changes, and [About the project — page proposal](docs/project_page_proposal.md) for a layout, publishable draft, pipeline scope, and optional components. The proposal is documentation only; it does not register a new Streamlit page.

## Test

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest streamlit_app\tests
.\.venv\Scripts\python.exe -m ruff check streamlit_app
```

