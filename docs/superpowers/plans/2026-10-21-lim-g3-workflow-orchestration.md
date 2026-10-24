# LIM G3 Workflow Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. The accepted contract basis is `docs/lim/g3-workflow-contract-proposal.md`.

**Goal:** Add the platform-owned, versioned DAG orchestration foundation needed for controlled cross-domain read-only diagnosis, with parallel tasks, shared parent scope, child LIM Runs/Traces, cancellation, and deterministic evidence conflict classification.

**Architecture:** LIM owns workflow definitions and run/task state. Workflow nodes reference immutable validated Agent/Tool versions. Only server-side registered read handlers execute. Each child Run retains existing lifecycle and trace contracts. The first MVP is explicitly single-process and bounded; it does not claim crash recovery or multi-instance scheduling.

**Constraints:** Preserve enterprise and Storefront owned changes. Do not create business domain evidence models; define only generic evidence references and conflict results. Never auto-resolve conflicts or claim root cause. Do not add production writes, model-generated graph edits, dynamic expressions, or a new queue dependency.

## Tasks

### 1. Generic workflow models and migration

- [x] Add workflow definition/version, parent run, and task/attempt records in migration `0033` after concurrent head `0032`; no prior revision was edited.
- [x] Enforce unique IDs, valid lifecycle states, fixed-version references, and parent/task foreign keys.
- [x] Define platform-owned task/DAG/condition/evidence validation helpers.

### 2. Draft registry and validation

- [x] Add create/list/version/validate APIs; require `lim:manage` for changes and `assistant:read` for reads.
- [x] Validate DAG acyclicity, references, schema shape, allowed condition operators, and active read-only Agent/Tool version compatibility.
- [x] Freeze validated versions; additional versions are created as new draft records.

### 3. Bounded orchestrator

- [x] Add create/read/trace/cancel workflow-run APIs; bind actor, current BusinessScope, workflow version, and budgets server-side.
- [x] Schedule ready nodes with bounded parallelism, dependencies, conditions, joins, max 12 total tasks/tool calls, and a 60-second deadline; validate and enforce the task budget at creation and execution.
- [x] Run each node through a child LIM Run and the registered read handler; persist task state and child Run ID with sanitized summaries.
- [x] Support partial failure, cancellation between waves, budget terminal state, and documented single-process/no-recovery limit.

### 4. Evidence aggregation

- [x] Define generic evidence reference validation and deterministic grouping; refs without an explicit `comparison_key`/`comparable_group` remain un-compared.
- [x] Return `CONSISTENT`, `CONFLICT`, `INCOMPARABLE`, and expected-claim `MISSING` groups with source refs; never select a winner.
- [x] Preserve business-specific evidence semantics and stable source hashes from domain adapters.

### 5. LIM workflow UI and docs

- [x] Add Workflow registry/run view to the existing LIM console without changing shared app entrypoints.
- [x] Display parent/task result and child trace summaries, gaps, findings, missing evidence, and conflict results.
- [x] Document API contract, single-process reliability limit, and consumer/adapter ownership.

### 6. Verification and review

- [x] Run focused workflow/knowledge/runtime/API/model/registry/scope/migration regressions after review fixes: 45 passed, 2 skipped; business evidence adapter regressions: 13 passed.
- [x] Run frontend production build (3160 modules; bundle-size advisory only).
- [x] Independent review confirmed budget enforcement and definition-order Run/Trace display; both findings were addressed.
