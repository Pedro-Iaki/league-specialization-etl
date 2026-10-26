# Run family experiments

The local experiment harness evaluates saved hunter libraries through the same candidate,
cover, and cohort-validation helpers as the dashboard. It runs independently of Streamlit,
without touching the hunter, dashboard draft, warehouse, or original evidence. It currently
supports **Compact audience cover**. It does not generate new hunter evidence or make manual
assignments.

Use the repository virtual environment with the optional family dependencies installed as
described in [Explore character families](explore-character-families.md).
Run commands from the repository root.

## Plan, run, and resume

Inspect the complete grid without loading evidence, waiting, or writing results:

```powershell
.venv/Scripts/python.exe streamlit_app/run_family_experiments.py streamlit_app/experiments/anchored-overnight.json --plan
```

Execute the same configuration:

```powershell
.venv/Scripts/python.exe streamlit_app/run_family_experiments.py streamlit_app/experiments/anchored-overnight.json
```

The overnight example waits for `anchored-1.json` to finish. It then evaluates the new library
alone and combined with `anchored-24f92067e71f.json`: 24 main combinations of consistency
75/80%, removal 20/30/40%, and coverage 85/90%. Its fixed exclusive-share minimum is 40%.
Up to three distinct shortlisted covers receive two separate follow-ups: coverage 95% and
maximum family cost 4. Each changes only one setting. These automatic choices are review
aids; the harness does not accept an audience taxonomy.

Run the command again with the same specification and output to resume. The runner verifies
each completed run's record and artifact hashes and skips its calculations. A run interrupted
before its final `result.json` commit is recalculated. Saved outputs are protected by an OS
lock so two processes cannot write the same experiment. The lock releases after a crash;
its leftover file can remain in place.

Changed settings, pinned libraries, implementation, or dependency versions require a new
output directory:

```powershell
.venv/Scripts/python.exe streamlit_app/run_family_experiments.py streamlit_app/experiments/completed-library-smoke.json --output data/local_lab/my-new-comparison
```

To run independently of an open terminal, launch a hidden process. Keep the computer awake.
This starts the program immediately; it waits only if its specification requires unfinished
libraries. Parent process exit does not necessarily mean the Python child has finished, so
use the manifest and log to check status.

```powershell
New-Item -ItemType Directory -Force -Path data/local_lab | Out-Null
Start-Process -FilePath '.venv/Scripts/python.exe' -ArgumentList '-u','streamlit_app/run_family_experiments.py','streamlit_app/experiments/anchored-overnight.json' -WindowStyle Hidden -RedirectStandardOutput 'data/local_lab/anchored-experiments.out.log' -RedirectStandardError 'data/local_lab/anchored-experiments.err.log' -PassThru
```

## Configure experiments

[compact-v2-new-anchored.json](../../streamlit_app/experiments/compact-v2-new-anchored.json)
is the waiting counterpart of the 36-run Compact v2 batch. It keeps all policies and the
scenario library fixed, replaces the previous anchored input with `anchored-1.json`, and
writes to `data/local_lab/compact-v2-new-anchored`. Its harness polls every 30 seconds until
the sweep is checksum-valid, complete, and error-free, with a 24-hour wait deadline and
one-hour stale-checkpoint limit. The manifest records Waiting/Running/Complete or failure;
`stderr.log` records progress. The local background process was launched on 2026-10-22.
Keep the computer awake. Use the same specification/output to resume; the output lock
prevents simultaneous runs, and completed artifacts are verified before being skipped.

The prepared Compact v2 batch is [compact-v2-combined.json](../../streamlit_app/experiments/compact-v2-combined.json).
It combines the frozen 26-scenario evidence library with the completed anchored-24f library:
75/80/85% family consistency × 20/30/40% maximum removal × 25/40% minimum exclusivity ×
base-cost ceiling 3/none = 36 runs. It uses the new coverage-first objective, overlap penalty 1,
an 85% eligible-coverage acceptance floor, and the original 95%/25% cohort as the baseline.
Its input paths point to local evidence; these files must already exist. This specification is
prepared, not automatically launched.

```powershell
.venv/Scripts/python.exe streamlit_app/run_family_experiments.py streamlit_app/experiments/compact-v2-combined.json --plan
```

Omit `--plan` to execute it when requested. Prepared evidence is reused; no discovery or bootstrap
is rerun. Results go to `data/local_lab/compact-v2-combined-main`, with feasible cohorts also
copied into the builder. Keep the newer unfinished anchored sweep outside this frozen comparison.

After the main results, freeze up to one distinct parent per consistency level, preferring higher
coverage, then more champions with best fit at least 80%, then a lower fraction below 50%, then
run ID. Independently change penalty to 0 and 2, minimum exclusivity to 0, and size preference to 0.
The size-only comparison uses the matched uncapped main result as its parent; skip it explicitly
if that parent is infeasible. Generate separate sensitivity specifications after parent selection,
deduplicate identical policies, and retain parent IDs. These are up to 12 additional runs, not
part of the 36-run main grid. A staged test can miss interactions in unselected configurations;
expand penalty strengths across the full grid only if those results warrant it.

Copy a versioned example under `streamlit_app/experiments/` to a local JSON file. JSON uses
only the standard library; the harness adds no YAML dependency. Data paths resolve relative
to the repository root, including paths in a specification stored elsewhere. Unknown fields
are rejected so misspelled settings do not silently select defaults.

- `libraries`: aliases mapped to plain/gzip hunter library or indexed checkpoint paths.
- `scopes`: names mapped to lists of library aliases. Sources with identical IDs must have
  identical evidence. Matrices are never averaged across sources.
- `fixed`: dashboard helper policy fields, as named in the examples.
- `grid`: lists of values for policy fields. Their Cartesian product runs within each scope;
  grid values override fixed values. Exact duplicate combinations run once.
- `output`: the persistent experiment directory. All data outputs remain local and ignored.
- `baseline`: optional portable cohort used to identify recovered/lost character names.
- `member_fit_target`: the cohort review threshold; default 0.8. Report counts also explicitly
  compare member fits with 80%, 65%, and 50%. This does not filter candidate members.
- `save_to_builder`: copy feasible portable cohorts into the dashboard's Saved cohorts
  directory; default false. Names identify settings and run IDs. Library-only optimizer
  controls live in `origin_suggestion`, matching the builder's Apply behavior.
- `retry_seconds`: optional larger budget for one retry of each timed-out run; default 0.
  The better feasible incumbent is kept according to the Compact objective order. Initial
  attempts remain recorded, including infeasibility or timeout. Retries do not pool evidence.
- `followups`: `shortlist` (default 0), `coverage_target` (default 0.95), and
  `max_family_cost` (default 4). Main results are shortlisted before follow-up execution.
- `wait`: `enabled` (default false), `poll_seconds` (30), `timeout_seconds` (86400),
  `stale_seconds` (3600). A checksum-valid complete index, matching job counts, terminal jobs,
  and no recorded errors are required. Errors or stale checkpoints stop the harness while
  preserving the hunter's work. The wait timeout spans resumes; use a fresh experiment
  directory for a new waiting window.

Policies use fractions, not percentages: `family_target: 0.8`, `coverage_target: 0.85`,
`trim_fraction: 0.3`, `minimum_exclusive_share: 0.4`. Trimming is limited to 40%, matching
the existing application. `cover_basis` is `Full + retained` or `Full only`.
`max_cost_per_character` must be null because Compact has no greedy marginal-cost stopping rule.
The hard `max_family_cost` filters BASE size/consistency cost, before any overlap addition;
null disables that ceiling while preserving size/evidence gates.

`compact_objective` selects `legacy_min_overlap` (the default for old specifications) or
`coverage_score_v2`. Legacy requires `overlap_penalty: 0`. V2 accepts a finite nonnegative
penalty and maximizes coverage first, then minimizes the sum of each family's base cost plus
`overlap_penalty × (1 - actual exclusive share)`, then family count. Both modes enforce
`minimum_exclusive_share` jointly on the selected collection. V2's soft penalty still operates
when that hard minimum is zero. Zero penalty leaves base size/consistency scoring active.
Every selected family contributes a positive base cost, favoring economical collections.

V2 automatic legacy coverage/cost followups are disabled: set `followups.shortlist` to 0 and
use separately frozen specifications for sensitivity comparisons. Review shortlists rank distinct
assignment sets by coverage, number of champions with best fit at least 80%, fraction below 50%,
then run ID. This is a review aid; it does not rank differently scaled raw costs across policies.
No new experiment batch is generated automatically when the implementation changes.

Libraries must agree on catalog, membership snapshot, and population reference. Their own
frozen identities are validated; the harness does not require that they be the newest
dashboard snapshot. Bootstrap budgets remain source-specific in the exports. Comparing
multiple sources or choosing their best options is exploratory selection, not independent
validation.

## Outputs and interpretation

`manifest.json` tracks Waiting, Running, Complete, Failed, or Interrupted, with the exact
specification, input hashes, helper hashes, versions, and frozen follow-up plan. Read the
log for live run progress.

Each completed run has:

- `result.json`: settings, solver status, artifact checksums, coverage, overlap, family sizes,
  consistency and member-fit summaries, recovered/lost/missing names, and best fits per character.
- `attempts.json`: solver stages, limits, gaps and statuses for original and retried solves.
- `candidate-character-status.csv`: eligibility/selection diagnostics under that run's gates.
- When feasible, `cohort.json.gz` and the four dashboard CSV views: families, memberships,
  character review, and overlap. Cohorts are reloaded through the real validator, totals
  reconcile with the solver, and CSV headers/counts are checked before the run commits.

`comparison.csv` and `README.md` update after each completed run. V2 reports objective identity,
base/overlap/adjusted cost totals and minimum/median/maximum exclusive shares. Family CSVs include
the separate cost components, and all four CSV views carry scoring identity and penalty. These
costs are recomputed from the portable cohort and checked against the solver. Source-specific
member fits, recovery availability and provenance remain separate from the optimization score.
`shortlist.json` lists
up to three distinct covers. The ordering is explicit: lower fraction whose best placement
is below 50%, then below 80%, then higher covered count, then fewer extra memberships.
That ordering applies to legacy; v2 uses the coverage/fit review order above.
Review coverage tradeoffs and individual families before selecting one. `same_assignments_as`
flags identical family membership sets even when different evidence representatives were chosen.
At completion, `all-cohort-*.csv` combines each exported view across feasible runs.

Coverage targets refer to characters eligible **after** filters, not all characters or players.
Compare the eligible denominator and roster coverage together. The per-character report
distinguishes any weak placement from all placements being weak. Unscored members are reported
separately. Average consistency and zero overlap do not guarantee a sound member assignment.

Empty candidate pools are explicit zero-eligible results rather than useful cohort candidates.
Proven infeasibility, feasible limited results, and no feasible result within the budget remain
distinct. No-result runs have diagnostics and blank cohort metrics, rather than fabricated
zero-coverage cohorts.

Runs are sequential to limit contention with an active hunter and avoid duplicating large
evidence in multiple workers. Candidate preparation is reused for adjacent runs whose
preparation controls agree. Parallel workers and automated hunter generation are future
extensions; they are not enabled by this harness.
