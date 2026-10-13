---
name: league-project-maintenance
description: Review or change the League Specialization ETL repository while preserving its helper boundaries, simple Python orchestration, dbt semantics, and the maintainer's coding conventions. Use for commit reviews, pipeline fixes, analytics refactors, and updates from maintainer feedback in this project.
---

# League project maintenance

Preserve the maintainer's existing design while making the smallest change that solves an evidenced problem. This project is a portfolio with periodically operated scripts; enterprise recovery machinery is not an implicit requirement. Read the affected code and its callers before proposing a replacement pattern. During sequential replay, apply these rules to the reviewed change; later fixes may still be absent.

## Review and iteration

- Apply this skill to every prompt in this project, using the guidance relevant to that task. End every response with brief skill cliffnotes: changed rules, or no update needed. When updating the skill, make three checks: fidelity to the latest maintainer feedback; consistency with current code and existing rules; clarity, brevity and absence of duplication. Validate the skill file after edits.
- When reviewing a commit, distinguish its original diff from subsequent fixes. Explain the concrete failure it addresses, whether the change is necessary, and whether its placement respects existing boundaries.
- Separate objective defects, style preferences, and deferred design decisions. Reproduce suspected defects locally when feasible; do not generate fixes from speculative worst cases.
- Match neighboring human-written code: naming, function shape, helper calls, validation, logging and error flow. A generally useful idiom can still be misplaced in this architecture.
- When asked to rewrite commits on a review branch, start at the parent of the first reviewed commit and replay each corrected commit there. Leave the original branch unchanged and defer later commits until their review.
- Keep changes cohesive and reviewable. During a feedback-led review, answer the comments and maintain this skill; do not turn a question about one pattern into an unsolicited project-wide rewrite.
- Flag optional safeguards with marginal practical benefit and disproportionate complexity, readability cost or scope for the maintainer to decide before implementing them. Negligible collection-budget rounding differences do not justify Decimal or replacement precision machinery. This does not require another approval for already authorized necessary fixes.
- Keep simple named functions when their names express a meaningful purpose and hide implementation details. Avoid redundant variables for the same quantity with only a type conversion, and extra wrappers without their own responsibility.
- Keep TODOs, implementation plans and agent handoff notes local and ignored; never stage or commit them. Preserve local copies when removing tracking. Check replayed commits for these artifacts because .gitignore alone does not untrack indexed files. Broader config-comment, function-ordering, comment and documentation cleanup belongs in the local TODO_NEW.md; the project-wide ordering convention is still to be agreed.
- Explain the reason for a departure from a local convention. Offer a small correction in the existing layer before adding abstractions, options or new state.
- Update this skill as the maintainer adds feedback. Record the enduring decision and its reason; avoid accumulating a transcript or turning a local example into a universal prohibition.

## Database ownership

`src/extract/extraction_db_helper.py` explicitly owns local database operations. Normal callers use its operations without opening a connection or passing `conn`. The optional connection argument primarily supports isolated tests; it also permits internal composition inside the helper.

- Keep SQL, connection ownership and transactions inside the database helper when implementing business operations. Do not move them into compaction, fetchers or the runner merely because `conn` is accepted. Check existing helper side effects before adding caller writes: player/mastery task creation already renews the SQLite run heartbeat; Neon claim renewal is a separate responsibility.
- If two updates must commit together, implement one cohesive helper operation that owns the connection and groups those updates. Preserve atomicity; restoring encapsulation must not reintroduce partial completion.
- Owned connections must close on failure as well as success. Existing helper functions use `own_conn = conn is None` and `try/finally`; preserve that convention unless a focused, justified consistency change is requested.
- Never close or commit a caller-provided connection as if the helper owned it. SQLite's `with conn` controls commit/rollback; it does not close the connection. `closing(conn)` closes it but does not itself commit. Cleanup syntax and ownership are separate decisions.
- Account for each driver's actual context-manager behavior rather than copying SQLite patterns into Postgres or Databricks helpers.

## Exceptions and validation

- Catch the errors the operation actually raises and that the current layer can handle meaningfully. File reads can raise `OSError` or Arrow errors; `RuntimeError` alone is not a general failure handler.
- A per-file validator can record an expected unreadable-file error and continue collecting diagnostics. Mark that error as a failed check so continuation does not silently permit upload.
- An operation may catch broadly to record failure and then re-raise. A pipeline boundary may catch broadly to finish run/task reporting and stop. Do not copy broad catches everywhere or swallow programming errors as successful or empty work.
- Retry only failures for which another attempt can plausibly succeed, with a fixed small limit. Exception families alone do not prove transience: `OSError` includes missing files and denied permissions; `sqlite3.OperationalError` includes persistent SQL errors as well as locking. Windows sharing violation 32 can surface as PermissionError; distinguish it from denied access when deciding whether to retry.
- Keep stage-specific facts and detailed errors in their stage result. Snapshots always have a result object, including skipped/not-started outcomes; staleness and allocation details belong in refresh_result. Run-level status, stage and error are justified as the human-readable failure summary, including interruptions. The outer error explains what stopped and what was retained; do not copy raw technical details there or duplicate a discovery flag.
- Preserve original exception details and chaining. Cleanup must not overwrite recorded diagnostics or report a failed task/run as successful. Treat operator interruption explicitly when finalizing state.
- Let the Pydantic configuration models validate configuration constraints. Avoid repeating the same checks in the runner. Operational checks of files, connections and returned job results remain separate responsibilities.
- Required upload checks apply to the actual compacted input on every normal pipeline upload. Use separate readiness functions for the two moments: is_compaction_ready checks database/raw inputs before compaction, and is_load_ready requires the compacted-output report before upload. Neither needs a stage-selection flag. An optional expensive raw-file scan is a different choice.

## Keep orchestration small

- Python coordinates the existing stages. SQLite is the local run/task/file/load ledger; Neon stores cross-worker freshness, claims and discovery progress. Logs and result exports describe execution, not an additional execution-state system.
- Reuse integrity checks, compaction, loaders and cleanup helpers. Use f-strings for log interpolation. Keep normal INFO messages concise and human-readable: work starting, progress, actual saved counts and elapsed time. Keep technical diagnostics in DEBUG, warnings/errors or existing reports. Rough request ETAs use the documented development-key assumption of 50 requests/minute at 95% efficiency (two requests per rank/mastery refresh); do not add an adaptive estimator unless requested.
- Wait for the ingestion job's completion before marking the uploaded observations loaded or applying their freshness/inactivity/page-completion changes. A valid no-file outcome can update directly. Run the separate dbt job afterward; clean local files only after the required stages and recorded loads succeed.
- Preserve successful ingestion state if dbt fails. Retain files and report the failing stage clearly so the operator can retry. A timeout is a failed local check; log the remote run ID rather than claiming remote cancellation.
- Do not add ready batches, round checkpoints, receipts, reservation frameworks, custom API budgets or automated recovery layers without a newly established need. Repeated lightweight submissions/loads are acceptable; downstream deduplication already exists.
- The runner owns refresh allocation: use weighted staleness, a named and explained intensity constant, and MAX_REFRESH_SCALE (a documented multiplier) to decide whether to fetch a snapshot and calculate the final player limit. Use the latest observed page count before freshness filtering; skipped/empty snapshots use the runner's named fallback. Skip both snapshot fetchers at the cap and record the reason. Pass the worker its final allocation once; do not import worker constants or bounce its own calculations back to it. Riot's client still owns rate limiting; keep claim maintenance to heartbeats and expired/failed-claim cleanup, accepting that lost ownership does not invalidate files.
- Read existing local configuration files directly, pass a selected config path consistently, and explain exact files/keys. Avoid unexplained numeric literals. Prefer observed values where available; operator policy choices need .env settings with defaults, units, effects and boundary behavior documented in both the example and README. Algorithm coefficients and fallback assumptions can remain named, explained script constants. Split important math into named steps; use standard-library tools such as math.ceil when they state the intended operation clearly.

## Analytics and serving

- dbt changes require particular care: establish each model's purpose, grain, consumers and metric definition. Prefer retained reusable models and shared saved SQL for repeated calculations over adding marts for every dashboard grouping. dbt analyses are saved queries; they do not create views or tables.
- Use the rank-population reference CSV directly for pooled population estimates, with local caching where useful. Tier-specific descriptions remain meaningful without a population correction. Use normalized weighted statistics or direct standardization, preserve observed support, and disclose missing tiers and conditional-selection limits.
- Distinguish lifetime profiles, recent active pools, ranked-observed follow-up and rank periods/observations/deltas when explaining metrics. The default/name redesign remains a maintainer decision; do not silently mix or reorganize these cohorts during unrelated fixes.
- Keep the synthetic business sample recognizable through folders, names and labels. Do not impose elaborate quarantine or publication controls on a portfolio placeholder.
- Dashboard compatibility is not a reason to retain an unnecessary dbt model: update its consumers with an approved model change. Keep documentation and captions aligned with the final behavior.
- Exports are manually run and can overwrite their existing files. Do not add automatic public S3 updates, versioned publication, or new lineage/recovery systems to solve a manually rerunnable export.

## Verification and handoff

- Use temporary SQLite databases and files, and mock cloud boundaries for local tests. Check actual connection arguments and captured default paths; a fixture that patches one module may leave another touching the working ledger.
- Test meaningful failure and state boundaries when changed. Avoid tests that merely assert implementation wording, structure, or a large framework introduced for testing.
- Report what changed, why, relevant checks, and remaining live validation. Passing mocked/local tests is not proof of live Riot/Neon/Databricks behavior.
- For authorized local commits, keep each part reviewable with a meaningful description. Deployment, push and live-service mutation remain distinct actions; skill use does not authorize them.
