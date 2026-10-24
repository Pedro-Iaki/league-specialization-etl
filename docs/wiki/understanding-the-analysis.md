# Understanding the analysis

[Project README](../../README.md) · [Documentation index](../README.md) · [Architecture](architecture.md) · [Metrics and methods](../reference/metrics-and-methods.md)

The analysis asks which behavioral patterns define useful audiences, how those audiences differ and what customer questions those differences could help investigate. Two people with similar spending can still prefer very different content. Behavioral context gives a transaction model more detail than a spending category alone.

The available source is League of Legends. Its players choose characters, called champions, and can participate in competitive play with visible ranks. Riot's API supplies rank and character activity observations. **Purchases in this project are simulated**: they demonstrate the analytical connection to customer questions, without revealing actual buying behavior.

This chapter explains how to read the comparisons. Exact formulas, defaults and eligibility rules live in [metrics and methods](../reference/metrics-and-methods.md).

## Start with the audience and the window

A character audience can mean several things: people who hold an activity record for that character, people whose inferred recent pool includes it, or people who concentrate heavily on it. Those groups answer different questions. A holder is not automatically a current fan, and audiences for several characters can contain the same person.

The four analysis windows keep accumulated context, current interests and observed outcomes separate:

| Window | Useful question | What to keep in mind |
|---|---|---|
| Lifetime | What has this person accumulated across characters? | An old favorite can dominate the activity score after interests change. This is not a complete lifetime match history. |
| Recent activity | Which characters appear relevant to current behavior? | Membership is inferred from recency and, with sufficient tracking history, activity gains. |
| Recent activity with rank follow-up | How do recent profiles compare among people with a usable latest outcome? | The outcome may be positive, zero or negative. Filtering changes the audience, without making activity ranked-only. |
| Observed rank periods | How did period-aligned behavior compare with rank movement over retained intervals? | Completed periods and usable outcomes have additional observation and eligibility requirements. |

For current audience membership, begin with Recent activity and use Lifetime as context. A hypothetical person with years of activity on character A but a recent focus on B illustrates why the two can disagree. That disagreement can be useful evidence of changed interests rather than a classification error.

Recent activity is still an estimate. With fewer than 30 tracked days, the default rule admits characters last played within 30 days, without requiring a measured gain. Pool shares use observed gains when available and equal membership weights otherwise. Thus an evenly divided recent pool can describe equally weighted evidence of membership rather than equally measured use. The included frozen export has short tracking histories throughout; [dated support counts](../reference/validation-and-evidence.md#cohort-counts-branch-by-question) show how much of it uses each weighting basis.

## Describe both focus and breadth

The activity score, or mastery, is a cumulative source measure associated with playing a character. It is a useful preference signal, but it does not directly measure matches, hours or skill, and it can increase outside competitive play.

Several measures describe its distribution. Top-character share shows how dominant the leading choice is. Preferred-character count describes the size of the more prominent set. Concentration and evenness measures describe how activity is distributed within a pool.

For example, two equally used characters and ten equally used characters both have perfect normalized evenness. Their breadth is very different. Reading only the evenness score would hide that difference; reading only the count would hide whether one character dominates.

The four labels—specialist, multispecialist, versatile and generalist—summarize these features through configurable SQL scoring. They are descriptive rules, rather than learned predictions or psychological types. A recent label and a Lifetime label can differ. Concentration also does not establish loyalty: persistence would need to be measured over time.

The intended plain label **Fan** refers to a more specific character-focused selection. The current code still uses `one_trick_*` names and an explicit activity/concentration filter; its final public definition remains deferred. Use the [implemented rule](../reference/metrics-and-methods.md#audience-comparisons) when interpreting those outputs rather than assuming every specialist is a fan of their leading character.

## Compare audiences through the right denominator

Character summaries describe the people associated with a character. They can show activity depth, rank composition and inferred roles. Roles are estimated from character metadata and associated players, rather than observed positions in individual matches. A role chart therefore needs its audience definition; it is not a direct character lane-use rate.

Audience overlap asks how often two characters occur in the same recent pools. Conditional overlap also has a direction: the fraction of A's audience associated with B need not equal the fraction of B's audience associated with A. A very popular character can overlap with many audiences simply because it is common; lift compares the overlap with what the two audience sizes would suggest.

Shared audiences can suggest content or recommendation hypotheses to investigate. They do not establish switching, competitive synergy or a recommendation's effectiveness. Similarly, combining character-holder records can count one person several times; it does not automatically produce the reach of a distinct audience.

## Separate rank composition from rank movement

A rank-distribution chart describes where an observed audience sits. It does not show which people improved or whether their character choice helped them do so. The project's small higher-rank groups also inherit discovery and refresh selection, so they should not be treated as representative samples of all high-ranked players.

Historical comparisons instead pair retained rank observations and use actual endpoint spacing. At the default weekly setting, usable completed periods need adjacent buckets, suitable spacing and no intervening counter reset. LP/game comparisons additionally require positive observed games and a bounded ranking-points change per game. A player can have a current profile without qualifying for that outcome.

Period lift compares ranking points per game with the pooled eligible baseline for the same queue and starting rank. Higher lift means a result above that observed baseline, rather than proof that a behavior caused improvement. The baseline can change when periods are added. Summaries can aggregate period lift within each player before comparing groups; this differs from pooling all game totals. [Growth definitions](../reference/metrics-and-methods.md#competitive-outcomes-and-attribution) explain those aggregations.

Character-level outcomes add another inference. The model allocates period outcomes according to positive activity-gain shares for preferred characters, leaving other mass unassigned. Fractional attributed games are therefore expected. They are not directly observed character-specific matches or wins.

The separate estimate of competitive activity assumes activity-score gains per win and loss. It is sensitive to those coefficients and does not reveal an observed fraction of matches or hours spent in competitive play. These distinctions keep progression useful as one audience feature without turning it into a general climbing recommendation.

## Account for different rank and experience mixes

The collected sample does not mirror the supplied rank distribution. Pooling its rows gives the collected sample's result, which can differ from an estimate adjusted toward that reference. There are three distinct ways to summarize a selected audience:

| Approach | Interpretation |
|---|---|
| Collected sample | Give each eligible observed person equal weight. |
| Inherited population weights | Adjust the calibration cohort's rank mix, then retain those weights when selecting an audience. The selected audience can still have a different rank mix. |
| Direct-standardized mean | Select an audience, calculate supported rank-specific means, then combine them under a common supported reference mix. |

These are different questions, so disagreement between their values is not automatically a defect. Guided behavioral pages use reference-weighted shares and supported means, calibrated on the full profile base before filters. Customer charts use unweighted scenario rows. The raw experience explorer retains its sample-based definition. Adjustment cannot supply missing outcomes or fix selection within ranks. The [population reference](../reference/population-adjustment.md) explains calibration, support and effective sample size.

The guided story starts with accumulated activity and recorded ranked volume. These separate past investment from competitive engagement at the observed counter date; ranked games are not a verified current-season frequency. The optional oldest retained play marker gives a lower bound on history, not account creation. Fixed activity, engagement and history ranges survive every subsequent slice. Page 3 adds rank through P(activity band | rank group), with saved reference prevalence shown separately from a filtered audience's composition. Axis inversion preserves that conditional question.

Page 4 adds the accepted 25 overlapping character families. Each player's affinity is lifetime mastery among model-active characters, with a 15,000-point numerator cutoff and all active mastery in the denominator. A character can contribute to several families, so affinities are not additive probabilities. A unique highest score gives the simple primary label; ties and missing evidence remain visible. Top affinity and the gap to the next coordinate show how distinct that label is without forcing a new taxonomy. The [family contract](../reference/character-family-cohort.md) documents its selected evidence and limits; adoption is not independent validation.

Inferred character types A–E complement families and map to Top/Jungle/Middle/Bottom/Support in League wording. They use the existing Recent-pool role weighting, not the family's lifetime weights. Unknown type is excluded only from type-specific charts, with coverage disclosed. Whole-history focus and positive-family breadth are optional detail after the main audience definition. The progressive map preserves activity/rank geometry and offers mean family affinity among scored pools or primary share of the whole cell; it does not repeat a leading-character surrogate. These cross-sections do not show switching, rank movement or a causal recommendation. Approximate hour labels assume 600 points and 30 minutes per match, change no band membership and do not measure actual playtime.

## Connect behavior to commercial questions

With an authorized real purchase source, an analyst could investigate whether character-focused audiences buy related cosmetics, how buying patterns differ across audiences, or whether a content group appears underserved. Those questions would need purchase exposure, timing, availability and other relevant context. Return on investment would also require costs and an appropriate comparison.

The included scenario demonstrates that connection using generated purchases attached to frozen real profiles. Its spending patterns are configured assumptions, rather than discoveries about actual customers. A simulated association is useful for inspecting joins, currency treatment, denominators and reporting behavior. It cannot establish demand, price sensitivity, promotion effectiveness or real revenue lift. [Simulated transactions](simulated-transactions.md) follows that branch in more detail.

## Check support before interpreting a result

The proposed Interests chapter uses archetypes to slice audiences and compare previously introduced activity, history and standing dimensions. Assignment prevalence is not presented as a comparable popularity ranking: family size, champion prevalence, overlap and training composition influence it. Selected reach describes support; conditional comparisons describe associations. Popularity normalization remains an explicitly separate research question.

The proposed story now uses the [eight player-pool archetypes](../reference/player-pool-archetypes.md) as its readable interests summary, followed by underlying family explanations. The implemented candidate supports strongest-match and overlapping expressed-interest selections, with explicit scored, weak-match and missing-evidence states. The planned audience-comparison and purchase chapters carry those selections alongside activity, history and standing. Current story pages have not yet been redesigned or promoted to that candidate.

Read the cohort, window, counting unit, estimator and date alongside a comparison. Current profiles, classified recent profiles, latest-outcome profiles and historical growth rows form different branches. Missing follow-up can mean insufficient observation or ineligibility; it should not become zero performance. The current profile also uses the dataset's latest completed bucket, without falling back to each person's older usable period.

Observed counts describe how many eligible rows support a result. Effective sample size describes concentration in a particular set of weights, rather than additional observed people or a confidence interval. Support rules and uncertainty methods vary by calculation; direct-standardized means currently have no calculated interval.

Growth comparisons remain inconclusive. The reviewed historical bootstrap intervals included zero, which does not prove equal outcomes or no effect. The [methods reference](../reference/metrics-and-methods.md#support-and-uncertainty) distinguishes that verification from the retained older row-bootstrap helper. [Validation and evidence](../reference/validation-and-evidence.md) records the snapshot, branching counts and limits of the available checks. The analytical value is a traceable description of audiences and testable hypotheses, with stronger customer claims reserved for suitable real outcomes and study designs.
