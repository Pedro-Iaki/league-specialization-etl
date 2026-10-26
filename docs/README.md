# Documentation

The [project README](../README.md) gives the project overview and the argument for its engineering and analysis. Use this index to choose a deeper explanation, a reproduction task or an exact contract.

## Understand the project

| I want to… | Read |
|---|---|
| Follow collection decisions, execution state and delivery gates | [Architecture](wiki/architecture.md) |
| Understand how audience questions become measurements and comparisons | [Understanding the analysis](wiki/understanding-the-analysis.md) |
| Review design choices, tradeoffs and ownership | [Engineering decisions](wiki/engineering-decisions.md) |
| Assess checks, inspectable artifacts and the limits of recorded evidence | [Validation and evidence](reference/validation-and-evidence.md) |
| Understand what generated purchases demonstrate | [Simulated transactions](wiki/simulated-transactions.md) |

For an engineering review, follow architecture into engineering decisions and validation. For an analytical review, begin with understanding the analysis, then follow its links to the relevant definitions and evidence.

## Operate or reproduce it

| I want to… | Read |
|---|---|
| View the bundled result locally without infrastructure credentials | [Run the dashboard](guides/run-the-dashboard.md) |
| Maintain the Portuguese and English story catalogs | [Story translation guide](../streamlit_app/story_component/locales/README.md) |
| Prepare services and operate collection and warehouse delivery | [Run the pipeline](guides/run-the-pipeline.md) |
| Export, check and replace the local serving snapshot | [Refresh dashboard data](guides/refresh-dashboard-data.md) |
| Explore full and anchored champion families locally | [Character family laboratory](guides/explore-character-families.md) |
| Run resumable comparisons over saved family evidence | [Family experiments](guides/run-family-experiments.md) |

These are separate tasks: viewing the bundled data does not operate the pipeline, and a successful warehouse build does not refresh the dashboard. The pipeline guide identifies manual setup and the limits of verified reproduction.

## Inspect exact behavior

The [player-pool archetype contract](reference/player-pool-archetypes.md) describes the frozen eight-component model, eligibility, mixtures and keyed export integration.

| I want to… | Read |
|---|---|
| Find settings, defaults, credentials and entrypoints | [Configuration](reference/configuration.md) |
| Trace stage order, allocation, state transitions, retries and failure boundaries | [Orchestration and execution state](reference/orchestration.md) |
| Look up layers, model grains, identities and serving contracts | [Data models and serving contracts](reference/data-models.md) |
| Check analysis windows, formulas, eligibility, attribution and denominators | [Metrics and methods](reference/metrics-and-methods.md) |
| Distinguish rank weighting from standardization and inspect support | [Population adjustment](reference/population-adjustment.md) |
| Use the wider family-audience base, fixed bands and map denominators | [Audience segments](reference/audience-segments.md) |
| Inspect the accepted family cohort, review gates and evidence limits | [Final champion family cohort](reference/character-family-cohort.md) |
