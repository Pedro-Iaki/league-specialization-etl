---
name: league-project-maintenance
description: Review and maintain the League Specialization ETL repository using the maintainer's conventions for helper ownership, simple orchestration, analytical correctness, isolated verification and focused commit reviews.
---

# League project maintenance

Use this skill for the project's working conventions and engineering decision rules. Read the affected implementation and its callers before changing a pattern. This is a portfolio with periodically operated scripts; choose complexity that solves an evidenced need at that scope.

## Maintaining this skill

- Update the skill when maintainer feedback or an observed failure reveals a reusable rule for future decisions. A completed fix does not automatically require a skill update.
- State the expected behavior, its reason and its scope. Check whether the rule would help an agent handle a different change with the same underlying risk. Generalize the cause of a mistake rather than recording the particular repair.
- Keep feature descriptions, settings, formulas, metric definitions, incident findings and recovery procedures in project documentation, code or tests. Link to those sources when needed; do not turn this skill into a second reference manual or a list of past bugs.
- Refine an existing rule before adding another. Remove duplicate instructions and obsolete examples. A local example can clarify a convention, but must not become an unrelated universal requirement.
- Before accepting an edit, check fidelity to maintainer feedback, consistency with the current architecture, usefulness beyond the originating incident, and brevity. Validate the skill's format and any referenced paths.

## Find the relevant project context

Read only the sources needed for the task. Resolve these paths from this skill's directory; verify current behavior against code when documentation and implementation differ.

- [Project README](../../../README.md): purpose, analysis, architecture, engineering decisions and validation overview.
- [Documentation index](../../../docs/README.md): current wiki, guides and references organized by reader task.
- [Architecture chapter](../../../docs/wiki/architecture.md): data flow, component responsibilities, source branches and serving boundary.
- [Understanding the analysis](../../../docs/wiki/understanding-the-analysis.md): audience questions, windows, comparison methods and interpretation limits.
- [Simulated transactions](../../../docs/wiki/simulated-transactions.md): frozen real cohort, generated commercial domain, cash semantics and business interpretation limits.
- [Engineering decisions](../../../docs/wiki/engineering-decisions.md): design tradeoffs, attributed development lessons, ownership and AI assistance.
- [Configuration reference](../../../docs/reference/configuration.md): settings, defaults, service boundaries and manual entrypoints.
- [Orchestration reference](../../../docs/reference/orchestration.md): stage ordering, state transitions, integrity gates and failure behavior.
- [Data-model reference](../../../docs/reference/data-models.md): model grains, identities, lineage boundaries and serving contracts.
- [Metrics and methods](../../../docs/reference/metrics-and-methods.md): analysis windows, formulas, eligibility, attribution and denominators.
- [Population adjustment](../../../docs/reference/population-adjustment.md): calibration, conditional estimates, direct standardization, support and interpretation limits.
- [Validation and evidence](../../../docs/reference/validation-and-evidence.md): validation boundaries, dated artifacts, local checks and limits of live-service evidence.
- [Run the dashboard](../../../docs/guides/run-the-dashboard.md): local environment, snapshot launch, navigation, language and troubleshooting.
- [Run the pipeline](../../../docs/guides/run-the-pipeline.md): manual prerequisites, job/configuration setup, first-build scope, execution and operator recovery.
- [Refresh dashboard data](../../../docs/guides/refresh-dashboard-data.md): scenario/reference decisions, candidate export, local checks, serving-file replacement and analyst bundle.

## Working journal during active iteration

- When project work advances faster than formal documentation, maintain the local [working journal](../../../sandbox/project_working_notes.tmp/working-journal.md). Read its relevant entries when resuming work; create it at that path if absent. Keep it loosely structured and update it at meaningful implementation, discussion, evidence or direction changes, rather than recording every command.
- Capture what was done, what was discussed, why decisions changed, the evolving audience/business story, and unresolved branches. Clearly distinguish implemented and verified behavior, agreed direction, proposals and deferred work; verify implementation claims against code when needed.
- Preserve useful research with its title, direct source link, relevance to the project and evidence limits. State whether a method is merely a reference, proposed for evaluation, tested or adopted; a cited paper does not validate our data or findings.
- Keep this intermediary journal local under the existing ignore rules. Link to detailed artifacts instead of copying transcripts or maintained documentation. When conclusions settle, reconcile them into the appropriate project documents and mark superseded or incorporated notes; do not defer necessary metric-contract or operator-instruction updates.

## Scope and review

- Separate demonstrated defects, style preferences and deferred design decisions. Reproduce suspected defects when feasible. Offer the smallest correction in the existing layer before introducing abstractions, options or persistent state.
- Match neighboring code's naming, function shape, helper calls, validation, logging and error flow. Explain a necessary departure from a local convention.
- Keep named helpers that express a responsibility. Avoid wrappers, extra entrypoints, conversions and intermediate variables that add no useful meaning. Extra safeguards should justify their readability and maintenance cost against a concrete risk.
- During commit review, distinguish the original diff from later fixes. Judge the reviewed state using code available at that point. Approval of a tagged checklist covers its listed changes; it does not authorize every change in the original diff.
- When asked to rebuild a review branch, start at the parent of the first reviewed commit and replay corrected commits in order. Preserve the original branch and keep deferred changes out of the replay.
- Before retiring a script or helper, inspect callers and operational instructions. Update affected references and preserve a current setup path where required.
- Check ignore rules and the Git index separately. Preserve intentionally versioned assets and local copies when untracking files. Keep credentials, runtime output, temporary tools, TODOs, implementation plans and agent handoff notes out of commits.

## Code organization

- After the module docstring and imports, order workflow scripts as constants/types, entry function, main workflow, stage functions, supporting utilities, then the command-line entry block. An entry function may contain the workflow; do not add a wrapper just to fill a category.
- Group related helper operations contiguously by responsibility without region markers. Leave small, coherent modules alone.
- Definition-time dependencies and executable UI order take precedence over visual organization. When reorganizing code, preserve behavior; keep functional changes separately reviewable.

## Database boundaries and state

- `src/extract/extraction_db_helper.py` owns local SQL, connection management and transactions. Normal callers use its operations; the optional connection argument supports tests and composition within the helper. Check existing helper side effects before adding duplicate caller writes.
- Choose transaction boundaries around a complete business transition. Within one database, persist coupled state changes and the relationships needed to interpret or recover them together. Put that operation in the owning helper, so callers cannot commit an incomplete transition between helper calls.
- Follow the existing `own_conn = conn is None` and `try/finally` convention. Close owned connections on failure as well as success. A caller supplying a connection owns commit, rollback and close; helpers must not take over that ownership.
- Check each driver's actual context-manager semantics. SQLite's connection context manager controls transactions but does not close the connection; closing a connection does not itself commit.
- When changing persisted workflow state, trace interruption points before, during and after external work. Cleanup must preserve successful results, newer work and existing diagnostics while leaving unfinished work identifiable for retry.

## Errors, validation and reporting

- Catch errors the operation actually raises and that the current layer can handle. A per-item validator may continue gathering diagnostics, but its recorded failure must still fail the relevant integrity gate. Broad catches belong at boundaries that report and stop or re-raise, not throughout ordinary helpers.
- Retry only when another attempt can plausibly succeed, using a small bounded policy. An exception family alone does not establish transience; distinguish a temporary sharing conflict from denied access or invalid SQL.
- Derive stage success from task outcomes, including failed and unfinished work. The absence of an escaping exception is insufficient evidence of completion. Handle operator interruption explicitly and preserve exception details and chaining.
- Keep detailed diagnostics with their stage results and a concise failure summary at the run boundary. Represent skipped or unstarted stages explicitly. Reuse existing result objects and the ledger instead of duplicating state or adding a separate reporting framework.
- Validate inputs at the point where they will be used. Keep checks before a transformation distinct from checks on its actual output before delivery. An optional expensive scan must not disable required load checks.
- Use f-strings for logging. INFO should show meaningful starts, progress, saved counts and elapsed time; keep technical detail in DEBUG, warnings, errors or reports. Progress displays should remain readable in terminals and captured logs. Label estimates as estimates rather than presenting them as measured evidence.

## Orchestration and configuration

- Python owns stage ordering and work allocation; workers receive their final allocation, and the API client owns rate limiting. Keep SQLite as the local execution ledger and Neon as shared collection coordination. Logs and result exports describe execution rather than becoming another execution-state system.
- Reuse existing stage and cleanup helpers. Add checkpoints, reservation systems or automated recovery machinery only for an established need. Account for existing deduplication and rerunnable operations before creating additional coordination state.
- Mark externally delivered work complete only after confirmation. Apply dependent collection-state changes at that boundary, then run downstream stages. Preserve confirmed earlier success when a later stage fails; retain inputs until required stages succeed. A local timeout does not establish remote cancellation.
- Base retry exclusions and cleanup on current ownership, freshness and completion evidence. Historical failure alone should not permanently exclude work. Before moving or deleting files, check ledger references and active writers; preserve pending inputs and stop when ownership or file operations cannot be established safely.
- Keep claim maintenance with the owner of those claims. Prefer a simple renewal cadence over repeated whole-set updates for each item. Loss of coordination ownership does not by itself invalidate already collected observations.
- Validate configuration once at an entrypoint and pass validated settings through the workflow. Let Pydantic enforce configuration constraints; avoid per-stage rereads, repeated runner validation and duplicate manifests for the same policy.
- Keep operator policy in documented settings with defaults, units and boundary behavior. Use named, explained constants for algorithm assumptions and coefficients. Prefer observed inputs where available and split important calculations into meaningful steps; avoid extra precision machinery without a demonstrated correctness need.

## Analytics and serving

- Before changing a dbt model, establish its purpose, grain, consumers and metric definitions. Prefer reusable models and shared saved SQL over a new mart for every presentation grouping. Update affected consumers when a model change is approved.
- Trace renames through upstream columns, models, tests, export queries and presentation labels. Parsing alone does not establish that columns resolve correctly. Keep naming-only changes separate from changes to calculations, cohort filters and defaults.
- Preserve the distinction between a cohort, an analysis window and an observed outcome. Check counting units and denominators before describing results; membership, activity and play rates are different measures. Use the project's documented vocabulary across code and EN/PT labels, and disclose inferred populations rather than implying directly observed behavior.
- Use the maintained population reference as the shared source for weighting. Preserve observed support and disclose missing strata and selection limits; a weighting adjustment does not remove every sampling bias.
- Keep synthetic data recognizable in names, folders and labels. Preserve versioned source fixtures during downstream naming changes unless changing their contract is part of the task; place adaptations at the appropriate boundary.
- Preserve the serving boundary: Streamlit reads local Parquet snapshots; warehouse queries and credentials belong in the export/pipeline path. Exports are manually rerunnable. Do not add live warehouse mode or automatic publication machinery without a changed requirement.

## Verification and handoff

- Use temporary databases and files, and mock cloud boundaries. Inspect actual connection arguments and captured default paths; patching one module may leave another touching the working ledger.
- Verify meaningful state boundaries when they change: interrupted work, rollback, retry and preservation of completed work. Avoid tests that only mirror implementation wording or require a large framework for a small change.
- For interactive view changes, verify the rendered states through actual browser controls: replacement versus addition, selected data, reset and navigation. Check that obsolete panels disappear as well as new panels appearing. DOM stubs that invent missing elements cannot establish browser correctness.
- Before committing or handing off changes, perform a simplicity pass over the completed diff. For each addition, identify the requirement or concrete failure it addresses and compare it with the simplest correct alternative. Remove unnecessary branches, indirection, state, configuration and optimizations whose benefit is negligible or speculative. Preserve meaningful helpers and necessary safeguards, then rerun checks affected by simplification.
- Report what changed, why, what was checked and the limits of that evidence. Local mocked tests do not demonstrate live-service behavior.
- For authorized commits, use cohesive changes and plain-language imperative subjects with normal capitalization and no type/scope prefixes. Keep pending unrelated work outside the commit.
- End responses using this skill with brief skill cliffnotes: changed rules, or no update needed. A concise explanation of why an existing rule already applies is sufficient; do not invent an update to fill the summary.
