# Legacy modules (not on the production evidence-first path)

Production diagnostics use:

`src/agent/agent.py` → normalized evidence → `src/agent/event_correlation.py` → `src/agent/report_builder.py`.

The following are **deprecated for new RCA work** but kept because tests, QA runners, and demos still import them:

| Module | Role |
|--------|------|
| `src/agent/orchestrator.py` | `DBAChatbotOrchestrator`, session + temporal graph |
| `src/agent/evidence_aggregator.py` | `compute_confidence`, legacy scoring |
| `src/pipeline/temporal_graph.py` | `TemporalGraphEngine`, print-heavy timeline anchor |

Do **not** extend these for new product RCA logic; add behavior in the evidence-first pipeline instead.
