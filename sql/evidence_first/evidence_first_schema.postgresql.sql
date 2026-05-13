-- evidence_first_schema.postgresql.sql
-- Evidence-first incident store for PRISM (PostgreSQL 12+).
-- Flexible fields use type JSON (portable). GIN indexes use (col::jsonb) for PostgreSQL jsonb_ops.
--
-- >>> Run this file ONLY with PostgreSQL (psql, pgAdmin, etc.). <<<
--
-- If you see: "Cannot execute statement of type CREATE on database metadata which is attached in read-only mode"
-- you are executing PostgreSQL DDL inside DuckDB against the RAG chunk DB (`metadata.duckdb`), which is often
-- attached read-only. That is the wrong engine and wrong file. For local DuckDB persistence use instead:
--   sql/evidence_first/evidence_first_schema.duckdb.sql
-- on a separate read-write file, e.g. data/duckdb/evidence_store.duckdb (see config/settings.yaml evidence_store.db_path).
--
-- Column `ts` stores the normalized event time (maps from API field `timestamp` to avoid reserved word `timestamp`).

CREATE TABLE IF NOT EXISTS incident_case (
    incident_id             TEXT PRIMARY KEY,
    title                   TEXT,
    status                  TEXT,
    created_at              TIMESTAMPTZ,
    updated_at              TIMESTAMPTZ,
    user_id                 TEXT,
    environment             TEXT,
    db_name                 TEXT,
    instance_name           TEXT,
    primary_host            TEXT,
    platform                TEXT,
    current_rca_status      TEXT,
    current_root_cause      TEXT,
    current_score           DOUBLE PRECISION,
    tags                    JSON,
    notes                   TEXT
);

CREATE TABLE IF NOT EXISTS source_bundle (
    bundle_id               TEXT PRIMARY KEY,
    incident_id             TEXT NOT NULL REFERENCES incident_case(incident_id),
    bundle_type             TEXT,
    original_name           TEXT,
    uploaded_at             TIMESTAMPTZ,
    sha256                  TEXT,
    size_bytes              BIGINT,
    storage_uri             TEXT,
    accepted                BOOLEAN,
    rejection_reason        TEXT,
    ingest_diagnostics      JSON,
    metadata                JSON
);

CREATE TABLE IF NOT EXISTS source_file (
    source_id               TEXT PRIMARY KEY,
    bundle_id               TEXT NOT NULL REFERENCES source_bundle(bundle_id),
    incident_id             TEXT NOT NULL REFERENCES incident_case(incident_id),
    source_file             TEXT,
    source_path             TEXT,
    internal_zip_path       TEXT,
    source_type             TEXT,
    detected_layer          TEXT,
    host                    TEXT,
    db_name                 TEXT,
    instance_name           TEXT,
    sha256                  TEXT,
    size_bytes              BIGINT,
    line_count              INTEGER,
    parse_status            TEXT,
    skip_reason             TEXT,
    storage_uri             TEXT,
    raw_stored              BOOLEAN DEFAULT FALSE,
    created_at              TIMESTAMPTZ,
    metadata                JSON
);

CREATE TABLE IF NOT EXISTS parser_run (
    parser_run_id           TEXT PRIMARY KEY,
    incident_id             TEXT NOT NULL REFERENCES incident_case(incident_id),
    source_id               TEXT NOT NULL REFERENCES source_file(source_id),
    parser_name             TEXT,
    parser_version          TEXT,
    schema_version          TEXT,
    started_at              TIMESTAMPTZ,
    finished_at             TIMESTAMPTZ,
    duration_ms             INTEGER,
    status                  TEXT,
    event_count             INTEGER,
    warning_count           INTEGER,
    error_message           TEXT,
    diagnostics             JSON
);

CREATE TABLE IF NOT EXISTS pattern_catalog (
    pattern_id              TEXT PRIMARY KEY,
    display_name            TEXT,
    description             TEXT,
    layer                   TEXT,
    code_type               TEXT,
    failure_family          TEXT,
    semantic_group          TEXT,
    default_role            TEXT,
    root_eligible           BOOLEAN DEFAULT TRUE,
    object_locator          BOOLEAN DEFAULT FALSE,
    confidence_weight       DOUBLE PRECISION,
    cascade_weight          DOUBLE PRECISION,
    requires_lower_layer_confirmation BOOLEAN DEFAULT FALSE,
    required_evidence        JSON,
    remediation_category    TEXT,
    diagnostic_hints         JSON,
    active                  BOOLEAN DEFAULT TRUE,
    version                 TEXT,
    metadata                JSON
);

CREATE TABLE IF NOT EXISTS normalized_event (
    event_id                TEXT PRIMARY KEY,
    incident_id             TEXT NOT NULL REFERENCES incident_case(incident_id),
    bundle_id               TEXT REFERENCES source_bundle(bundle_id),
    source_id               TEXT REFERENCES source_file(source_id),
    parser_run_id           TEXT REFERENCES parser_run(parser_run_id),
    ts                      TIMESTAMPTZ,
    timestamp_raw           TEXT,
    timestamp_confidence    TEXT,
    source_file             TEXT,
    source_path             TEXT,
    line_number             INTEGER,
    line_start              INTEGER,
    line_end                INTEGER,
    host                    TEXT,
    platform                TEXT,
    database_name           TEXT,
    instance_name           TEXT,
    layer                   TEXT,
    component               TEXT,
    process                 TEXT,
    pid                     TEXT,
    thread                  TEXT,
    code                    TEXT,
    code_type               TEXT,
    message                 TEXT,
    severity                TEXT,
    role_hint               TEXT,
    failure_family          TEXT,
    object_type             TEXT,
    object_name             TEXT,
    file_path               TEXT,
    trace_file              TEXT,
    device                  TEXT,
    multipath_device        TEXT,
    diskgroup               TEXT,
    asm_group               TEXT,
    asm_disk                TEXT,
    asm_file                TEXT,
    au                      TEXT,
    offset_value            TEXT,
    block_value             TEXT,
    size_value              TEXT,
    redo_group              TEXT,
    redo_thread             TEXT,
    redo_sequence           TEXT,
    os_errno                TEXT,
    linux_error             TEXT,
    cell                    TEXT,
    flash_disk              TEXT,
    cell_disk               TEXT,
    grid_disk               TEXT,
    crs_resource            TEXT,
    raw_hash                TEXT,
    raw                     TEXT,
    preview                 TEXT,
    parse_confidence        TEXT,
    evidence_state          TEXT,
    row_kind                TEXT,
    details                 JSON,
    tags                    JSON,
    created_at              TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS event_pattern_match (
    match_id                TEXT PRIMARY KEY,
    event_id                TEXT NOT NULL REFERENCES normalized_event(event_id),
    pattern_id              TEXT NOT NULL REFERENCES pattern_catalog(pattern_id),
    match_type              TEXT,
    match_confidence        DOUBLE PRECISION,
    matched_text            TEXT,
    matcher_name            TEXT,
    matcher_version         TEXT,
    details                 JSON
);

CREATE TABLE IF NOT EXISTS correlation_run (
    correlation_run_id    TEXT PRIMARY KEY,
    incident_id             TEXT NOT NULL REFERENCES incident_case(incident_id),
    run_number              INTEGER,
    correlation_version     TEXT,
    started_at              TIMESTAMPTZ,
    finished_at             TIMESTAMPTZ,
    duration_ms             INTEGER,
    event_count             INTEGER,
    source_count            INTEGER,
    observed_layers         JSON,
    observed_ora_codes      JSON,
    observed_non_ora_codes  JSON,
    correlation_model_score DOUBLE PRECISION,
    root_cause_evidence_status TEXT,
    retrieval_confidence    DOUBLE PRECISION,
    retrieval_note          TEXT,
    summary                 TEXT,
    diagnostics             JSON
);

CREATE TABLE IF NOT EXISTS event_correlation_edge (
    edge_id                 TEXT PRIMARY KEY,
    correlation_run_id      TEXT NOT NULL REFERENCES correlation_run(correlation_run_id),
    from_event_id           TEXT REFERENCES normalized_event(event_id),
    to_event_id             TEXT REFERENCES normalized_event(event_id),
    relation_type           TEXT,
    confidence              DOUBLE PRECISION,
    reason                  TEXT,
    correlation_keys        JSON,
    created_at              TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS rca_candidate (
    candidate_id            TEXT PRIMARY KEY,
    correlation_run_id      TEXT NOT NULL REFERENCES correlation_run(correlation_run_id),
    incident_id             TEXT NOT NULL REFERENCES incident_case(incident_id),
    rank                    INTEGER,
    root_cause              TEXT,
    root_layer              TEXT,
    status                  TEXT,
    score                   DOUBLE PRECISION,
    why_this_candidate      TEXT,
    what_would_change       TEXT,
    evidence_event_ids      JSON,
    missing_evidence        JSON,
    is_selected             BOOLEAN DEFAULT FALSE,
    details                 JSON
);

CREATE TABLE IF NOT EXISTS cascade_step (
    step_id                 TEXT PRIMARY KEY,
    correlation_run_id      TEXT NOT NULL REFERENCES correlation_run(correlation_run_id),
    candidate_id            TEXT REFERENCES rca_candidate(candidate_id),
    step_order               INTEGER,
    label                   TEXT,
    layer                   TEXT,
    marker                  TEXT,
    role                    TEXT,
    event_id                TEXT REFERENCES normalized_event(event_id),
    evidence_preview        TEXT,
    details                 JSON
);

CREATE TABLE IF NOT EXISTS report_snapshot (
    report_id               TEXT PRIMARY KEY,
    incident_id             TEXT NOT NULL REFERENCES incident_case(incident_id),
    correlation_run_id      TEXT REFERENCES correlation_run(correlation_run_id),
    report_version          TEXT,
    status                  TEXT,
    title                   TEXT,
    executive_summary       TEXT,
    root_cause_summary      TEXT,
    confidence_summary      TEXT,
    report_json             JSON,
    report_markdown         TEXT,
    created_at              TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS recommended_action (
    action_id               TEXT PRIMARY KEY,
    report_id               TEXT NOT NULL REFERENCES report_snapshot(report_id),
    incident_id             TEXT NOT NULL REFERENCES incident_case(incident_id),
    action_order            INTEGER,
    layer                   TEXT,
    action_type             TEXT,
    title                   TEXT,
    command_text            TEXT,
    explanation             TEXT,
    risk_level              TEXT,
    requires_approval       BOOLEAN DEFAULT FALSE,
    details                 JSON
);

CREATE TABLE IF NOT EXISTS human_feedback (
    feedback_id             TEXT PRIMARY KEY,
    incident_id             TEXT NOT NULL REFERENCES incident_case(incident_id),
    report_id               TEXT REFERENCES report_snapshot(report_id),
    user_id                 TEXT,
    created_at              TIMESTAMPTZ,
    feedback_type           TEXT,
    severity                TEXT,
    user_comment            TEXT,
    corrected_root_cause    TEXT,
    corrected_layer         TEXT,
    affected_event_ids      JSON,
    details                 JSON
);

CREATE INDEX IF NOT EXISTS idx_event_incident ON normalized_event(incident_id);
CREATE INDEX IF NOT EXISTS idx_event_code ON normalized_event(code);
CREATE INDEX IF NOT EXISTS idx_event_layer ON normalized_event(layer);
CREATE INDEX IF NOT EXISTS idx_event_ts ON normalized_event(ts);
CREATE INDEX IF NOT EXISTS idx_event_source ON normalized_event(source_id);
CREATE INDEX IF NOT EXISTS idx_event_host ON normalized_event(host);
CREATE INDEX IF NOT EXISTS idx_event_diskgroup ON normalized_event(diskgroup);
CREATE INDEX IF NOT EXISTS idx_event_device ON normalized_event(device);
CREATE INDEX IF NOT EXISTS idx_event_mpath ON normalized_event(multipath_device);
CREATE INDEX IF NOT EXISTS idx_event_redo_group ON normalized_event(redo_group);
CREATE INDEX IF NOT EXISTS idx_event_cell_disk ON normalized_event(cell_disk);
CREATE INDEX IF NOT EXISTS idx_event_flash_disk ON normalized_event(flash_disk);
CREATE INDEX IF NOT EXISTS idx_event_grid_disk ON normalized_event(grid_disk);

CREATE INDEX IF NOT EXISTS idx_correlation_incident ON correlation_run(incident_id);
CREATE INDEX IF NOT EXISTS idx_candidate_run ON rca_candidate(correlation_run_id);
CREATE INDEX IF NOT EXISTS idx_cascade_run ON cascade_step(correlation_run_id);
CREATE INDEX IF NOT EXISTS idx_bundle_incident ON source_bundle(incident_id);
CREATE INDEX IF NOT EXISTS idx_file_bundle ON source_file(bundle_id);
CREATE INDEX IF NOT EXISTS idx_parser_source ON parser_run(source_id);
CREATE INDEX IF NOT EXISTS idx_report_incident ON report_snapshot(incident_id);
CREATE INDEX IF NOT EXISTS idx_feedback_incident ON human_feedback(incident_id);

CREATE INDEX IF NOT EXISTS idx_event_details_gin ON normalized_event USING GIN ((details::jsonb));
CREATE INDEX IF NOT EXISTS idx_report_json_gin ON report_snapshot USING GIN ((report_json::jsonb));
