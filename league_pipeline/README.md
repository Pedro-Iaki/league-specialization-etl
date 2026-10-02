# League Pipeline dbt Project

This dbt project turns player rank snapshots, champion mastery snapshots, and champion metadata into player- and champion-level analytical datasets.

The full model catalog is in [docs/model_reference.md](docs/model_reference.md). It documents each model's purpose, grain, upstream and downstream dependencies, columns, implementation details, and interpretation edge cases.

## Layers

- `bronze`: latest ingested copy of each raw snapshot.
- `silver`: normalized historical and current player, mastery, and champion records.
- `gold`: reusable activity, role, concentration, and rank facts plus analyst-facing marts.

## Main analytical outputs

- `mart_player_profile`
- `mart_player_delta_history`
- `mart_champion_profile`
- `mart_champion_tier_growth`
- `mart_champion_playstyle_profile`
- `mart_champion_cooccurrence`

## Validation and build

Run commands from this directory with a configured `league_pipeline` dbt profile:

```powershell
dbt parse --no-partial-parse
dbt build
```

Use `dbt build --full-refresh` after changing the grain, unique key, or schema of an incremental bronze or silver history model.

### Last verified build

Validated against Databricks on 2026-09-30 using dbt Core 1.12.3 and dbt-databricks 1.12.5 with six threads.

| Build | Result | Resources | Duration | Purpose |
|---|---:|---:|---:|---|
| `dbt build --profiles-dir $HOME/.dbt --full-refresh` | Passed | 150/150 | 2m 27s | Rebuilt all models from the raw sources and validated the complete DAG. |
| `dbt build --profiles-dir $HOME/.dbt` | Passed | 150/150 | 2m 39s | Verified the normal incremental execution path after the rebuild. |

Each run covered 21 models and 129 data tests across the bronze, silver, and gold layers, with `WARN=0`, `ERROR=0`, and `SKIP=0`. This includes source constraints, uniqueness and grain checks, accepted-value and range checks, the silver mastery-to-champion relationship test, and nine end-to-end business-rule tests under `tests/business`.

These results record a successful validation at the commit where they were produced; they are not a substitute for rerunning `dbt build` after future model or source-contract changes.
