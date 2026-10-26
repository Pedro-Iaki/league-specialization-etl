# Inspect or reproduce family discovery

The optional laboratory in `legacy_app.py` explores groups of characters with shared audiences. The current dashboard uses a frozen result and exposes saved method evidence; it needs neither this laboratory nor its private inputs.

For the project's analytical argument, start with [Understanding the analysis](../wiki/understanding-the-analysis.md). For the adopted result, read [Champion audience families v1](../reference/character-family-cohort.md): 25 overlapping families, their acceptance criteria and evidence limits. This guide is for reproducing or extending the research workflow, not a prerequisite for reviewing the portfolio.

## Prepare the local input

Use the project environment from [Run the dashboard](run-the-dashboard.md). From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r streamlit_app/requirements-families.txt
.\.venv\Scripts\python.exe streamlit_app/scripts/export_character_families.py
.\.venv\Scripts\python.exe -m streamlit run streamlit_app/legacy_app.py
```

Only the export command requires the existing Databricks connection. It reads existing models; it does not collect data, change models or regenerate purchases. The **Local laboratory > Character families** navigation appears when `data/character_families/membership.parquet` exists. Restart an app with file watching disabled after adding the input. Laboratory controls are in English.

The export contains anonymous profile rows with active-character membership and lifetime mastery. Its manifest binds the source dates and file hash. It can be newer than the public dashboard snapshot; never associate rows across independently anonymized exports. Saved scenarios and local evidence under `data/character_families/` are ignored by Git and are not included in a fresh checkout.

## Follow the research stages

| Stage | Operation | Result to inspect |
|---|---|---|
| Define the relationship | Choose the source audience, population weights, mastery cutoff and association measure. | Character coverage and raw pair support. |
| Discover candidates | Build a strongest-neighbor graph and run Leiden; optionally search anchored neighborhoods. | Candidate groups, outside neighbors and unassigned characters. |
| Evaluate sensitivity | Compare random seeds and resample player rows, rebuilding the relevant graph. | Co-assignment matrices, member fit, retention and family recovery. |
| Curate a collection | Compare saved alternatives, allow overlap, and review coverage and individual placements. | Selected groups with their original source evidence. |
| Freeze a version | Save the portable cohort and review gates before downstream attribution. | Stable memberships, source fingerprints and explicit limitations. |

Saving a scenario, changing a name or applying a cover suggestion does not adopt a new serving definition. The accepted v1 search is closed; reopening it requires new evidence or a concrete downstream problem. Routine exports apply the accepted family and archetype definitions without discovery or fitting.

## Define what an edge means

**Observed repertoire** uses weighted audience Jaccard: shared audience divided by the audience associated with either character. **Specific affinity** uses positive log2 observed/expected overlap, with expectation conditioned on pool-size ranges. Both apply declared raw-support and Jaccard floors. Breadth adjustment can distinguish unusually strong association from broad repertoires; neither representation establishes the cause of an interest.

Discovery uses [Leiden community detection](https://www.nature.com/articles/s41598-019-41695-z) with a resolution-capable partition. Resolution, strongest-neighbor count, reciprocal edges and size constraints change the candidate space. Unsupported, isolated and too-small groups remain unassigned. No parameter combination proves a natural taxonomy or guarantees semantic correctness.

The lab's default 15,000-point cutoff applies to every active member. Its family affinity sums qualifying lifetime mastery in a family and divides by all active-pool lifetime mastery, retaining below-cutoff and unmapped denominator mass. A pool without positive mastery has unavailable affinity. The **archetype input is different**: all active members contribute without that cutoff, and a nonempty zero-total pool has an equal-member fallback. See the [archetype contract](../reference/player-pool-archetypes.md) before reusing either vector.

## Read the diagnostics

| Diagnostic | What it tells you | Limit |
|---|---|---|
| Seed sensitivity | Whether optimizer randomness changes the result. | Does not test changes in the sampled audience. |
| Bootstrap co-assignment | How often two characters remain grouped after resampling players. | Unconditional over repeats; two unassigned characters are not companions. |
| Co-member Jaccard | How much a character retains its original neighbors. | Different from player-audience overlap or assignment retention. |
| Member fit / family consistency | Mean co-assignment with the other members / across a family's members. | A high family average can hide a weak individual placement. |
| Separation and recovery | Whether a group stays distinct and is recovered in repeats. | Merging can produce strong cohesion without a distinct family. |
| Collection coverage and exclusivity | Which characters are covered and which belong to only one selected family. | Character membership, not the fraction of exclusive player audiences. |

The heatmaps expose cores, weak members and subgroups that a headline average conceals. Review thresholds are analyst choices, not calibrated confidence levels. Reusing the same evidence to select and assess a group makes these selection diagnostics, not held-out validation. Results from separate sources retain their own matrices and resampling budgets; do not average them into a new collection-wide stability score.

Manual variants retain their source and edit reason. Recomputed peer fit can describe the changed set, but original whole-family recovery and separation do not carry over automatically. A member absent from the evaluated source is unscored, not a measured zero.

## Full-roster and anchored search

The full-roster hunter varies frozen graph configurations and uses bounded iterative consensus to collect candidate groups. It retains initial, intermediate and final alternatives, with nonconvergence disclosed. This is an adaptation of [consensus clustering](https://doi.org/10.1038/srep00336), not an exact implementation of every procedure in that paper.

Anchored search builds a neighborhood around a selected character, then discovers groups containing it. Neighborhood eligibility is ranked before graph top-K truncation, using the declared support/association filters. Bootstrap evaluation rebuilds the neighborhood: a character can disappear because it no longer enters that window. Anchor inclusion itself is not evidence of 100% stability. Boundary retention measures connections inside the cropped group relative to incident eligible connections on the full network; it is separate from recovery.

Inspect saved libraries before launching another search. Loading, filtering or reviewing evidence does not rerun discovery. Indexed anchored checkpoints use a small `anchored-*.json` index and an adjacent `.json.sources` directory of immutable evidence. Preserve both; use a self-contained plain/gzip download when transferring a library. Resume skips completed jobs only when request, data, reference, software and method identities match. A changed configuration is a different run.

## Select and preserve a collection

The cohort builder imports saved sources, compares individual placements and offers deterministic cover suggestions. Compact v2 first maximizes coverage, then minimizes combined size/consistency and overlap cost, then family count. It also enforces the chosen joint exclusivity floor. The legacy objective minimizes overlap first and is retained only to reproduce older policies. Their costs are not interchangeable quality scores.

Suggestions operate within a bounded candidate library. They are review aids, not proofs that the best possible taxonomy has been found. The final accepted collection additionally applies member-fit and champion-relative Jaccard gates; it is not merely the output of a generic Compact run.

Portable cohorts retain selected memberships, names, manual reasons, original source settings, catalog and input fingerprints, and saved evidence. Exported family, membership, character-review and overlap views allow the selection to be inspected without replaying the UI. [The accepted reference](../reference/character-family-cohort.md#evidence-and-local-loading) records the finalized local bundle and exact limitations. [Run family experiments](run-family-experiments.md) covers resumable policy comparisons over these saved sources.
