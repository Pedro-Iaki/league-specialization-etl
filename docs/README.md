# Documentation

Start with the [project README](../README.md) for the goal, compact data flow and local dashboard quickstart. These pages provide three ways to go deeper: wiki chapters explain the project, guides walk through operations, and references specify exact behavior.

For a short technical review, read [architecture](wiki/architecture.md) and [engineering decisions](wiki/engineering-decisions.md), then follow the implementation links that interest you. The dashboard's guided story presents the case study; its explorers support closer inspection.

## Choose a task

| I want to… | Read |
|---|---|
| Try the included result without pipeline credentials | [Run the dashboard](guides/run-the-dashboard.md) |
| Follow data from collection to the dashboard | [Architecture](wiki/architecture.md) |
| Understand audience comparisons and their limits | [Understanding the analysis](wiki/understanding-the-analysis.md) |
| Understand what generated purchases demonstrate | [Simulated transactions](wiki/simulated-transactions.md) |
| Review design choices, tradeoffs and ownership | [Engineering decisions](wiki/engineering-decisions.md) |
| Configure and operate collection and warehouse delivery | [Run the pipeline](guides/run-the-pipeline.md) |
| Export, check and replace the local serving snapshot | [Refresh dashboard data](guides/refresh-dashboard-data.md) |

The wiki chapters explain why the parts fit together. The guides distinguish viewing the bundled output from running its source infrastructure; a reviewer can use the local dashboard independently of that infrastructure.

## Look up an exact contract

| Reference | Owns |
|---|---|
| [Configuration](reference/configuration.md) | Settings, defaults, credentials, fixed paths and manual entrypoints. |
| [Orchestration and execution state](reference/orchestration.md) | Stage ordering, state ownership, confirmation, retry and failure boundaries. |
| [Data models and serving contracts](reference/data-models.md) | Layers, identities, row grains, relationships, dates and public extracts. |
| [Metrics and methods](reference/metrics-and-methods.md) | Analysis windows, calculations, eligibility, attribution and denominators. |
| [Population adjustment](reference/population-adjustment.md) | Sample/weighted/standardized summaries, reference provenance, support and limits. |
| [Validation and evidence](reference/validation-and-evidence.md) | Checks, dated artifact inventories, recorded runs and limits of demonstrated behavior. |

## Read results with their source and date

Behavioral observations come from Riot's API. Purchases and commercial patterns are simulated. The distinction is explained before spending interpretations in the transaction chapter and guides.

The [serving manifest](../streamlit_app/data/manifest.json) identifies the bundled snapshot. A warehouse build, a new collection run and a manual serving export are different events; recorded results retain their dates and cohorts. Use the evidence reference to distinguish implemented checks, local verification and historical service records.

Earlier documents are preserved in the [documentation archive](deprecated/README.md). They are historical originals; current guides and references provide the maintained instructions and definitions.
