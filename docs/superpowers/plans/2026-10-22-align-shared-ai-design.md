# Align the AI cockpit to the user's existing design

Source: https://chatgpt.com/s/t_6ad8bf38f8b8819190f3f4d4e1008e43

The complete source is saved in `../specs/2026-10-22-ai-decision-center-user-design.txt`. It defines all 12 menus, shared evidence/task components, and the lifecycle from discovery to analysis, approval and review. Treat it as the product baseline, not a new brainstorming request.

Current implementation scope: correct the cockpit already being worked on, including the analysis entry it needs. Do not claim all 12 modules have been implemented.

1. Follow the referenced light, purple-accented command-center layout: KPIs first, compact insight strip, trends beside risks/todos, recommendations below.
2. Provide sales, contribution profit, ad spend, order volume, turnover and stock-risk metrics, daily/weekly/monthly trend grouping and a labeled sample target comparison.
3. Separate observed sample values from hypotheses needing validation. Show approval, failure and manual-intervention todos as clearly labeled fixtures.
4. Each action can transfer its object, scope, date range, evidence and constraints into a three-column demonstration task preview. Keep this demo flow isolated from live APIs; preserve the existing live assistant via an explicit exit.
5. Build and run focused UI checks for metrics, grouping, todo details, context transfer, editing a demo goal, no mutation requests, and responsive layout.

The image is a visual reference; the Chinese 12-menu domain specification determines the application behavior. Existing ERP and real assistant behavior remain intact.
