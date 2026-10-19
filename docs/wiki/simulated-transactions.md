# Simulated transactions

[Project README](../../README.md) · [Documentation index](../README.md) · [Architecture](architecture.md) · [Understanding the analysis](understanding-the-analysis.md)

Behavioral profiles can describe an audience's interests, but customer questions also need commercial outcomes. Do people focused on a particular character acquire different content? Does an audience contain more purchasers, or do its purchasers spend more? The transaction branch demonstrates how those questions could connect to the behavioral models.

**Every purchase and spending measure in this project is simulated.** No authorized real purchase-history source is included. Real profiles supply behavioral context; generated events make the integration, modeling and reporting path inspectable. Relationships in the scenario are configured assumptions, rather than discoveries about actual Riot customers.

## Keep the two sources distinct

| Part of the scenario | Origin | Meaning |
|---|---|---|
| Competitive status and character activity | Real Riot API observations | The frozen cohort's available behavioral context, including its collection and measurement limits. |
| Purchase history, cash spending and discounts | Generated events | Fictional commercial behavior used to exercise the data path. |
| Customer types, owned characters and tenure | Scenario assumptions | Generation controls and simulated context, rather than observed customer attributes. |
| Product and currency references | Fictional demonstration catalog | Coherent event categories and currency treatment; not a reproduction of Riot's catalog, prices or exchange rates. |

The source is generated in Python, rather than delivered by a demonstrated deployed HTTP endpoint. Its long fictional history does not mean the project observed the same people or their purchases over that span. The [evidence reference](../reference/validation-and-evidence.md#frozen-transaction-scenario) records the included scenario's dates and counts without presenting generated revenue as a portfolio achievement.

## Freeze the audience before generating events

A fixed purchase scenario needs a fixed behavioral input. Otherwise a later gameplay build could silently change the people, classifications or activity features behind the same commercial analysis.

The generator freezes eligible profiles with complete required core fields at one analytical date and queue. It does not impose an arbitrary row cap. Some optional longitudinal features can remain missing, so a complete core profile does not imply a usable rank outcome or equally strong evidence for every measure.

The scenario records cohort identity, configuration identity, generator version and seed together. Reusing the frozen cohort is the normal path; replacing it is explicit. A seed alone would not reproduce the scenario if the cohort or assumptions had changed. The [frozen transaction contract](../reference/data-models.md#frozen-transaction-contract) specifies these inputs and their source schemas.

This cohort inherits the original collection process and the additional completeness filter. Its members are real profiles, but simulated purchases do not turn them into observed paying customers or a representative consumer sample.

## Generate relationships deliberately

The generator uses real profile features, fictional controls and randomness to shape events. For example, a relationship between character focus and cosmetic acquisition can be inserted through the scenario configuration. Seeing it in a downstream chart demonstrates that the pipeline preserved the scenario; it does not independently validate that relationship.

These settings give the views useful variation and exercise different reporting cases. They were not calibrated against actual customers. Generator controls with names such as frequency or intensity also describe event production; the reporting measures are calculated from the resulting events and have their own definitions.

The [scenario settings](../../src/sample/scenario.py) and [generator](../../src/sample/generate_transactions.py) make those assumptions inspectable. They support a reproducible integration example without requiring a fabricated explanation for each generated shape.

## Count cash once

Buying virtual currency with cash and spending that currency on content are different events. Treating both as cash revenue would count the same economic flow twice.

| Event category | Contribution to cash spending | Other analytical use |
|---|---|---|
| Fiat purchase, such as a cash top-up | Source-provided USD amount on the generated fiat event. | Cash purchaser counts, discounts and payment patterns. |
| Cosmetic acquisition using game currency | No additional cash valuation. | Cosmetic share of content-acquisition events. |
| Character acquisition using game currency | No additional cash valuation. | Character acquisition and content-event comparisons. |

This separation also matters for denominators. Spending per player includes nonpayers; spending per cash purchaser includes only people with qualifying cash events. An audience can have higher spending per person because more members pay, because purchasers spend more, or both. Keeping those measures separate makes the comparison interpretable.

Cosmetic preference uses content-acquisition events and excludes cash top-ups. It is not automatically a share of cash revenue. Simulated ownership, characters with observed activity scores and acquisition-event counts also describe different things; none should silently substitute for another.

## Follow the source into a checked output

Generation and delivery are separate manual operations. Local validation checks schemas, identities, dates, amounts and reconciliation before the sample loader connects to the warehouse. The loader writes only the dedicated sample tables. It invalidates the cohort completion marker first, replaces transactions, then writes the cohort last and reconciles the result.

dbt builds transaction facts and a player spending mart from that source. Serving checks require a complete matching raw scenario and matching Gold summaries, so an incomplete load or stale spending mart blocks export. The public business extract contains player-level summaries with operational linkage fields excluded, rather than the full event history.

Those checks establish agreement between the scenario and its modeled outputs. They do not certify realistic customer behavior or make the separate table replacements one atomic transaction. [Validation boundaries](../reference/validation-and-evidence.md#validation-boundaries) and [orchestration](../reference/orchestration.md#separate-transaction-and-serving-operations) describe the exact gates.

## Explore four commercial questions

The Business sample explorer carries a selected rank/role audience through four comparisons. All outcomes below remain generated:

| Comparison | What it illustrates | Interpretation limit |
|---|---|---|
| Spending by player traits | Separate payer participation and purchaser spending across behavioral groups. | Configured relationships do not establish actual purchasing differences. |
| Experience within simulated tenure | Compare relative activity-score context within generated account-age groups. | Activity score is not hours; tenure begins at the first fictional purchase, rather than actual account creation. |
| Cosmetic acquisition | Compare cosmetic fractions among content events. | Event fractions are not emotional attachment or cash-revenue shares; averaging player fractions differs from pooling events. |
| Cash discounts | Separate the frequency of discounted fiat purchases from depth conditional on those discounted purchases. | Neither measure demonstrates price sensitivity, promotion effectiveness or revenue lift. |

The story's transaction page explains what real data would add; the explorer lets readers inspect the generated calculations. Exact denominators, payment-frequency/intensity/consistency definitions and discount aggregation are in [simulated commercial measures](../reference/metrics-and-methods.md#simulated-commercial-measures).

## What a real source would change

In a real product setting, this approach could support a hypothesis such as an underserved character audience or a content theme that fits related interests. Evaluating it would require authorized transactions, a trustworthy identity join, clear currency and event semantics, suitable windows and corrections, and a defined outcome. An intervention would also need an appropriate comparison; return on investment would require costs as well as revenue.

No real Riot financial integration is planned. The simulated branch is a completed engineering demonstration of the missing domain. Adapting its patterns to another product would still require source-specific work, potentially reusing selected components rather than extending the entire platform. The demonstrated result is a traceable path from a frozen audience through events, checked models and usable comparisons.
