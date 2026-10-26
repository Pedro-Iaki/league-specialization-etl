# Reviewed audience definitions

[Player pool archetypes v1](player-pool-archetypes-v1.json) freezes the eight reviewed NMF profiles, training weights, feature order, accepted names and deterministic inference contract. See the [archetype reference](../../docs/reference/player-pool-archetypes.md) for eligibility, mixtures, reproduction differences and keyed export integration. Routine exports apply this artifact without fitting.

[Champion audience families v1](champion-audience-families-v1.json) is the accepted
25-family definition finalized on October 23, 2026. It contains champion identities,
selected memberships, saved source references and review thresholds, with no
profile-level records or embedded bootstrap matrices.

The [cohort reference](../../docs/reference/character-family-cohort.md) owns the
metric definitions, acceptance rationale, evidence limits, local loading path and
boundary for downstream work. The pure
[family-affinity helper](../app_core/family_affinity.py) consumes this versioned
definition to calculate vectors and primary/tied categories. The optional
[joint export](../../docs/guides/refresh-dashboard-data.md#family-enriched-profile-and-business-exports)
calculates these fields on correctly associated profiles and business rows
before anonymization. The loader checks their versions and hashes; legacy family charts use these affinities and primary categories. The current story uses the family definition to construct the distinct archetype input vector and exposes saved family evidence for explanation. The definition file's original export-status note is historical; its immutable hash and memberships are preserved.

[Rank reference v1](rank-population-20261010-v1.csv) preserves the exact historical
reference used by saved family-lab scenarios and libraries. Its generic metadata
is historical, not the current attribution. The dashboard's maintained reference
now identifies OP.GG/NA solo-duo; numeric shares are unchanged. The lab retains
the original fingerprint while shares match, preserving saved evidence without
rewriting it. Changing numeric shares still invalidates the old lab reference.
