# Evidence-first persistence schema (PRISM)

This folder defines the **evidence-first** relational model: source of truth is `normalized_event` and versioned `correlation_run`, not a single mutable “root cause” row.

## Files

| File | Engine |
|------|--------|
| `evidence_first_schema.duckdb.sql` | DuckDB (good for local / single-file deployments; keep **separate** from `data/duckdb/metadata.duckdb` used for RAG chunk metadata) |
| `evidence_first_schema.postgresql.sql` | PostgreSQL 12+ (`JSON` columns; GIN on `(details::jsonb)` / `(report_json::jsonb)`). **Not for DuckDB** — use the `.duckdb.sql` file there. |

### Troubleshooting: `CREATE` on database `metadata` read-only

That message comes from **DuckDB** when this PostgreSQL DDL (or any `CREATE`) is run while the **`metadata.duckdb`** catalog is attached **read-only** (typical for RAG / BM25 exploration). Fix: run `evidence_first_schema.postgresql.sql` only against **PostgreSQL**; for DuckDB use **`evidence_first_schema.duckdb.sql`** on **`evidence_store.duckdb`** (read-write), not `metadata.duckdb`. The Python API refuses to use the same path for evidence and retrieval metadata.

## Pipeline (mental model)

```text
incident_case → source_bundle → source_file → parser_run → normalized_event → event_pattern_match
incident_case → correlation_run → event_correlation_edge | rca_candidate | cascade_step
incident_case → report_snapshot → recommended_action
human_feedback → links to incident_case / report_snapshot
```

## Design notes

- **`incident_case.current_*`**: convenience only; authoritative conclusions live under `correlation_run` / `rca_candidate` / `report_snapshot`.
- **`normalized_event.ts`**: event time column (avoids SQL reserved word `timestamp`). Map from your in-app JSON field `timestamp` when inserting.
- **`normalized_event.database_name`**: aligns with SQL naming; your Python normalized dict uses `database` — map on read/write.
- **Raw log bodies**: prefer `storage_uri` on `source_file` + `sha256`; use `normalized_event.raw` / `preview` only when policy allows inline storage.
- **`pattern_catalog`**: load or sync from `config/patterns.json` (and future metadata) so semantic groups are not only in Python.

## Apply (DuckDB)

```bash
cd /path/to/dba_agent
./venv/bin/python -c "
import duckdb
path = 'data/duckdb/evidence_store.duckdb'
con = duckdb.connect(path)
con.execute(open('sql/evidence_first/evidence_first_schema.duckdb.sql').read())
con.close()
print('initialized', path)
"
```

## Python persistence API (DuckDB)

When `evidence_store.enabled` is `true` in `config/settings.yaml`, `OracleDiagnosticAgent._build_evidence_first_report` calls `persist_evidence_first_diagnosis` after each run. The report gains `report["evidence_store"]` with `persisted`, `incident_id`, `correlation_run_id`, `report_id`, `db_path`, etc.

You can also call it from custom code:

```python
from src.persistence.evidence_store import persist_evidence_first_diagnosis

ids = persist_evidence_first_diagnosis(
    parsed_input=parsed,
    report=report,
    source_summary={"source_type": "pasted_text"},
    incident_id=None,  # new inc_* id if omitted
    db_path=None,      # uses settings evidence_store.db_path
)
```

**What gets written today:** `incident_case`, `source_bundle`, `source_file`, `parser_run`, `normalized_event` (all rows), `correlation_run`, `rca_candidate` (primary), `report_snapshot` (subset JSON + status). Not yet: `event_pattern_match`, `event_correlation_edge`, `cascade_step`, `recommended_action`, `human_feedback` (extend as needed).


If you start smaller, create only: `incident_case`, `source_file`, `normalized_event`, `correlation_run`, `rca_candidate`, `report_snapshot` (derive the rest later). The full DDL here is the complete target so you do not rename tables mid-flight.
