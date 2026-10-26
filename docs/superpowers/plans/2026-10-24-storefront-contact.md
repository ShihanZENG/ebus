# Storefront contact entry implementation plan

**Goal:** Implement the user-approved floating contact button and product enquiry entry, including pre-order messages and authorized order enquiries.
**Architecture:** Reuse storefront support requests and the ERP storefront inbox. Add a separate public pre-sales endpoint; retain existing order authorization. Use a native dialog and current React/FastAPI stack.
**Constraints:** No instant-chat or automatic-email claims. Preserve existing workspace changes. No fabricated orders. Existing customer order credentials remain required for order messages.

- [x] Add API tests: anonymous enquiry appears in authorized admin inbox, contact validation, unavailable product rejection, order access isolation.
- [x] Add migration 0046 for nullable support order ID and contact email; add validated pre-sales endpoint under existing origin/rate/body guards.
- [x] Add accessible contact dialog and persistent launcher, product context entry, order-context submission; show contact and pre-sales source in ERP.
- [x] Run support regression tests and frontend builds; migrate local development database; verify desktop/mobile UI and submission.

Review focus: invalid email, unpublished product, unauthorized order, duplicate clicks, small-screen dialog and keyboard dismissal.

Validation: 8 support/origin/pre-sales tests passed (20 unrelated deselected); storefront production build and ERP typecheck passed. Browser submission ZJS-4033C7F7A016D128 appeared in ERP inbox. Product context and 390px native dialog checked. Local PostgreSQL migration upgraded to 0046.

Independent review: fixed SQLite downgrade attachment loss and inactive ERP product acceptance, each verified with failing-then-passing regression test. No other important findings.

Local runtime repair: duplicate ERP frontend occupied storefront port 15174. Replaced that duplicate with storefront dev server. Storefront proxy defaults to shared ERP backend 18080; isolated demos may override VITE_API_TARGET.
