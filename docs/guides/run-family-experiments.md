# Reproduce family-selection experiments

This optional command-line harness compares collection-selection policies over saved family evidence. It reuses the laboratory's candidate, Compact cover and validation helpers without running new discovery or changing the accepted taxonomy. Read the [family laboratory guide](explore-character-families.md) for input preparation and the [accepted family reference](../reference/character-family-cohort.md) for the result used by the dashboard.

A fresh checkout includes example specifications, not their private source libraries. Inspect the named paths before running an example. These are dated research configurations, not instructions to repeat an old overnight session or a claim that any process is currently running.

## Plan, run and resume

From the repository root, use the environment with optional family dependencies installed:

```powershell
.venv/Scripts/python.exe streamlit_app/run_family_experiments.py streamlit_app/experiments/completed-library-smoke.json --plan
```

`--plan` expands the configuration without loading evidence, waiting or writing results. Copy an example to a local specification and set its library paths and a new output directory before execution:

```powershell
.venv/Scripts/python.exe streamlit_app/run_family_experiments.py path/to/local-specification.json --output data/local_lab/my-new-comparison
```

The specification path above is a placeholder. Use the same specification and output to resume. Completed runs are skipped only after record and artifact hashes validate; an interrupted run without a committed `result.json` is recalculated. An OS lock prevents simultaneous writers to that output. Changed settings, libraries, implementation or dependency versions require a new output directory.

## Configure the comparison

The checked-in [Compact v2 example](../../streamlit_app/experiments/compact-v2-combined.json) shows a coverage-first grid; the [waiting example](../../streamlit_app/experiments/compact-v2-new-anchored.json) shows checkpoint waiting. Neither launches automatically. JSON paths resolve relative to the repository root, including when the specification is elsewhere. Unknown fields are rejected.

| Field | Purpose |
|---|---|
| `libraries`, `scopes` | Name source libraries and which combinations to compare. Identical source IDs must carry identical evidence. |
| `fixed`, `grid` | Fixed policy and Cartesian-product alternatives; grid values override fixed ones, and exact duplicates run once. |
| `output`, `baseline` | Persistent output location and optional prior portable cohort for recovered/lost-member comparisons. |
| `member_fit_target` | Review target, default 0.8; does not filter candidate membership. |
| `save_to_builder` | Optional copying of feasible cohorts into local saved cohorts; default false. |
| `retry_seconds` | Optional extra solver budget; retains original attempts and compares feasible results under the same objective. |
| `wait` | Optional bounded waiting for checksum-valid, complete source checkpoints; stale/error states stop the harness. |

Policies use fractions, such as `family_target: 0.8`, not percentages. Compact has no greedy marginal-cost stopping rule: `max_cost_per_character` must be null. `max_family_cost` filters base size/consistency cost before overlap additions.

Set `compact_objective` explicitly. `coverage_score_v2` maximizes coverage, then minimizes summed base cost plus `overlap_penalty * (1 - actual exclusive share)`, then family count. `legacy_min_overlap` preserves older objective ordering and requires zero overlap penalty. Both enforce the joint minimum exclusive share. Comparing raw costs between differently configured policies is not a quality ranking.

For v2, set `followups.shortlist` to zero and freeze separate sensitivity specifications after selecting parents. Keep parent IDs and change one control at a time when isolating a tradeoff. Selection among many policies uses the same evidence and is not independent validation. Library inputs must agree on catalog, membership snapshot and population reference; they need not match the newest serving snapshot.

## Inspect the output

| Artifact | Review |
|---|---|
| `manifest.json` and logs | State, specification, input/helper hashes, versions and any waiting/failure details. |
| Per-run `result.json` | Settings, feasibility, checksums, coverage, overlap and member-fit summaries. |
| `attempts.json` | Solver stages, limits, gaps and retry outcomes. |
| `candidate-character-status.csv` | Why characters are eligible, excluded or left uncovered. |
| Feasible `cohort.json.gz` and four CSV views | Portable selected collection; family, membership, character-review and overlap detail. |
| `comparison.csv`, generated README and shortlist | Cross-run comparisons, objective identity and duplicate assignment sets. |

Before committing a result, the harness reloads its portable cohort, reconciles solver totals and checks CSV structure/counts. Source-specific fit and recovery evidence remain separate from optimization cost. Coverage percentages refer to the eligible set after filters; inspect full-roster coverage as well.

Proven infeasibility, a feasible time-limited result and failure to find a feasible result within the budget are different outcomes. Empty candidate pools are diagnostics, not useful zero-coverage taxonomies. Runs are sequential, with preparation reused where compatible. A completed experiment does not promote serving files, alter an active hunter or establish player-archetype validity.
