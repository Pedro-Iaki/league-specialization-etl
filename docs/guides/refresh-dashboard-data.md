# Refresh dashboard data

[Documentation index](../README.md) · [Run the pipeline](run-the-pipeline.md) · [Run the dashboard](run-the-dashboard.md)

The dashboard reads local Parquet files. Refreshing them is a manual export from warehouse models, followed by review and replacement of the serving snapshot. Collection, a successful dbt build and restarting Streamlit do not perform that export.

This guide describes replacing the complete bundled snapshot. It also explains selective exports and the separate frozen business scenario. **All purchase history remains simulated**, even when its behavioral input is refreshed.

## 1. Prepare a settled source build

Use the local Python environment with the root [requirements](../../requirements.txt) and the Databricks configuration described in [run the pipeline](run-the-pipeline.md). The exporter needs SQL access to the existing warehouse outputs; exporting already-built data does not require a new Riot collection or access to the Neon registry.

Confirm that the relevant ingestion and build jobs finished, and record their revision, outcomes and scope. Export from settled models rather than starting a scenario replacement or build in parallel. The exporter does not take a transactionally consistent snapshot of the entire warehouse.

`config/DATABRICKS_CONFIG.env` supplies `HOST`, `HTTP_PATH` and `TOKEN`, with process environment values taking precedence. The script sets its own import paths. Run it from the repository root so the relative output paths below are unambiguous. The examples use PowerShell and the existing `.venv\Scripts\python.exe`; on POSIX, use `.venv/bin/python` and equivalent shell/file operations.

## 2. Decide what happens to the frozen scenario and reference

Refreshing gameplay models does not change the business cohort. Choose its treatment explicitly:

| Intended result | Action |
|---|---|
| Keep the existing commercial scenario | Preserve its cohort and generated files. Its older behavioral date can remain intentional; label it separately from newer gameplay data. |
| Regenerate events from the same cohort | Reuse the cohort with the generator. Reproduction depends on configuration, seed and generator version as well as that cohort. This does not refresh its real profiles. |
| Align the scenario with newly built eligible profiles | Explicitly replace the cohort, regenerate events, validate/load the sample and rebuild its models before export. |

For the last option, use the `PYTHONPATH` setup from the pipeline guide and run:

```powershell
.\.venv\Scripts\python.exe -m sample.generate_transactions --refresh-cohort
if ($LASTEXITCODE -ne 0) { throw "Scenario generation failed; stop before validation and loading." }
.\.venv\Scripts\python.exe -m load.load_business_sample --validate-only
if ($LASTEXITCODE -ne 0) { throw "Scenario validation failed; do not load it." }
.\.venv\Scripts\python.exe -m load.load_business_sample
if ($LASTEXITCODE -ne 0) { throw "Scenario load failed; stop before rebuilding and exporting." }
```

The first command replaces the default frozen cohort and generated scenario files under `data/business_sample`. The load replaces the two dedicated raw sample tables. Then run the configured dbt build job, which includes sample seeds and spending models. A failed/incomplete load or stale Gold spending mart must be resolved before exporting the business dataset. The [scenario contract](../reference/data-models.md#frozen-transaction-contract) and [pipeline bootstrap guide](run-the-pipeline.md#6-complete-a-fresh-warehouses-generated-source) explain the boundaries.

Review the local [rank reference CSV](../../league_pipeline/seeds/rank_population_reference.csv) before calculating population estimates. If changing it, update shares, version, dates and provenance together, then inspect coverage and weight diagnostics. The author-supplied MetaSRC/NA solo origin and the file's still-generic metadata are distinguished in [population adjustment](../reference/population-adjustment.md#ownership-and-reference-input); do not describe the metadata update or external verification as already complete.

The player exporter attaches weights using this local CSV, and the dashboard recalculates weights from its local CSV rather than trusting cached values. The serving manifest does not record an exact reference fingerprint. Keep the reviewed reference revision with the snapshot; the optional analyst bundle below records both input hashes.

## 3. Export to a fresh candidate directory

The default destination is `streamlit_app/data`. Use a new candidate directory for a complete refresh so a failed export cannot partially overwrite the result people are viewing:

```powershell
$refreshDir = Join-Path "data" ("dashboard_refresh_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
if (Test-Path -LiteralPath $refreshDir) { throw "Choose a new candidate directory." }
.\.venv\Scripts\python.exe streamlit_app/scripts/export_data.py --output-dir $refreshDir
if ($LASTEXITCODE -ne 0) { throw "Export failed; do not replace the serving snapshot." }
```

On POSIX, supply a new directory explicitly to the same script with `--output-dir`. The exporter writes configured dataset filenames and `manifest.json`, and rejects empty results, missing required columns and forbidden public identifiers. Business output additionally requires its exact column allowlist and matching scenario metadata.

Without `--dataset`, all configured queries are attempted. An absent optional business sample can be skipped only when its error indicates a missing table/view; an incomplete or mismatched scenario is a failure. Check what was actually exported before calling it a complete replacement.

`--dataset` is repeatable and uses dataset keys, such as `--dataset players --dataset champions`, rather than filenames. A selective export into an existing destination retains unselected manifest entries and files. Its new top-level export time therefore does not establish that every dataset was refreshed. A fresh directory containing only selected datasets is a subset, not a complete dashboard package.

Each Parquet replacement uses a temporary file, but the whole export is not atomic. If a later dataset fails, earlier output files can already have changed while the manifest remains unwritten or old. Inspect that candidate; use a new directory for a clean retry.

## 4. Check the candidate locally

For a complete replacement of the bundled package, this PowerShell command reads local files, reuses the exporter's public-contract validator and checks the configured dataset set against the manifest:

```powershell
@'
import json
import sys
from pathlib import Path
import pandas as pd
from streamlit_app.scripts.export_data import validate_public_frame
from app_core.config import DATASET_FILES

candidate = Path(sys.argv[1])
manifest = json.loads((candidate / "manifest.json").read_text(encoding="utf-8"))
assert set(manifest["datasets"]) == set(DATASET_FILES), "Candidate is not the complete configured dataset set"
for name, filename in DATASET_FILES.items():
    item = manifest["datasets"][name]
    assert item["file"] == filename, f"Unexpected filename: {name}"
    path = candidate / filename
    frame = pd.read_parquet(path)
    validate_public_frame(name, frame)
    assert (len(frame), len(frame.columns), path.stat().st_size) == (item["rows"], item["columns"], item["size_bytes"]), name
    if name == "business_players":
        scenario = item["scenario"]
        assert len(frame) == scenario["player_count"], "Business player count mismatch"
        assert set(frame["scenario_id"]) == {scenario["scenario_id"]}, "Business scenario mismatch"
print(f"Validated {len(DATASET_FILES)} local datasets")
'@ | .\.venv\Scripts\python.exe -B - $refreshDir
if ($LASTEXITCODE -ne 0) { throw "Candidate validation failed; keep the current serving snapshot." }
```

This completeness check intentionally rejects a selective export or a package that skipped the optional business source. Such outputs can be useful for a narrower task, but should not silently replace this complete bundle. The check verifies file contracts and inventory, not every metric or the realism of generated behavior.

Inspect dates and provenance separately:

| Manifest information | Review |
|---|---|
| `exported_at_utc` | Time of this export, distinct from observation coverage. |
| Dataset row/column counts and available date ranges | Expected grain, analytical cutoff and latest-known observation dates; not every dataset has every date field. |
| Business `scenario` | Cohort/configuration identity, seed, generator version, as-of date and purchase windows. |
| Source build and local reference revision | Whether the selected artifacts support the intended release; full file coverage alone does not prove date alignment. |

The [data models](../reference/data-models.md#serving-datasets) define grains, and [validation and evidence](../reference/validation-and-evidence.md) owns dated numerical inventories. Keep older figures labeled with their original source/date until the new files have been inspected.

## 5. Optionally rebuild the analyst bundle

The local population exporter can freeze the candidate's profiles and exact reference with support diagnostics, comparisons and direct-standardized means:

```powershell
.\.venv\Scripts\python.exe streamlit_app/scripts/export_population_estimates.py --snapshot (Join-Path $refreshDir "player_profiles.parquet") --output-dir (Join-Path $refreshDir "analyst_bundle")
if ($LASTEXITCODE -ne 0) { throw "Analyst bundle export failed; do not share the partial output." }
```

It requires no warehouse connection and writes a separate bundle, including a manifest with snapshot/reference hashes and `population_estimates.zip`. Recreate it after changing either input. The generated handoff reports the local reference metadata; it does not independently verify that provenance. The [population reference](../reference/population-adjustment.md) defines interpretation and provenance limits.

## 6. Replace the serving files and reopen the app

Stop Streamlit before replacement. After the complete candidate passes review, preserve the existing serving directory and copy only the reviewed manifest-listed Parquet files, followed by the manifest:

```powershell
$backupDir = Join-Path "data" ("dashboard_backup_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
if (Test-Path -LiteralPath $backupDir) { throw "Choose a new backup directory." }
Copy-Item -LiteralPath streamlit_app/data -Destination $backupDir -Recurse -ErrorAction Stop
$candidateManifest = Get-Content -LiteralPath (Join-Path $refreshDir "manifest.json") -Raw | ConvertFrom-Json
foreach ($entry in $candidateManifest.datasets.PSObject.Properties.Value) {
    Copy-Item -LiteralPath (Join-Path $refreshDir $entry.file) -Destination streamlit_app/data -ErrorAction Stop
}
Copy-Item -LiteralPath (Join-Path $refreshDir "manifest.json") -Destination streamlit_app/data/manifest.json -ErrorAction Stop
```

This is still a sequence of file operations. If copying fails, keep the app stopped and restore the backed-up file set and manifest together or complete replacement from the validated candidate. Do not mix files from unrelated attempts. Private cohort/event files under `data/business_sample` do not belong in the public serving directory.

Launch the app using [run the dashboard](run-the-dashboard.md). Check the story, representative explorer views, dates and the business scenario. The loader keys its cache on manifest modification time; restarting also avoids retaining old cached frames. For repository verification, the existing snapshot-contract checks can then run against the active serving path:

```powershell
.\.venv\Scripts\python.exe -B -m pytest streamlit_app/tests/test_snapshot_contracts.py -q
```

Review changed artifacts and update any published dates/counts that the new export replaces. This refresh does not publish a hosted dashboard or schedule future updates. Preserve the earlier artifact record where it is needed to explain a historical result.
