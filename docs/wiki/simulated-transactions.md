# Simulated transactions

[Project overview](../../README.md) / [Understanding the analysis](understanding-the-analysis.md)

Behavioral profiles describe interests, but customer questions also need commercial outcomes. Does an audience contain more purchasers, do its purchasers spend more, and what content do they acquire? This branch demonstrates how a separate transaction source can answer those questions alongside the behavioral models.

**All purchases are simulated.** Real profiles supply behavioral context; configured relationships and reproducible randomness generate commercial events. The result demonstrates integration and reporting, not actual Riot customer demand.

## Supply the missing domain

The generator freezes eligible real profiles at one analytical date and queue, then records cohort identity, configuration, generator version and seed. A seed alone would not reproduce the result if the input people or assumptions changed. Regenerating the cohort is explicit; refreshing gameplay data does not silently replace it.

| Input | Origin and purpose |
|---|---|
| Competitive status and character activity | Observed profiles supply the frozen behavioral context. |
| Customer types, ownership and tenure | Scenario assumptions control variation; they are not observed customer attributes. |
| Products, currencies and prices | A demonstration catalog supplies coherent event categories, not a reproduction of Riot pricing. |
| Purchases and discounts | Generated events exercise customer, cash and content reporting. |

The [scenario configuration](../../src/sample/scenario.py) specifies the relationships used by the [generator](../../src/sample/generate_transactions.py). For example, a specialist modifier adds 0.10 to a generation control; it does not guarantee a ten-percentage-point difference in reported cosmetic share. These choices create useful variation but were not calibrated against real customers. The eight player-pool archetypes were attached later and were not generator inputs.

## Carry identity and provenance through delivery

Local validation checks schemas, identities, dates, amounts and reconciliation before loading dedicated sample tables. The loader invalidates the completion marker, replaces transactions, then writes the cohort last and reconciles the result. dbt builds transaction facts and spending summaries; export rejects an incomplete source or stale Gold summary.

Those gates make partial delivery inspectable without claiming an atomic transaction across the entire workflow. The [frozen transaction contract](../reference/data-models.md#frozen-transaction-contract) records the source and model grains.

Current audience traits join to scenario members through private player key and queue before anonymous export. The September 29 scenario and its purchase window remain frozen while attached behavioral context is dated October 20. That later context supports a reporting demonstration, not historical purchase preferences or prediction. Independently anonymized files cannot be joined by assumed row order.

## Count cash once

Buying virtual currency with cash and spending that currency on content are different events. Cash spending uses the generated fiat event's USD amount; cosmetic and character acquisitions add no second cash valuation.

The current Purchases chapter applies Combine's last applied audience definition to unweighted customer rows. It separates four questions:

| Question | Measure |
|---|---|
| How many buy? | Cash purchaser share, retaining nonbuyers in the selected audience. |
| How much do buyers spend? | Integer USD cents summed and divided by cash purchasers. |
| How frequently do they buy? | Cash-event frequency including nonbuyers, with repeat share among purchasers. |
| What content do they acquire? | Cosmetic events divided by cosmetic-plus-character-acquisition events. |

Cash uses the inclusive 60-day scenario window; content mix uses all generated history. A pooled content-event share differs from averaging each person's fraction, and neither is a revenue share. [The story contract](../reference/dashboard-story.md#measures-and-denominators) owns exact denominators and display-support rules. [Validation and evidence](../reference/validation-and-evidence.md#frozen-transaction-scenario) records scenario counts and reconciliation.

## Connect the family audience definition

The retained legacy interface uses exclusive primary-family labels to partition customer rows and cash once, including tied/missing states. It does not allocate revenue across overlapping family-affinity coordinates. Its separate Business sample explorer also covers simulated tenure and discounts; those are optional analyses, not the current four-question story. Their formulas remain in [commercial measures](../reference/metrics-and-methods.md#simulated-commercial-measures).

## What this demonstrates

The completed branch shows how to introduce another source while preserving cohort identity, provenance, event semantics and reporting denominators. It is useful engineering evidence even though the outcomes are generated.

A real application would require authorized transactions, trustworthy linkage, appropriate dates and exposure context. Assessing demand, promotion effectiveness or return on investment would additionally require suitable outcomes and study design. No real Riot financial integration is planned; the simulation is the explicit boundary of this portfolio example.
