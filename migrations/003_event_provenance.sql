-- Foundation Production Readiness 1: event code-revision provenance.
-- Fleet Law 6: every event carries run/source/code-revision. Historical
-- rows keep the literal UNKNOWN — never backfilled with a current SHA,
-- which would fabricate provenance.

ALTER TABLE events ADD COLUMN code_revision TEXT NOT NULL DEFAULT 'UNKNOWN';

CREATE INDEX IF NOT EXISTS idx_events_code_revision ON events(code_revision);
