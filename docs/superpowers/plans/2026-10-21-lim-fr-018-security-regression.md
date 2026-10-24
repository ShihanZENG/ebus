# LIM-FR-018 Security Regression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a repeatable isolated regression set proving document prompt injection, invalid Tool arguments/scope, write gating, and duplicate write attempts cannot produce unauthorized writes.

**Architecture:** Exercise the existing knowledge catalog and read-only LIM Runtime with temporary SQLite data and controlled handler spies. Keep the cases deterministic and local; no model provider or real credentials are used. If a case reveals a bypass, fix only that boundary and pin it with the failing case.

**Tech Stack:** Python, pytest, FastAPI application models, SQLAlchemy, temporary SQLite.

**Spec:** Attached `02_AI平台管理端_PRD.docx`, LIM-FR-018, L-T02 and L-T03; supervisor task dated 2026-10-21.

## Global Constraints

- Unauthorized high-risk writes that succeed: 0 in the test set.
- Untrusted document text must not grant Tool authority or override server-side permission/scope checks.
- Runtime remains read-only; a declared idempotency key does not enable a write Tool.
- Tests use temporary SQLite and synthetic values only; no real credentials or shared database.
- Do not edit enterprise FR-010 files.

## Review Focus

- Malicious retrieved Markdown asks to ignore instructions and invoke an unregistered write Tool; backend must still reject it.
- Missing, wrong-typed, additional, and forged scope arguments must be rejected before the read adapter runs.
- A write Tool declaring required idempotency and a repeated key must still produce zero side effects in this read-only phase.
- Rejected arguments containing synthetic secrets must not be echoed into API errors or persisted Trace summaries.
- A different actor or a user whose permission was revoked cannot reuse a previously created Run to invoke a Tool.

---

### Task 1: Isolated Security Regression Cases

**Files:**
- Create: `backend/tests/test_lim_security_regression.py`
- Modify: `docs/lim/g0-capability-inventory.md`

**Interfaces:**
- Consumes: `sync_knowledge_sources`, `search_registered_knowledge`, `create_run`, `transition_run`, `invoke_read_tool`, `validate_agent_definition`, and existing LIM ORM models.
- Produces: pytest cases named `test_retrieved_prompt_injection_cannot_bypass_runtime_tool_allowlist`, `test_invalid_tool_arguments_are_rejected_before_handler`, `test_idempotent_write_replay_remains_blocked_by_read_only_runtime`, and `test_run_owner_and_permission_are_rechecked_before_tool_invocation`.

- [x] **Step 1: Write the isolated regression tests**
  - Use a temporary SQLite database and a temporary `docs/oms` Markdown source containing a synthetic prompt injection that requests a forbidden refund/write Tool.
  - Assert the document is retrievable as source text, but an attempt to invoke a Tool outside the validated Agent allowlist is rejected and no handler runs.
  - Parameterize missing required input, wrong type, extra tenant/shop scope, and synthetic API-key input; assert stable rejection and zero adapter calls, with no secret echoed or persisted.
  - Declare a write Tool with `idempotency_mode='required'`; assert Agent validation and Runtime deny it, including repeated submissions with the same synthetic key, with zero handler calls.
  - Revoke `assistant:read` after Run creation; assert invocation is denied before adapter execution.

- [x] **Step 2: Run the focused module**

  Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_lim_security_regression.py -q`

  Expected: all deterministic negative cases pass against the existing server-side security boundaries, or a test identifies a reproducible bypass.

- [x] **Step 3: Fix only reproduced bypasses with a failing regression case first**
  - Keep any production changes within LIM security files; do not alter enterprise FR-010 files.

- [x] **Step 4: Run all LIM regression tests**

  Run in PowerShell: `& backend/.venv/Scripts/python.exe -m pytest (Get-ChildItem backend/tests/test_lim_*.py | ForEach-Object FullName) -q`

  Expected: 80 passed, 2 skipped; all cases use isolated temporary databases. Re-ran after capturing the final output: 80 passed, 2 skipped in 172.65s.

- [x] **Step 5: Refresh the capability inventory and check the diff**
  - Record that FR-018 has an isolated deterministic security regression set for the covered cases; retain remaining limits about model-level prompt interpretation and production security validation.
  - Run `git diff --check`.
