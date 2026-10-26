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

Open the local URL printed by Streamlit. Keep the terminal running while browsing, and press `Ctrl+C` there to stop the server. Launching `app.py` opens the new seven-chapter story. Its approved controls and diagrams run in a bundled Streamlit component; Python handles the audience queries through Streamlit. No separate sandbox HTTP server, Node build, warehouse connection or credentials are needed.

## 3. Follow the story

1. **Purpose** introduces the observed behavior, interpreted audiences and simulated purchases.
2. **Activity** distinguishes accumulated play, competitive frequency and retained history.
3. **Standing** adds competitive context and the saved reference distribution.
4. **Interests** compares the eight frozen player-pool archetypes and their mixtures, with underlying family evidence available to inspect.
5. **Combine** constructs shared conditions and independent A/B audiences. Horizontal bars and the archetype grid allow multiple selections; dropdowns cover expression, evidence and inferred role. Collapsing a section keeps its filters active.
6. **Purchases** applies the same audience predicates to already-associated simulated customer rows. It shows purchaser participation, cash per purchaser, purchase frequency and the cosmetic share of content purchases.
7. **Engineering** links the architecture, design decisions, saved family diagnostics and separate recorded execution timelines to their sources.

The question dropdown opens two comparison cards in place of the overview. Guided adjustments keep their shared parent context. Ordinary chapter changes reset the question; moving from Combine directly to Purchases carries the **last applied** definition. Builder edits remain pending until **Apply comparison**. Multiple choices within a field use OR; fields and shared conditions use AND. Empty selections are unrestricted, including unavailable values. A/B may overlap; the intersection is reported explicitly.

**Linguagem simples / Termos precisos** (Plain language / Precise terms) changes labels while preserving selections. The story opens in Brazilian Portuguese. Use **Idioma / Language**, beside the terminology selector, to switch between **Português (BR)** and **English**. Switching preserves the current question, applied audience, pending edits and open details. Numbers and dates follow the selected locale; monetary amounts remain USD. The [translation guide](../../streamlit_app/story_component/locales/README.md) covers catalog maintenance. Linked source documentation and downloaded diagnostic evidence retain their original language. Legacy language controls are unchanged.

Activity and standing charts, maps and builder bars hide categories that contain
no profiles in either complete behavioral or customer population. The displayed
categories stay fixed when filtering; a future snapshot automatically restores
populated zero/unknown categories. Internal states and denominators are retained.

The approved layout is maintained in [story_component](../../streamlit_app/story_component). [story_query.py](../../streamlit_app/app_core/story_query.py) owns the canonical predicates, original population weights, support checks, summaries and integer-cent customer reporting. Streamlit sends only aggregate summaries and sanitized evidence to the component. All profiles remain in Python memory.

The [dashboard story contract](../reference/dashboard-story.md) documents chapter
responsibilities, exact guided parents, builder semantics and chart denominators.

### Keep using the previous interface

The original story, analytical explorers and optional local laboratories remain runnable:

```powershell
.\.venv\Scripts\python.exe -m streamlit run streamlit_app/legacy_app.py --server.port 8502
```

This preserves the previous six chapters, EN/PT controls and explorer pages. It reads the original `streamlit_app/data` package. The new default story independently reads `streamlit_app/data/story`; switching the entry point does not replace the legacy files or trigger an export.

### Evidence preparation and verification

The story ships sanitized saved family matrices, frozen component explanations, threshold tradeoffs and two separate execution summaries. Viewing these needs no local research archives or run databases. Maintainers with those source archives can reproduce the publication offline:

```powershell
.\.venv\Scripts\python.exe streamlit_app/scripts/prepare_story_evidence.py
```

This script verifies source hashes and numerical diagnostics before writing `story_component/public-evidence.json` and its publication manifest. It does not run during rendering or discover/refit families. Do not copy raw logs or the archived ledger into component assets.

Focused analytical and host checks:

```powershell
.\.venv\Scripts\python.exe -m pytest streamlit_app/tests/test_story_query.py streamlit_app/tests/test_story_host.py -q
```

For the real-browser regression sweep, run the new app on port 8510 and Edge with its existing debugging endpoint at `127.0.0.1:9251`, then run `streamlit_app/tests/browser_story.py`. This checks the actual Streamlit component, not the sandbox viewer. Local reports/screenshots go under the ignored `sandbox/streamlit_story_validation.tmp` directory. Browser verification uses the existing development environment; browser tooling is not a dashboard runtime dependency.

Run `streamlit_app/tests/browser_story_localization.py --published` for actual
Portuguese layout and language-switch state checks, and `browser_scroll.py` in
the same tests directory for physical scrolling and navigation reset. Run browser
sweeps sequentially: they share the same preview tab. Catalog validation is
available through `streamlit_app/scripts/check_story_locales.py`; focused catalog
and formatting tests are in `streamlit_app/tests/test_story_localization.py`.

## 4. Read dates and support alongside results

The default story reads [streamlit_app/data/story](../../streamlit_app/data/story). Its [manifest](../../streamlit_app/data/story/manifest.json) records `exported_at_utc`, dataset counts and available analytical dates, plus generated-scenario metadata. An export date and a profile's analytical date have different meanings, and profiles can use older latest-known observations.

The bundled result stays frozen until an operator exports again. Restarting Streamlit, changing a filter or running a warehouse build does not refresh those files. Selective exports can also leave different datasets with different freshness. The [evidence reference](../reference/validation-and-evidence.md#inspectable-serving-snapshot) records the inspected snapshot.

Explorer controls can change the cohort, window and estimator. A filtered weighted audience is different from a directly standardized mean; unsupported outcomes are different from zero outcomes. Use [understanding the analysis](../wiki/understanding-the-analysis.md) for the reading guide and [population adjustment](../reference/population-adjustment.md) for the exact methods. The simulated commercial relationships remain designed assumptions under every filter.

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
