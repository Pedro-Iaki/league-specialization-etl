# Metrics and methods

[Project README](../../README.md) · [Documentation index](../README.md) · [Data models](data-models.md) · [Population adjustment](population-adjustment.md)

This reference defines the implemented calculations and their interpretation. Use [data models](data-models.md) for grains and lineage, [population adjustment](population-adjustment.md) for estimands and weights, and [validation and evidence](validation-and-evidence.md) for dated counts and checks. Parameter defaults are listed in [configuration](configuration.md).

## Vocabulary and measurement

The source is League of Legends. A **champion** is a playable character; a **tier** is a competitive rank; **LP** means ranking points. **Mastery** is the source's accumulated character activity score. It covers several game modes and is neither hours played nor an observed match count. Dividing mastery by a points-per-game assumption does not recover observed games.

Roles are inferred from character metadata and associated players, rather than directly observed match positions. Specialization describes concentration of activity. Loyalty requires persistence over time and should not be inferred from concentration alone. Purchase history, ownership, customer types and account tenure in the transaction branch are simulated.

## Four analysis windows

| Window | Measurement and eligibility |
|---|---|
| Lifetime | Accumulated mastery at the latest retained snapshot. It provides historical context; collection does not cover the account's entire history. |
| Recent activity | Characters admitted by the recent-pool rule below, summarized using observed gains or equal membership weights. Preferred lens for the current audience. |
| Recent activity with rank follow-up | Recent profiles restricted to those with a nonmissing latest eligible rank-period outcome. This changes the cohort, not the activity formula. |
| Observed rank periods | Activity, classification and competitive outcomes aligned to retained historical periods. Starting rank belongs to the period. |

The latest outcome and the historical-period datasets have different eligibility and aggregation rules. Equal row counts do not establish equal membership. A positive-LP climbers view remains in the current code but is deprecated for the planned presentation rework; it is not another canonical window.

## Recent membership, shares and preferred characters

The [activity model](../../league_pipeline/models/gold/fct_players_champion_activity.sql) decides membership before the [recent-pool model](../../league_pipeline/models/gold/dim_players_recent_pool.sql) assigns shares.

With the default maturity threshold of 30 tracked days:

- Below 30 days, include a character when its last-play recency is between 0 and 30 days inclusive. No observed gain is required.
- At 30 days or more, require recency between 0 and 60 days inclusive **and** positive recent gain strictly greater than `max(3000 * min(days_tracked / 60, 1), 0.10 * player_total_recent_gain)`.

These conditions define membership. If the player's total recent gain is positive, each member receives its observed positive recent character gain as pool points; a member can consequently have zero share. Otherwise every member receives one point. Dividing by total pool points produces character shares. Equal shares therefore sometimes represent membership evidence rather than equal measured activity. A player with no qualifying members has no recent classification.

Lifetime shares use positive accumulated character mastery. For both lifetime and recent summaries, preferred characters (`favoured_*` in SQL) use a deterministic gap heuristic:

1. Sort descending points, breaking ties by character key, and retain at most 10 candidates.
2. Calculate adjacent log point ratios within those candidates, where the next value is positive. The tenth-to-eleventh gap is not considered.
3. Choose the largest gap, breaking ties toward the earlier position. Split there if the gap is at least `ln(2)` and either there are two candidates, the median gap is zero, or the gap is at least 1.5 times the median.
4. Otherwise retain all candidates. A single candidate is preferred by itself.

The preferred share is the sum of the selected characters' shares in the **whole** pool. It need not equal one. This heuristic identifies a useful concentration boundary; it is not a learned preference model.

## Concentration and classification

For shares `q_j` over `N` characters:

| Measure | Definition | Interpretation |
|---|---|---|
| Breadth | `N` | Number of represented characters. |
| Top-character share | `max(q_j)` | Concentration in the leading character. |
| Preferred count / share | Gap-selected count / sum of its shares | Size and combined prominence of the preferred pool. |
| HHI | `sum(q_j^2)` | Larger values indicate greater concentration. |
| Entropy | `-sum(q_j * log2(q_j))` | Zero shares contribute zero. |
| Normalized entropy | Entropy divided by `log2(N)`; zero when `N = 1` | Evenness within the represented pool. |

Two equally used characters and ten equally used characters both have normalized entropy one. Always read evenness alongside breadth.

The [classification macro](../../league_pipeline/macros/playstyle_score.sql) scores five features against configurable target profiles: `sum(weight_f * (1 - abs(feature_f - target_f)))`. Preferred count becomes `clip((count - 1) / (maximum_count - 1), 0, 1)`. Default weights, in the order below, are `0.30, 0.15, 0.25, 0.15, 0.15`.

| Label | Top share | Preferred share | HHI | Normalized entropy | Normalized preferred count |
|---|---:|---:|---:|---:|---:|
| Specialist | .75 | .90 | .60 | .25 | .10 |
| Multispecialist | .42 | .90 | .32 | .45 | .22 |
| Versatile | .30 | .75 | .20 | .70 | .44 |
| Generalist | .15 | .70 | .08 | .95 | 1.00 |

The highest score wins; ties resolve specialist, multispecialist, versatile, then generalist. These are descriptive SQL rules, not psychological categories or predictions of future performance. [Lifetime SQL](../../league_pipeline/models/gold/fct_players_lifetime_mastery_profile.sql) and recent-pool SQL own their application.

## Competitive outcomes and attribution

The [rank coordinate](../../league_pipeline/macros/rank_score.sql) assigns ordinary tiers Iron through Diamond indices 0 through 6, and Master/Grandmaster/Challenger index 7. The coordinate is `400 * tier_index + 100 * (4 - division) + LP`, with no division offset for apex tiers. LP change is a difference in this coordinate, allowing ordinary tier/division transitions to be compared. It is not simply the difference between two displayed within-division LP values.

The [eligibility macro](../../league_pipeline/macros/lp_growth_eligible.sql) requires positive observed games and `abs(LP_delta) <= 50 * games`. Counter resets are excluded by the period-building logic; special seasonal normalization is outside the current release.

At period grain, `LP_per_game = LP_delta / games`, win rate is `wins_delta / games`, and LP per day divides by the actual endpoint spacing, `period_in_days`. A queue/starting-tier baseline is pooled eligible LP change divided by pooled games. Period lift subtracts that baseline from period LP per game. Adding periods can change the baseline. A mean of player ratios answers a different question from a ratio of pooled totals.

Character outcomes are inferred in the [attribution model](../../league_pipeline/models/gold/fct_players_period_champion_growth.sql). Positive mastery-gain shares allocate outcomes to preferred characters. Shares remain relative to the entire positive-gain pool: mass belonging to other characters stays unassigned. Attributed games can be fractional. These are not directly observed character-specific ranked matches or wins.

The exported `climbing_efficiency` is a summary of period lift. In [player growth queries](../../streamlit_app/app_core/queries.py), it is the median eligible period lift per player/starting tier, additionally grouped by period classification in `growth_player_styles`. In [character growth SQL](../../league_pipeline/macros/champion_player_growth.sql), each player/character/starting-tier summary instead takes an attribution-share-weighted median: the first sorted lift whose cumulative share reaches half the total. Broader character summaries average these player-level medians. This attribution weighting is separate from population weighting.

Character player-level LP/game and win rate divide summed attributed outcomes by summed attributed games. Broader character `expected_lp_per_game` and `observed_win_rate` average those player-level ratios; the former is descriptive despite its `expected_*` name. Grouping gives one vote per player/character/starting tier, optionally within classification, rather than one vote per game or one distinct person across all groups.

Estimated ranked mastery share is `clip((1000 * wins_delta + 300 * losses_delta) / positive_period_mastery, 0, 1)` when games and gains are positive. This calculation does not itself require the LP/game eligibility cutoff. The coefficients are assumptions; the result is not an observed share of matches played in ranked mode. Missing values and LP-ineligible outcomes must retain their measure-specific meaning rather than becoming zero performance.

Tracked mastery accrual per day divides retained mastery deltas by the observed accrual span. The lifetime-profile implementation includes nonzero negative corrections in its delta sum. Its denominator is tracked time, not hours played, account age or a complete lifetime exposure.

## Audience comparisons

The [cooccurrence mart](../../league_pipeline/models/gold/mart_champion_cooccurrence.sql) counts recent-pool membership. Let `N` be players with a pool, `A` and `B` the character audience counts, and `AB` the shared audience:

- Jaccard: `AB / (A + B - AB)`.
- Conditional overlap: `P(B|A) = AB / A`; the reverse uses `B`.
- Lift: `AB * N / (A * B)`.
- Normalized pointwise mutual information: `log2(lift) / -log2(AB / N)`, where defined.

The default minimum shared audience is five players. Overlap indicates co-membership, not character switching, substitution, purchase intent or simultaneous play.

[Analysis helpers](../../streamlit_app/app_core/analysis.py) implement several distinct comparisons:

| Comparison | Definition and limit |
|---|---|
| Group composition | Category mass divided by eligible group mass; raw player counts remain separate from weighted mass. |
| Role skew | Percentage-point difference from the selected audience's overall category mix. Roles remain inferred. |
| Mastery-normalized composition | Observed category share divided by expected share at the group's median lifetime mastery. Separate window-specific baselines use up to eight pooled quantile bands; shares interpolate between band medians and use the nearest endpoint outside the range. Population mode weights shares and median centers; band boundaries remain sample-defined. A zero expected share gives an undefined ratio. This is a median-based descriptive adjustment, not full distribution standardization. |
| Mastery representation by rank | A character's rank distribution of mastery-point mass divided by the corresponding distribution pooled across characters. This uses mastery mass, rather than a simple count of people. |
| Fan distribution, currently `one_trick_*` | Default implementation selects account lifetime mastery at least 300,000 **AND** (recent top share at least .80 **OR** recent HHI at least .65), then assigns the recent primary character. Compare its rank distribution with zero-threshold character-holder counts. The final public Fan definition remains deferred. |

The [experience view](../../streamlit_app/app_core/experience.py) uses classified lifetime profiles and five pooled, approximately equal-count mastery bands. Stable source order breaks ties, so identical mastery values can cross a boundary. Bands are formed before optional Master exclusion. Rank groups are Iron–Silver, Gold–Platinum, Emerald and Diamond+. It shows raw specialist shares with 95% Wilson intervals; it is a descriptive sample view, not a causal decomposition or population adjustment. The default display support is three total classified players in the cell, rather than three specialists. Individual Wilson intervals do not provide simultaneous tests of every group difference.

## Simulated commercial measures

All measures below describe generated events attached to frozen real profiles. [Spending SQL](../../league_pipeline/models/gold/mart_player_spending.sql) defines player measures; [business helpers](../../streamlit_app/app_core/business.py) define dashboard aggregation. Lifetime means generated history; recent means the inclusive 60-day purchase window ending at the scenario as-of date.

| Measure | Denominator and behavior |
|---|---|
| Cash spending | USD on fiat events only. Buying in-game currency and later spending it are not two cash revenues. |
| USD per player | Cash USD divided by every player in the selected cohort, including nonpayers. |
| USD per cash purchaser | Cash USD divided by players with at least one cash event in the same window. |
| Purchaser share | Cash purchasers divided by selected players. |
| Payment frequency | Cash-active calendar months divided by inclusive calendar tenure from the first generated purchase of **any** currency to the as-of month. |
| Payment intensity | Cash USD per cash-active month; undefined without a cash-active month. |
| Payment consistency | `1 / (1 + population_SD(gaps) / mean(gaps))`, using gaps between distinct cash-purchase dates; requires at least two gaps. |
| Cosmetic fraction | Cosmetic events divided by character-plus-cosmetic content events; cash top-ups are excluded. The view averages player fractions, which differs from a pooled event share. |
| Discounted purchase share | Discounted fiat events divided by all fiat events. |
| Discount depth | Mean fractional reduction conditional on discounted fiat events. Aggregate player means using their discounted-event counts, rather than giving each player equal weight. |

Simulated account age starts at the first fictional purchase. Activity bands are relative mastery-based proxies, even where current code retains a `playtime` name; they do not measure hours. Empty denominators produce missing measures where undefined. Zero spending for a nonpayer is meaningful and is retained.

## Support and uncertainty

Support rules are method-specific. Pair support, display controls and direct-standardization support are separate settings; no new universal minimum is implied by this reference. [Population adjustment](population-adjustment.md) defines the current five-observation standardization rule and coverage warning.

The current [growth story](../../streamlit_app/app_core/story_analysis.py) uses 2,000 row bootstrap resamples with seed 42 for eligible per-player outcome summaries, with a minimum of three supported rows per style. Its anonymous input cannot identify repeated players for clustering. A separate historical verification used 10,000 player-cluster resamples with a fixed baseline. Those intervals are not interchangeable. An interval containing zero does not prove zero effect.

The story's detectable-gap calculation is a two-group normal approximation using pooled within-style variance, two-sided alpha .05 and target power .80. It does not measure achieved power or establish a release requirement. Direct-standardized means currently have no calculated confidence interval. A common support/uncertainty policy and any future rank-skew summary remain deferred analytical work.
