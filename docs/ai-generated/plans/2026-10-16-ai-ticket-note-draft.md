# AI Ticket Note Draft Implementation Plan

> **For agentic workers:** Implementation is authorized inline in this session. Use test-driven development; steps use checkbox syntax.

**Goal:** Let the AI assistant draft an internal support-ticket handling note and write it only after the user explicitly confirms.

**Architecture:** Add a read-only draft endpoint that sends only ticket number/status/priority and user-entered handling context to the configured model; it returns text and persists nothing. The UI previews editable text and calls the existing ticket-notes endpoint only when the user presses an explicit save button, preserving its existing permission, audit, closed-ticket, and shop-scope checks.

**Tech Stack:** FastAPI, pytest, React, TypeScript, Ant Design.

**Spec:** User-approved scope in chat: first low-risk action is an AI-generated internal support note; preview before write; no customer messaging or automatic status change.

## Global Constraints

- Draft generation requires `assistant:read` and `customer_tickets:read`.
- Saving requires `customer_tickets:write` and uses the existing `/customer-tickets/{ticket_id}/notes` API.
- Do not send ticket description, contact details, or other customer data to the model; send only ticket number, status, priority, and user-provided context.
- Never write on model generation; never send external messages or transition ticket status.
- Treat generated text as a draft; allow the user to edit it before saving.

## Review Focus

- A user without ticket-read permission cannot generate drafts; a ticket outside shop scope is indistinguishable from missing.
- Empty or malformed model output is rejected; it cannot create a ticket event.
- Draft generation does not mutate ticket state or events.
- Save is unavailable without ticket-write permission; existing endpoint enforces closed-ticket and audit behavior.
- Prompt context excludes ticket description/contact fields.

### Task 1: Draft API and acceptance tests

**Files:** Modify `backend/app/assistant.py`; create `backend/tests/test_assistant_ticket_notes.py`.

**Interface:** `POST /api/v1/assistant/ticket-note-draft` accepts `{ticket_id, context}` and returns `{ticket_id, ticket_no, note, read_only: true}` without persisting changes.

- [x] Add failing tests for valid draft/no mutation, ticket-read and shop-scope boundaries, and invalid/blank model output.
- [x] Run the new tests and confirm they fail because the endpoint is missing.
- [x] Implement bounded draft generation with the existing model client, no tools, minimal ticket fields, and no database writes.
- [x] Re-run the focused tests (3 passed); run ticket regression before handoff.

### Task 2: Assistant UI preview and confirmed save

**Files:** Modify `frontend/src/pages/AssistantPage.tsx`.

- [x] Add a ticket picker and user context field, gated by assistant/ticket read permissions.
- [x] Add editable draft preview and a separate explicit “确认写入内部处理记录” action, gated by ticket write permission.
- [x] Save only through the existing ticket notes endpoint; do not modify the general chat execution behavior.
- [x] Replace the inaccurate generic “read-only trial” label with precise capability boundaries.
- [x] Run the production build.
- [ ] Verify draft, preview, save, and no-external-send copy in the browser (current browser session redirects to login after reload).

### Task 3: Handoff

- [x] Update the roadmap with the action's boundaries and permissions.
- [ ] Verify the running backend and frontend against the implementation.
