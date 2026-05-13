-- evidence_first_schema.duckdb.sql
-- Evidence-first incident store for PRISM (DuckDB).
-- JSON columns use DuckDB JSON type (not JSONB).
-- Apply to a dedicated database file (recommended: separate from retrieval metadata.duckdb).

CREATE TABLE IF NOT EXISTS incident_case (
    incident_id            VARCHAR PRIMARY KEY,
    title                  VARCHAR,
    status                 VARCHAR,
    created_at             TIMESTAMPTZ,
    updated_at             TIMESTAMPTZ,
    user_id                VARCHAR,
    environment            VARCHAR,
    db_name                VARCHAR,
    instance_name          VARCHAR,
    primary_host           VARCHAR,
    platform               VARCHAR,
    current_rca_status     VARCHAR,
    current_root_cause     VARCHAR,
    current_score          DOUBLE,
    tags                   JSON,
    notes                  VARCHAR
);

CREATE TABLE IF NOT EXISTS source_bundle (
    bundle_id              VARCHAR PRIMARY KEY,
    incident_id            VARCHAR NOT NULL REFERENCES incident_case(incident_id),
    bundle_type            VARCHAR,
    original_name          VARCHAR,
    uploaded_at            TIMESTAMPTZ,
    sha256                 VARCHAR,
    size_bytes             BIGINT,
    storage_uri            VARCHAR,
    accepted               BOOLEAN,
    rejection_reason       VARCHAR,
    ingest_diagnostics     JSON,
    metadata               JSON
);

CREATE TABLE IF NOT EXISTS source_file (
    source_id              VARCHAR PRIMARY KEY,
    bundle_id              VARCHAR NOT NULL REFERENCES source_bundle(bundle_id),
    incident_id            VARCHAR NOT NULL REFERENCES incident_case(incident_id),
    source_file            VARCHAR,
    source_path            VARCHAR,
    internal_zip_path      VARCHAR,
    source_type            VARCHAR,
    detected_layer         VARCHAR,
    host                   VARCHAR,
    db_name                VARCHAR,
    instance_name          VARCHAR,
    sha256                 VARCHAR,
    size_bytes             BIGINT,
    line_count             INTEGER,
    parse_status           VARCHAR,
    skip_reason            VARCHAR,
    storage_uri            VARCHAR,
    raw_stored             BOOLEAN DEFAULT FALSE,
    created_at             TIMESTAMPTZ,
    metadata               JSON
);

CREATE TABLE IF NOT EXISTS parser_run (
    parser_run_id          VARCHAR PRIMARY KEY,
    incident_id            VARCHAR NOT NULL REFERENCES incident_case(incident_id),
    source_id              VARCHAR NOT NULL REFERENCES source_file(source_id),
    parser_name            VARCHAR,
    parser_version         VARCHAR,
    schema_version         VARCHAR,
    started_at             TIMESTAMPTZ,
    finished_at            TIMESTAMPTZ,
    duration_ms            INTEGER,
    status                 VARCHAR,
    event_count            INTEGER,
    warning_count          INTEGER,
    error_message          VARCHAR,
    diagnostics            JSON
);

CREATE TABLE IF NOT EXISTS pattern_catalog (
    pattern_id             VARCHAR PRIMARY KEY,
    display_name           VARCHAR,
    description            VARCHAR,
    layer                  VARCHAR,
    code_type              VARCHAR,
    failure_family         VARCHAR,
    semantic_group         VARCHAR,
    default_role           VARCHAR,
    root_eligible          BOOLEAN DEFAULT TRUE,
    object_locator         BOOLEAN DEFAULT FALSE,
    confidence_weight      DOUBLE,
    cascade_weight         DOUBLE,
    requires_lower_layer_confirmation BOOLEAN DEFAULT FALSE,
    required_evidence      JSON,
    remediation_category   VARCHAR,
    diagnostic_hints       JSON,
    active                 BOOLEAN DEFAULT TRUE,
    version                VARCHAR,
    metadata               JSON
);

CREATE TABLE IF NOT EXISTS normalized_event (
    event_id               VARCHAR PRIMARY KEY,
    incident_id            VARCHAR NOT NULL REFERENCES incident_case(incident_id),
    bundle_id              VARCHAR REFERENCES source_bundle(bundle_id),
    source_id              VARCHAR REFERENCES source_file(source_id),
    parser_run_id          VARCHAR REFERENCES parser_run(parser_run_id),
    ts                     TIMESTAMPTZ,
    timestamp_raw          VARCHAR,
    timestamp_confidence   VARCHAR,
    source_file            VARCHAR,
    source_path            VARCHAR,
    line_number            INTEGER,
    line_start             INTEGER,
    line_end               INTEGER,
    host                   VARCHAR,
    platform               VARCHAR,
    database_name          VARCHAR,
    instance_name          VARCHAR,
    layer                  VARCHAR,
    component              VARCHAR,
    process                VARCHAR,
    pid                    VARCHAR,
    thread                 VARCHAR,
    code                   VARCHAR,
    code_type              VARCHAR,
    message                VARCHAR,
    severity               VARCHAR,
    role_hint              VARCHAR,
    failure_family         VARCHAR,
    object_type            VARCHAR,
    object_name            VARCHAR,
    file_path              VARCHAR,
    trace_file             VARCHAR,
    device                 VARCHAR,
    multipath_device       VARCHAR,
    diskgroup              VARCHAR,
    asm_group              VARCHAR,
    asm_disk               VARCHAR,
    asm_file               VARCHAR,
    au                     VARCHAR,
    offset_value           VARCHAR,
    block_value            VARCHAR,
    size_value             VARCHAR,
    redo_group             VARCHAR,
    redo_thread            VARCHAR,
    redo_sequence          VARCHAR,
    os_errno               VARCHAR,
    linux_error            VARCHAR,
    cell                   VARCHAR,
    flash_disk             VARCHAR,
    cell_disk              VARCHAR,
    grid_disk              VARCHAR,
    crs_resource           VARCHAR,
    raw_hash               VARCHAR,
    raw                    VARCHAR,
    preview                VARCHAR,
    parse_confidence       VARCHAR,
    evidence_state         VARCHAR,
    row_kind               VARCHAR,
    details                JSON,
    tags                   JSON,
    created_at             TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS event_pattern_match (
    match_id               VARCHAR PRIMARY KEY,
    event_id               VARCHAR NOT NULL REFERENCES normalized_event(event_id),
    pattern_id             VARCHAR NOT NULL REFERENCES pattern_catalog(pattern_id),
    match_type             VARCHAR,
    match_confidence       DOUBLE,
    matched_text           VARCHAR,
    matcher_name           VARCHAR,
    matcher_version        VARCHAR,
    details                JSON
);

CREATE TABLE IF NOT EXISTS correlation_run (
    correlation_run_id     VARCHAR PRIMARY KEY,
    incident_id            VARCHAR NOT NULL REFERENCES incident_case(incident_id),
    run_number             INTEGER,
    correlation_version    VARCHAR,
    started_at             TIMESTAMPTZ,
    finished_at            TIMESTAMPTZ,
    duration_ms            INTEGER,
    event_count            INTEGER,
    source_count           INTEGER,
    observed_layers        JSON,
    observed_ora_codes     JSON,
    observed_non_ora_codes JSON,
    correlation_model_score DOUBLE,
    root_cause_evidence_status VARCHAR,
    retrieval_confidence   DOUBLE,
    retrieval_note         VARCHAR,
    summary                VARCHAR,
    diagnostics            JSON
);

CREATE TABLE IF NOT EXISTS event_correlation_edge (
    edge_id                VARCHAR PRIMARY KEY,
    correlation_run_id     VARCHAR NOT NULL REFERENCES correlation_run(correlation_run_id),
    from_event_id          VARCHAR REFERENCES normalized_event(event_id),
    to_event_id            VARCHAR REFERENCES normalized_event(event_id),
    relation_type          VARCHAR,
    confidence             DOUBLE,
    reason                 VARCHAR,
    correlation_keys       JSON,
    created_at             TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS rca_candidate (
    candidate_id           VARCHAR PRIMARY KEY,
    correlation_run_id     VARCHAR NOT NULL REFERENCES correlation_run(correlation_run_id),
    incident_id            VARCHAR NOT NULL REFERENCES incident_case(incident_id),
    rank                   INTEGER,
    root_cause             VARCHAR,
    root_layer             VARCHAR,
    status                 VARCHAR,
    score                  DOUBLE,
    why_this_candidate     VARCHAR,
    what_would_change      VARCHAR,
    evidence_event_ids     JSON,
    missing_evidence       JSON,
    is_selected            BOOLEAN DEFAULT FALSE,
    details                JSON
);

CREATE TABLE IF NOT EXISTS cascade_step (
    step_id                VARCHAR PRIMARY KEY,
    correlation_run_id     VARCHAR NOT NULL REFERENCES correlation_run(correlation_run_id),
    candidate_id           VARCHAR REFERENCES rca_candidate(candidate_id),
    step_order             INTEGER,
    label                  VARCHAR,
    layer                  VARCHAR,
    marker                 VARCHAR,
    role                   VARCHAR,
    event_id               VARCHAR REFERENCES normalized_event(event_id),
    evidence_preview       VARCHAR,
    details                JSON
);

CREATE TABLE IF NOT EXISTS report_snapshot (
    report_id              VARCHAR PRIMARY KEY,
    incident_id            VARCHAR NOT NULL REFERENCES incident_case(incident_id),
    correlation_run_id     VARCHAR REFERENCES correlation_run(correlation_run_id),
    report_version         VARCHAR,
    status                 VARCHAR,
    title                  VARCHAR,
    executive_summary      VARCHAR,
    root_cause_summary     VARCHAR,
    confidence_summary     VARCHAR,
    report_json            JSON,
    report_markdown        VARCHAR,
    created_at             TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS recommended_action (
    action_id              VARCHAR PRIMARY KEY,
    report_id              VARCHAR NOT NULL REFERENCES report_snapshot(report_id),
    incident_id            VARCHAR NOT NULL REFERENCES incident_case(incident_id),
    action_order           INTEGER,
    layer                  VARCHAR,
    action_type            VARCHAR,
    title                  VARCHAR,
    command_text           VARCHAR,
    explanation            VARCHAR,
    risk_level             VARCHAR,
    requires_approval      BOOLEAN DEFAULT FALSE,
    details                JSON
);

CREATE TABLE IF NOT EXISTS human_feedback (
    feedback_id            VARCHAR PRIMARY KEY,
    incident_id            VARCHAR NOT NULL REFERENCES incident_case(incident_id),
    report_id              VARCHAR REFERENCES report_snapshot(report_id),
    user_id                VARCHAR,
    created_at             TIMESTAMPTZ,
    feedback_type          VARCHAR,
    severity               VARCHAR,
    user_comment           VARCHAR,
    corrected_root_cause   VARCHAR,
    corrected_layer        VARCHAR,
    affected_event_ids     JSON,
    details                JSON
);

-- Indexes (DuckDB: standard B-tree / ART style indexes on scalar columns)
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
