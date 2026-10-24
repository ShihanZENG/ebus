# LIM Knowledge Source Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a governed, versioned catalog for the existing local Markdown knowledge search, with ACL-aware lexical retrieval and stable citations.

**Architecture:** Extend LIM's current SQLAlchemy/Alembic models with source, content-version, and immutable chunk records. A LIM-only service scans the two fixed Markdown roots, creates hash-versioned snapshots, and serves both the current assistant tool and authenticated management APIs; no arbitrary filesystem path is accepted. The existing LIM Console gains a Knowledge Sources tab and all administration stays behind `lim:manage`.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Pydantic, existing deterministic lexical scoring, React, TypeScript, Ant Design.

**Spec:** `docs/superpowers/specs/2026-10-21-lim-knowledge-source-registry-design.md`

## Global Constraints

- Scan only `docs/功能章节` and `docs/oms`; accept `.md` files only and resolve paths under the repository root.
- Content versions use SHA-256; unchanged content produces no duplicate version; changed content is draft until activation.
- Initial scan of the currently approved corpus creates active versions to preserve current assistant behavior.
- Search only active, effective, permission-matching chunks from non-archived sources; preserve the lexical `retrieval='lexical'` label.
- `assistant:read` gates search and read APIs; `lim:manage` or admin gates mutations. ACL values must exist in the existing permissions catalog.
- Preserve immutable content/version/chunk snapshots, audit config mutations, and never return absolute filesystem paths.
- Do not change Portal/Storefront-owned files or create business evidence objects.
- Do not commit changes in the shared checkout.

## Review Focus

- Traversal, symlink, non-Markdown, and out-of-root paths never read files or disclose absolute paths.
- Repeated scan is idempotent; changed content remains draft and the current active snapshot remains searchable until activation.
- Effective-time boundaries and source ACLs exclude content consistently from both API search and the assistant tool.
- Competing activation requests cannot leave multiple active versions; audit records reflect the winning transition.
- Removed files remain visible as missing snapshots until an administrator archives the source; archiving stops search without deleting history.

## File Map

- Modify `backend/app/lim_models.py`: add `LimKnowledgeSource`, `LimKnowledgeSourceVersion`, and `LimKnowledgeChunk`.
- Create `backend/migrations/versions/<current-head>_lim_knowledge_sources.py`: add only LIM knowledge tables and constraints.
- Create `backend/app/lim_knowledge.py`: fixed-root scanning, safe source IDs, chunking, hash-based sync, lifecycle transitions, permission-aware lexical search.
- Modify `backend/app/lim_routes.py`: source sync/list/version metadata/update/activate/archive endpoints.
- Modify `backend/app/assistant_knowledge.py`: preserve tool name/contract and delegate retrieval to the LIM knowledge service.
- Create `backend/tests/test_lim_knowledge.py`: sync, path safety, permissions, lifecycle, version snapshots, and search citations.
- Modify `frontend/src/api/lim.ts` and `frontend/src/pages/LimConsolePage.tsx`: add typed source APIs and Knowledge tab.
- Modify `backend/README.md`: document initial sync, review/activation, API and retrieval limits without replacing Portal/Storefront text.

## Tasks

### Task 1: Immutable knowledge source models and migration

**Files:** modify `backend/app/lim_models.py`; create a new LIM migration after the latest Alembic head; create `backend/tests/test_lim_knowledge.py`.

**Interfaces:**
- `LimKnowledgeSource`: stable `source_id`, relative `path`, display/category/summary, required permission codes, `is_present`, `archived`.
- `LimKnowledgeSourceVersion`: `(source_id, version)` unique key where version is SHA-256 content hash; effective dates, status (`draft|active|archived`), creator/reviewer and timestamps.
- `LimKnowledgeChunk`: `(source_id, version, chunk_id)` unique key; section, inclusive start/end lines, immutable body and content hash.

- [x] Write model/migration tests for unique version/chunk identity, foreign-key integrity, valid statuses, and date metadata.
- [x] Run tests and confirm they fail before model/migration implementation.
- [x] Add models and reversible migration `0031` after `0030`; do not edit existing revisions.
- [x] Run model/migration tests. Full Alembic metadata check is currently blocked by concurrent Storefront attachment constraint drift (`ck_storefront_support_attachments_size`).

### Task 2: Safe scan, sync, and source lifecycle APIs

**Files:** create `backend/app/lim_knowledge.py`; modify `backend/app/lim_routes.py`; extend `backend/tests/test_lim_knowledge.py`.

**Interfaces:**
- `sync_knowledge_sources(db, actor) -> dict`: scan only the two fixed roots, hash content, persist unchanged-safe versions, mark absent sources, and return counts.
- `visible_knowledge_sources(db, user) -> list[dict]`: filter by current role permissions, source status, and active version summary.
- `activate_knowledge_version(db, actor, source_id, version) -> LimKnowledgeSourceVersion`: validate metadata and atomically archive the previous active version.
- `search_registered_knowledge(db, user, query, *, limit=5) -> dict`: search authorized active chunks and return stable source/version/chunk/hash citations.
- APIs: `POST /knowledge/sync`; `GET /knowledge/sources`; `GET /knowledge/sources/{source_id}/versions`; `PATCH /knowledge/sources/{source_id}`; `POST /knowledge/sources/{source_id}/versions/{version}/activate`; `POST /knowledge/sources/{source_id}/versions/{version}/archive`; `POST /knowledge/sources/{source_id}/archive`.

- [x] Add failing API/service tests for traversal/symlink rejection, idempotent scan, changed content as draft, missing-source retention, and admin-only mutations.
- [x] Implement fixed-root enumeration, stable IDs, first-import active versions, later draft versions, immutable chunks, and audited metadata/lifecycle changes.
- [x] Implement pagination and role-permission filtering for reads; admin can inspect all sources, `assistant:read` is still required.
- [x] Run focused service/API tests and assert no arbitrary absolute path appears in responses.

### Task 3: ACL-aware registered lexical retrieval

**Files:** modify `backend/app/lim_knowledge.py`, `backend/app/assistant_knowledge.py`; extend `backend/tests/test_lim_knowledge.py`.

**Interfaces:**
- `search_registered_knowledge(db, user, query, *, limit=5)` returns `source`, `retrieval='lexical'`, `items`, and limitations.
- Each item contains `ref_id`, `source_id`, `source_version`, `chunk_id`, `content_hash`, `path`, `section`, `start_line`, `end_line`, `excerpt`, and `relevance`.
- `search_knowledge(db, user, args)` remains the current assistant Tool function contract and delegates to the registered search service.

- [x] Add failing tests for ACL filtering and stable citation metadata.
- [x] Reuse existing tokenization/chunking/scoring behavior, but score only authorized persisted chunks.
- [x] Run LIM knowledge and assistant-related regressions; old `search_knowledge` tool input remains supported.

### Task 4: Knowledge Sources management UI

**Files:** modify `frontend/src/api/lim.ts`, `frontend/src/pages/LimConsolePage.tsx`.

- [x] Add TypeScript types and API helpers for source listing, scan, metadata edit, versions, activation, and archive.
- [x] Add Knowledge Sources tab with source presence/status, version history, scan and activation/archive actions.
- [x] Show draft/missing/archived states distinctly; never show local absolute paths or arbitrary file-path inputs.
- [x] Run `npm run build`; production build passed after the concurrent replenishment type fixes.

### Task 5: Documentation and verification

**Files:** modify `backend/README.md`; verification only for all implementation files.

- [x] Document migration, initial sync, review/activation, API, ACL behavior, and lexical-only limitations.
- [x] Run LIM tests: 33 passed, 1 skipped. Migration seed test ran but fails its final autogenerate assertion on concurrent Storefront constraint drift (`ck_storefront_support_attachments_size`).
- [x] Run frontend production build (3158 modules; bundle-size advisory only).
- [x] Finish independent review of the LIM diff and resolve all findings, including UTC normalization of effective dates.
