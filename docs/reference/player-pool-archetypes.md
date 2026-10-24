# Player-pool archetypes

The accepted eight archetypes summarize mixtures of active character interests. They use a frozen nonnegative matrix factorization (NMF), fitted on 13,348 eligible profiles in the October 20, 2026 snapshot. Names received informal recognizability feedback from League players; this is not statistical validation.

| ID | Name |
|---|---|
| A1 | Bruisers And Tanks |
| A2 | Mages And Enchanters |
| A3 | ADCs (attack damage carries; ranged sustained attackers) |
| A4 | Assassins And Duelists |
| A5 | Front-Line Disablers |
| A6 | Control Mages |
| A7 | Burst Mages |
| A8 | Aggressive Junglers |

## Frozen definition and inference

[player-pool-archetypes-v1.json](../../streamlit_app/definitions/player-pool-archetypes-v1.json) stores eight profiles in the reviewed component order, training-derived family weights, accepted family hash/order, normalization, inference tolerances, seed, settings, package versions and provenance. Its canonical JSON fingerprint identifies the entire inference contract. Routine exports never refit or recalculate training weights. NumPy-only fixed-profile inference is independent of export cohort composition.

The accepted settings are eight components, minimum pool four, sparsity zero, rare-family weighting 1.0, active-loading threshold 0.20, seed 42, no concentration features. The component profiles are normalized to peak one in plain affinity units. Fixed inference minimizes KL divergence on the family-weighted matrix using those fixed profiles; constant per-row initialization and independent convergence prevent business-subset results from drifting.

Features use **every model-active champion's lifetime mastery**, including points below 15,000. Each champion contributes fully to every containing family. Unknown champions retain denominator mass. A nonempty zero-total pool uses equal champion weights, matching the laboratory. This differs deliberately from the story-family metric's 15,000-point numerator cutoff and no-fallback rule. The existing activity membership policy is unchanged and requires no ranked follow-up.

The reviewed laboratory run reproduces all eight primary counts exactly: 2476, 1554, 2835, 3581, 825, 1039, 544, 494; its expression counts are Single 8655, Blend 4120, Diffuse 573. Features agree with saved laboratory vectors within 2.23e-16. Fixed-profile inference optimizes rows beyond the joint fit's global stopping point: two best-match identities, eleven individual threshold decisions and eight expression kinds change. Median loading difference is 2.29e-6; maximum is 0.02321. Fixed inference yields Single 8655, Blend 4118, Diffuse 575. These differences are measured and retained; frozen export inference is the serving contract. No statistical confidence is inferred from a loading.

## Anonymous row contract

All exported fields use the `archetype_` prefix:

| Field | Meaning |
|---|---|
| `model_id` | Version of the fixed transformation; dataset metadata also contains its fingerprint and feature ID. |
| `state` | scored, empty_pool, below_minimum_pool, uncovered_pool or unavailable_pool. |
| `pool_size` | Complete active membership count; null if unavailable. |
| `loadings` | Eight nonnegative strengths ordered A1–A8, null when unscored; not probabilities and not capped at one. |
| `best_ids`, `strength` | All maxima within absolute 1e-12 and their strength; Diffuse best matches are weak. |
| `runner_up_ids`, `gap` | Next distinct positive loading set; top tie has gap zero. |
| `active_ids` | Components with loading at least 0.20; its length is the expression count. |
| `kind` | Single: one active; Blend: at least two; Diffuse: none. Null when unscored. |
| `primary_id` | Unique strongest component for a non-Diffuse profile; null for weak or tied maxima. |

Missing source evidence is distinct from confirmed empty membership. The joint source query checks whether any activity rows exist for each player; a complete export fails on unavailable membership rather than silently converting it to empty. Missing business-profile matches receive unavailable archetype fields. Enrichment occurs through real player keys and queue before anonymization, never through independent public-row positions.

Use [archetype_serving.py](../../streamlit_app/app_core/archetype_serving.py): `select_archetype(..., mode='primary')` for confident exclusive labels; `expressed` for threshold-passing mixtures; `best_match` for explicit weak-match inspection. `coverage(frame, weight='population_weight')` retains the complete behavioral denominator; omit weights for synthetic customer reporting. Older snapshots without the fields report unavailable coverage and no selected members. Snapshot loaders validate model and dataset fingerprints and derived assignments.

Archetypes will summarize Interests and carry into synthesis/purchasing; underlying families remain available for explanation. These story interactions are future presentation work. Role comparisons should use the eligible, known-role parent audience under the same non-archetype filters and original weights; a uniform 20% split is not the audience baseline. Inferred character-role composition is not a player's observed match position.

## Planned dashboard placement

The revised sample design uses three paired questions: accumulated investment versus competitive participation, different archetypes within a shared activity context, and Single versus Blend within one archetype/context. Selection carries A/B and an explicit parent across pages. Model identity or expression states fixed by these predicates are definitions, not findings. The local standalone storyboard implements this comparison interface, shared A/B state and primary-interest refinement. Production story-page integration remains proposed.

Combine additionally proposes an interest over/under panel using centered horizontal bars: selected weighted archetype share divided by its explicit parent's weighted share, minus one. Shares condition on all scored profiles, with unscored coverage separate. Zero is parity; +50% is 1.5 times the parent's share. Undefined parent-zero cases remain unavailable. This contextual comparison is not a correction for structural popularity or family-size bias. Archetypes fixed by the selection are labeled as filter consequences. The storyboard uses the whole behavioral base as parent, consistent with its context map; production uses the explicitly selected parent.

Updated presentation decision: archetypes act as audience slicers. Page 4 introduces their meaning, then compares playtime, competitive frequency, account history and standing against an explicit eligible parent or another archetype. Reach is support context, not a ranked measure of interest popularity. The earlier primary-share chart proposal below is superseded. Family size, overlap, champion popularity and the training sample influence assignments; the fitted rare-family weights do not establish popularity normalization. Describe cross-sectional associations, not effects. A champion-playrate baseline requires a defined measure, population/window and overlap-aware aggregation; it is deferred rather than inferred from lifetime mastery or role shares.

The proposed seven-chapter story introduces archetypes in Interests, combines them with activity/history/standing in audience synthesis, and carries the identical predicate into all four customer questions. Engineering explains the frozen definition and private-key inference boundary. These page changes are proposed; the candidate export and serving helpers are implemented.

Interests opens with coverage against the full selected behavioral audience, then eight primary-archetype shares plus separate weak/tied-match categories within scored profiles. Strongest clear match is the default; expressed-interest mode permits overlap at the frozen 0.20 threshold. Single/Blend/Diffuse becomes One expressed interest / Several expressed interests / No strong match in plain language. Family detail explains shared inputs and preserves the distinct cutoff-based family metric.

The shared predicate stores archetype ID, selection mode and optional expression state alongside activity/history/rank and advanced family/role refinements. A/B reports intersection size for overlapping audiences. Customer reporting recalculates its own coverage and retains nonbuyers; the candidate has 12,008 scored members out of 24,990. Neither eligibility nor loading strengths imply purchase propensity. Default examples must be chosen for support and clarity, not dramatic synthetic spending differences.

## Candidate preparation

```powershell
.venv/Scripts/python.exe streamlit_app/scripts/prepare_archetype_candidate.py --output-dir data/local_lab/archetype-candidate-new
```

This requires warehouse read access, copies the current serving bundle to a new directory, refreshes player/business rows with `--pool-archetypes`, checks the frozen scenario and source traits, updates reference source fingerprints without changing cuts, validates all manifest datasets and verifies serving-file preservation. On failure the directory remains diagnostic evidence and must not be promoted. The model artifact is included in the candidate manifest.

For an independently managed export, `export_data.py --pool-archetypes` implies the keyed family-audience path. Selective exports are not a complete package. The one-time `freeze_pool_archetypes.py` script refuses to overwrite an existing definition and is not part of routine export.

Promotion follows the [refresh guide](../guides/refresh-dashboard-data.md): stop readers, back up serving, copy reviewed manifest-listed snapshots and references, include the manifest's archetype model file, then replace the manifest last. Reopen and validate through the real loader. Candidate generation does not promote serving or regenerate the frozen synthetic scenario.
