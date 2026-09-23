-- Board Clank schema v1. Additive. Domain truth lives here.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vendors (
    vendor_key TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS board_families (
    family_key TEXT PRIMARY KEY,
    vendor_key TEXT NOT NULL REFERENCES vendors(vendor_key),
    family_slug TEXT NOT NULL,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS socs (
    soc_key TEXT PRIMARY KEY,
    vendor TEXT NOT NULL,
    marketing_name TEXT NOT NULL,
    architecture TEXT NOT NULL,
    cpu_configuration TEXT NOT NULL,
    gpu TEXT NOT NULL,
    npu TEXT NOT NULL,
    npu_tops TEXT NOT NULL,
    process_node_if_known TEXT NOT NULL,
    source_provenance TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS boards (
    board_key TEXT PRIMARY KEY,
    vendor_key TEXT NOT NULL REFERENCES vendors(vendor_key),
    family_key TEXT NOT NULL REFERENCES board_families(family_key),
    board_slug TEXT NOT NULL,
    marketing_name TEXT NOT NULL,
    board_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    first_seen_source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS board_revisions (
    revision_key TEXT PRIMARY KEY,
    board_key TEXT NOT NULL REFERENCES boards(board_key),
    revision_kind TEXT NOT NULL,
    revision_token TEXT NOT NULL,
    soc_key TEXT NOT NULL REFERENCES socs(soc_key),
    ports_signature TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS board_variants (
    variant_key TEXT PRIMARY KEY,
    board_key TEXT NOT NULL REFERENCES boards(board_key),
    revision_key TEXT NOT NULL REFERENCES board_revisions(revision_key),
    variant_fingerprint TEXT NOT NULL,
    ram TEXT NOT NULL,
    storage TEXT NOT NULL,
    wireless TEXT NOT NULL,
    region TEXT NOT NULL,
    bundle TEXT NOT NULL,
    sku TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (revision_key, variant_fingerprint)
);

CREATE TABLE IF NOT EXISTS sources (
    source_key TEXT PRIMARY KEY,
    vendor TEXT NOT NULL,
    plane TEXT NOT NULL,
    authority TEXT NOT NULL,
    base_urls_json TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0,
    promotion_state TEXT NOT NULL,
    registered_state TEXT NOT NULL,
    notes TEXT NOT NULL,
    expected_identity_surface TEXT NOT NULL,
    expected_variant_surface TEXT NOT NULL,
    placeholder INTEGER NOT NULL DEFAULT 0,
    out_of_scope INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS source_baselines (
    source_key TEXT PRIMARY KEY,
    baseline_run_id TEXT NOT NULL,
    established_at TEXT NOT NULL,
    observation_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS collector_runs (
    run_id TEXT PRIMARY KEY,
    source_key TEXT NOT NULL,
    collector_key TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    fixture_scenario TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS canonical_observations (
    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_kind TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    board_key TEXT NOT NULL,
    revision_key TEXT NOT NULL,
    variant_key TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    first_accepted_at TEXT NOT NULL,
    first_source_key TEXT NOT NULL,
    UNIQUE (entity_kind, entity_key, content_hash)
);

CREATE TABLE IF NOT EXISTS observation_occurrences (
    occurrence_id INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id INTEGER NOT NULL REFERENCES canonical_observations(observation_id),
    run_id TEXT NOT NULL REFERENCES collector_runs(run_id),
    source_key TEXT NOT NULL,
    plane TEXT NOT NULL,
    entity_kind TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    content_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS current_entity_observations (
    entity_kind TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    observation_id INTEGER NOT NULL REFERENCES canonical_observations(observation_id),
    content_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_run_id TEXT NOT NULL,
    PRIMARY KEY (entity_kind, entity_key)
);

CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    entity_kind TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    board_key TEXT NOT NULL,
    revision_key TEXT NOT NULL,
    variant_key TEXT NOT NULL,
    source_key TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES collector_runs(run_id),
    from_hash TEXT NOT NULL,
    to_hash TEXT NOT NULL,
    baseline_silent INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    code_revision TEXT NOT NULL DEFAULT 'UNKNOWN'
);

CREATE TABLE IF NOT EXISTS notifications (
    notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT NOT NULL REFERENCES events(event_key),
    disposition TEXT NOT NULL,
    channel TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    UNIQUE (event_key, channel)
);

CREATE TABLE IF NOT EXISTS delivery_policy (
    event_type TEXT PRIMARY KEY,
    disposition TEXT NOT NULL,
    notes TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS processed_run_receipts (
    run_id TEXT PRIMARY KEY,
    source_key TEXT NOT NULL,
    receipt_hash TEXT NOT NULL,
    accepted_at TEXT NOT NULL,
    observation_count INTEGER NOT NULL,
    event_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS run_errors (
    error_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    source_key TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS board_classifications (
    board_key TEXT NOT NULL,
    context TEXT NOT NULL,
    source_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (board_key, context)
);

CREATE TABLE IF NOT EXISTS novelty_evidence (
    entity_kind TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    first_seen_source TEXT NOT NULL,
    official_announcement_at TEXT NOT NULL,
    official_sale_at TEXT NOT NULL,
    official_shipping_at TEXT NOT NULL,
    docs_date TEXT NOT NULL,
    store_date TEXT NOT NULL,
    novelty_status TEXT NOT NULL,
    novelty_basis TEXT NOT NULL,
    novelty_confidence TEXT NOT NULL,
    PRIMARY KEY (entity_kind, entity_key)
);

CREATE TABLE IF NOT EXISTS price_observations (
    price_id INTEGER PRIMARY KEY AUTOINCREMENT,
    variant_key TEXT NOT NULL,
    source_key TEXT NOT NULL,
    amount TEXT NOT NULL,
    currency TEXT NOT NULL,
    region TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    run_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS software_support (
    support_id INTEGER PRIMARY KEY AUTOINCREMENT,
    board_key TEXT NOT NULL,
    os_name TEXT NOT NULL,
    source_key TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    UNIQUE (board_key, os_name, source_key)
);

CREATE TABLE IF NOT EXISTS diagnostic_conditions (
    condition_key TEXT PRIMARY KEY,
    source_key TEXT NOT NULL,
    plane TEXT NOT NULL,
    diagnostic_type TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    reason TEXT NOT NULL,
    state_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL,
    first_observed_at TEXT NOT NULL,
    first_run_id TEXT NOT NULL,
    last_observed_at TEXT,
    last_run_id TEXT,
    resolved_at TEXT,
    resolved_run_id TEXT,
    open_occurrences INTEGER NOT NULL DEFAULT 0,
    total_occurrences INTEGER NOT NULL DEFAULT 0,
    transition_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS diagnostic_sightings (
    sighting_id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_key TEXT NOT NULL REFERENCES diagnostic_conditions(condition_key),
    run_id TEXT NOT NULL,
    source_key TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    state_hash TEXT NOT NULL,
    emitted_event_key TEXT
);

CREATE INDEX IF NOT EXISTS idx_diagnostic_conditions_source_status
    ON diagnostic_conditions(source_key, status);
CREATE INDEX IF NOT EXISTS idx_diagnostic_sightings_run
    ON diagnostic_sightings(run_id);
