# Run the dashboard

[Project README](../../README.md) · [Documentation index](../README.md) · [Understanding the analysis](../wiki/understanding-the-analysis.md) · [Run the pipeline](run-the-pipeline.md)

This guide launches the bundled Streamlit dashboard from local Parquet snapshots. You need Python and the dashboard dependencies. Viewing the included result requires no Riot API key, Neon account, Databricks credentials or running SQL warehouse.

The dashboard combines real behavioral observations with a separate **simulated transaction scenario**. Purchase history and spending patterns in that scenario are generated; the profiles supplying its behavioral context come from real observations.

## 1. Prepare the Python environment

Open a terminal in the repository root, the directory containing `streamlit_app` and this project's root `README.md`. Use an existing suitable virtual environment, or create one with:

```sh
python -m venv .venv
```

Create the environment only if it does not already exist. The included dashboard was verified with Python 3.11 in the project environment; the repository does not declare a minimum Python version. Dependency compatibility determines which other versions work.

Install the [dashboard requirements](../../streamlit_app/requirements.txt) using that environment's interpreter. In PowerShell on Windows:

```powershell
.\.venv\Scripts\python.exe -m pip install -r streamlit_app/requirements.txt
```

On a POSIX shell:

```sh
.venv/bin/python -m pip install -r streamlit_app/requirements.txt
```

These explicit interpreter paths avoid depending on shell activation. The root `requirements.txt` belongs to extraction, loading, transformations and development; it is not needed just to view the dashboard.

## 2. Launch the app

From the same repository root, run the application entrypoint. In PowerShell:

```powershell
.\.venv\Scripts\python.exe -m streamlit run streamlit_app/app.py
```

On a POSIX shell:

```sh
.venv/bin/python -m streamlit run streamlit_app/app.py
```

Open the local URL printed by Streamlit. Keep the terminal running while browsing, and press `Ctrl+C` there to stop the server. Launching `app.py` provides the shared navigation and language control; individual page files are not the intended starting point.

## 3. Follow the story, then inspect the data

Start with **The story**. Its current sequence is:

1. **Pipeline and data** — source, pipeline and evidence context.
2. **What transactions would add** — the missing real purchase-data opportunity and the generated-source contract.
3. **Comparing audiences** — paired active-pool/whole-history concentration, rank and activity-band counts, a fixed audience map, and all four historical focus groups in supporting detail.
4. **Specialization and growth** — observed competitive outcomes and their limits.
5. **Champion case studies** — character-audience comparisons.
6. **Findings and limits** — interpretation and boundaries.

**Pipeline and data** is the default landing page. This is the implemented navigation; presentation wording and emphasis are still being finalized.

Use **Explore the data** for a more detailed question:

| Page | Use it to inspect |
|---|---|
| Population | Audience composition, character focus and activity context. |
| Specialization and rank | Focus, rank and window comparisons. |
| Cross-champion | Differences and shared audiences across characters. |
| Champion Explorer | One character's audience in more depth. |
| Population Estimates | Sample/adjusted comparisons, support diagnostics, standardization and downloads. |
| Business sample | Generated spending, simulated tenure, cosmetic acquisition and discounts. |

The **EN / PT** language control supports English and Brazilian Portuguese. **Comparing audiences** also has an independent **Plain language / League terms** control. Both preferences survive story navigation; changing terminology changes wording, not the data. Other pages retain their current terminology while the story revamp continues: champion means character, tier means rank, and mastery is a cumulative activity score. That score is neither hours nor an exact match count.

Page 3 uses 19,722 comparable profiles from the current reference, including the Grandmaster profile. Active-pool and whole-history leading shares both use accumulated mastery weights, with different character-pool denominators. The two main panels share a 0–100% scale. **Show the middle 50% of profiles** displays interquartile ranges around the medians; these are distribution summaries, not confidence intervals. Existing category proportions retain their Wilson intervals in the expandable historical section. Character-type context moves to the later character chapter.

Activity-score boundaries are fixed for the paired snapshot in `data/audience_reference.json`; equal scores stay together. Optional hour-equivalents assume 600 points per match and 30 minutes per match (`score / 1,200`), without claiming observed hours or time to a rank. The ending map uses 10-percentage-point concentration display bins and rank facets. Its view control changes the pool denominator, while the reference cohort, activity bands and color scale stay fixed.

**Activity bands on the horizontal axis** swaps the line-chart orientation: when enabled, four rank-group lines run across the five bands. When disabled, five activity-band lines run across rank groups. The legend and labels follow the selected view; counts, medians, quartiles and support stay the same.

## 4. Read dates and support alongside results

The app reads files under [streamlit_app/data](../../streamlit_app/data). The [manifest](../../streamlit_app/data/manifest.json) records `exported_at_utc`, dataset counts and available analytical dates, plus generated-scenario metadata. An export date and a profile's analytical date have different meanings, and profiles can use older latest-known observations.

The bundled result stays frozen until an operator exports again. Restarting Streamlit, changing a filter or running a warehouse build does not refresh those files. Selective exports can also leave different datasets with different freshness. The [evidence reference](../reference/validation-and-evidence.md#inspectable-serving-snapshot) records the inspected snapshot.

Explorer controls can change the cohort, window and estimator. A filtered weighted audience is different from a directly standardized mean; unsupported outcomes are different from zero outcomes. Use [understanding the analysis](../wiki/understanding-the-analysis.md) for the reading guide and [population adjustment](../reference/population-adjustment.md) for the exact methods. The Business sample's commercial relationships remain fictional under every filter.

## Troubleshoot the local launch

| Symptom | Action |
|---|---|
| Python cannot import `streamlit` or another app dependency | Install the dashboard requirements using the same interpreter path as the launch command. |
| The entrypoint path is not found | Return to the repository root and confirm `streamlit_app/app.py` exists. |
| The server reports an occupied port | Append `--server.port 8502` to the launch command to choose another port. |
| Terminal output raises `UnicodeEncodeError` | Add Python's `-X utf8` before `-m streamlit` in the launch command to enable UTF-8 output. |
| A snapshot is missing, unreadable or lacks required columns | Check the named file against the manifest. Restore a complete compatible snapshot from the repository version being viewed; changing credentials will not repair a local-file contract error. |
| A chart has no usable observations after filtering | Relax the filters or inspect support and eligibility. Missing data need not indicate a broken installation. |

After replacing files with a coherent snapshot, restart the app if needed to clear cached data. [Refresh dashboard data](refresh-dashboard-data.md) describes that separate warehouse/export operation; the [configuration reference](../reference/configuration.md#manual-entrypoints-and-options) identifies its entrypoints. Running the [collection pipeline](run-the-pipeline.md) is optional for a reviewer who only wants to inspect the bundled output.
