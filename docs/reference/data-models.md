# Data models and serving contracts

[Project README](../../README.md) · [Documentation index](../README.md) · [Configuration](configuration.md) · [Orchestration](orchestration.md)

The warehouse separates source observations, dated history, behavioral interpretation and serving exports. This reference owns model grains, identities and relationships. [Metrics and methods](metrics-and-methods.md) owns formulas; [population adjustment](population-adjustment.md) owns weighting; [validation and evidence](validation-and-evidence.md) owns dated inventories and checks. A model's existence or a populated column does not establish a business outcome or a newly successful warehouse build.

Code identifiers retain `player`, `champion`, `tier` and `mastery`. In explanatory text these mean user, character, rank and activity score. Activity score is cumulative gameplay context across modes, not a match or hour count.

## Identities and scope

- `puuid` is the private source player identifier. Gold's `player_id` commonly carries that same identity under a different name; renaming it does not anonymize it. History/period surrogate keys identify analytical rows and are also private linkage fields.
- `champion_key` is the numeric character identifier joined to the standard metadata roster. Source mastery responses can contain mode-specific variants without a matching roster entry; Silver mastery history retains only recognized roster keys.
- Player history filters to dbt's configured `ranked_queue`, defaulting to competitive solo/duo. Current player selection partitions by player and queue; the portfolio's analytical scope is North America solo/duo.
- Region and queue are not present in every deduplication/surrogate key. For example, Bronze player keys are `(puuid, queueType, date)` and Bronze mastery keys are `(puuid, championId, date)`. Changing collection scope alone does not establish a safe combined multi-region or multi-queue warehouse. Review keys, current-state joins and retained incremental history first.
- A warehouse player can belong to several character audiences and appear in multiple periods or starting-rank groups. Those rows cannot be added together as a count of distinct people.

## Raw and Bronze: source observations

[Raw source declarations](../../league_pipeline/models/staging/sources.yml) name `league_pipeline.raw.players`, `masteries`, `champions`, `transactions` and `business_sample_players`. The gameplay ingestion job adds `_ingested_at` to landed player/mastery records. Source `date` is encoded as `yyMMdd`; it describes the extraction date, separately from ingestion time.

Raw player/mastery tables can contain repeated observations. Bronze selects the latest `_ingested_at` within each source-date key before merging:

| dbt model | Physical relation | Grain and responsibility |
|---|---|---|
| [bronze_players](../../league_pipeline/models/bronze/bronze_players.sql) | `bronze.players` | One player/queue/source-date record. Retains the latest ingestion for that key. |
| [bronze_masteries](../../league_pipeline/models/bronze/bronze_masteries.sql) | `bronze.masteries` | One player/character/source-date record. Retains the latest ingestion for that key. |
| [bronze_transactions](../../league_pipeline/models/bronze/bronze_transactions.sql) | `bronze.transactions` | One generated transaction ID, read from the dedicated simulated source. Rebuilt as a table. |

The gameplay Bronze models use incremental Delta merges with `append_new_columns`. They currently reconsider the raw source rather than applying Silver's bounded source-date lookback. Daily deduplication means warehouse history is not a record of every request or every within-day observation.

## Silver: dated history and current state

| Model | Grain | Contract |
|---|---|---|
| [dim_players_history](../../league_pipeline/models/silver/players/dim_players_history.sql) | Player/selected queue/snapshot date | Normalize rank/division, counters and dates. Retain a rank snapshot only when mastery evidence exists within the configured date tolerance. `player_history_id` is the row's surrogate key. |
| [dim_players_current](../../league_pipeline/models/silver/players/dim_players_current.sql) | Latest snapshot per player/queue | Select the most recent retained history row. “Current” means latest known in the dataset. |
| [fct_masteries_history](../../league_pipeline/models/silver/masteries/fct_masteries_history.sql) | Player/character/snapshot date | Retain recognized characters for players present in rank history. Normalize activity points and last-play time; identify rows with `mastery_history_id`. |
| [fct_masteries_current](../../league_pipeline/models/silver/masteries/fct_masteries_current.sql) | Latest snapshot per player/character | Select each character's latest known mastery row, which need not share one observation date with every other character. |
| [dim_champions](../../league_pipeline/models/silver/dim_champions.sql) | Character key | Current metadata, patch and expected positions assembled from the reference source. |
| [fct_transactions](../../league_pipeline/models/silver/fct_transactions.sql) | Transaction ID | Join generated events to product/currency seeds and derive discount context. Currency kind determines which events count as fictional cash spending. |

The two history models merge incrementally. Their five-day default late-arrival window is measured against retained snapshot dates; it is not a guarantee that arbitrarily old corrections are incorporated. Current models are rebuilt tables over retained history. The history/current split represents snapshots, without a claim of full interval-validity or season-reset handling.

## Gold: behavioral and historical facts

| Model | Grain | Meaning |
|---|---|---|
| [fct_players_champion_mastery_deltas](../../league_pipeline/models/gold/fct_players_champion_mastery_deltas.sql) | Player/character/ending snapshot date | Nonzero observed changes between mastery snapshots with positive elapsed time. Both positive and negative deltas can exist; downstream activity uses positive gains. |
| [fct_players_champion_activity](../../league_pipeline/models/gold/fct_players_champion_activity.sql) | Current player/character | Recent gain, recency, tracking length and inferred recent-pool membership for characters with retained mastery. |
| [fct_players_lifetime_mastery_profile](../../league_pipeline/models/gold/fct_players_lifetime_mastery_profile.sql) | Player | Accumulated activity, concentration, preferred-character and classification context. |
| [dim_players_naive_role_distribution](../../league_pipeline/models/gold/dim_players_naive_role_distribution.sql) | Player | Initial role association inferred from recently used characters and metadata positions. |
| [dim_champion_role_weights](../../league_pipeline/models/gold/dim_champion_role_weights.sql) | Character | Aggregate role association from the initial player profiles; carries observed support. |
| [dim_players_recent_pool](../../league_pipeline/models/gold/dim_players_recent_pool.sql) | Player with a usable recent pool | Recent preferred characters, role mix, concentration and classification. |
| [fct_players_rank_deltas](../../league_pipeline/models/gold/fct_players_rank_deltas.sql) | Player/queue/ending snapshot date | Changes between consecutive rank observations, including a counter-reset flag. An interval is not an individual match. |
| [fct_players_rank_periods](../../league_pipeline/models/gold/fct_players_rank_periods.sql) | Player/queue/completed period bucket | Pair endpoints in adjacent completed buckets, subject to actual spacing and counter-reset checks. Key: `rank_period_id`. |
| [fct_players_period_champion_activity](../../league_pipeline/models/gold/fct_players_period_champion_activity.sql) | Rank period/character | Positive mastery gains ending inside that period, shares and preferred-character status. |
| [fct_players_period_pool_profile](../../league_pipeline/models/gold/fct_players_period_pool_profile.sql) | Rank period with positive mastery movement | Concentration and classification of the period's observed character activity. |
| [fct_players_period_champion_growth](../../league_pipeline/models/gold/fct_players_period_champion_growth.sql) | Eligible rank period/preferred character | A view allocating period outcomes by observed activity share. Allocated games/wins are fractional estimates, not observed character-specific match results. |

The role pipeline is an inference chain: initial player association → character role weights → refined recent-pool role mix. These are not observed match positions.

## Gold: reusable marts

| Mart | Grain | Main consumers and distinctions |
|---|---|---|
| [mart_player_profile](../../league_pipeline/models/gold/mart_player_profile.sql) | Current player | Combines current rank, recent pool, Lifetime context, inferred role and latest-bucket outcomes for the dashboard and scenario cohort. Features can have different observation support. |
| [mart_player_rank_periods](../../league_pipeline/models/gold/mart_player_rank_periods.sql) | Rank period | Left-join period pool context to completed rank periods, add LP eligibility, starting-rank baselines and estimated competitive activity. A completed period can lack a classified pool or usable LP/game outcome. |
| [mart_champion_profile](../../league_pipeline/models/gold/mart_champion_profile.sql) | Character | Describes associated audiences using recent membership, primary users, activity depth, inferred roles and supported historical summaries. Each support column retains its own counting unit. |
| [mart_champion_cooccurrence](../../league_pipeline/models/gold/mart_champion_cooccurrence.sql) | Unordered character pair | Shared recent-pool membership above minimum support, with overlap/association measures. Pairs use `champion_key_a < champion_key_b`. Shared audiences do not imply team synergy. |
| [mart_player_spending](../../league_pipeline/models/gold/mart_player_spending.sql) | Frozen scenario/player | Real behavioral context joined to generated transaction summaries, including cohort members without cash purchases. The current source holds one frozen scenario. |

Character historical summaries reuse [saved growth SQL](../../league_pipeline/macros/champion_player_growth.sql) to aggregate at player/character/starting-rank grain before broader comparisons. A user observed in several starting ranks can contribute to several groups. `observed_games` in the character mart aliases attributed games; it is not a newly observed character match count.

## Dates, windows and missing values

An `as_of_date` is an analytical reference date; `snapshot_date` identifies a contributing observation. A profile can use an older latest-known snapshot. Recent feature models derive their reference from the current dataset's maximum rank snapshot date. The configurable [report cutoff](../../league_pipeline/macros/report_cutoff.sql) controls its consumers, including completed buckets; it does not uniformly time-travel all current features.

At the default seven-day bucket size, rank-period endpoints must come from adjacent completed buckets, be six to eight days apart and contain no intervening counter reset. Further eligibility depends on the measure. Positive games and bounded LP/game are required for the eligible ranking-points outcome; classified comparisons also need pool context.

The current profile joins outcomes only from the **dataset's latest completed period bucket**. A player with an older valid period has missing latest outcomes, without fallback to that older period. Missing pool or follow-up values are not zero activity or zero performance.

Keep the four analytical windows distinct: **Lifetime**, **Recent activity**, **Recent activity with rank follow-up**, and **Observed rank periods**. Recent activity remains inferred and mixed-mode; follow-up restricts outcome availability without recalculating the pool as competitive-only behavior.

## Frozen transaction contract

The [scenario contract](../../src/sample/contract.py) defines private Arrow schemas for cohort profiles, generated customers and transactions. The cohort selects all complete required real profiles at one as-of date and queue, without an arbitrary row cap; optional competitive-activity measures can remain missing. Generation records the cohort/configuration identities, seed and generator version.

The dedicated raw tables are `raw.transactions` and `raw.business_sample_players`. The sample loader writes the cohort last as its completion marker and reconciles the scenario. Frozen fields such as `active_*` and `alltime_*` remain part of that source contract; the spending mart aliases them to canonical `recent_*` and `lifetime_*` names. Changing display vocabulary does not require renaming frozen fixture columns or altering their fingerprints.

Generated money fields use fixed two-decimal precision, and events distinguish cash from in-game currency. Purchase dates, customer types, ownership and tenure are simulated. The branch demonstrates an integration contract and internally consistent summaries, without establishing actual customer outcomes.

## Serving datasets

The [export queries](../../streamlit_app/app_core/queries.py) define these datasets. Names below are manifest keys; filenames are owned by [app configuration](../../streamlit_app/app_core/config.py).

| Dataset | Row meaning before identity columns are removed |
|---|---|
| `players` | Current player profile, with population weights attached during export and separate `active_pool_lifetime_*` preference fields. |
| `champions` | Character summary. |
| `cooccurrence` | Supported unordered character pair. |
| `champion_player_mastery_share` | Player/character mastery-holder membership passing its activity-score threshold. A person can supply several rows. |
| `champion_tier_mastery` | Character/rank/minimum-activity threshold, including `ALL` rollups. Threshold cohorts overlap. |
| `growth_players` | Eligible player/starting rank summary across retained periods. |
| `growth_player_styles` | Eligible player/starting rank/observed period classification summary. |
| `champion_growth_players` | Eligible player/character/starting rank summary from shared saved SQL. |
| `champion_tier_growth` | Character/starting rank/region/queue summary, with overall and classification-specific `cohort_scope` rows. |
| `ranked_mastery_cohorts` | Player/window summary, with starting rank chosen from the last included period and current role attached separately. One person can appear in several windows. |
| `champion_population_activity` | Character/region/queue/current-rank counts and role summaries, including zero membership rows in supported strata. |
| `champion_population_pairs` | Supported character pair/region/queue/current-rank counts; a pair supported overall can have zero shared members in a stratum. |
| `business_players` | Frozen scenario/player summary with real profile context and generated commercial measures. |

Public extracts exclude operational player and interval identifiers; they cannot reconstruct cross-dataset player joins. Public character identifiers remain useful analytical dimensions. Exact required columns are in [contracts.py](../../streamlit_app/app_core/contracts.py); the business dataset additionally uses an explicit [column allowlist](../../streamlit_app/app_core/business.py). Export validation rejects missing required columns, forbidden identifiers and empty results.

The player export derives `active_pool_lifetime_*` by joining the mart's complete `recent_champion_names` membership to existing current mastery records before removing player identifiers. No recency filter, mastery minimum, ranked-follow-up requirement or dbt model change is added. For a player with active pool `A`, each character's share is its Lifetime mastery divided by the sum of Lifetime mastery across `A`. The export includes pool count/total, leading character key/name/points, leading share and HHI. Tied leaders resolve by ascending character key. Empty pools have zero count/total and null preference fields; zero-total pools also have null preference fields.

To report only favorites with at least 15,000 Lifetime points, filter `active_pool_lifetime_primary_champion_points >= 15000` after calculation. The share and HHI still describe the full active pool, including members below that cutoff. Removing low-point characters from the denominator would define a different measure and requires recalculation before aggregation; it cannot be reconstructed from these profile summaries alone.

These fields describe accumulated preference among recently active characters, rather than measured recent play shares. Existing `recent_*`, `lifetime_*`, inferred roles and classifications retain their original definitions. The short-history membership rule uses last-play recency of 0–30 days inclusive at default settings; mature history uses the model's existing 60-day/gain requirements, as defined in [metrics and methods](metrics-and-methods.md#recent-membership-shares-and-preferred-characters). A single active member produces a share of one without proving exclusive recent play. No new gap-selected subset or Fan classification is introduced. New player exports require these fields, while older serving snapshots remain readable until refreshed.

The [manifest](../../streamlit_app/data/manifest.json) records export time, per-dataset size/count/date metadata where available, and scenario provenance. A selective export retains existing manifest entries for unselected files, so one top-level export timestamp does not prove every dataset was refreshed together. Dates, eligibility and grains must accompany numerical claims; equality of row counts does not establish identical cohorts. Streamlit reads these local Parquet files and does not query the warehouse.
