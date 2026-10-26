# Read the project

This project turns economical behavioral observations into audience comparisons, then demonstrates how a separate purchase source could extend them. The [project overview](../README.md) introduces the result; [run the dashboard](guides/run-the-dashboard.md) to explore the bundled data without infrastructure credentials.

## Follow the reasoning

Read these three chapters in order for the main argument. The technical references are optional depth, not prerequisites.

1. **[Understanding the analysis](wiki/understanding-the-analysis.md)**: How activity observations became character families, player archetypes and useful audience questions; what those comparisons can establish.
2. **[Architecture](wiki/architecture.md)**: How collection, history, coordination and checked delivery make that analysis possible.
3. **[Engineering decisions](wiki/engineering-decisions.md)**: Why the implementation took this shape, what changed during development and which tradeoffs remain.

Use **[Validation and evidence](reference/validation-and-evidence.md)** to inspect the resulting artifacts and distinguish tested behavior, recorded executions and remaining limits. **[Simulated transactions](wiki/simulated-transactions.md)** explains the commercial demonstration when you reach Purchases.

## Reproduce or maintain a result

| Task | Guide |
|---|---|
| Launch the current interface | [Run the dashboard](guides/run-the-dashboard.md) |
| Prepare services and operate collection/delivery | [Run the pipeline](guides/run-the-pipeline.md) |
| Prepare, validate and replace a serving snapshot | [Refresh dashboard data](guides/refresh-dashboard-data.md) |
| Maintain display languages | [Translation guide](../streamlit_app/story_component/locales/README.md) |

Viewing, collecting and refreshing serving data are separate operations. The dashboard does not require a new collection, a warehouse connection or a model fit.

## Look up an exact contract

| Question | Reference |
|---|---|
| What does each current chapter select and calculate? | [Dashboard story](reference/dashboard-story.md) |
| Which character groups were accepted, and why? | [Champion families](reference/character-family-cohort.md) |
| How are players scored against the eight accepted mixtures? | [Player-pool archetypes](reference/player-pool-archetypes.md) |
| What do the metrics and population weights mean? | [Metrics](reference/metrics-and-methods.md) / [Population adjustment](reference/population-adjustment.md) |
| Which tables, identities and state transitions implement the pipeline? | [Data models](reference/data-models.md) / [Orchestration](reference/orchestration.md) |
| Which settings and entrypoints control operation? | [Configuration](reference/configuration.md) |

## Optional research tools and legacy views

The retained `legacy_app.py` hosts earlier explorers and local research tools. They are useful for inspecting or extending the method; they are not required to understand or run the current story.

- [Family laboratory](guides/explore-character-families.md): reproduce discovery and inspect saved evidence.
- [Family experiments](guides/run-family-experiments.md): compare collection-selection policies over existing evidence.
- [Legacy audience segments](reference/audience-segments.md): earlier family-based views and their aggregation contracts.

The guides describe reusable workflows. Session instructions and abandoned experiments are not part of the public reading path; accepted decisions and their evidence are retained in the references above.
