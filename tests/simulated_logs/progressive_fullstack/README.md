# Progressive Full-Stack Incident Simulation

Use this scenario to test **Continue Investigation** step-by-step across
RDBMS + DB + OS + Infra correlation.

## Goal

- First upload/paste should produce a provisional response and ask for more evidence.
- Second follow-up should still ask for more evidence.
- Third/fourth follow-up should provide enough correlated context for a near-final/final diagnosis.
- Mismatch guard should reject unrelated follow-up evidence.

## Host / Incident Window

- Host: `dbhost07`
- Progressive observation window: `2024-03-16 07:00:00` to `2024-03-16 07:36:30` UTC
- Primary ORA family: `ORA-27072`, `ORA-15080`, `ORA-00353`

> Note: this simulation intentionally spreads events over ~36 minutes.
> Follow-up uploads can be later as long as they
> remain causally related (same host/platform/ORA family or directly linked
> storage/network symptoms).

## Upload / Paste Order

1. `step1_rdbms_alert_only.log` (paste or upload)
2. `step2_db_trace_followup.log` (follow-up)
3. `step3_os_syslog_followup.log` (follow-up)
4. `step4_infra_storage_followup.log` (follow-up)

Then optionally try:

5. `wrong_incident_unrelated.log` (should be rejected by relevance guard)

## What this validates

- Regex pattern detection for ORA/storage signatures
- Chunking continuity with timestamped multi-line logs
- Chronological correlation across multiple sources
- Follow-up confidence/reason messaging
- Same-incident relevance filtering (ORA/host/platform/time guard)

## Recommended Practical Correlation Policy

- Start with a tight anchor (`+-10 minutes`) around the first failure.
- If evidence is sparse, expand progressively (`+-30 minutes`, then `+-60 minutes`).
- Keep host/platform constraints strict, but allow ORA family evolution
  (for example `ORA-27072` -> `ORA-15080` -> `ORA-00353`) inside one incident.
