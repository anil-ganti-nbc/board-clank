-- Foundation 2B: durable diagnostic conditions.
-- Persistent uncertainty is state, not perpetual novelty: an unchanged
-- unresolved/anomalous condition must stay queryable and per-run observable
-- without minting a fresh intelligence event or outbox row every run.

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
