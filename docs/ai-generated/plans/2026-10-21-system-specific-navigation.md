# System-Specific Navigation Implementation Plan

> **For agentic workers:** Execute this plan task-by-task in the current workspace. Preserve pre-existing user edits.

**Goal:** Give ERP, AI, LIM, and Storefront their own context-appropriate navigation while keeping OMS's existing standalone menu.

**Architecture:** Keep the current React Router and permission checks. Define one route-backed navigation tree per in-process system and select it from the current route; route modules and APIs stay unchanged. Add a permission-filtered shell switcher for ERP, AI, LIM, and the Storefront operator page; `/workspace` remains the authoritative five-system entry, including disabled OMS availability. ERP's remaining business menu groups are kept as-is while the user considers further ERP changes.

**Tech Stack:** React, TypeScript, React Router, Ant Design.

**Spec:** User-approved design in this conversation, based on the five-system menu examples on the shared ChatGPT page.

## Global Constraints

- Each of the five systems has its own product boundary and navigation.
- ERP's remaining business menu structure is provisional and must not be redesigned in this change.
- Only expose routes that already exist; do not add placeholder menu items for planned modules.
- OMS retains its existing standalone navigation; Storefront retains its consumer-facing navigation and its existing operator route.
- Preserve existing permission filtering and current uncommitted changes.

## Review Focus

- Direct navigation to a route selects the matching system menu and active item.
- A user without a page permission must not see that item in the corresponding system menu.
- Nested ERP groups continue to expand and resolve breadcrumbs correctly.
- Switching systems via `/workspace` continues to use server-provided availability and deep links.
- OMS and the public Storefront remain in their existing standalone frontends.

## File Structure

- `frontend/src/config/menu.ts`: define ERP, AI, LIM, and Storefront menu trees; retain shared permission and API metadata.
- `frontend/src/layouts/MainLayout.tsx`: select the system menu from the active route, label the current system, and provide a quick switcher for permitted internal systems.
- `frontend/src/pages/WorkspacePage.tsx`: unchanged; its server-backed cards remain the system switcher.
- `oms/frontend/src/MainLayout.tsx` and `storefront/src/main.tsx`: unchanged standalone navigation.

### Task 1: Split route-backed menu trees

**Files:**
- Modify: `frontend/src/config/menu.ts`

- [x] Keep the current ERP business groups, moving AI pages (`ai-assistant`, `product-agent`, `operations-agent`, `customer-agent`, `purchase-agent`, and inventory-replenishment evidence) into an AI menu and the governance console (`lim-console`) into a LIM menu.
- [x] Move the existing operator route `storefront` into its own Storefront menu.
- [x] Export system metadata, route-to-system lookup, and a `findNavPath(key, nodes)` helper that searches the selected tree; keep permission and API maps intact.

### Task 2: Render the matching system navigation

**Files:**
- Modify: `frontend/src/layouts/MainLayout.tsx`

- [x] Choose the active tree by `location.pathname`, with unknown/default business routes resolving to ERP.
- [x] Filter that tree through the existing permission checks before building the sidebar and submenu.
- [x] Use the active system name in the shell branding and current menu tree for breadcrumbs/tab labels.
- [x] Keep `/workspace` as the server-driven system entry; do not alter the OMS disabled state or either standalone frontend.
- [x] Provide a shell quick switcher for permitted internal systems and leave OMS visibly unavailable until its separate identity is connected.

### Task 3: Give LIM its own Chinese navigation and section entry points

**Files:**
- Modify: `frontend/src/config/menu.ts`
- Modify: `frontend/src/layouts/MainLayout.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/LimConsolePage.tsx`

- [x] Organize LIM navigation into Chinese groups for runtime/orchestration and quality/knowledge governance, following the referenced LIM menu structure.
- [x] Route implemented menu items to existing LIM console capabilities; visibly disable the unimplemented model gateway item instead of presenting it as usable.
- [x] Keep knowledge wording scoped to the current source registry and lexical retrieval; do not claim GraphRAG, memory execution, or production-cost data that is not implemented.
- [x] Add a resource-count overview using existing LIM registry data and clearly state that model calls, token usage, cost, and tenant metrics are not connected.
- [x] Translate LIM console tab labels to Chinese and keep tab selection synchronized with the navigation route.
- [x] Rework Run / Trace into a Chinese three-panel analysis workspace with run filtering, span timeline, selected-span attributes, and sanitized trace data, using the existing trace endpoint.

### Task 4: Apply the AI Decision Center navigation structure

**Files:**
- Modify: `frontend/src/config/menu.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/AssistantPage.tsx`
- Modify: existing AI page headings where their current routes map to the menu

- [x] Arrange AI navigation in the requested 01–12 sequence, grouping business agents and execution/history entries for the current shell layout.
- [x] Route existing decision workspace, product, order snapshot, replenishment evidence, procurement, after-sales, and task-history modules to their corresponding entries.
- [x] Keep ads, finance, policy-compliance, and cross-business approval center planned/disabled until those pages exist.
- [x] Keep current feature limits visible in existing page descriptions; do not claim trend analysis, business execution, or compliance checks beyond the implemented behavior.

### Task 5: Implement the AI经营驾驶舱

**Files:**
- Create: `frontend/src/pages/AiDashboardPage.tsx`
- Modify: `frontend/src/config/menu.ts`
- Modify: `frontend/src/App.tsx`

- [x] Render an authorized current-state overview using the existing order, inventory, purchase, and replenishment summary endpoints; keep each section permission-filtered and show data provenance.
- [x] Prioritize only actionable risks supported by current data: draft orders, low-stock warehouse/SKU combinations, pending replenishment suggestions, and submitted purchase approvals.
- [x] Provide next-step links to existing business modules and a read-only current-snapshot entry to the decision workbench when no deterministic risk action is pending.
- [x] Make the dashboard the AI system landing page and replace its planned menu entry with a permission-guarded route.
- [x] State that the page is a local operational snapshot, not platform-live data; do not claim historical trends, profit analysis, or AI-generated diagnosis.

### Task 6: Redesign the management cockpit (approved 2026-10-22)

The user rejected the snapshot-first layout and approved a complete product design before capability integration. Build a Chinese management cockpit around an executive briefing, business trends, risk explanations/evidence, and prioritized actions. The shared visual reference could not be retrieved; use the agreed information hierarchy without claiming pixel fidelity.

- Replace the main page with a responsive, designed management workspace and clearly labeled sample data.
- Provide scope/date filters, selectable trend metrics, risk details with evidence, and action previews with page-local simulation state. Do not submit business changes.
- Keep the existing API-backed snapshot accessible separately in a data drawer, with its original permissions and provenance.
- Preserve the approved 12-item AI navigation and existing ERP design.
- Verify frontend compilation and inspect responsive layout where browser access is available.

Implementation: `AiDashboardPage.tsx`, `aiCockpitDemo.ts`, and `aiCockpit.css` implement the design; `AiDashboardLiveSnapshot.tsx` retains the previous API-backed view. `MainLayout.tsx` and scoped `aiShell.css` give AI its own 12-entry sidebar and responsive overlay without changing the ERP shell.

Validation: isolated Playwright review with intercepted API requests passed period and store filters, metric selection, trend-table access, risk/evidence details, local plan confirmation/reset, permission-limited live snapshot, and 698/390px layouts including navigation expansion. No business mutation requests or browser page errors. Review script/results/screenshots are in `outputs/ai-cockpit-review/`. The existing application bundle exceeds Vite's 500 kB chunk warning threshold; this redesign does not split the entire application bundle.
