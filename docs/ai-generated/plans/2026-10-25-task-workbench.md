# Unified task workbench

Approved scope: the user's approval of the preceding six-stage workbench proposal. Reuse React/Ant Design and existing decision-center APIs, starting with replenishment.

## Plan
- [x] Add tested stage/context helpers: canonical task URL, allowlisted source, status-derived next stage, selected-version rules.
- [x] Extract TaskWorkbench from DecisionCenterPage; provide risk, strategy, simulation, approval, execution, result tabs. Preserve backend actions and permissions. Shared drawer/full-page content.
- [x] Add /ai/tasks/:taskId route, URL stage/version context, origin return link, loading/error handling; existing center entry links choose appropriate stage.
- [x] Run helper tests, TypeScript build, existing decision-center backend tests, and browser checks; obtain review findings.

## Constraints and review focus
No invented server states, no automatic approval/execution, no external purchase. Backend already locks tasks and SKU, checks version expiry/evidence and permissions, and atomically creates ERP drafts with duplicate protection. Retain these contracts.
Check stale task loads, invalid URL versions, rejected-version regeneration, navigation without mutation, and inability to approve/execute the wrong version.
Existing working tree includes unrelated approved changes; edit in place and do not stage or commit those changes.

## Verification and recovery record
- Frontend helper/navigation tests: 6 passed; TypeScript check passed; production build passed (existing large-chunk warning).
- Backend decision-center suite: 8 passed, including immutable versions, changed-stock rejection, duplicate execution and ERP record confirmation.
- Browser: real empty task list and task route; temporary clearly labelled UI-only fixture exercised generation → simulation → approval → execution → result. Fixture removed. No live purchase draft created.
- Reviewer identified stale async detail writes and missing approval/execution decision summary; both addressed. Reviewer subsequently hit usage limit; remaining review performed by implementer.
- During continuation the entire pages directory had disappeared outside this work. User explicitly authorized restoration. Restored missing tracked pages from Git index, reconstructed TaskWorkbench/helpers and missing capability hub, and reapplied the prior storefront contact-email display. Existing staged dashboard deletions were preserved.
- Ruling: preserve existing backend contracts rather than add speculative workflow states; first release focuses on replenishment. Current local database has no strategy tasks, so live authenticated full lifecycle remains unexercised; backend tests cover lifecycle behavior.
