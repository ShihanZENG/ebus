# LIM Trace JSON export

## Acceptance
- Add a dedicated JSON export endpoint using the same Trace payload serializer as reads.
- Re-sanitize the complete serialized payload before export.
- Enforce `assistant:read` and existing run visibility; record content-free allowed/denied export audit events.
- Provide an explicit Console download through the authenticated API client.
- Verify secret/PII redaction, payload parity, headers, and access denial.

## Steps
1. Add failing API tests for export, whole-payload redaction, and allowed/denied audit.
2. Extract shared Trace serialization and implement the audited download response.
3. Add authenticated frontend download and update capability inventory.
4. Run focused and LIM suite checks plus frontend typecheck/build.
