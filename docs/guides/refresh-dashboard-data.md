# Refresh dashboard data

The default seven-chapter story reads `streamlit_app/data/story`. The previous
interface in `legacy_app.py` continues to read the original `streamlit_app/data`.
The instructions below describe export and validation boundaries for both; choose
the intended package explicitly rather than replacing both during a UI change.

For a new story snapshot, export to an isolated candidate directory with
`--pool-archetypes` (which implies family enrichment), including `players` and
`business_players`. Keep the frozen scenario and keyed enrichment rules described
below. After validation, install the two Parquets, their complete matching
`audience_segments_reference.json`, `player-pool-archetypes-v1.json` and
`manifest.json` together under `streamlit_app/data/story`, retaining a rollback
copy. A full exporter manifest may contain additional datasets; the story consumes
only these two. Restart Streamlit and verify counts, original behavioral weights,
customer cash and the guided/custom comparisons. Rendering never performs this
export or refits the model. The shipped story package was copied from the validated
October 24 archetype candidate, retaining the original Parquet bytes and scenario.

The public family/run evidence is a separate dated publication under
`streamlit_app/story_component`. Refresh it offline with
`streamlit_app/scripts/prepare_story_evidence.py` only when its reviewed source archives change;
do not substitute raw logs or databases. Its checksum manifest pins both adopted
definitions and the sanitized evidence file. It does not claim those historical
runs produced every row of a later story snapshot.

[Documentation index](../README.md) · [Run the pipeline](run-the-pipeline.md) · [Run the dashboard](run-the-dashboard.md)

## Default story: candidate and replacement

Use a new directory; export requires warehouse access. The source-build and
scenario decisions in sections 1–2 below apply to both interfaces.

```powershell
$storyCandidate = Join-Path "data" ("story_candidate_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
if (Test-Path -LiteralPath $storyCandidate) { throw "Choose a new candidate directory." }
.\.venv\Scripts\python.exe streamlit_app/scripts/export_data.py --output-dir $storyCandidate --pool-archetypes --dataset players --dataset business_players
if ($LASTEXITCODE -ne 0) { throw "Export failed; keep serving unchanged." }
.\.venv\Scripts\python.exe streamlit_app/scripts/export_audience_reference.py --audience-segments --snapshot (Join-Path $storyCandidate "player_profiles.parquet") --output (Join-Path $storyCandidate "audience_segments_reference.json")
if ($LASTEXITCODE -ne 0) { throw "Reference failed; keep serving unchanged." }
@'
import sys
sys.path.insert(0, "streamlit_app")
from app_core.story_query import AudienceEngine
engine = AudienceEngine(sys.argv[1])
result = engine.compare({"schema_version": 1})
print({"profiles": result["parent"]["profiles"],
       "scored_profiles": result["parent"]["archetypes"]["scored"],
       "customers": result["parent"]["synthetic"]})
'@ | .\.venv\Scripts\python.exe -B - $storyCandidate
if ($LASTEXITCODE -ne 0) { throw "Story loader validation failed; keep serving unchanged." }
```

Review dates, archetype coverage, source provenance and scenario identity before
promotion. The current package has 38,403 profiles, 13,348 scored profiles, 24,990
customers, 6,790 cash purchasers and 28,369,366 cash cents in the 60-day window.
These are dated checks, not constants to force onto future behavioral snapshots.
An unchanged frozen purchase scenario should preserve its amounts and identity.

After review, stop readers of `streamlit_app/data/story`, copy that complete
directory to a new backup under `data/`, and replace these five files from the
same candidate: `player_profiles.parquet`, `business_players.parquet`,
`audience_segments_reference.json`, `player-pool-archetypes-v1.json`, then
`manifest.json` last. Do not copy private research archives or mix candidates.
If replacement fails, keep readers stopped and restore the complete package.
Repeat the loader check with `streamlit_app/data/story` as its argument. Reopen
`app.py` and check guided comparisons, custom Apply, purchase carry, both languages
and evidence links. This does not replace legacy data, regenerate purchases,
refit archetypes or publish hosting.

## Full legacy/explorer package workflow

The numbered export, full-inventory validation and copy examples below target
`streamlit_app/data` for `legacy_app.py`. A two-dataset story candidate is complete
for the new story but deliberately fails the legacy full-inventory check.

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

Review the local [rank reference CSV](../../league_pipeline/seeds/rank_population_reference.csv) before calculating population estimates. If changing it, update shares, version, dates and provenance together, then inspect coverage and weight diagnostics. Its accepted saved shares are attributed to OP.GG/NA solo-duo; the October 23 metadata correction preserves the values and does not independently authenticate a historical capture. See [population adjustment](../reference/population-adjustment.md#ownership-and-reference-input).

The player exporter and population explorers calculate weights using the reviewed local seed CSV rather than trusting cached values. Guided behavioral chapters use the reference embedded in the matching frozen audience-segment JSON. Family-enriched player exports record the seed fingerprint and version in the manifest; legacy exports do not. Preserve the matching packaged rank CSV and review the seed revision with the snapshot; the optional analyst bundle below records both input hashes.

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

### Family-enriched profile and business exports

Add `--family-audience` to calculate the versioned [family-affinity metric](../reference/metrics-and-methods.md#player-family-affinity). A complete candidate export uses:

```powershell
.\.venv\Scripts\python.exe streamlit_app/scripts/export_data.py --output-dir $refreshDir --family-audience
if ($LASTEXITCODE -ne 0) { throw "Family export failed; do not replace the serving snapshot." }
```

To update just these datasets in a separately staged complete package, also pass `--dataset players --dataset business_players`. Preserve the other files and their original dates explicitly; the new export time does not make them current. Rebuild the matching audience reference after any profile replacement. The flag is optional; omitting it retains the legacy export shape.

The exporter reads active membership, lifetime champion mastery and profile dimensions together while actual player keys remain available. It calculates family fields on those associated rows, then drops keys and champion-member records from the public output. Business rows are joined to the same current profiles by private player key and queue, preserving the frozen scenario and every customer, including nonbuyers. No anonymous row-order or feature matching is used. Unmatched customers have an unavailable family state rather than an invented preference.

Existing business traits and dates remain unchanged. Current profile context has an `audience_` prefix and its own observation dates. For example, October audience traits attached to September synthetic purchases describe a cross-date demonstration; they do not establish September preferences or predictive performance. Regenerating transactions is unnecessary when this real-key linkage is available.

The manifest records the family definition hash, metric version, coordinate order, scoring rules, dataset hashes, source dates, association coverage and existing scenario metadata. The loader rejects mismatched hashes, incompatible metric metadata and invalid vectors or categories. `oldest_retained_play_at` is the earliest valid last-play marker among retained positive-mastery champions; its elapsed days are a history lower bound, not account creation. Family scoring uses lifetime mastery within model-selected active membership, not preferred characters or recent gain weights.

The family-enriched package and six legacy guided chapters remain implemented. The default story additionally requires archetype enrichment. A new export is only a candidate until the intended package and its references pass review and are installed together.

### Freeze the matching audience reference

Freeze the audience reference for that complete candidate before replacing serving files:

```powershell
.\.venv\Scripts\python.exe streamlit_app/scripts/export_audience_reference.py --snapshot (Join-Path $refreshDir "player_profiles.parquet") --output (Join-Path $refreshDir "audience_reference.json")
if ($LASTEXITCODE -ne 0) { throw "Audience reference failed; do not replace the serving snapshot." }
```

This legacy local step creates value-based score cuts once for the paired cohort and records the player-file hash. It neither queries the warehouse nor changes the models. The reference is an additional serving artifact, not a fourteenth warehouse dataset. Legacy paired consumers reject an absent or mismatched reference instead of silently rebucketing a newer snapshot. Guided pages 1–4 use the wider reference below.

For a family-enriched release, also freeze the **wider** [audience-segment reference](../reference/audience-segments.md):

```powershell
.\.venv\Scripts\python.exe streamlit_app/scripts/export_audience_reference.py --audience-segments --snapshot (Join-Path $refreshDir "player_profiles.parquet") --output (Join-Path $refreshDir "audience_segments_reference.json")
if ($LASTEXITCODE -ne 0) { throw "Audience segments failed; keep the existing serving package." }
Copy-Item -LiteralPath league_pipeline/seeds/rank_population_reference.csv -Destination (Join-Path $refreshDir "rank_population_reference.csv") -ErrorAction Stop
```

This records the full base, saved tier reference, readable fixed activity/engagement/history cuts and support policy. It updates the neighboring candidate manifest with the reference hash after checking its player-file identity. It does not recalibrate a focus-only or family-only subset. Keep the legacy paired reference for existing paired consumers. Later page filters reuse the frozen inputs instead of rewriting this file.

## 4. Check the candidate locally

For a complete replacement of the bundled package, this PowerShell command reads local files, reuses the exporter's public-contract validator and checks the configured dataset set against the manifest:

```powershell
@'
import json
import hashlib
import sys
from pathlib import Path
import pandas as pd
from streamlit_app.scripts.export_data import validate_public_frame
from app_core.config import DATASET_FILES
from app_core.audience import prepare_audience
from app_core.data import _validate_dataset

candidate = Path(sys.argv[1])
manifest = json.loads((candidate / "manifest.json").read_text(encoding="utf-8"))
assert set(manifest["datasets"]) == set(DATASET_FILES), "Candidate is not the complete configured dataset set"
for name, filename in DATASET_FILES.items():
    item = manifest["datasets"][name]
    assert item["file"] == filename, f"Unexpected filename: {name}"
    path = candidate / filename
    frame = pd.read_parquet(path)
    validate_public_frame(name, frame)
    _validate_dataset(name, frame)
    assert (len(frame), len(frame.columns), path.stat().st_size) == (item["rows"], item["columns"], item["size_bytes"]), name
    if "family_affinity" in item:
        assert item["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest(), name
        assert frame.attrs["family_affinity"] == item["family_affinity"], name
    if name == "business_players":
        scenario = item["scenario"]
        assert len(frame) == scenario["player_count"], "Business player count mismatch"
        assert set(frame["scenario_id"]) == {scenario["scenario_id"]}, "Business scenario mismatch"
reference = json.loads((candidate / "audience_reference.json").read_text(encoding="utf-8"))
profile_path = candidate / DATASET_FILES["players"]
assert reference["source_profile_sha256"] == hashlib.sha256(profile_path.read_bytes()).hexdigest()
prepare_audience(pd.read_parquet(profile_path), reference)
if "audience_segments_reference" in manifest:
    from app_core.audience_segments import prepare_segments
    item = manifest["audience_segments_reference"]
    path = candidate / item["file"]
    assert item["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    segments = json.loads(path.read_text(encoding="utf-8"))
    assert segments["source_profile_sha256"] == hashlib.sha256(profile_path.read_bytes()).hexdigest()
    prepare_segments(pd.read_parquet(profile_path), segments)
    rank_csv = pd.read_csv(candidate / "rank_population_reference.csv")
    pd.testing.assert_frame_equal(rank_csv, pd.DataFrame(segments["rank_reference"]), check_dtype=False)
print(f"Validated {len(DATASET_FILES)} local datasets and their audience reference")
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

For the eight-archetype candidate workflow, use the [archetype export contract](../reference/player-pool-archetypes.md). Include the model file named by the candidate manifest's `pool_archetypes.file` alongside references during replacement. Its hash and per-dataset model fingerprints are required by the loader.

Stop the local Streamlit instances that read this serving directory before replacement. After the complete candidate passes review, preserve the entire existing serving directory and copy only the reviewed manifest-listed Parquet files and matching references, followed by the manifest. The directory backup preserves unrelated files; candidate analysis exports and private evidence do not belong in serving:

```powershell
$backupDir = Join-Path "data" ("dashboard_backup_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
if (Test-Path -LiteralPath $backupDir) { throw "Choose a new backup directory." }
Copy-Item -LiteralPath streamlit_app/data -Destination $backupDir -Recurse -ErrorAction Stop
$candidateManifest = Get-Content -LiteralPath (Join-Path $refreshDir "manifest.json") -Raw | ConvertFrom-Json
foreach ($entry in $candidateManifest.datasets.PSObject.Properties.Value) {
    Copy-Item -LiteralPath (Join-Path $refreshDir $entry.file) -Destination streamlit_app/data -ErrorAction Stop
}
Copy-Item -LiteralPath (Join-Path $refreshDir "audience_reference.json") -Destination streamlit_app/data/audience_reference.json -ErrorAction Stop
if ($candidateManifest.pool_archetypes) {
    Copy-Item -LiteralPath (Join-Path $refreshDir $candidateManifest.pool_archetypes.file) -Destination streamlit_app/data -ErrorAction Stop
}
if (Test-Path -LiteralPath (Join-Path $refreshDir "audience_segments_reference.json")) {
    Copy-Item -LiteralPath (Join-Path $refreshDir "audience_segments_reference.json") -Destination streamlit_app/data/audience_segments_reference.json -ErrorAction Stop
    Copy-Item -LiteralPath (Join-Path $refreshDir "rank_population_reference.csv") -Destination streamlit_app/data/rank_population_reference.csv -ErrorAction Stop
}
Copy-Item -LiteralPath (Join-Path $refreshDir "manifest.json") -Destination streamlit_app/data/manifest.json -ErrorAction Stop
```

For a directory swap, prepare a sibling staging directory by copying the existing package, overlay only the reviewed release files above, validate it again and verify every resolved path stays inside the intended workspace before moving directories. Preserve the old directory at a new backup path, then rename the staged package into serving; restore the backup if the second move fails. Do not replace files under a running reader. The copy example above is still a sequence of file operations. If copying fails, keep the app stopped and restore the entire backed-up directory or complete replacement from the validated candidate. Preserve the failed directory separately when restoring; overlaying old files can leave incompatible newer reference files behind. Do not mix files from unrelated attempts. Private cohort/event files under `data/business_sample` do not belong in the public serving directory.

Launch `legacy_app.py` using [run the dashboard](run-the-dashboard.md). Check the legacy story, representative explorer views, dates and the business scenario. The loader keys its cache on manifest modification time; restarting also avoids retaining old cached frames. For repository verification, the existing snapshot-contract checks can then run against the active serving path:

```powershell
.\.venv\Scripts\python.exe -B -m pytest streamlit_app/tests/test_snapshot_contracts.py -q
```

Review changed artifacts and update any published dates/counts that the new export replaces. This refresh does not publish a hosted dashboard or schedule future updates. Preserve the earlier artifact record where it is needed to explain a historical result.
