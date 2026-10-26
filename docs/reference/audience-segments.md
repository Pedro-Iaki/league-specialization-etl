# Family-based audience segments

[Documentation index](../README.md) · [Metrics](metrics-and-methods.md#player-family-affinity) · [Population adjustment](population-adjustment.md)

This reference documents the cutoff-based family-segment helpers and the retained
six-chapter **legacy** presentation in `streamlit_app/legacy_app.py`, including its
October 23 evidence. The default interface is the seven-chapter archetype story;
see [dashboard story](dashboard-story.md) for its current comparisons and controls.
The fixed bands and full-base calibration below are shared inputs, but the old
family maps, Primary share switch and optional focus lens are not the new UI.

The [audience helpers](../../streamlit_app/app_core/audience_segments.py) define
the wider base without requiring a focus classification, known role, active pool,
scored family or purchase. Family and archetype evidence are lenses on that base,
not general entry conditions.

## Frozen inputs and bands

`audience_segments_reference.json` is generated manually alongside an enriched
player snapshot. It records the exact player-file hash and count, region/queue,
family metric and definition, complete saved rank reference and its fingerprint,
tier support, fixed bands and suppression policy. The definition is
`family-audience-segments-v1`. The loader rejects mismatched profile/reference
hashes, metric definitions and band policies. A deliberate band change needs a
new version; a filter never creates new cuts.

The accepted population target is NA ranked solo/duo. Prepare the complete
matching scope once, including all recognized apex tiers, using individual-tier
weights. Filter that result while retaining its weights. Unknown ranks have no
invented weight. Separate scopes cannot be pooled without a population mixture.

| Dimension | Five positive ranges, upper bounds inclusive | Meaning |
|---|---|---|
| Activity | ≤600,000; 600,000–1.5m; 1.5m–2.5m; 2.5m–4m; >4m mastery | Accumulated activity across characters and modes |
| Competitive engagement | 1–24; 25–99; 100–249; 250–499; ≥500 games | Ranked games recorded at the retained observation |
| History marker, optional | ≤365; 365–1,095; 1,095–1,825; 1,825–2,555; >2,555 days | Span since oldest retained positive-mastery champion last-play marker |

The overlapping printed endpoints in the activity/history ranges are open at
the lower bound and closed at the upper bound. Codes are A1–A5, E1–E5 and H1–H5.
Zero has a separate A0/E0/H0 code; missing, negative or nonfinite measures are
`Missing`. The October candidate has no zero-game profiles; it does not measure
the unranked or zero-game population. The ranges are rounded presentation cuts,
not quintiles or equally sized audiences. History uses 365-day year equivalents
and remains a lower bound, never account creation. Optional mastery/1,200 hour
equivalents retain the [assumption and limits](metrics-and-methods.md).

## Maps and denominators

| View | Statistic | Denominator |
|---|---|---|
| Activity × ranked volume | Joint reference-adjusted audience share | All selected profiles with positive frozen weights, including missing-value categories |
| Activity × rank | P(activity band given rank group) | Selected weighted profiles in that rank group |
| Family affinity on activity × rank | Weighted mean of one coordinate | Scored vectors in that cell; report scored coverage against the whole cell |
| Primary family on the same map | Exclusive primary-family prevalence | All selected weighted profiles in the cell, including Shared top and unavailable states |
| Inferred character type | Type composition | Known types only, with their share of the whole cell reported separately |

Turning the rank map sideways changes layout only. Selecting engagement or
history makes its conditional population explicit and preserves the same cuts
and weights. The original saved rank shares remain context labels, not the
selected audience's composition: Lowest 42.03%, Medium 41.16%, High 12.34%,
Highest 4.47%. Their mappings are Iron–Silver, Gold–Platinum, Emerald and
Diamond–Challenger. Do not reconstruct reference prevalence from collected row
counts.

Primary categories are exclusive and can be combined as Top N plus Other;
Shared top and each missing-evidence state stay separately identified. Family
affinities overlap: measured zero stays zero, unavailable vectors stay null,
and coordinates must not be stacked into a 100% composition or summed into
Other. Family members and family sizes accompany the interpretation. Existing
type A–E maps to Top/Jungle/Middle/Bottom/Support and uses its own Recent-pool
weighting; it is distinct from family and is not an observed match position.

The character-interest chapter defaults to mean affinity for a selected family;
its **Primary share** switch changes the statistic and denominator explicitly.
The compact primary overview shows five families ordered by their full-base
primary mass, then Other families, Shared top and observed missing-evidence
states. The complete family table retains all 25 IDs, actual members, raw
shares, masked estimates and support. Other is reaggregated before suppression.
Ordering and filters never change the definition or choose ties arbitrarily.

Type composition compares the selected unique-primary audience with all
unique-primary audiences, using known types only and reporting coverage for
both. A supported comparison within the selected family's most common type
shows that a single type can still contain several primary families. This is
descriptive, not a prediction or an independent validation of either measure.
The profile adds supported weighted medians of accumulated activity, ranked
games, top affinity and gap, plus the largest supported rank group.

The collapsed optional lens starts Off. Whole-history focus preserves all four
existing classifications and reports their coverage; it is separate from family
affinity and recent-match behavior. Pool breadth shows median scored mapped
characters and positive family coordinates. The latter overlap: one shared
character can reach multiple families. Character counts inside a particular
family are unavailable in the serving rows and are not inferred from coordinates.

Displayed estimates are masked below **30 observed profiles or Kish effective
size 20**. A frequency cell uses the profiles counted in that cell; a mean
affinity cell uses its scored-vector denominator. Primary-family prevalence
therefore reports both whole-cell and primary-member support. Empty cells have
a separate status. Raw shares and full denominators remain in analytical outputs, so
suppressed cells do not cause remaining cells to be renormalized. Counts,
effective support and missingness belong in hover/method detail; they are not
market sizes or confidence intervals. This is a presentation guard, not a
statistical significance guarantee.

## Dated evidence: October 20 profiles, reviewed October 23, 2026

The installed joint export has 38,403 profiles. Tier calibration covers **99.98%**
of the saved reference: Challenger's 0.02% has no observations. Grandmaster's
0.04% rests on one observation and is separately flagged as sparse; pooling it
into Highest does not create reliable individual-tier evidence. Calibration
does not correct within-tier collection bias.

- **Engagement adds information to accumulated activity.** An estimated 61.34%
  of the supported audience has fewer than 100 recorded ranked games. Among
  those above 4m lifetime mastery, 38.65% also have fewer than 100. Low recorded
  ranked volume does not establish a preference for another game mode.
- **Activity differs by rank.** The >4m band is 6.88% of Lowest versus 37.71%
  of Highest, conditional on rank. This is cross-sectional, not evidence that
  accumulating mastery causes climbing. Engagement-filtered maps may differ.
- **Family coverage is part of the result.** Unique primary families cover
  40.05% of the adjusted base; Shared top 10.68%; no active pool 46.33%;
  insufficient mastery 2.94%. Mean affinity describes the 50.73% scored subset.
  Known inferred type covers 53.67%. None of these exclusions should silently
  remove people from the base audience.
- **The simple label needs its detail.** Among scored profiles, the weighted
  median top affinity is 58.14% and median gap 11.81 percentage points. Shared
  top can result from one shared character. It does not establish diversified
  interests. About 79.37% of scored profiles have coordinate sums above one,
  demonstrating why an additive family composition would be misleading.
- **Family and type overlap without being interchangeable.** Twenty-three of
  25 primary-family groups contain at least two inferred types with ≥10% each.
  Selecting each family's most common type accounts for 58.72% of primary
  profiles, versus 41.02% for the single overall most common type. This is an
  in-sample descriptive crosswalk, not a validated prediction model; both
  dimensions derive from character behavior.

Family size correlates with both primary prevalence (Spearman 0.72) and mean
affinity (0.86) across the 25 accepted families. Larger sets offer more ways to
score; these correlations do not identify a causal size effect or justify
changing the accepted metric. Avoid calling the largest score the strongest
independent preference. History markers are also unevenly distributed: 60.61%
span more than seven 365-day years, which describes retained timestamps rather
than verified account tenure. Use this as optional context.

The numerical chart inputs remain with the local analytical candidate; its
matching frozen reference and enriched datasets are installed in serving.
The retained six-chapter legacy story uses that family-enriched package. The business demonstration retains
its September 29 synthetic scenario and attaches October audience traits by
actual private key before anonymization, with both dates disclosed.
