"""Unexpected schema restrictions and failed restore activation are fail-closed."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from board_clank.backup import BackupError, create_backup, restore_backup, sha256_file, verify_backup
from board_clank.compatibility import CompatibilityState, StateCompatibilityError, inspect_path
from board_clank.models import CollectorRunRequest
from board_clank.observer import full_snapshot
from board_clank.pipeline import Pipeline
from board_clank.sources import sync_sources_to_store
from board_clank.store import Store


def _alter_empty_table(con, table, transform):
    assert con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] == 0
    sql = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]
    con.execute(f'DROP TABLE "{table}"')
    con.execute(transform(sql))


def _restrict(path, kind):
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA foreign_keys=OFF")
        if kind == "unique":
            con.execute("CREATE UNIQUE INDEX unexpected_single_run ON collector_runs(source_key)")
        elif kind == "abort-trigger":
            con.execute("CREATE TRIGGER unexpected_abort BEFORE INSERT ON collector_runs "
                        "BEGIN SELECT RAISE(ABORT, 'unexpected policy'); END")
        elif kind == "mutation-trigger":
            con.execute("CREATE TRIGGER unexpected_enable AFTER INSERT ON collector_runs "
                        "BEGIN UPDATE sources SET enabled=1; END")
        elif kind == "foreign-key":
            con.execute("ALTER TABLE collector_runs ADD COLUMN guard TEXT REFERENCES sources(source_key)")
        elif kind == "required-column":
            _alter_empty_table(con, "collector_runs", lambda sql: sql[:-1] + ", guard TEXT NOT NULL)")
        elif kind == "null-default":
            _alter_empty_table(con, "collector_runs", lambda sql: sql[:-1] + ", guard TEXT NOT NULL DEFAULT NULL)")
        elif kind == "unsafe-default":
            _alter_empty_table(con, "collector_runs", lambda sql: sql[:-1] + ", guard TEXT DEFAULT (unavailable_guard()))")
        elif kind == "conflict-policy":
            _alter_empty_table(con, "collector_runs", lambda sql: sql.replace("run_id TEXT PRIMARY KEY", "run_id TEXT PRIMARY KEY ON CONFLICT REPLACE"))
        elif kind == "check":
            _alter_empty_table(con, "collector_runs", lambda sql: sql[:-1] + ", CHECK(source_key='forbidden'))")
        elif kind == "collation":
            _alter_empty_table(con, "collector_runs", lambda sql: sql.replace("source_key TEXT NOT NULL", "source_key TEXT NOT NULL COLLATE NOCASE"))
        elif kind == "generated":
            _alter_empty_table(con, "collector_runs", lambda sql: sql[:-1] + ", guard INTEGER GENERATED ALWAYS AS (length(source_key)) STORED)")
        elif kind == "strict":
            _alter_empty_table(con, "collector_runs", lambda sql: sql + " STRICT")
        elif kind == "deferred-key":
            _alter_empty_table(con, "boards", lambda sql: sql.replace("REFERENCES vendors(vendor_key)", "REFERENCES vendors(vendor_key) DEFERRABLE INITIALLY DEFERRED"))
        else:
            raise AssertionError(kind)
        con.commit()
    finally:
        con.close()


@pytest.mark.parametrize("kind", ["unique", "abort-trigger", "mutation-trigger", "foreign-key",
    "required-column", "null-default", "unsafe-default", "check", "collation", "generated", "strict", "deferred-key", "conflict-policy"])
def test_unexpected_write_affecting_schema_cannot_activate(tmp_path, kind):
    source = tmp_path / "source.db"
    Store(source).close()
    valid = create_backup(source, tmp_path / "valid")
    forged = tmp_path / "forged.db"
    reader = sqlite3.connect(f"file:{valid.database_path.as_posix()}?mode=ro", uri=True)
    writer = sqlite3.connect(forged)
    try:
        reader.backup(writer)
    finally:
        writer.close()
        reader.close()
    _restrict(forged, kind)
    metadata = dict(valid.metadata, sha256=sha256_file(forged))
    meta_path = tmp_path / "forged.json"
    meta_path.write_text(json.dumps(metadata), encoding="utf-8")
    original = forged.read_bytes()
    report = inspect_path(forged)
    assert report.observed_version == 3 and not report.missing_tables
    assert report.state is CompatibilityState.PARTIAL
    assert full_snapshot(forged)["health"]["overall"] == "degraded"
    with pytest.raises(StateCompatibilityError):
        Store(forged, migrate=True)
    with pytest.raises(BackupError):
        verify_backup(forged, meta_path)
    target = tmp_path / "target.db"
    Store(target).close()
    target_before = target.read_bytes()
    with pytest.raises(BackupError):
        restore_backup(forged, meta_path, target, activate=True, force=True)
    assert target.read_bytes() == target_before and forged.read_bytes() == original
    assert not target.with_name(target.name + ".restore-staging").exists()
    assert verify_backup(valid.database_path, valid.metadata_path)["verified"]


@pytest.mark.parametrize("addition", ["future_note TEXT", "future_count INTEGER NOT NULL DEFAULT 0",
                                    "future_note TEXT DEFAULT 'CHECK( is just data'"])
def test_benign_additions_and_ordinary_indexes_remain_writable(tmp_path, addition):
    path = tmp_path / "benign.db"
    Store(path).close()
    with sqlite3.connect(path) as con:
        con.execute("ALTER TABLE collector_runs ADD COLUMN " + addition)
        con.execute("CREATE INDEX future_run_search ON collector_runs(source_key)")
        con.execute("CREATE TABLE future_audit (note TEXT)")
    before = path.read_bytes()
    assert inspect_path(path).state is CompatibilityState.COMPATIBLE
    assert full_snapshot(path)["status"]["state"] == "COMPATIBLE"
    assert path.read_bytes() == before
    with Store(path, migrate=False) as store:
        sync_sources_to_store(store)
        result = Pipeline(store).accept_run(CollectorRunRequest(run_id="safe-extra", source_key="raspberry-pi-product",
            collector_key="schema-regression", started_at="2026-10-03T00:00:00Z", ok=False, error="fixture failure"))
        assert result.status == "failed"


def test_failed_forced_replace_preserves_target_and_verified_staging(tmp_path, monkeypatch):
    source = tmp_path / "source.db"
    Store(source).close()
    backup = create_backup(source, tmp_path / "backup")
    target = tmp_path / "target.db"
    Store(target).close()
    before = target.read_bytes()
    attempted = []
    def reject_replace(self, destination):
        assert self.parent == target.parent and self.name.startswith(".board-clank-restore-")
        assert Path(destination) == target
        attempted.append(self)
        raise OSError("injected replacement failure")
    monkeypatch.setattr(Path, "replace", reject_replace)
    with pytest.raises(OSError, match="injected replacement failure"):
        restore_backup(backup.database_path, backup.metadata_path, target, activate=True, force=True)
    assert target.exists() and target.read_bytes() == before
    assert len(attempted) == 1
    assert attempted[0].exists() and verify_backup(attempted[0], backup.metadata_path)["verified"]


def test_late_target_creation_without_force_is_not_overwritten(tmp_path, monkeypatch):
    source = tmp_path / "source.db"
    Store(source).close()
    backup = create_backup(source, tmp_path / "backup")
    target = tmp_path / "target.db"
    native_link = os.link
    late_content = b"another actor's explicitly named target"
    attempted = []
    def link_after_target_creation(staging, destination):
        assert Path(staging).parent == target.parent and Path(destination) == target
        attempted.append(Path(staging))
        target.write_bytes(late_content)
        return native_link(staging, destination)
    monkeypatch.setattr(os, "link", link_after_target_creation)
    with pytest.raises(FileExistsError):
        restore_backup(backup.database_path, backup.metadata_path, target, activate=True, force=False)
    assert target.read_bytes() == late_content
    assert len(attempted) == 1
    assert attempted[0].exists() and verify_backup(attempted[0], backup.metadata_path)["verified"]
