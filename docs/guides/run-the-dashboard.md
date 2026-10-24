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

1. **The audience question** — purpose, a genuine audience-map preview, observed traits versus synthetic purchases, and a compact source-to-reporting flow.
2. **Activity and engagement** — accumulated activity versus recorded ranked volume, fixed ranges, optional estimated-hour labels and a retained-history lens.
3. **Rank and activity** — activity shares within Lowest/Medium/High/Highest rank groups, saved reference percentages, ranked-volume and retained-history filters, and axis inversion.
4. **Character interests** - adopted families, primary-label coverage, a selectable affinity/primary map, inferred-type comparisons and optional focus/breadth detail.
5. **Audiences and customers** - synthetic purchaser share, cash per purchaser and customer-versus-cash composition by primary family, with one current audience refinement at a time.
6. **Engineering and evidence** — the source-to-reporting flow, concrete design decisions, current coverage, snapshot dates and verification limits.

**The audience question** is the default landing page. All six chapters implement the audience-first direction. The new views require a matching family-enriched profile export and `audience_segments_reference.json`, described in [refresh dashboard data](refresh-dashboard-data.md). An older bundled package shows an availability note and preserves navigation rather than inventing bands or substituting the narrower paired cohort. The coherent bundled package includes these inputs; restore them together when replacing a snapshot.

Use **Explore the data** for a more detailed question:

| Page | Use it to inspect |
|---|---|
| Population | Audience composition, character focus and activity context. |
| Specialization and rank | Focus, rank and window comparisons. |
| Cross-champion | Differences and shared audiences across characters. |
| Champion Explorer | One character's audience in more depth. |
| Population Estimates | Sample/adjusted comparisons, support diagnostics, standardization and downloads. |
| Business sample | Generated spending, simulated tenure, cosmetic acquisition and discounts. |

The optional **Local laboratory** section appears when its separate local membership export is available. **Character families** provides discovery controls, family naming, stability checks, overlapping assignment review and scenario save/load. **Full Family Sweep** collects alternatives from shared global Leiden ensembles. **Anchored Family Sweep** runs independent character-centered searches in configurable local neighborhoods, with neighborhood rebuilding during player-bootstrap evaluation. **Family cohort builder** compares scenarios and sweep libraries, supports manual family/member selection, character resolution, coverage/overlap diagnostics and separate cohort save/load. See [Explore character families locally](explore-character-families.md) for setup and interpretation. These pages do not change the six story chapters or adopt exploratory groups as a taxonomy.

The **EN / PT** language control supports English and Brazilian Portuguese. All six story pages also have an independent **Plain language / League terms** control. Both preferences survive story navigation; changing terminology changes wording, not the data. Explorer pages retain their current terminology: champion means character, tier means rank, and mastery is a cumulative activity score. That score is neither hours nor an exact match count.

Page 1 previews an audience map and explains the route from observed behavior to reporting. Page 2 contrasts accumulated activity with recorded ranked volume on the complete profile base. Missing family, type or focus evidence does not remove players. Bands and individual-tier weights are frozen before filtering; counts and support belong in methods and hovers rather than headline audience-size claims.

Page 3 answers **P(activity band | rank group)** within any selected ranked-volume/history lens. Each rank group's shares total 100% before sparse cells are hidden. The 0–100% color scale and underlying score cuts stay fixed. **Put rank groups across the chart** transposes the same estimates; it does not change their denominator. The methods expander offers chart data, aggregate CSV, individual-tier support and the actual selected-audience rank mix when filters apply.

Rank labels retain the saved October 10, 2026 NA solo/duo reference: Lowest 42.03% (Iron–Silver), Medium 41.16% (Gold–Platinum), High 12.34% (Emerald), Highest 4.47% (Diamond–Challenger). The reference is attributed to [OP.GG tier statistics](https://op.gg/lol/statistics/tiers); it is distinct from the filtered audience's composition. Challenger's 0.02% has no observations; the Highest group's observed behavior covers 4.45 reference percentage points, including sparsely observed Grandmaster. These are cross-sectional comparisons, not evidence of climbing speed or a specialization effect.

Optional hour equivalents use mastery / 1,200, assuming 600 points per match and 30 minutes per match. This changes labels, not band membership, and does not measure actual hours. The optional retained-history marker is a lower bound from positive-mastery champion last-play timestamps, not account creation or tracking duration. See [audience segments](../reference/audience-segments.md) for the exact cuts, denominator and suppression contracts.

Page 4 uses the frozen 25-family definition rather than a leading-character surrogate. The overview shows five primary families, Other families, Shared top and missing-evidence states. **Choose a character family** searches all families by ID and character examples, then shows its actual members. The map defaults to **Mean affinity** among scored pools; **Primary share** instead uses everyone in a cell, including tied and missing states. Each tile exposes scoring coverage and its own support in the hover. The original activity/rank geometry, tier weights and engagement/history filters remain fixed.

The inferred-type comparison shows the selected unique-primary audience versus all unique-primary audiences. Plain wording uses A-E; League wording uses Top/Jungle/Middle/Bottom/Support. Both views disclose known-type coverage. The profile adds supported medians of activity, ranked games, top affinity and the top-versus-next gap, with rank context. No minimum gap forces a different assignment. The collapsed optional lens starts Off and offers all four whole-history focus classes or scored-pool/positive-family breadth. Positive-family breadth overlaps and does not count independent interests; character counts inside a family are unavailable in the exported rows. Methods include complete tables and aggregate CSV downloads. See [audience segments](../reference/audience-segments.md) and the [family definition](../reference/character-family-cohort.md).

Page 5 keeps the existing synthetic purchase scenario and uses the already attached current audience fields. It starts with three complementary family charts: purchaser share (including nonbuyers), cash per purchaser and profile share versus cash share. Ordering uses the six largest primary families in the complete scenario before filters, with Other families, Shared top and missing-evidence states retained. **Refine the scenario audience** chooses one activity, ranked-volume, rank or inferred-type range at a time. These use the same fixed behavioral definitions as the earlier chapters, without applying gameplay population weights to customer cash.

The purchase window and original frozen profile date remain separate from the later current-audience cutoff. Current families are not historical purchase preferences or predictors. A prominent simulation marker, chart captions and the provenance expander explain the editable generator assumptions and cash-counted-once rule. Cash is summed in integer cents. Displayed purchaser shares require 30 profiles, and cash per purchaser requires 30 purchasers; zero purchasers leave the latter undefined. Sparse values stay in denominators and raw aggregate downloads. The methods expander provides the complete selected family summary and CSV. See [synthetic transactions](../wiki/simulated-transactions.md) for the source and interpretation contract.

Page 6 connects API/task state, Bronze/Silver/Gold, private audience export and local reporting. Expand individual decisions for their maintained public contracts, or inspect the manifest inventory and coverage boundaries. The competitive-growth extracts remain separate explorer evidence rather than a causal conclusion to the audience story.

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
