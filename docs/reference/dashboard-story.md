# Dashboard story contract

[Run the dashboard](../guides/run-the-dashboard.md) · [Archetypes](player-pool-archetypes.md) · [Population adjustment](population-adjustment.md)

The default `streamlit_app/app.py` serves seven chapters in Brazilian Portuguese
and English. `legacy_app.py` preserves the previous six-chapter story, explorers
and optional research laboratories. This reference describes the default interface;
the [family-segment reference](audience-segments.md) retains the older presentation
and its dated evidence.

## Chapter responsibilities

| Chapter | Introduces | Exploration |
|---|---|---|
| Purpose | Observed behavior, interpreted audiences, simulated purchases | Journey and linked architecture, without an analytical comparison |
| Activity | Accumulated play, competitive frequency, retained history | Activity distributions, supported medians for selection-constrained bands, compact activity maps |
| Standing | Competitive position and saved OP.GG prevalence | Standing in relation to activity; reference prevalence stays separate from selected composition |
| Interests | Eight overlapping NMF archetypes | Activity, standing, expression and additional interests; expandable family and component evidence |
| Combine | Compound audience construction | Shared conditions, independent A/B filters, overlap, paired joint distributions and interest over/under |
| Purchases | Four customer questions | Participation, spending per purchaser, purchase frequency and cosmetic share of content events |
| Engineering | Why, how and when mechanisms are used | Linked architecture, delivery boundaries, scoped capabilities, archived run timelines and task/file lineage |

An overview precedes each guided comparison. Selecting a question replaces the
overview with two audience cards; it does not append a second dashboard below it.
Earlier chapters offer only questions whose concepts have already been introduced.
Ordinary chapter navigation resets the question. Moving directly from Combine to
Purchases carries the last applied definition, never pending edits.

## Guided questions and construction

[story_examples.py](../../streamlit_app/app_core/story_examples.py) owns canonical
question definitions; translated labels are separate.

| Question | Shared context | Default A / B |
|---|---|---|
| Competitive frequency | Highest accumulated-activity band A5 (>4m mastery) | E1–E2 (<100 games) / E4–E5 (≥250) |
| Competitive standing | Frequency E3 (100–249 games) | Lowest / High or Highest |
| Character interests | Unique non-Diffuse primary match | Primary A1 / primary A3 |
| Single versus blended interests | Primary A4 | Single / Blend |

Guided adjustments change the named comparison dimension while keeping its shared
context. They do not match individuals or freeze every other trait. The last two
questions have no preset activity restrictions. Differences are descriptive
associations, not isolated effects of one characteristic.

Combine exposes shared/A/B activity, frequency, history, standing, inferred role,
interest evidence, expression, primary eligibility and primary/expressed archetype
conditions. Multiple values within a field use OR; fields and shared conditions
use AND. Empty selections impose no restriction, including on unavailable values.
Collapsing controls keeps filters active. Apply submits all conditions together;
results retain the previous applied definition while edits are pending. A/B can
overlap or be identical, and the interface reports that explicitly.

Language and Plain/Precise terminology affect display only. Switching language
preserves questions, applied selections, drafts, disclosures and scroll without
querying again. A fresh page load starts in Portuguese. Currency remains USD.

## Measures and denominators

Behavioral weights are calibrated on the complete matching base and inherited
through filtering. Customer summaries are unweighted. Fixed bands come from
`audience_segments_reference.json`; they are not recalculated for each audience.
Estimated hours divide lifetime mastery by 1,200 (600 points and 30 minutes per
match). Competitive frequency uses recorded wins plus losses under an annual-season
assumption, not independently verified season coverage. Retained history is a
minimum span from last-play markers, not account age or collection duration.

| Display | Denominator / meaning |
|---|---|
| Selected reach and compact activity map | Original weighted behavioral base; fixed 0–10% map scale |
| Ordinary distribution | Selected audience's weighted mass |
| Combine joint distribution | Each selected audience's weighted mass; fixed 0–100% scale |
| Within-standing activity distribution | Selected weighted profiles in that standing band |
| Interest coverage | Full selected audience, including unscored profiles |
| Expression and additional expressed interests | Selected scored profiles; additional-interest shares may overlap |
| Primary-interest over/under | Selected primary share ÷ shared-parent primary share − 1, each among scored profiles including weak/tied matches |

Over/under zero means parity; +50% means 1.5 times the parent's share. A zero parent
share is undefined. It does not correct character popularity, family size or
overlap. Selection-imposed traits are labeled as definitions, not findings.
The default Interests chapter uses archetypes as slicers rather than ranking
their prevalence as comparable preference strength. The builder does not expose
individual family-affinity filters; family evidence explains the inputs.

Weighted cells require at least 30 observed profiles and Kish effective N of 20
for supported presentation. Empty and limited cells retain their mass in the
denominator; remaining shares are not renormalized. These are display guards,
not significance tests. Supported medians summarize selected distributions;
they do not fix all players to the median. Globally empty activity/frequency/history/
standing categories are hidden using the union of both complete populations;
filtering never changes the category set. Missing states remain in calculations.

Purchaser share includes nonbuyers. Cash per purchaser divides summed integer
USD cents by buyers in the inclusive 60-day scenario window. Repeat share is the
fraction of those buyers with at least two cash events; the frequency distribution
includes zero, one, two and three-or-more events among all selected customers.
Cosmetic share pools cosmetic events over cosmetic-plus-character-unlock events
across all simulated history, not revenue or mean player fractions. This differs
from the legacy Business sample explorer. Purchase participation, frequency and
cosmetic-share displays require 30 selected members; spending per purchaser and
repeat-share displays require 30 cash purchasers. Undefined denominators remain
unavailable. No archetype was an input to the frozen
purchase generator. Later attached audience traits do not establish purchase-time
preferences or predictive performance.

## Implementation and evidence ownership

| Owner | Responsibility |
|---|---|
| `app_core/story_query.py` | Validates schema-v1 definitions; applies the same predicates to profiles and linked customer traits; returns aggregates |
| `app_core/story_app.py` | Validates local inputs, caches bootstrap data, transports per-session requests/responses through Streamlit |
| `story_component/bridge.js` | Streamlit component protocol; no separate HTTP query service |
| `story_component/story.js`, `presentation.js`, `story.css` | Presentation, draft/applied state, diagrams and navigation |
| `story_component/locales/` | Complete English/PT-BR display catalogs, publication and formatting settings |
| `story_component/public-evidence.json` | Sanitized saved family diagnostics, eight frozen component explanations and separate archived run summaries |

The browser receives aggregate summaries and sanitized evidence, not profile rows.
Private-key enrichment happens before export; independently anonymized files are
never joined in the viewer. Rendering performs no fitting, warehouse access,
credential use or purchase generation. Family co-assignment/member-fit diagnostics
come from exact saved selection sources; they are not held-out accuracy or
archetype stability tests. Recorded runs are evidence of those executions, not a
claim that they produced every serving row.

The five-file package in `streamlit_app/data/story` contains two Parquets, the
audience reference, frozen archetype definition and manifest. The app additionally
needs the checked-in definitions and component assets. Legacy data remains in
`streamlit_app/data`. See the [refresh guide](../guides/refresh-dashboard-data.md)
for package-specific validation and the [evidence reference](validation-and-evidence.md)
for measured counts and verification limits. Local verification is complete;
clean-environment installation and hosted smoke testing remain release checks.
