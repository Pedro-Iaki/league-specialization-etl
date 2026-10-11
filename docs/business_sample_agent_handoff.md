# AI agent handoff: synthetic business sample

Use this document from the repository root in a new coding-agent conversation. The [implementation plan](business_sample_implementation_plan.md) is the specification; this handoff is a compact instruction to execute it. The complete implementation can be handled in one high-context prompt. Use the follow-up prompt only if the agent finishes with a concrete integration blocker or incomplete item.

## Prompt 1 — implement the full sample

**Start:** Open a fresh agent session in `C:\Dev\Data_Science\league-specialization-etl`, then paste the following prompt. The agent should inspect the repository and the plan before editing.

```text
Implement docs/business_sample_implementation_plan.md end to end in this repository. Read the full plan and relevant existing code first. Work in the current worktree, preserve all unrelated user changes, and edit existing files only where the new business sample needs integration. Continue through implementation, focused verification, export, documentation, and a final concise report; do not stop after proposing a plan.

The objective is a small portfolio sample that joins generated purchase history to frozen real player-profile data. Build it as one practical implementation task. Use a Python CLI to fetch and freeze the cohort automatically from the current Gold player and rank-period marts, with an offline --cohort option. Generate reproducible historical transactions and a compact Parquet. Add separate simple product/currency seeds, a dedicated sample loader that writes only sample raw tables, Bronze/Silver transaction models, one Gold player spending mart, an anonymous dashboard export, and a clearly labeled business opening page that links to the current real gameplay pages. Reuse current helpers and dashboard patterns when useful. Keep external warehouse work limited to dedicated sample resources.

Important decisions from the conversation:
- Keep currency_id, amount_spent, and source-provided amount_usd. Fiat USD values are supplied by the hypothetical endpoint; do not add FX or inflation integration.
- The currency seed has only currency_id, name, and currency_kind. No is_legacy field.
- product_id identifies the SKU; transaction_id uniquely identifies each event. The product seed supplies name, description, category, currency, and fictional generation defaults.
- Skip Pydantic, mock HTTP, SQLite integration, Airflow changes, and gameplay activity profiling.
- Generate purchase patterns with editable BASE_WEIGHTS for payment consistency, payment frequency, payment intensity, cosmetic bias, simulated owned champions, discount share, and mean conditional discount. Add offsets by tier, role, primary champion, playstyle, simulated tenure band, mastery-sum band, ranked-share band, active top-one share band, active champion-pool entropy band, and seeded sardine/dolphin/whale customer type. Sum offsets per player, clamp valid ranges, then sample with residual noise. Do not represent champion-pool entropy as playrate regularity.
- Fetch every real feature required by those offsets from the existing marts, including primary champion, total mastery points, champions with mastery, active top-one share, and estimated ranked mastery share when it exists. Keep nulls when unobserved. Generate simulated tenure before any purchases so first_purchase_at is not used to cause itself.
- Give each sampled ranked player a plausible BE champion-purchase history and a separately labeled simulated owned-champion count. Keep purchases and played/mastered champion count loosely related, allowing rewards, rotations, and unused owned champions. Every player has a simulated purchase; zero fiat purchases remain valid.
- Use fiat transactions and amount_usd for monetization. RP/BE events can support content and acquisition mix, but do not calculate RP spending, value RP in USD, or present it as additional cash revenue.
- Gold has one row per frozen player, contains first_purchase_at once, the requested real profile context, simulated customer type and ownership, cash recent/all-history summaries, derived consistency/frequency/intensity, cosmetic bias, and discount share/mean. Derive flags from purchase counts; do not store has_purchase or is_synthetic_spending columns.
- Keep tests lean. Verify stable generation, unique IDs and grains, no writes to real raw tables, correct source-provided USD sums, scenario match, safe anonymous export, and dashboard rendering. Avoid tests that only repeat field definitions.
- Make the dashboard useful to someone who has never played League. State immediately that spending data and its patterns are synthetic while player metrics are real. Show only a few business plots and guide users into the existing real analysis. Do not portray imposed generator weights as discoveries. Keep the author/project introduction and architecture explanation readable.

Check git status before editing. Follow repo instructions. Validate what can be validated locally; if configured Databricks access is available, run the sample load and targeted dbt build without modifying real gameplay tables. If an external dependency is unavailable, finish all local code and checks, then report the exact missing step. Do not invent successful warehouse or dashboard export results. Update the relevant README/model-reference documentation and preserve the existing real dashboard pages.

At completion, report: files changed, executed commands/results, actual sample row counts if run, and any unresolved dependency. Stop after the requested sample is implemented and sufficiently verified.
```

**End:** Prompt 1 is complete when the agent has implemented the plan, produced the local generated artifacts, built or clearly diagnosed the sample warehouse path, and reported verification results. Do not use Prompt 2 simply because the agent asks whether to continue; the pasted prompt already authorizes completion.

## Commands — run or adapt during Prompt 1

These commands belong to the implementation flow. The new agent should adjust the exact CLI flags it implements and record the final working versions in the README. Run them from the repository root unless a command changes directory. They require the existing configured environment; they are not expected to work before implementation.

```powershell
$env:PYTHONPATH = "src"
python -m sample.generate_transactions --cohort data/business_sample/cohort.parquet --seed 42 --output-dir data/business_sample
python -m load.load_business_sample --input-dir data/business_sample
```

```powershell
cd league_pipeline
dbt seed --select sample_currencies sample_products
dbt build --select tag:business_sample
cd ..
```

```powershell
python streamlit_app/scripts/export_data.py --dataset business_players
python -m pytest streamlit_app/tests
git status --short
```

Run any generator/loader tests the implementation actually adds. If `business_players` is optional in the tests, check the new export explicitly when warehouse access succeeds. Do not run the existing Riot extractor to create the business sample.

## Prompt 2 — only for an incomplete handoff

**Start:** Use this in the same new-agent conversation only after Prompt 1 ends with a concrete incomplete item. Replace the bracketed text with the agent's own reported blocker or unfinished file. Do not ask it to restart from scratch.

```text
Continue the business sample implementation from the current worktree. The remaining issue is: [paste the exact blocker or incomplete item]. Inspect the current code and docs/business_sample_implementation_plan.md, resolve that issue, complete any downstream integration it affected, run only the checks needed to verify the fix, and update the final report. Preserve existing unrelated changes. If this depends on unavailable external credentials or service state, complete the local work and state the exact command that remains.
```

**End:** The agent has resolved the reported issue, checked its dependent path, and stated clearly what was and was not executed. Do not repeat all checks unless the fix changes their assumptions.
