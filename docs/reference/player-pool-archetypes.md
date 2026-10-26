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

Use [archetype_serving.py](../../streamlit_app/app_core/archetype_serving.py): `select_archetype(..., mode='primary')` for unique, non-Diffuse primary labels; `expressed` for threshold-passing mixtures; `best_match` for explicit weak-match inspection. `coverage(frame, weight='population_weight')` retains the complete behavioral denominator; omit weights for synthetic customer reporting. Older snapshots without the fields report unavailable coverage and no selected members. Snapshot loaders validate model and dataset fingerprints and derived assignments.

Archetypes summarize Interests and carry into audience construction and purchasing in the default seven-chapter Streamlit story; underlying families remain available for explanation. Role comparisons should use the eligible, known-role parent audience under the same non-archetype filters and original weights; a uniform 20% split is not the audience baseline. Inferred character-role composition is not a player's observed match position.

## Current dashboard placement

The default story uses archetypes as audience slicers, comparing activity, competitive frequency, retained history, standing and Single/Blend expression. Additional expressed interests can overlap. Reach describes support; it is not a comparable ranking of preference strength. Family size, overlap, character popularity and the training cohort affect assignments, and rare-family weighting does not establish popularity normalization.

The [story contract](dashboard-story.md) owns question defaults, guided parents, Combine predicates, navigation and chart denominators. The builder exposes primary/expressed archetypes, expression, evidence and inferred role alongside behavioral dimensions; it does not expose individual family-coordinate filters. Over/under compares a selected share with its explicit parent's share and does not remove structural popularity bias. Conditions imposed by a filter are definitions, not findings.

The optional evidence view explains accepted family-source co-assignment matrices and member fits separately from the frozen NMF profiles. Family selection diagnostics do not establish player-archetype stability, causal effects or purchase propensity. A champion-playrate normalization remains deferred: it would require a defined population, window, measure and overlap-aware aggregation.

Customer rows use the same predicate without behavioral population weights, retaining nonbuyers. The promoted package has 12,008 scored members out of 24,990 customers. Later attached archetypes were not inputs to the frozen purchase generator and do not establish purchase-date preferences.

## Candidate preparation

```powershell
.venv/Scripts/python.exe streamlit_app/scripts/prepare_archetype_candidate.py --output-dir data/local_lab/archetype-candidate-new
```

This migration helper requires warehouse read access, copies the legacy `streamlit_app/data` bundle to a new directory, refreshes player/business rows with `--pool-archetypes`, checks the frozen scenario and source traits, updates reference source fingerprints without changing cuts, validates all manifest datasets and verifies serving-file preservation. On failure the directory remains diagnostic evidence and must not be promoted. The model artifact is included in the candidate manifest.

For a routine current-story refresh, use the [story candidate workflow](../guides/refresh-dashboard-data.md#default-story-candidate-and-replacement). `export_data.py --pool-archetypes` implies the keyed family-audience path. A two-dataset export with its matching references and model can form the complete story package; it is not a complete legacy explorer package. The one-time `freeze_pool_archetypes.py` script refuses to overwrite an existing definition and is not part of routine export.

Promotion follows the [refresh guide](../guides/refresh-dashboard-data.md): stop readers, back up serving, copy reviewed manifest-listed snapshots and references, include the manifest's archetype model file, then replace the manifest last. Reopen and validate through the real loader. Candidate generation does not promote serving or regenerate the frozen synthetic scenario.
