# Business sample implementation plan

## Outcome and boundaries

Add a small, clearly labeled synthetic purchase history to the existing League data pipeline. Use it to demonstrate how observed player attributes could support customer spending analysis if a private transaction endpoint were available. Open the dashboard with a short business example, then guide visitors into the real Riot API analysis and the engineering behind it.

The purchase history and any relationship it shows are generated. The player rank, mastery, role, and playstyle attributes come from the real collected snapshot. The purpose is to demonstrate a usable data model and presentation, not to claim findings about Riot's customers. Keep the implementation tight and reuse existing helpers where they make the code simpler. Make only changes needed for this sample in existing files; preserve unrelated work and the current gameplay pipeline.

This is one implementation task, with no two-day deadline. The accompanying [agent handoff](business_sample_agent_handoff.md) gives prompts and commands for an agent starting with a fresh conversation.

## Core decisions

| Area | Decision |
| --- | --- |
| Purchase schema | Keep `currency_id`, `amount_spent`, and source-provided `amount_usd`. Cash conversion has already happened in the hypothetical source. |
| Currencies | Seed only `currency_id`, name, and kind (`fiat` or `game`). Include USD, BRL, `L_RP`, `L_BE`, and `L_IP`; no `is_legacy` field. |
| Products | Seed `product_id`, name, description, category, purchase currency, and simple generation defaults. `product_id` identifies a SKU; `transaction_id` identifies one purchase occurrence. |
| Analysis | Monetization metrics use fiat transactions and `amount_usd`. BE/RP events provide purchase-history context and cosmetic/champion mix; there is no RP-spending or RP-balance analysis. |
| Scope | One generated historical transaction fact, one simple player mart with recent and full generated-history summaries, and a small dashboard introduction. |
| Engineering | One Python cohort-export/generation path, one compact Parquet file, a minimal dedicated warehouse load, and focused dbt models. No mock HTTP server, SQLite lifecycle, Pydantic models, FX feed, inflation, new orchestration, or activity-profile mart. |

The simulated history must extend before the current 60-day window: a window-only extract cannot produce a meaningful earliest recorded purchase or champion acquisition history. Use a fixed `as_of_date` from the frozen real cohort and generate a plausible earlier history per player. The mart reports `first_purchase_at`, meaning the first event in the **complete simulated history**. It is a simulated proxy for account tenure, not a real account creation date. Do not create a second, redundant `account_age` field in Gold; the dashboard can derive `datediff(as_of_date, first_purchase_at)` when needed.

Riot's current [ranked eligibility guidance](https://support.riotgames.com/en-us/league-of-legends/gameplay/unlocking-game-modes) requires at least 20 acquired champions. It does not say every champion is bought with BE. This scenario deliberately gives every sampled ranked player some BE champion purchases and a simulated owned-champion count of at least 20. Treat those as generation assumptions, never as verified account inventories. A player may still have zero **fiat** purchases; that is necessary for cash-purchaser share.

## 1. Reference seeds and purchase contract

Create `league_pipeline/seeds/sample_currencies.csv`, `sample_products.csv`, and one seed schema YAML. Configure their column types and schema within this sample's dbt configuration. Currency fields are exactly `currency_id`, `name`, and `currency_kind`. Product fields are `product_id`, `name`, `description`, `category`, `purchase_currency_id`, `sample_original_price`, and `sample_amount_usd`. Product names/prices are fictional scenario inputs. Include a few RP packages bought with USD/BRL, BE champion-unlock SKUs, and RP cosmetic SKUs. `L_IP` can exist in the currency seed without generated contemporary events.

One row in `transactions.parquet` is one completed purchase:

| Column | Type | Meaning |
| --- | --- | --- |
| `transaction_id` | STRING | Stable unique event ID; two purchases of one product have different IDs. |
| `player_id` | STRING | Private join key to the frozen real player cohort. |
| `product_id` | STRING | Purchased SKU in the product seed. |
| `region_at_purchase` | STRING | Generated from the frozen region, with no simulated transfer. |
| `currency_id` | STRING | Unit of `original_price` and `amount_spent`. |
| `original_price` | DECIMAL(18,2) | Original event price before a discount. |
| `amount_spent` | DECIMAL(18,2) | Amount actually paid in that currency. |
| `amount_usd` | DECIMAL(18,2), nullable | Hypothetical source's post-conversion cash amount for fiat events; null for game currency. |
| `occurred_at` | TIMESTAMP | UTC event time. |
| `scenario_id` | STRING | Identifies the active synthetic sample. |

For USD events `amount_usd = amount_spent`; for BRL events the source provides the scenario USD amount, with no pipeline conversion. For BE/RP events `amount_usd` is null. Discounts affect `amount_spent` and the corresponding scenario `amount_usd`. No quantity, granted currency, wallet state, RP-to-USD imputation, or transaction-level synthetic boolean is needed. Synthetic provenance belongs in the scenario manifest, model descriptions, and dashboard labels.

Use plain Python checks and explicit decimal/Arrow schemas for the generator. Do not add Pydantic just for data that this script creates.

## 2. Export the cohort and generate shaped history

Implement `src/sample/generate_transactions.py` as a CLI that performs the export as part of the run. It should query the existing Databricks Gold marts through the repository's connection helper, write a private `data/business_sample/cohort.parquet`, then generate `data/business_sample/transactions.parquet` and `manifest.json`. A `--cohort` option can reuse the frozen local file offline; `--refresh-cohort` explicitly replaces it from the warehouse. Root `data/` is already ignored by Git. No manual download is required.

Export one row per ranked player, including:

| Requested input | Source/interpretation |
| --- | --- |
| `player_id`, `region`, `queue`, `tier`, `main_role`, `active_playstyle`, `snapshot_date`, `as_of_date` | `gold.mart_player_profile`; filter to the configured ranked queue and fail if player IDs remain duplicated. |
| `active_primary_champion_key`, `active_primary_champion_name`, `active_top1_share`, `active_normalized_entropy` | Same player mart. Entropy here is **champion-pool diversity**, not irregularity of playrate. |
| `champions_with_mastery`, `total_mastery_points`, `alltime_top1_share`, `games_per_day_recent` | Same player mart. `champions_with_mastery` means played/mastered champions, not verified owned champions. |
| `ranked_mastery_share` | If available, derive once per player from non-null `estimated_ranked_mastery_share` in `gold.mart_player_delta_history`, for example a median over observed valid periods. Persist null when unavailable; do not infer it from total mastery. |

Keep `active_top1_share` as the generator's `top1_champion_share` feature; record the exact source in the manifest. Keep the selected cohort's real snapshot date and a single `as_of_date`; avoid silently combining player profiles from different dates. The generator may use a neutral offset for missing ranked-share or active-entropy values. `games_per_day_recent` is only a recent activity level proxy; there is no measured weekly playrate consistency yet.

### Shape controls

Put one small, editable `BASE_WEIGHTS` mapping and a grouped `WEIGHT_OFFSETS` mapping near the generator, or in one adjacent scenario configuration file. The seven base controls are:

| Control | Meaning in the generated purchase history |
| --- | --- |
| `payment_consistency` | Regularity of gaps between **fiat** purchase occasions; higher means less variable gaps. |
| `payment_frequency` | Number of months/periods with a fiat purchase over simulated tenure. |
| `payment_intensity` | Expected cash transactions or USD amount per purchasing period; distinguish it from frequency. |
| `cosmetic_bias` | Target share of **content purchase events** that are cosmetics. These may be RP events; do not equate the share with fiat revenue. |
| `owned_champions` | Simulated owned-champion target, loosely anchored to `champions_with_mastery`, with at least the scenario's ranked-eligibility floor. |
| `discount_share` | Target share of purchase events with `amount_spent < original_price`. |
| `discount_mean` | Mean discount fraction conditional on a discounted event. |

Provide offset dictionaries for **tier, main role, primary champion, active playstyle, simulated account-age band, mastery-sum band, ranked-share band, active top-one-share band, active-entropy band, and customer type** (`sardine`, `dolphin`, `whale`). Each matching group contributes offsets to the relevant seven controls. Assign a seeded random customer type with documented probabilities for every player. For each player, start with the defaults, add all applicable offsets, then clamp probability controls to `[0,1]` and counts/rates to sensible nonnegative bounds. Use a documented neutral/default bucket for null real features and rare champion keys. A sparse primary-champion override table with a default is enough; there is no need for an entry for every champion.

Generate a seeded latent simulated tenure first. Its age band supplies the `account_age` offset. Place an initial BE champion purchase near the simulated start so `first_purchase_at` reflects that tenure approximately; do not use a first purchase calculated from later events as an input to its own generation. Do not export the latent tenure as a second Gold age variable. Make cash frequency, intensity, and consistency affect event timing/size separately. Make cosmetic bias, discount share, and discount mean affect product selection and event prices. Retain random residual variation so groups overlap and the result does not look like a deterministic formula.

For every player, generate a plausible number of BE champion purchases across the full simulated history. Anchor it loosely to `champions_with_mastery`, then allow a small spread and a simulated owned-champion count that can exceed played/mastered champions. Free rewards, rotations, and unused owned champions mean purchases, ownership, and mastery are different concepts. Preserve their differences; do not force equality. The actual `be_champion_purchase_count` must come from generated events, while `simulated_owned_champions` is a separately labeled scenario attribute. Ensure the scenario contains at least one purchase event per sampled player, while allowing cash nonpayers.

Sort the cohort and seed each player's random stream from a stable combination of global seed and player ID, so input row order does not alter the result. Use stable event IDs. Save generator seed/version, base weights, offsets or their fingerprint, cohort fingerprint, scenario dates, and counts in the private manifest. Emit one compressed transaction Parquet, already suitable for loading; skip the existing player/mastery compactor and SQLite ledger.

The weights are illustrative choices designed to make the sample visibly heterogeneous. Do not tune them after viewing a dashboard to prove a desired real-world claim. Document which relationships the generator itself imposes; the plots reveal the scenario's shapes, not empirical evidence.

## 3. Load safely with minimal code

Create `src/load/load_business_sample.py`. Reuse the existing Databricks connection and file-upload helpers where useful. Copy only the small relevant part of the current ingestion notebook's Parquet-to-Delta pattern if it saves code; use static schemas for this known sample instead of Auto Loader or dynamic type inference.

Load two dedicated raw tables: `league_pipeline.raw.transactions` and `league_pipeline.raw.business_sample_players`. The frozen cohort table holds both real input features and generated scenario attributes needed by the mart, including `simulated_customer_type`, `simulated_owned_champions`, `scenario_id`, `as_of_date`, and the 60-day window bounds. It preserves one row per player and the denominator when there are no fiat transactions.

Before replacing those **sample-only** tables, make a few cheap checks: expected columns/types; readable files; one scenario ID and date window shared by both files; unique `transaction_id` and cohort `player_id`; no transaction outside the cohort; valid product/currency IDs; no grossly broken or negative amounts; and no attempt to write to any existing real players/masteries/champions table. Re-run by replacing the same sample tables, yielding the same logical rows. A failed two-table load must be visibly incomplete and block export until scenario IDs and row counts agree. Avoid an elaborate validation framework, file ledger, or new operational registry.

## 4. Model one useful Gold output

Declare the two new raw sources in `league_pipeline/models/staging/sources.yml`. Add `bronze_transactions.sql` (alias `transactions`) and `silver/fct_transactions.sql` with explicit casts, one event per `transaction_id`, product/currency references, and a derived category from the product seed. Add `gold/mart_player_spending.sql`, one row per player in the frozen sample. Configure the new models/seeds so a targeted dbt build can run without rebuilding the unrelated gameplay models. Use `ref()`/`source()` and the repository's layer conventions; do not modify existing gameplay models.

Aggregate transactions to one row per player first; then join to the frozen cohort. The mart should expose the following groups of fields:

- **Context:** `player_id`, `scenario_id`, `as_of_date`, purchase-window bounds, current `tier`, `main_role`, `active_playstyle`, `active_primary_champion_key/name`, `active_normalized_entropy`, `active_top1_share`, `alltime_top1_share`, `total_mastery_points`, `champions_with_mastery`, nullable `ranked_mastery_share`, `simulated_owned_champions`, and `simulated_customer_type`. Include the relevant frozen profile snapshot date.
- **History:** `first_purchase_at` and `last_purchase_at`, each derived from all generated transaction types across the full simulated history. This is the only account-tenure date field; do not repeat it as `account_age` in Gold. Include `purchase_count_alltime` and `be_champion_purchase_count_alltime` if useful to explain ownership assumptions.
- **Fiat all-history:** `cash_purchase_count_alltime`, `cash_spent_usd_alltime`, `cash_active_months_alltime`, `payment_frequency_alltime` (active cash-purchase months / simulated tenure months), `payment_intensity_alltime` (USD cash spending / active cash-purchase months), and `payment_consistency_alltime` (a documented decreasing function of the coefficient of variation of gaps between successive cash-purchase dates). Consistency is null with too few purchases to measure gaps. These are summaries of the complete **generated** history, never a claim of observed lifetime spending.
- **Fiat recent 60 days:** `cash_purchase_count_60d`, `cash_spent_usd_60d`, `cash_active_months_60d`, `last_cash_purchase_at_60d`, and `days_since_last_cash_purchase_60d`. These support frequency, intensity, and recency without a separate activity-profile mart.
- **Purchase mix:** `content_purchase_count_alltime`, `cosmetic_purchase_count_alltime`, `cosmetic_bias_alltime` (cosmetic count / content count), `discounted_purchase_count_alltime`, `discount_share_alltime` (discounted count / all purchases), and `discount_mean_alltime` (mean discount fraction among discounted purchases). Derive these from actual generated events, not directly from latent weight settings. Cosmetic share's denominator is content purchases, not cash top-ups. Use null where a ratio's denominator is zero.

All count/spend columns are zero for a sampled player with no matching **fiat** event. `first_purchase_at` remains present because the scenario gives every sampled player some BE acquisition. Recency and conditional discount means are null when their denominator is zero. Purchaser status is `cash_purchase_count_60d > 0` or `cash_spent_usd_60d > 0`; do not store redundant `has_purchase` flags. Do not add `is_synthetic_spending` to the mart; the scenario and source documentation identify provenance.

Use source-provided `amount_usd` only for fiat events. RP and BE amounts have no Gold spending totals in this release. Do not infer USD value for an RP content purchase or count that content purchase as another cash payment.

## 5. Export and present the result

Add one `business_players` entry to the existing dashboard dataset configuration, query, required-column contract, and exporter. Export an anonymous one-row-per-player Parquet from the Gold sample mart; omit `player_id`, `transaction_id`, and any other internal identifiers. Include the context and metrics needed for a few charts. Preserve source/scenario ID, generator seed/version, frozen date, full synthetic-history range, and recent window in manifest metadata. Make live and snapshot mode label the sample correctly. Treat the business dataset as optional so older snapshots still show the real gameplay pages.

Create one opening Streamlit page and set it as the default in `streamlit_app/app.py`. Keep the current Overview, Population Analysis, Cross Champion View, and Champion Explorer pages. Use a clear app title, a short introduction for a visitor unfamiliar with League, an About the project/author section, and a visible link into the real gameplay analysis. Update the repository architecture diagram and reviewer walkthrough to show the synthetic branch separately from the real Riot API branch.

Choose two or three simple plots from available Gold fields, for example cash purchaser share by current tier/playstyle, mean USD per cash purchaser by tenure band, and recent-versus-generated-history cash spending. Display support counts. Every chart must say that purchase history and spending patterns are synthetic and player traits are from the real collected snapshot. The presentation may show the imposed scenario patterns but must not claim their direction or size as a real Riot finding. Separate account tenure proxy, mastery count, and simulated ownership in labels.

No reporting-currency dropdown, currency conversion, inflation toggle, ROI claim, retention claim, RP-spending chart, or new gameplay activity profile is needed. A single USD view is enough for the business sample.

## 6. Verification and finish line

Prefer a short manual smoke run and at most a few focused checks:

1. Repeating generation with the same cohort/seed/config yields the same logical transaction IDs and amounts; no duplicate transaction or cohort IDs.
2. The loader only writes dedicated sample tables, and a repeat load preserves row counts/totals. New dbt models build; the Gold row count equals the frozen cohort count; all Gold cash USD totals reconcile to fiat facts.
3. A sampled non-cash buyer has BE purchases and zero fiat spending. A player with repeated purchases of the same SKU has distinct transaction IDs. Recent and all-history windows produce sensible first/last purchase ordering.
4. Export contains no private IDs; its manifest describes synthetic provenance; the business page and existing gameplay pages render.

Add only compact tests where they catch a likely regression in generation, join grain, or money separation. Do not build a sample-specific test suite that mirrors each field. Run the existing relevant dashboard checks once if its contracts are changed. Document execution commands, source/field meanings, generation assumptions, and the synthetic/real split in `README.md`, `streamlit_app/README.md`, `league_pipeline/README.md`, and the dbt model reference as needed.

The task is complete when the agent can generate/freeze the cohort without manual downloading, load the sample without touching real source tables, build one player spending mart, publish an identifier-free dashboard snapshot, and open a clearly labeled business demonstration that leads to the real project.
