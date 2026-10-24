# LIM Skill Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Implement the locally deliverable PRD LIM-FR-015 Skill governance lifecycle with immutable versions, evidence metadata, permissions, and audit.

**Architecture:** Add LIM-owned Skill and SkillVersion tables, a deterministic transition service, authenticated APIs, and a governance tab in the existing LIM Console. Skill definitions remain inert data and are never injected into a model or executed.

**Tech Stack:** Existing FastAPI, SQLAlchemy, Alembic, pytest, React, TypeScript, Ant Design.

**Spec:** `docs/superpowers/specs/2026-10-21-lim-skill-governance-design.md`

## Global Constraints

- Preserve all shared files and inspect their latest content before editing.
- Create the next migration after the current live Alembic head; never rewrite a concurrent revision.
- Require `assistant:read` for reads and `lim:manage` for mutations/transitions.
- Do not auto-learn, auto-activate, inject, or execute Skill contents.
- Keep usage/correction counts at zero until a trusted runtime reference is implemented.
- Do not commit changes in the shared checkout.

## Review Focus

- Invalid lifecycle edges and terminal revocation must be rejected deterministically.
- Verification/activation without evidence, scope, verifier timestamp, calibration, or valid expiry must fail.
- Concurrent activation must leave at most one active version.
- Non-owner reads and non-manager mutations must respect existing permissions.
- Owner may complete a `CANDIDATE` version; edits and lifecycle transitions serialize on the version row, and content locks once review begins.

## File Map

- Modify `backend/app/lim_models.py`: add LIM Skill and SkillVersion persistence.
- Create next Alembic migration: create only the two LIM Skill tables.
- Create `backend/app/lim_skills.py`: candidate registration, validation, state transition, and serialization helpers.
- Modify `backend/app/lim_routes.py`: Skill APIs with existing auth dependencies.
- Create `backend/tests/test_lim_skills.py`: lifecycle, version, access, audit, and migration coverage.
- Modify `frontend/src/api/lim.ts` and `frontend/src/pages/LimConsolePage.tsx`: type-safe registry APIs and Skills tab.
- Modify `backend/README.md`: record lifecycle API and inert runtime boundary.

## Tasks

### Task 1: Persistence and lifecycle rules

- [x] Add failing tests for valid/invalid transitions, immutable versions, required verification metadata, expiry, and single active version.
- [x] Run the focused tests and confirm they fail because the Skill model/service is missing.
- [x] Add `LimSkill` and `LimSkillVersion`, with stable IDs, version uniqueness, lifecycle checks, foreign keys, and active lookup indexes.
- [x] Add reversible migration `0034` following `0033` without editing existing revisions.
- [x] Implement create and transition operations in `lim_skills.py`; activate the new version and demote the old active version in one transaction.
- [x] Run focused Skill tests and isolated migration upgrade/downgrade checks.

### Task 2: Authenticated API and audit

- [x] Add tests for unauthenticated reads, owner/manager visibility, manager-only mutations, bad transitions, missing evidence, expiry, and audit records.
- [x] Add list/create/candidate-edit/version-list/transition routes using existing permissions and stable error responses.
- [x] Require audit rationale on every transition; sanitize audit summaries and return `runtime_enabled=false`.
- [x] Run focused API tests and inspect OpenAPI paths.

### Task 3: Console governance UI

- [x] Add TypeScript Skill types and API helpers.
- [x] Add a Skills tab for candidate registration, version history, review metadata, and allowed state transitions.
- [x] Show validation reasons and the inert/no-auto-execution boundary.
- [x] Run frontend typecheck and production build.

### Task 4: Documentation and handoff

- [x] Document endpoints, lifecycle, audit, and runtime limitations in `backend/README.md`.
- [x] Run the focused LIM regression suite and `git diff --check`.
- [x] Review the implementation against PRD LIM-FR-015; mark remaining memory retrieval/runtime gaps explicitly in G0 inventory.
