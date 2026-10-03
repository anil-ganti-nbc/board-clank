"""Malformed v3 and audit-failure regressions using disposable databases only."""
from __future__ import annotations

import json
import sqlite3
import pytest

from board_clank.backup import (
    BackupError, DURABLE_TABLES, create_backup, restore_backup, sha256_file, verify_backup,
)
from board_clank.compatibility import (
    CompatibilityState, StateCompatibilityError, inspect_path,
)
from board_clank.models import CollectorRunRequest
from board_clank.observer import full_snapshot
from board_clank.store import PACKAGED_SCHEMA, Store, load_migration_sql


@pytest.mark.parametrize("table,column", [
    ("schema_migrations", "applied_at"), ("schema_migrations", "name"),
    ("events", "code_revision"), ("collector_runs", "status"),
    ("sources", "plane"), ("sources", "promotion_state"),
    ("processed_run_receipts", "receipt_hash"),
])
def test_all_tables_and_v3_stamp_do_not_admit_wrong_columns(tmp_path, table, column):
    path = tmp_path / "malformed.db"
    Store(path).close()
    with sqlite3.connect(path) as con:
        con.execute(f'ALTER TABLE "{table}" RENAME COLUMN "{column}" TO "missing_{column}"')
    before = path.read_bytes()
    report = inspect_path(path)
    assert report.observed_version == 3 and not report.missing_tables
    assert report.state is CompatibilityState.PARTIAL
    assert table in report.reason and column in report.reason
    snapshot = full_snapshot(path)
    assert snapshot["health"]["overall"] == "degraded"
    for migrate in (False, True):
        with pytest.raises(StateCompatibilityError):
            Store(path, migrate=migrate)
    with pytest.raises(BackupError):
        create_backup(path, tmp_path / "refused-backup")
    assert not (tmp_path / "refused-backup").exists()
    assert path.read_bytes() == before


@pytest.mark.parametrize("table,before,after", [
    ("sources", "enabled INTEGER NOT NULL DEFAULT 0", "enabled TEXT NOT NULL DEFAULT 0"),
    ("sources", "promotion_state TEXT NOT NULL", "promotion_state TEXT"),
    ("sources", "enabled INTEGER NOT NULL DEFAULT 0", "enabled INTEGER NOT NULL DEFAULT 1"),
    ("collector_runs", "run_id TEXT PRIMARY KEY", "run_id TEXT"),
    ("boards", " REFERENCES vendors(vendor_key)", ""),
    ("board_variants", "UNIQUE (revision_key, variant_fingerprint)",
     "UNIQUE (revision_key, variant_fingerprint, ram)"),
])
def test_v3_requires_column_constraints_keys_and_foreign_keys(tmp_path, table, before, after):
    path = tmp_path / "wrong-structure.db"
    Store(path).close()
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA foreign_keys=OFF")
        sql = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]
        assert before in sql
        con.execute(f'DROP TABLE "{table}"')
        con.execute(sql.replace(before, after, 1))
        con.commit()
    finally:
        con.close()
    original = path.read_bytes()
    report = inspect_path(path)
    assert report.observed_version == 3 and not report.missing_tables
    assert report.state is CompatibilityState.PARTIAL
    assert table in report.reason
    assert path.read_bytes() == original


def test_missing_provenance_index_is_partial(tmp_path):
    path = tmp_path / "missing-index.db"
    Store(path).close()
    with sqlite3.connect(path) as con:
        con.execute("DROP INDEX idx_events_code_revision")
    assert inspect_path(path).state is CompatibilityState.PARTIAL


def test_invalid_backup_cannot_activate_even_with_matching_hash_and_counts(tmp_path):
    source = tmp_path / "source.db"
    Store(source).close()
    valid = create_backup(source, tmp_path / "valid")
    # Make a NEW counterfeit fixture with SQLite backup; retained valid artifacts stay immutable.
    forged = tmp_path / "forged.db"
    reader = sqlite3.connect(f"file:{valid.database_path.as_posix()}?mode=ro", uri=True)
    writer = sqlite3.connect(forged)
    try:
        reader.backup(writer)
        writer.execute("ALTER TABLE schema_migrations RENAME COLUMN name TO wrong_name")
        writer.commit()
    finally:
        writer.close()
        reader.close()
    metadata = dict(valid.metadata, sha256=sha256_file(forged))
    meta_path = tmp_path / "forged.json"
    meta_path.write_text(json.dumps(metadata), encoding="utf-8")
    target = tmp_path / "target.db"
    Store(target).close()
    before = target.read_bytes()
    with pytest.raises(BackupError):
        verify_backup(forged, meta_path)
    with pytest.raises(BackupError):
        restore_backup(forged, meta_path, target, activate=True, force=True)
    assert target.read_bytes() == before
    assert not target.with_name(target.name + ".restore-staging").exists()
    assert verify_backup(valid.database_path, valid.metadata_path)["verified"] is True


def _rows(store):
    return {table: [tuple(row) for row in store.all(f"SELECT * FROM {table}")]
            for table in DURABLE_TABLES}


@pytest.mark.parametrize("fault", ["serialization", "second-insert"])
def test_failed_attempt_is_atomic_for_every_registered_product(store, pipeline, fault):
    sources = store.all("SELECT source_key FROM sources WHERE plane='PRODUCT' AND "
                        "registered_state='REGISTERED' AND placeholder=0 AND out_of_scope=0")
    assert len(sources) >= 8
    if fault == "second-insert":
        store.execute("CREATE TRIGGER reject_error BEFORE INSERT ON run_errors "
                      "BEGIN SELECT RAISE(ABORT, 'injected audit failure'); END")
    for row in sources:
        run_id = "audit-fault-" + row["source_key"]
        request = CollectorRunRequest(run_id=run_id, source_key=row["source_key"],
                                      collector_key="audit-regression", started_at="2026-10-03T00:00:00Z",
                                      ok=False, error="fixture transport failure",
                                      diagnostics={"problem": {object(): "invalid JSON key"}} if fault == "serialization" else {"problem": "fixture"})
        before = _rows(store)
        with pytest.raises(TypeError if fault == "serialization" else sqlite3.IntegrityError):
            pipeline.accept_run(request)
        assert _rows(store) == before
        assert not store.con.in_transaction
    if fault == "second-insert":
        store.execute("DROP TRIGGER reject_error")
    request.diagnostics = {"problem": "serializable"}
    result = pipeline.accept_run(request)
    assert result.status == "failed"
    assert store.one("SELECT run_id FROM run_errors WHERE run_id=?", (request.run_id,))
    assert not store.one("SELECT run_id FROM processed_run_receipts WHERE run_id=?", (request.run_id,))


def test_packaged_bootstrap_and_migrations_have_identical_material_structure():
    migrated = sqlite3.connect(":memory:")
    packaged = sqlite3.connect(":memory:")
    try:
        for version in (1, 2, 3):
            migrated.executescript(load_migration_sql(version))
        packaged.executescript(PACKAGED_SCHEMA.read_text(encoding="utf-8"))
        for table in DURABLE_TABLES:
            # cid is layout, not a material column contract.
            columns = lambda con: sorted(tuple(r)[1:] for r in con.execute(f"PRAGMA table_info({table})"))
            assert columns(migrated) == columns(packaged)
            indexes = lambda con: sorted((r[1], r[2], r[3], r[4]) for r in con.execute(f"PRAGMA index_list({table})"))
            assert indexes(migrated) == indexes(packaged)
    finally:
        migrated.close()
        packaged.close()


def test_packaged_store_bootstrap_has_full_v3_contract(tmp_path, monkeypatch):
    import board_clank.store as store_module
    monkeypatch.setattr(store_module, "MIGRATIONS_DIR", tmp_path / "no-repository-migrations")
    path = tmp_path / "wheel-state.db"
    Store(path).close()
    assert inspect_path(path).state is CompatibilityState.COMPATIBLE
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_events_code_revision'").fetchone()


def test_valid_additive_extra_state_remains_read_only_and_compatible(tmp_path):
    path = tmp_path / "additive.db"
    Store(path).close()
    with sqlite3.connect(path) as con:
        con.execute("ALTER TABLE sources ADD COLUMN future_note TEXT")
        con.execute("CREATE TABLE future_audit (note TEXT)")
    original = path.read_bytes()
    assert inspect_path(path).state is CompatibilityState.COMPATIBLE
    assert full_snapshot(path)["status"]["state"] == "COMPATIBLE"
    assert path.read_bytes() == original


def test_wrong_provenance_index_key_fails_closed(tmp_path):
    path = tmp_path / "wrong-index.db"
    Store(path).close()
    with sqlite3.connect(path) as con:
        con.execute("DROP INDEX idx_events_code_revision")
        con.execute("CREATE INDEX idx_events_code_revision ON events(source_key)")
    assert inspect_path(path).state is CompatibilityState.PARTIAL
