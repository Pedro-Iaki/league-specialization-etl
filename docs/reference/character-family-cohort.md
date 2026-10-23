# Final champion audience family cohort

The accepted working cohort is **Champion audience families v1**, finalized on
**October 23, 2026**. It selects the 87.5% champion-relative Jaccard alternative.
Family search and threshold tuning are closed for this version.

The [versioned definition](../../streamlit_app/definitions/champion-audience-families-v1.json)
records all 25 selected families, champion keys and names, stable F01–F25 labels,
source identities, evidence summaries, input fingerprints and review rules.
Display names list representative included champions; they are not inferred player
personas. This definition is ready for downstream implementation and is not yet
consumed by the public dashboard or a player categorization model.

## Acceptance and measured results

| Measure | Required | Selected cohort |
|---|---:|---:|
| Champion coverage | 173/173 | 173/173 |
| Family count | No fixed target | 25 |
| Included memberships | Overlap allowed | 251, including 78 extra memberships |
| Family consistency | At least 90% in every family | Minimum 94%; family mean 98.0604% |
| Individual member fit | At least 80% in every membership | Minimum 83.6364% |
| Joint exclusive share | At least 25% in every family | Minimum 25% |
| Family size | 5–28 champions | 5–24 champions |
| Champion-relative Jaccard | At least 87.5% in every membership | Minimum 88.1506% |
| Membership-weighted consistency | Reported diagnostic | 98.3974% |

Family consistency and member fit come from each selected source's saved bootstrap
co-assignment matrix, excluding self. Exclusive share counts a family's champions
that occur in no other selected family, divided by that family's size; the required
exclusive count rounds up. This is exclusivity of champion membership, not players.
Family mean consistency weights families equally; membership-weighted consistency
weights them by included champion count. Neither is a new cohort-wide stability test.

For champion `c` in selected family `F`, the additional review metric is:

```text
mean weighted audience Jaccard(c, each other member of F)
----------------------------------------------------------------
median of c's mean Jaccards across its other reviewed family sets
```

The denominator belongs to that same champion. Each alternative is scored under
the selected source's rank, tracking-history, weighting and mastery-cutoff context.
The reference contains **12,102 distinct reviewed compositions**, sizes 5–28. The
exact current composition is excluded if present; newly searched compositions are
not added to the frozen denominator. An 87.5% floor allows at most a 12.5% relative
deficit. Reference-pool composition and family-size mix affect this descriptive
median; the floor is an accepted review choice rather than a population parameter.

The definition stores the reference-pool SHA-256 and both input fingerprints.
The frozen reference pool remains with the local final evidence bundle.

## Why this version was selected

Overlap is expected. Earlier analysis overemphasized minimizing extra memberships;
the revised direction uses joint exclusivity as a hard filter and allows overlap
above that floor to trade against coverage, size and consistency. The general
Compact v2 solver implements coverage first, then base cost plus a soft overlap
cost. The final local synthesis additionally applies the member-fit and
champion-relative Jaccard gates; it is not merely a Compact v2 run.

The 80% relative-floor candidate covered every champion in 21 families. Raising
the floor to 87.5% required 25 families while preserving its weakest member fit and
improving both saved consistency averages. At 90%, the found alternative used 26
families and reduced weakest fit to 80.6818% and weighted consistency to 97.8477%.
A 90.8695% alternative used 28 families. The accepted 87.5% version balances these
tradeoffs; further optimization on the same evidence was deliberately stopped.

Elise is included with **Evelynn, Nidalee, Zoe and Lillia**. Rek'Sai is included
with **Nunu & Willump, Rammus, Skarner and Zac**. These focused subsets replace
earlier weak or broad placements while meeting every whole-cohort gate. Other
families intentionally overlap, and source-specific evidence is retained.

## Evidence and local loading

Twenty-four selected families use 20-repeat sources and one uses a 100-repeat
source; these counts refer to families, not distinct source identities. Scores reuse
evidence involved in discovery and selection. They describe observed affinities;
they are not independent validation or predictions of an individual's next choice.
Source matrices are never pooled. Analyst subsets do not inherit parent recovery.
The search was bounded; optimal solver stages apply to their candidate pool and
fixed-family neighborhood, not every possible taxonomy.

Load the finalized portable cohort through the laboratory's existing save/load
control from:

```text
data/character_families/cohorts/champion-audience-families-v1-20261023.json.gz
```

The full local finalization bundle is
`data/local_lab/final-champion-family-cohort-20261023/`. It includes the portable
cohort, frozen reference compositions, standard four CSV views, detailed family
and membership gates, definition copy and checksums. The preceding sensitivity
comparison is under `data/local_lab/relative-floor-sensitivity-20261023/`.
These local evidence files remain outside Git; the maintained definition contains
no profile-level data and does not embed bootstrap matrices.

Finalization preserved selected memberships and source identities exactly. It
changed display names, checked original artifact hashes and all acceptance gates,
reloaded the portable cohort through the application validator, and regenerated
the standard exports. The preceding sensitivity validation independently rebuilt
raw audience matrices, alternative scores and exact medians. No additional
discovery or bootstrap was run for finalization.

## Boundary for the next step

First define player family participation: which existing champion-activity weights
to use, what happens when a champion belongs to several families, whether the
resulting vector sums to one, and how missing activity is represented. Splitting
a champion's weight across its families and counting full participation in each
family answer different questions; neither attribution rule has been adopted yet.

Then implement a simple descriptive categorization from those percentages and
inspect its distribution. Rank, specialization, role, weekly activity, inferred
account age and mastery band can be added progressively as audience filters.
Clustering is optional later work. Reopen family search only for new evidence or
a concrete problem found during downstream use.
