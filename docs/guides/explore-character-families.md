# Explore character audience families locally

[Run the dashboard](run-the-dashboard.md) · [Metrics and methods](../reference/metrics-and-methods.md)

The optional **Local laboratory → Character families** page discovers candidate groups from shared active-character audiences. It is a review tool for parameter exploration, naming and manual assignments. Saving a scenario does not adopt it as a validated taxonomy or change story pages.

## Prepare the local input

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r streamlit_app/requirements-families.txt
.\.venv\Scripts\python.exe streamlit_app/scripts/export_character_families.py
.\.venv\Scripts\python.exe -m streamlit run streamlit_app/app.py
```

Only the export command requires the existing Databricks connection configuration. It reads existing marts/current mastery without changing models or refreshing transactions. The laboratory subsequently uses local files without warehouse access. The navigation section appears when `data/character_families/membership.parquet` exists. Restart a previously running app if its file watcher is disabled.

The local export contains one anonymous row per profile with its active-character keys, names and accumulated mastery. It carries no player IDs and does not join independently anonymized public files. A manifest binds its contents to a SHA256 hash and export/source dates. The local warehouse snapshot can be newer than the bundled public snapshot; they remain separate. `data/` and saved scenarios remain ignored by Git. The laboratory currently uses English controls.

## Find a useful scenario

1. Start with all ranks, all tracking histories, reference weights and the 15,000-point member cutoff. Weights are calibrated on the base export before filters. Unsupported reference tiers have no fabricated observations.
2. Enable **Automatic stability checks** to apply discovery changes immediately and refresh both seed and player-bootstrap diagnostics. With the toggle off, use **Find candidate families** to apply discovery changes, or **Run both stability checks** to apply them and evaluate both. Pending settings are labeled; previous results are never presented as checks of the new definition.
3. Inspect the overview, family matrix and outside neighbors. Change resolution to explore wider/narrower groups. Minimum character/edge support, a Jaccard floor, strongest-neighbor count and reciprocal-neighbor requirement control the graph. Minimum accepted size leaves small groups unassigned; maximum detected size constrains Leiden rather than proving a natural family size.
4. Compare **Observed repertoire (Jaccard)** with **Specific affinity (breadth-adjusted)**. The latter weights edges by positive log₂(observed/expected) overlap, conditioning the expected overlap on pool-size ranges 2; 3–5; 6–10; 11–20; 21–50; 51+. Both use the declared raw-support and Jaccard floors. The matrix and directional rates remain observed associations.
5. Repeat with other mastery cutoffs, weighting choices and tracking-history subsets. A family that weakens under breadth adjustment can still describe a useful observed repertoire. Neither view resolves whether a character type causes generalism.
6. Compare **Random seeds** for algorithm sensitivity with **Player bootstrap** for sample sensitivity. Both have their own top summary and small plot. **Repeats per check** applies equally to both; changing it refreshes both in automatic mode. The bootstrap resamples entire selected profiles, retaining their frozen reference weights. It does not independently resample pair rows or recalculate population weights. Co-member Jaccard compares each character's other family members across runs and is independent of family ID labels. This diagnostic is not a universal publication threshold or a correction for selection bias.

Seed repeats reuse the already constructed graph and vary only the community-detection seed. Bootstrap repeats rebuild relationships for their resampled players. The accelerated implementation preserves support thresholds, tie ordering, repeat counts and diagnostic definitions; it avoids repeated graph construction and per-row table lookups rather than reducing the work being evaluated.

The method uses weighted Jaccard and strongest-neighbor graph construction followed by [Leiden community detection](https://www.nature.com/articles/s41598-019-41695-z), with the [resolution-capable RB configuration partition](https://leidenalg.readthedocs.io/en/stable/reference.html). The selected representation and thresholds are project choices. No predetermined number of families is required. Isolated, unsupported and too-small groups stay unassigned.

## What each control does

Hover over the question mark beside a control for the same practical explanation. Change one setting at a time and save useful comparisons; changing several together hides which choice caused a difference.

| Control | Practical meaning | What happens when you change it |
|---|---|---|
| Rank tiers | Whose choices build the families. | A rank-specific audience can have different repertoires. Keep fixed while comparing graph settings. |
| Tracking history | How long this project observed a profile. | This is not the player's experience or account age. Membership rules differ between short and mature histories. |
| Population weights | Adjust the influence of rank tiers toward the saved reference. | Off gives each observed profile equal influence. Neither setting removes all collection bias. |
| Minimum mastery per character | How much accumulated experience a character needs to count in someone's active set. | Higher removes minor choices, but can hide genuine secondary interests. Compare 15,000 and 30,000; neither is a proven ideal. |
| Minimum profiles per character | How many qualifying observed players a character needs to enter discovery. | Higher removes poorly supported characters, particularly niche ones. It does not guarantee reliable placements elsewhere. |
| Minimum shared profiles | How many observed players must qualify for both characters before their connection can count. | Higher removes rare connections and may hide smaller families. Counts remain raw even when weighting is on. |
| Exclude characters | Remove particular characters and their graph connections temporarily. | Tests whether a bridge drives a placement. It does not justify deleting an inconvenient character permanently. |
| Association method | Shared repertoires versus relationships unusually strong among similarly broad players. | Adjusted mode asks a different question; it is not a quality upgrade over Jaccard. The displayed matrix still shows Jaccard. |
| Minimum Jaccard | Minimum shared audience as a fraction of the audience playing either character. | At 0.10, at least 10% of the combined audience plays both. Higher removes weaker overlap; it applies in both association modes. |
| Strongest neighbors | Maximum number of strongest connections retained per character. | Fewer emphasizes local neighborhoods; more retains broad connections and can introduce bridges. Neither direction guarantees improvement. |
| Reciprocal connections | Both characters must select each other as a strongest neighbor. | Can reduce one-sided bridges, but may isolate niche characters. Compare on/off before adopting it. |
| Resolution | How broadly the graph is divided. | Lower usually gives wider groups; higher gives finer divisions. It changes the level of detail, not accuracy. |
| Minimum family size | Smallest detected group to keep. | Smaller groups become Unassigned after detection; they are not merged. Use 2–3 while exploring pairs/trios. |
| Maximum family size | Hard cap on detected group size. | Small caps can force coherent families apart and distort borderline placements. Start with 0, meaning unlimited. |
| Random seed | Repeatable starting randomness of the algorithm. | Different seeds test fragility. Do not choose a seed solely because a favorite character moves where expected. |
| Automatic stability checks | Apply discovery changes and evaluate both check types immediately. | Off supports manual application. Chart/character selections, names and review-target edits reuse existing diagnostics. |
| Repeats per check | Number of repeated runs for each method. | More gives a steadier diagnostic and takes longer. Start with 10; increase for a shortlist. |
| Co-member review target | Reviewer-selected boundary for the below-target share. | Changes both summaries and plot markers without rerunning discovery. It is not a validated quality boundary. |

## Read the stability overview

The main discovery filters come first, followed immediately by the check controls, **automatic family count**, and side-by-side **Random seeds** and **Player bootstrap** summaries with compact distribution plots. Audience filters and advanced connections expand within the filter panel. Each method shows four metrics: mean Jaccard, below-target share, assigned rate and coverage. Initially only coverage/family count is known; missing checks show a pending message rather than a fabricated score. The compact desktop layout keeps the main filters and summaries together; narrow screens stack them. Detailed charts, per-family results and per-character tables remain available farther down through **Detailed check**. These are repeatability measures, not percentages of correctly classified champions.

| Summary option | Strength | Limitation / implemented use |
|---|---|---|
| Mean co-member Jaccard | One comparable overall number. | Can hide weak cases; shown as a headline alongside the below-target share. |
| Median and 10th percentile | Typical result and the lower end of the distribution. | Supplementary readout; neither identifies the affected characters alone. |
| Share below a review target | Quantifies how much needs attention. | Target is a reviewer choice, default 80%, not a validated pass/fail boundary. |
| Box plot with points | Shows spread, skew and outliers without bins. | Default chart; hover points for characters/families. Mean and median are both shown. |
| Jaccard-versus-retention scatter | Reveals characters that stay assigned but change neighbors. | Alternate chart; exact coordinate ties overlap. |
| Per-family summary | Locates unstable groups hidden by a good global mean. | Expandable table, ordered from lowest mean Jaccard. |

The four cards in each method are **mean co-member Jaccard**, **share below your review target**, **mean assignment retention**, and **initially assigned coverage**. Every character has equal weight in these summaries, even when population weights were used to build the graph. Larger families contribute more characters; inspect the family table to avoid hiding a small weak family. The top family count describes the automatic definition used by the checks; manual reassignment and titles below do not redefine that diagnostic baseline.

Co-member Jaccard compares the other members of a character's original family with its other family members in a repeat. It is intersection divided by union, averaged over repeats for that character. A character moving from neighbors B/C to B/D has Jaccard 1/3 for that repeat. The headline mean then averages character scores. It is not the overlap between player audiences and does not depend on matching family IDs.

Assignment retention asks whether an initially assigned character belongs to any accepted family in a repeat. A value of 100% can coexist with weak Jaccard when the character keeps changing families. Initial coverage separately shows how many snapshot characters were assigned in the original run, including unsupported/excluded characters in that coverage denominator. A stable-looking model covering very few characters should not be compared with a broad model by mean alone.

Initially unassigned characters have no original family, so their Jaccard is unavailable and they are excluded from the Jaccard and retention headlines. Their actual assignment rates in repeat runs are measured and remain available in the detail table. Missing values never become zero; an observed Jaccard of zero is retained. Counts beside the metrics disclose how many characters were scored. New diagnostic exports carry `metric_version: 2`, distinguishing the corrected assignment-rate handling from earlier exports.

Changing the review target updates summaries and the dotted chart marker without rerunning discovery. It does not filter weak characters out. In the box view, the target marker appears only on the Jaccard row. Boxes show the middle half, the internal solid line is the median, and the dashed line is the mean. Points retain their exact scores; vertical jitter only separates points in each row. In the scatter, the upper-right area means consistent neighbors and retained assignment, while upper-left means retained assignment with changing neighbors.

The JSON scenario includes the chosen target and both numerical summaries with their raw diagnostic rows under `stability_checks`. The older single `stability` field remains readable and holds the bootstrap result when available. Loading a scenario restores saved diagnostics, repeat count and review target; older scenarios containing one method display that method and leave the other pending. Diagnostics refer to the automatic baseline; manual membership edits are not validated by them. Seeds-only and player-bootstrap runs remain different tests, so compare like with like and keep the number of repetitions visible.

## Evaluate each family and its weakest members

**Consistency of each original family** sits immediately beneath the discovery panel. It uses player-bootstrap pair evidence and keeps families separate, so a weak family cannot hide nine strong ones behind an overall average. Older scenarios need a new bootstrap run to supply this evidence.

The gold point is the full family's mean off-diagonal co-membership frequency, equivalent to averaging its members' own-family consistency. Small points show the individual members; pink identifies those below the current review target. The blue diamond recalculates mean pair frequency after removing the least consistent members. The default removal fraction is 20%, rounded up, retaining at least two; the detailed table discloses the actual count, names and uplift in percentage points. Pairs cannot be reduced. This is a diagnostic comparison, not a new assignment or independent validation: weakest members were selected using the same repeats.

Read the comparison with median separation from alternative families. Strong cohesion with poor separation can arise when two original families repeatedly merge; it does not establish two distinct robust families. The headline counts show families that meet both cohesion and separation targets, those whose cohesion reaches the target only after weak-member removal, and the remainder. The table distinguishes cohesive groups with loose members, sensitivity to weakest members, overlapping alternatives, and loose groups or possible subgroups. A persistent subgroup inside a divided family may still have a low whole-family score; the pair heatmap remains useful. All targets are review choices, not calibrated confidence thresholds.

## Generate overlapping final memberships

Expand **3 · Refine overlapping memberships** after the stability summaries. This is a separate third operation after discovery and bootstrap evaluation. Set the single-family threshold (default 80%) and shared threshold (default 40% for each family), then select **Generate final assignments**. It reuses the existing pair evidence without running discovery or bootstrap again. Changed thresholds or changed bootstrap evidence invalidate the generated view until regeneration.

| State | Rule, evaluated in this order | Final output |
|---|---|---|
| Both | Own and strongest-alternative consistency each meet the shared threshold. | Both families; higher score becomes final primary, with original family winning exact ties. |
| Primary only | Otherwise, own consistency meets the single threshold. | Original family only. |
| Secondary only | Otherwise, strongest-alternative consistency meets the single threshold. | Alternative promoted to final primary. |
| Indecisive | None applies. | No forced final assignment. |

The shared threshold cannot exceed the single threshold. The **Both** rule takes priority: 90% own and 45% alternative qualifies for both with defaults. Zero evidence never creates membership, even if a reviewer sets thresholds to zero. Originally unassigned characters can qualify through a strong alternative; a singleton original has no own-peer score. Only the strongest alternative is evaluated, so output is capped at two families.

These scores are companionship frequencies rather than mutually exclusive membership probabilities. Both families can score highly because of repeated merging, not necessarily two independent audience preferences. Review family separation and the heatmap before accepting the output. Generating assignments from these repeats does not independently validate the resulting memberships.

Scenario JSON stores the valid generated view under `refinement`, including source fingerprint, rules, per-character states, and a long membership lookup. **Download final assignment review CSV** includes indecisive characters; **Download refined memberships CSV** in the save panel has one row per accepted character/family membership. Indecisive characters have zero membership rows. Loading restores rules and recomputes final rows from matching saved pair evidence; original discovery groups and the manual assignment editor remain separate reference views. Existing affinity charts use the manual editor's exclusive mapping. Overlapping membership rows are binary links without allocation weights: counts across families are not additive, and future audience integration needs explicit union or attribution semantics.

## Handling bridges and questionable placements

An audience family groups shared players. It need not align perfectly with lanes, gameplay mechanics or visual character design. A cross-type placement may reveal a real audience connection, an ambiguous bridge, a hard-constraint artifact, or weak evidence. A familiar champion classification alone cannot distinguish those cases.

First remove a hard maximum-size cap and inspect small groups rather than automatically discarding all pairs/trios. Compare reciprocal neighbors while keeping the selected people, mastery cutoff, weights, resolution and seed fixed. Then inspect the selected character's connections to several members of its proposed family, its strongest outside family, and both the Jaccard and adjusted evidence. Temporarily excluding suspected bridges tests whether one or two connections carry the assignment. Preserve those as sensitivity scenarios rather than overwriting a preferred result.

Use **Family cores and flexible members** to inspect the player-bootstrap pair evidence. Each repeat contributes one count when two characters belong to the same accepted family, regardless of the numerical family ID. Two unassigned characters never count as companions. Dividing by all repeats produces a symmetric co-membership matrix; rates are unconditional, so loss of assignment reduces consistency. Collection happens inside the existing repeats and does not run additional clustering.

| Character measure | Definition and use |
|---|---|
| Own-family consistency | Mean pair frequency with the other members of the original automatic family; self is excluded. Reveals how much of the original group survives. |
| Strongest alternative | Other original family with the highest mean pair frequency. Groups stay fixed for this comparison even when repeat partitions split, merge or change IDs. Exact ties use the first family ID. |
| Alternative consistency | Mean pair frequency with all members of that alternative. A strong single connection is diluted when the rest of the alternative does not travel with it. |
| Separation | Own minus alternative consistency, displayed and exported as percentage points. Negative values favor the alternative; a small gap suggests ambiguity. |
| Assigned rate | Fraction of repeats in any accepted family, including for originally unassigned characters. |

The sortable table can show all original families or one selected family. **Adjust review highlights** changes working targets for own consistency, separation and assignment retention without rerunning checks. The resulting labels flag strong core signals, close alternatives, weak ties, stronger alternatives, frequent unassignment, or missing original peers. These are review prompts, not calibrated confidence or automatic reassignments. Originally unassigned characters and singleton originals have no own-family consistency; one-family results have no alternative/separation.

The accompanying heatmap follows strongest remaining pair links within each original family, placing persistent companions together. Full-view boundaries mark original families and expose connections across them; selecting one family makes labels readable. Self-pairs are hidden. A family containing two coherent subgroups can have modest own-family averages but two dark blocks: inspect these before treating all low-average characters as peripheral. The ordering is a visual aid, not a new clustering result. With 10 repeats, pair rates move in 10-point steps; use more repeats for shortlisted definitions.

The character consistency CSV exports every character, including unresolved cases, with `separation_pp`. New scenario JSON files retain the full matrix and its character keys under each check's `co_membership` field. Old scenarios load normally but need **Run both stability checks** to populate pair evidence. Scalar Jaccard/retention definitions and their `metric_version: 2` are unchanged. Manual assignment edits do not change the automatic reference groups used here. Comparing nearby parameter settings remains a separate sensitivity review.

Keep audience similarity separate from a gameplay/design explanation. Character presentation, lore and mechanics can be coded as inspectable metadata and compared with the discovered groups. A pattern involving female-presenting characters is a hypothesis about character choice; it does not establish player gender, motive or that aesthetics caused it. Avoid an invented score for how much a character's audience values aesthetics. For a hybrid model, add a separately reviewed metadata view and compare audience-only, metadata-only and combined results. Such a hybrid would be an analyst-designed archetype with explicit feature weights, not a purely discovered audience family.

## Review names and membership

The assignment table lets you move characters to another family ID, create a new ID or use `Unassigned`. Edit titles and descriptions below it. A–E character types remain distinct from these audience families. Algorithm constraints and stability diagnostics describe the automatic discovery; manual overrides need their own interpretation. Family IDs are scenario-specific and may change after another run.

Discovery and the manual editor use exclusive family membership. The optional refinement operation produces a separately exported overlapping view from bootstrap consistency. Avoid labeling these shared audiences as verified gameplay-design causes.

Affinity sums qualifying active members' Lifetime mastery within a family and divides by all active-pool Lifetime mastery. Below-cutoff and unmapped mass remains in the denominator. Profiles without a positive known pool have unavailable affinity. The page distinguishes mean affinity from the fraction with at least one qualifying family member and shows their eligible support. Neither measure is a recent match share.

The source membership rule combines short-history 30-day recency with mature 60-day recency and gain requirements. The cutoff applies to every member in this lab; the story's existing cutoff applies only to its leading-character reporting. These are different reporting definitions.

## Save and resume exploration

Expand **Save a scenario**, beside **Load a saved scenario** at the top, to access save/download controls. Collapsing it preserves your unfinished name and notes. **Auto-name scenario** suggests an editable name using the displayed automatic family count (`F`), bootstrap mean Jaccard (`B`), seed mean Jaccard (`S`), bootstrap share below the current review target (`U`), character coverage (`C`), and the association, resolution, neighbor count, Jaccard floor and reciprocal/either connection rule. Percentages are rounded; `na` means a check is unavailable. `p` replaces decimal points to keep filenames valid. It names the computed definition when unapplied filter changes are pending. Full settings and precise metrics remain in the JSON.

Choose a scenario name and save locally, or download its JSON and mapping CSV. Local saves receive unique timestamped filenames under `data/character_families/scenarios/`, preserving earlier reviews. JSON records source/reference fingerprints, filters, exclusions, settings, software versions, automatic/manual final assignments, titles, notes and any stability diagnostic. It contains no per-player data.

Load a saved local scenario or upload its JSON to restore settings, assignments and names. A different membership source is rejected. Rerunning with new settings creates a new review state; export a scenario before leaving a configuration you want to retain. The CSV is a convenient named lookup, while JSON is the reproducible review artifact. Future audience integration needs an explicitly chosen scenario and its matching source, not an anonymous-row-order join.

## Compare scenarios in a batch

Open **Local laboratory → Family cohort builder** (`/batch-scenario-viewer`, retaining the original bookmark). In **Evidence library and batch settings**, select local JSON scenarios, use **Select marked scenarios** or **Select all saved scenarios**, and/or upload multiple scenario JSON files. Marked (`!`) files are selected by default. Set the common bootstrap repeat count/seed, family consistency target, weakest-member removal fraction and final assignment thresholds, then select **Run batch comparison**. Scenario comparisons and detailed charts remain available under **Scenario evidence and comparison** below the builder.

The original groups are rediscovered using each scenario's saved settings and audience filters. Whole-player bootstrap draws use the same repeat seed and count (defaults 42 and 20); candidates with equal cohorts therefore receive the same player resamples. Frozen population weights remain attached to the original base cohort. Matching saved bootstrap evidence is reused only when settings/signature, regenerated original groups, repeat count, repeat seed and software versions agree. Missing, incompatible or invalid pair evidence is recomputed. Saved JSON files remain unchanged. Repeated comparisons are cached; changed review thresholds, removal fraction or chart selections reuse the existing evidence. Changed selected files, repeat count/seed, membership source or population reference require a new batch run. Invalid scenarios are listed separately and never represented by fabricated zero scores.

The comparison table and two stacked-bar charts show final **Primary only / Secondary only / Both / Indecisive** character counts alongside each scenario's family counts in these mutually exclusive categories:

- **Full:** mean pair consistency of all original family members meets the target (default 80%).
- **Retained only:** full mean is below target, but the mean recalculated among retained members reaches it.
- **Below:** both full and retained means are below target.
- **No score:** no original peers, rather than a measured zero.

These categories follow cohesion alone. Separation remains a separate detailed diagnostic: high cohesion can coincide with recurring merges into another family. The final assignment rules are shared across the batch and use the same four-state precedence as the single-scenario laboratory. Higher single-family counts are not automatically a better definition; interpret alongside family granularity, coverage, unresolved characters and consistency. Cohorts can differ between saved scenarios, so counts are descriptive comparisons rather than controlled estimates of setting improvements.

### Find small families that cover the catalog

**Small families, complete coverage** combines viable families across the successful scenarios. It counts unique character IDs against the full snapshot catalog, including excluded or unresolved characters in the denominator. **Full families only** uses all members of original groups meeting the consistency target. **Full + retained** also includes the kept members of groups whose full mean fails but retained mean passes. Removed outliers and below-target groups contribute no coverage. A full family's retained version is not introduced as another candidate; the catalog consists of qualifying original families and qualifying retained-only groups.

The size curve shows coverage as larger groups are allowed. Its horizontal axis is the maximum number of characters in an included family, using retained size for retained-only candidates. In **Coverage settings**, **Minimum included family size** filters the coverage totals, gaps, size curve and suggested cover; set it to **3** to exclude pairs, or higher for larger groups. It defaults to 2. Retained-only candidates must have at least this many kept members, regardless of their original size. The optional **Maximum included family size** additionally filters the totals, gaps and suggested cover. The curve ignores that upper limit, while **All viable families** ignores both limits so all alternatives remain inspectable. Size changes reuse the existing bootstrap evidence.

**Smallest-family cover** finds each character's smallest available viable family. The largest of these per-character minima is the exact smallest size limit that permits complete coverage within the selected candidate pool. If some characters have no viable option, complete coverage is unavailable and those gaps are named. Choose full-only or full-plus-retained evidence to compare the result.

The suggestion keeps at least one minimum-size option for every coverable character. It selects smaller groups first, then those supplying more still-needed minimum-size options, then stronger pair consistency; redundant choices are removed. The number of chosen groups is a greedy convenience, not a claimed minimum. This objective favors fine audience slices rather than the fewest groups. Groups can overlap, and a broader group can remain necessary for a character lacking a smaller viable option. The character table identifies that character's minimum size and suggested source.

### Prefer a target size while preserving coverage

In **Suggested cover**, change **Selection approach** to **Target-size cover**. The default ideal interval is **10–15 characters**. Families outside it stay eligible: the interval expresses a preference rather than an exclusion. **Preference for ideal size** balances family count against each character's best selected size fit. At 0, size has no influence and selection favors fewer, more consistent families; higher values give size fit more weight. Consistency eligibility remains controlled by the shared family target, using the same full-only or full-plus-retained candidates.

By default this mode ignores the hard minimum and maximum in **Coverage settings**, allowing fallback families to cover characters absent from preferred-size groups. **Apply coverage size limits to target cover** explicitly enables those hard exclusions. The coverage totals, curve and gap tab above retain their existing size-filtered meaning; the target cover reports its own coverage and effective settings. No method can cover a character absent from every eligible family, so such gaps are named rather than silently removed from the denominator.

For a family of size `s`, its proportional distance `d` is 0 within the ideal interval, `log2(low / s)` below it, or `log2(s / high)` above it. Halving a below-range family and doubling an above-range family each increase distance by 1. With an ideal interval of 10–15, sizes 8, 4, 20 and 40 have distances approximately 0.32, 1.32, 0.42 and 1.42. The raw member-count gap remains available as **Size gap**, alongside **Proportional size gap**. Set `w = 10 × preference`. The greedy cost is `1 + (1 - consistency) + w × d`; select the family with the highest **newly covered characters / cost**, recalculating new coverage after every choice. Ties use family ID order, so the same input produces the same result regardless of row order. Already-covered candidates have zero gain.

The second pass evaluates adding, removing or swapping one family. Each move must preserve coverage of the greedily covered characters and strictly reduce the same objective: **sum of `1 + (1 - consistency)` over selected families, plus `w × sum of each covered character's smallest selected proportional size distance`**. Without a marginal limit this permits adding an ideal-sized alternative even when a broader family already covers that character, while charging for the extra group. It removes redundant groups when their removal improves the count/fit tradeoff. Selection stops when no such move improves the objective. This is a deterministic local heuristic; it does not guarantee the globally best or smallest cover. The original candidate families and memberships remain unchanged.

**Cost limits and stopping rule** contains two optional controls, disabled by default:

- **Limit family cost** excludes any candidate whose greedy cost exceeds **Maximum family cost**, before both selection and refinement. This is a fixed family-level eligibility filter; overlapping affordable families can still produce a long list.
- **Limit cost per additional character** stops selection when the cheapest next option exceeds **Maximum cost per additional character**. This ratio is recalculated against the remaining uncovered characters. A cost-3 family adding 12 new characters costs 0.25 each; adding only one costs 3. A value equal to the limit is allowed. This intentionally permits partial coverage rather than forcing an expensive final tail.

When the marginal limit is enabled, refinement preserves exactly the greedily selected covered set. It cannot add zero-gain families solely for size fit or bring previously uncovered characters back through another route. Removals must preserve coverage, and replacement families must meet the marginal limit against the characters they restore relative to the other selected families. This prevents refinement from bypassing the stopping rule. The tradeoff is that some fit-only improvements available in unlimited mode are deliberately unavailable in budgeted mode.

The additional summary separates **No eligible family** from **Left uncovered by marginal limit**. The first includes characters absent from the current viable scope, plus characters whose every option exceeds the family-cost ceiling; its caption counts those excluded specifically by that ceiling. The second has eligible options, but the remaining cost per newly covered character is too high. **Uncovered characters and cheapest remaining options** lists each missing character's reason and its cheapest remaining source. Its family table orders alternatives by current cost per additional character, includes newly covered counts, and identifies the first blocking limit when both fail. These alternatives may overlap and must not be added together. Characters absent from all candidates have no remaining option. Download the remaining-options CSV to compare settings. Both ceilings, the proportional distance method and effective hard-size limits are recorded in exports; cost changes reuse bootstrap evidence.

The summary reports selected family count, full-catalog coverage, characters with a selected ideal-sized family and covered characters outside the ideal range. The character-fit table defaults to those exceptions, showing their chosen family size, raw and proportional distance from the interval and whether any eligible ideal-sized candidate existed. That distinction separates gaps in the candidate library from selection tradeoffs and active cost limits. A character's suggested family is its closest selected proportional size fit, with stronger consistency breaking equal-distance ties. Families overlap; this reporting choice does not reassign their original members or invent smaller subsets. Family and character CSVs include the selection approach, preferred interval, preference, effective hard size limits, evidence settings and source fingerprints. Changing cover settings reuses bootstrap evidence.

**All viable families** lists every qualifying candidate with source scenario, original family ID, coverage basis, included size, member names, qualifying pair consistency and original median separation. Filter by basis or find families containing particular characters. **Inspect a viable family** shows its included members' bootstrap heatmap, preserving the source matrix and excluding removed outliers from retained-only candidates. This makes alternatives inspectable without rerunning bootstrap checks. Suggested families, per-character smallest options, all viable families, character coverage and coverage memberships have CSV downloads.

These are overlapping candidate groups from separate scenario-specific definitions, not a jointly validated final partition. A passing family mean does not guarantee that every member passes individually. Trimming is a sensitivity diagnostic selected on the same bootstrap evidence; it is not independent confirmation of a newly discovered family. Inspect separation, individual members and the heatmap before adopting a family. Repeated appearances across scenarios are references, not independent confirmations. The viewer does not invent arbitrary smaller subsets or modify saved scenario files.

Enable **Show individual scenario charts** under **Scenario evidence and comparison** to inspect each scenario's **Consistency of each original family** chart, family-metrics table, bootstrap co-membership heatmap and final character assignment list. **Expand all scenario charts** opens all sections for visual comparison; each heatmap can show every original family or a selected family. Individual charts are opt-in so routine collection edits avoid rendering every scenario's heatmap. The graphs share the single-scenario laboratory's plotting functions and definitions.

Download the comparison CSV, all final assignments, or all family metrics. Exports include review rules, repeat settings, cohort scope and membership/reference fingerprints. Overlapping assignments remain separate original/final membership views; the viewer does not adopt them into story pages or overwrite scenarios.

### Curate a family cohort

Immediately beneath the suggested-cover table, choose **Start from suggested cover** or **Start empty**. This creates an editable draft. **Replace draft with this suggestion** is an explicit reset; changing suggestion settings never replaces your selections. **Undo last edit** restores the previous draft after a family addition, removal, replacement or saved review edit.

**Add a family manually** browses source families independently of the suggestion's size, basis and cost exclusions. A passing family omitted by the optimizer may still be a good choice. **Add as manual exception** records deliberate exclusions and an optional review note. Selecting a family adds its entire included membership; it does not assign only the character currently under review. The first release edits whole-family selections and titles, preserving source member sets.

The **Current cohort** summary counts unique covered characters against the complete snapshot catalog, missing characters, repeated characters and covered characters below the **Member-fit review target** in every selected family. Unscored cases are reported separately. A repeated character appears in two or more selected families; **extra memberships** counts every membership beyond each character's first. These quantities differ when characters appear in three or more groups. Per-family **exclusive characters** identifies exactly whose coverage would be lost by removing that family. Zero exclusive coverage does not establish that a family is useless: it may provide a finer or stronger fit.

In **Resolve characters**, choose missing, weakly fitted, repeated or all characters. The default alphabetical queue also supports sorting by the number of distinct viable member sets. The selected character remains in view after an addition; **Next missing character** explicitly advances the queue. **Keep unresolved / review note** saves context without counting the character as covered.

Family options default to **Character fit**: the character's mean bootstrap co-membership with every other included member, excluding itself. **Family consistency** is the mean across all included distinct pairs. For a retained family both quantities are recalculated within the retained subset; original-family scores and original median separation describe a different comparison. A high group mean can conceal a weak individual member. Singletons have unavailable peer scores. The distinct member-fit target flags cases for review without excluding families automatically.

Rank alternatives by personal fit, preferred size, family mean, new coverage or cost per additional character. The table includes all applicable suggestion exclusions; these are not interchangeable evidence failures. A size- or cost-excluded family can have strong consistency. The individual detail shows pair-by-pair bars, peer support (the fraction of other members whose pair score reaches the review target), a source heatmap, and newly/already covered names. The add or atomic replacement preview recalculates coverage, missing characters, family count, repeated characters and the selected character's best fit. With zero new coverage, marginal cost is unavailable rather than infinite. You may deliberately add a different fit without new coverage.

Enable **Inspect below-target original families** to review nonpassing groups. Their retained diagnostic identifies whether trimming removed the character. Below-target groups require an explicit manual exception; missing or incompatible evidence cannot be converted into a measured pass. A character removed from a retained subset is never counted as its member. **Family library** supports the same inspection, including individual fit for one searched character or a long character/family table for multiple searches. The original **All viable families** browser also shows individual included-member scores when filtering by characters.

**Overlap and coverage** shows membership counts, named repeated/missing characters with fit in each selected family, each family's unique/shared coverage contribution, and a **Membership overlap** heatmap. Jaccard is shared members divided by the union. Directional containment divides shared members by the row family's size, helping identify nested groups. Shared count is also available; choose a pair to see the actual shared names. These are set overlaps of characters in the curated collection, not player-audience overlap or bootstrap consistency. Identical member sets from different sources retain their separate evidence and add no unique coverage.

Every family retains its source cohort, settings and bootstrap evidence. Different scenarios' scores are descriptive alternatives, not calibrated membership probabilities. The builder does not stitch matrices together or calculate a global cohort-stability score. Reused bootstrap evidence supports curation rather than independent validation of an edited collection. Future audience reporting needs an explicit overlap-attribution rule before adding affinities across families.

### Save and resume a cohort

**Save / load cohort** works even before running a batch. Save timestamped JSON under `data/character_families/cohorts/`, download it, or load/upload a previous collection. The JSON contains frozen selected member IDs, titles, notes, manual exceptions, origin settings, snapshot/reference fingerprints, the complete character catalog and a source registry with scenario definitions and bootstrap matrices. It contains no profile-level data. Valid saved evidence restores the resolver and diagnostics without rerunning discovery or bootstrap. Downloads also provide family summaries, long character-family memberships, a character review table including gaps, and pairwise overlap.

Saved membership sets remain fixed after trim or threshold changes; current rules only update library candidates and review flags. Changing the batch selection or bootstrap settings preserves the existing draft and its original evidence, with a notice when it differs from the new batch. Save the current draft before explicitly rebuilding from a new suggestion. A different snapshot/reference or invalid matrix/checksum is rejected on load. Source scenario files remain unchanged. Family IDs use source content and member identities, so renaming a source file or changing batch order does not change their identity.
