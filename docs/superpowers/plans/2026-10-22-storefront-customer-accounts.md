# Storefront customer accounts implementation plan

**Goal:** Implement the user-approved customer registration/login and persistent own-order history, keeping guest checkout.
**Architecture:** Separate customer and session tables, plus an order ownership table. HttpOnly SameSite cookie with seven-day expiry, hashed server-side session tokens, existing PBKDF2 password hashing. Account writes require trusted Origin plus custom header. Ownership is set inside the checkout transaction and enforced on retries. Never infer ownership from contact email.
**Stack:** Existing FastAPI/SQLAlchemy/Alembic and React/TypeScript. Username/password accounts (no email verification or password-reset service in this iteration).
**Spec:** User approved the description in this conversation on 2026-10-22.

## Constraints and review focus
- Preserve existing ERP identities, data and guest credentials. Additive schema only.
- Member sessions must not access another member's orders; expired sessions must not silently place guest orders.
- Switching accounts/logout must clear displayed private order data; stale asynchronous responses must not restore it.
- Checkout ownership and idempotent retry must agree; guest orders are not automatically claimed.
- Persistent history is paginated; all existing order status and support authorization must work with membership.
- Current developer instruction prohibits adding/running tests unless requested. Use source review and production compilation; do not claim runtime flow validation.

## Tasks
- [ ] Backend: add customer/session/ownership schema and migration; implement account endpoints, origin protection and rate limits; integrate checkout ownership, order/support access.
- [ ] Frontend: create Chinese account page and permanent header links; restore cookie session; member history/detail and checkout identity protection; clear private state on logout.
- [ ] Integration: compile, inspect scoped diff, apply additive migration only to validated demo database, restart only identified storefront demo API, document usage and limitations.

## Execution
Proceed inline as explicitly authorized. Reuse the current checkout to preserve active work. No commits or broad cleanup. Backend/Frontend shared interface: `/api/storefront/v1/account/{register,login,me,logout,orders}`, `{customer:{id,username}}`, paginated `{items,total,page,page_size}`; frontend supplies `X-Storefront-Request: 1` on writes and expected `X-Customer-Id` for member checkout.
