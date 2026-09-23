"""Production Readiness 1: recoverability, provenance, manifest, observer.

Acceptance gates under test:
1. backup works; 2. restore works; 3. restore/replay creates no false
novelty; 4. provenance records code revision truthfully; 5. migrations
preserve historical truth; 6. manifest validates; 7. observer surface is
read-only and contract-shaped; 8. six-vendor regressions stay green.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from board_clank._version import CLANK_ID, EXPECTED_SCHEMA_VERSION, SOURCE_REVISION
from board_clank.backup import (
    BackupError,
    create_backup,
    durable_state_snapshot,
    restore_backup,
    verify_backup,
)
from board_clank.collectors.banana_pi import collect_corpus as bpi_collect
from board_clank.collectors.odroid import collect_corpus as od_collect
from board_clank.collectors.orange_pi import collect_corpus as opi_collect
from board_clank.collectors.pine64 import collect_corpus as p64_collect
from board_clank.collectors.radxa import collect_corpus as radxa_collect
from board_clank.collectors.raspberry_pi import collect_corpus as rpi_collect
from board_clank.compatibility import CompatibilityState, inspect_path
from board_clank.cli import main
from board_clank.manifest import build_manifest, load_manifest, validate_manifest
from board_clank.observer import (
    capability_states,
    full_snapshot,
    health,
    identity,
    last_run,
    status,
)
from board_clank.pipeline import Pipeline
from board_clank.store import Store

OBS = "2026-09-23T00:00:00+00:00"


def _run_pytool(args: list[str], env_extra: dict[str, str] | None = None) -> tuple[int, str]:
    env = {key: value for key, value in os.environ.items() if key in ("SYSTEMROOT", "COMSPEC", "PATH", "TEMP", "TMP", "SYSTEMDRIVE")}
    env["PYTHONPATH"] = "src"
    if env_extra:
        env.update(env_extra)
    # Capture via files, not pipes: pytest's replaced std handles are not
    # valid inheritable handles on Windows (WinError 6 in DuplicateHandle).
    # Own devnull handle too: subprocess.DEVNULL caches an fd that pytest's
    # capture can invalidate.
    out_path = Path(os.environ.get("TEMP", os.getcwd())) / "pr1-stdout.txt"
    err_path = Path(os.environ.get("TEMP", os.getcwd())) / "pr1-stderr.txt"
    with out_path.open("w", encoding="utf-8") as fo, err_path.open("w", encoding="utf-8") as fe:
        with open(os.devnull, "rb") as dn:
            proc = subprocess.run(
                [sys.executable, "-m", "board_clank.cli", *args],
                stdout=fo, stderr=fe, stdin=dn,
                env=env, timeout=600,
            )
    return proc.returncode, out_path.read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------- provenance (WS-B)


def test_events_carry_injected_code_revision(tmp_path: Path) -> None:
    db = tmp_path / "prov.db"
    code, out = _run_pytool(
        ["--db", str(db), "collect", "--source", "orange-pi-product", "--run-id", "prov-1"],
        env_extra={"BOARD_CLANK_SOURCE_REVISION": "build-abc-123"},
    )
    assert code == 0, out
    con = sqlite3.connect(db)
    revisions = {row[0] for row in con.execute("SELECT DISTINCT code_revision FROM events")}
    con.close()
    assert revisions == {"build-abc-123"}


def test_unknown_revision_stays_literal_unknown(tmp_path: Path, monkeypatch, capsys) -> None:
    """No BOARD_CLANK_SOURCE_REVISION in the environment: events carry the
    literal UNKNOWN, never a fabricated value."""
    import importlib

    monkeypatch.delenv("BOARD_CLANK_SOURCE_REVISION", raising=False)
    import board_clank._version as version_module
    import board_clank.pipeline as pipeline_module

    monkeypatch.setattr(version_module, "SOURCE_REVISION", "UNKNOWN")
    monkeypatch.setattr(pipeline_module, "SOURCE_REVISION", "UNKNOWN")
    db = tmp_path / "unknown.db"
    assert main(["--db", str(db), "collect", "--source", "orange-pi-product", "--run-id", "prov-unknown"]) == 0
    capsys.readouterr()
    con = sqlite3.connect(db)
    revisions = {row[0] for row in con.execute("SELECT DISTINCT code_revision FROM events")}
    con.close()
    assert revisions == {"UNKNOWN"}
    assert version_module.SOURCE_REVISION == "UNKNOWN"


def test_event_identity_is_not_code_revision_dependent(pipeline: Pipeline, store: Store) -> None:
    """Provenance, not novelty: replaying identical evidence through a
    different build must not fork events or create false novelty."""
    pipeline.accept_run(rpi_collect("baseline", run_id="prov-a", started_at=OBS))
    keys_a = [row["event_key"] for row in store.all("SELECT event_key FROM events ORDER BY event_id")]
    pipeline.accept_run(rpi_collect("baseline", run_id="prov-b", started_at="2026-09-24T00:00:00+00:00"))
    events_before = store.count("events")
    live_new = store.all(
        "SELECT event_id FROM events WHERE event_type = 'NEW_BOARD' AND baseline_silent = 0"
    )
    assert store.count("events") >= events_before  # sightings only
    assert live_new == []
    keys_after = [row["event_key"] for row in store.all("SELECT event_key FROM events ORDER BY event_id")]
    assert keys_a == keys_after[: len(keys_a)]


def test_migrations_preserve_historical_truth_with_literal_unknown(tmp_path: Path) -> None:
    """A schema-v2 database migrates to v3; pre-existing events keep the
    literal UNKNOWN revision (never backfilled with the current SHA)."""
    db = tmp_path / "legacy.db"
    Store(db)  # builds at current version
    con = sqlite3.connect(db)
    con.execute("DROP INDEX IF EXISTS idx_events_code_revision")
    con.execute("ALTER TABLE events DROP COLUMN code_revision")
    con.execute("DROP INDEX IF EXISTS idx_events_code_revision")
    con.execute("DELETE FROM schema_migrations WHERE version = 3")
    con.execute(
        "INSERT INTO events(event_key, event_type, entity_kind, entity_key, board_key, revision_key,"
        " variant_key, source_key, run_id, from_hash, to_hash, baseline_silent, payload_json, created_at)"
        " VALUES ('legacy-key', 'NEW_BOARD', 'BOARD', 'x:y', 'x:y', 'x:y:unknown:unknown',"
        " 'x:y:unknown:unknown:fp', 'x-product', 'legacy-run', 'UNKNOWN', 'UNKNOWN', 1, '{}', '2026-01-01T00:00:00+00:00')"
    )
    con.execute(
        "INSERT INTO processed_run_receipts(run_id, source_key, receipt_hash, accepted_at, observation_count, event_count)"
        " VALUES ('legacy-run', 'x-product', 'hash', '2026-01-01T00:00:00+00:00', 0, 1)"
    )
    con.commit()
    con.close()

    report = inspect_path(db)
    assert report.state is CompatibilityState.MIGRATION_REQUIRED
    assert report.observed_version == 2

    Store(db, migrate=True)
    assert inspect_path(db).state is CompatibilityState.COMPATIBLE
    con = sqlite3.connect(db)
    legacy_revision = con.execute(
        "SELECT code_revision FROM events WHERE event_key = 'legacy-key'"
    ).fetchone()[0]
    version_rows = [row[0] for row in con.execute("SELECT version FROM schema_migrations ORDER BY version")]
    con.close()
    assert legacy_revision == "UNKNOWN"
    assert version_rows == [1, 2, 3]


def test_v1_forward_migration_path_reaches_v3(tmp_path: Path) -> None:
    db = tmp_path / "v1.db"
    Store(db)
    con = sqlite3.connect(db)
    for table in ("diagnostic_sightings", "diagnostic_conditions"):
        con.execute(f"DROP TABLE {table}")
    con.execute("DROP INDEX IF EXISTS idx_events_code_revision")
    con.execute("ALTER TABLE events DROP COLUMN code_revision")
    con.execute("DROP INDEX IF EXISTS idx_events_code_revision")
    con.execute("DELETE FROM schema_migrations WHERE version >= 2")
    con.commit()
    con.close()
    assert inspect_path(db).state is CompatibilityState.MIGRATION_REQUIRED
    Store(db, migrate=True)
    assert inspect_path(db).observed_version == EXPECTED_SCHEMA_VERSION
    assert inspect_path(db).state is CompatibilityState.COMPATIBLE


# --------------------------------------------------------------------------- backup matrix (WS-A)


def _populated_six_vendor_db(tmp_path: Path) -> Path:
    from board_clank.sources import sync_sources_to_store

    db = tmp_path / "six-vendor.db"
    store = Store(db)
    sync_sources_to_store(store)
    pipeline = Pipeline(store)
    for index, (collect, vendor) in enumerate((
        (rpi_collect, "rpi"), (opi_collect, "opi"), (radxa_collect, "radxa"),
        (bpi_collect, "bpi"), (od_collect, "od"), (p64_collect, "p64"),
    )):
        pipeline.accept_run(collect("baseline", run_id=f"{vendor}-base", started_at=OBS))
        pipeline.accept_run(
            collect("baseline", run_id=f"{vendor}-replay", started_at=f"2026-09-23T0{index + 2}:00:00+00:00")
        )
    store.close()
    return db


def test_healthy_backup_metadata_complete(tmp_path: Path) -> None:
    db = _populated_six_vendor_db(tmp_path)
    result = create_backup(db, tmp_path / "backups", code_revision="drill-rev-1")
    meta = result.metadata
    assert meta["clank_id"] == CLANK_ID
    assert meta["schema_version"] == EXPECTED_SCHEMA_VERSION
    assert meta["code_revision"] == "drill-rev-1"
    assert meta["integrity"] == "ok"
    assert len(meta["sha256"]) == 64
    assert meta["row_counts"]["boards"] > 0
    assert meta["row_counts"]["events"] > 0
    verification = verify_backup(result.database_path, result.metadata_path)
    assert verification["verified"] is True


def test_backup_refuses_integrity_failure(tmp_path: Path) -> None:
    db = tmp_path / "corrupt-source.db"
    db.write_bytes(b"this is not a database")
    with pytest.raises(BackupError):
        create_backup(db, tmp_path / "out")


def test_exact_restore_state_equivalence(tmp_path: Path) -> None:
    db = _populated_six_vendor_db(tmp_path)
    result = create_backup(db, tmp_path / "backups")
    target = tmp_path / "restored" / "restored.db"
    report = restore_backup(result.database_path, result.metadata_path, target, activate=True)
    assert report["activated"] is True
    before = durable_state_snapshot(db)
    after = durable_state_snapshot(target)
    assert after.keys() == before.keys()
    for table in before:
        assert after[table] == before[table], table


def test_restore_then_replay_creates_no_false_novelty(tmp_path: Path) -> None:
    db = _populated_six_vendor_db(tmp_path)
    result = create_backup(db, tmp_path / "backups")
    target = tmp_path / "restored.db"
    restore_backup(result.database_path, result.metadata_path, target, activate=True)

    store = Store(target)
    pipeline = Pipeline(store)
    boards_before = store.count("boards")
    variants_before = store.count("board_variants")
    events_before = store.count("events")
    outbox_before = store.count("notifications")
    conditions_before = store.count("diagnostic_conditions")
    for vendor, collect in (
        ("rpi", rpi_collect), ("opi", opi_collect), ("radxa", radxa_collect),
        ("bpi", bpi_collect), ("od", od_collect), ("p64", p64_collect),
    ):
        result2 = pipeline.accept_run(
            collect("baseline", run_id=f"{vendor}-post-restore", started_at="2026-09-25T00:00:00+00:00")
        )
        assert result2.status == "accepted"
    assert store.count("boards") == boards_before
    assert store.count("board_variants") == variants_before
    assert store.count("events") == events_before
    assert store.count("notifications") == outbox_before
    assert store.count("diagnostic_conditions") == conditions_before
    assert store.all("SELECT event_id FROM events WHERE event_type = 'FIELD_CHANGED'") == []
    assert store.all(
        "SELECT event_id FROM events WHERE event_type = 'NEW_BOARD' AND baseline_silent = 0"
    ) == []
    assert store.all(
        "SELECT event_id FROM events WHERE event_type = 'NEW_VARIANT' AND baseline_silent = 0"
    ) == []


def test_restore_refuses_hash_mismatch(tmp_path: Path) -> None:
    db = _populated_six_vendor_db(tmp_path)
    result = create_backup(db, tmp_path / "backups")
    tampered = tmp_path / "tampered.board-clank-backup.db"
    tampered.write_bytes(result.database_path.read_bytes() + b"tampered")
    meta = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    meta_path = tmp_path / "tampered.meta.json"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(BackupError, match="SHA-256 mismatch"):
        restore_backup(tampered, meta_path, tmp_path / "target.db")


def test_restore_refuses_corrupt_database(tmp_path: Path) -> None:
    db = _populated_six_vendor_db(tmp_path)
    result = create_backup(db, tmp_path / "backups")
    meta = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    corrupt = tmp_path / "corrupt.board-clank-backup.db"
    corrupt.write_bytes(b"garbage not sqlite")
    meta["sha256"] = __import__("hashlib").sha256(corrupt.read_bytes()).hexdigest()
    meta_path = tmp_path / "corrupt.meta.json"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(BackupError):
        restore_backup(corrupt, meta_path, tmp_path / "target.db")


def test_restore_refuses_incompatible_schema(tmp_path: Path) -> None:
    db = _populated_six_vendor_db(tmp_path)
    result = create_backup(db, tmp_path / "backups")
    meta = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    meta["schema_version"] = 99
    meta_path = tmp_path / "future.meta.json"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(BackupError, match="schema"):
        restore_backup(result.database_path, meta_path, tmp_path / "target.db")


def test_restore_never_overwrites_existing_target_without_force(tmp_path: Path) -> None:
    db = _populated_six_vendor_db(tmp_path)
    result = create_backup(db, tmp_path / "backups")
    target = tmp_path / "occupied.db"
    target.write_bytes(b"existing operator state")
    with pytest.raises(BackupError, match="refusing to overwrite"):
        restore_backup(result.database_path, result.metadata_path, target, activate=True)
    assert target.read_bytes() == b"existing operator state"
    # Explicit operator instruction is required.
    report = restore_backup(result.database_path, result.metadata_path, target, activate=True, force=True)
    assert report["activated"] is True
    assert target.read_bytes() != b"existing operator state"


def test_backup_artifacts_are_immutable(tmp_path: Path) -> None:
    db = _populated_six_vendor_db(tmp_path)
    create_backup(db, tmp_path / "backups", name="drill")
    with pytest.raises(BackupError, match="immutable"):
        create_backup(db, tmp_path / "backups", name="drill")


def test_backup_refuses_unmigrated_state(tmp_path: Path) -> None:
    db = tmp_path / "v2.db"
    Store(db)
    con = sqlite3.connect(db)
    con.execute("DROP INDEX IF EXISTS idx_events_code_revision")
    con.execute("ALTER TABLE events DROP COLUMN code_revision")
    con.execute("DROP INDEX IF EXISTS idx_events_code_revision")
    con.execute("DELETE FROM schema_migrations WHERE version = 3")
    con.commit()
    con.close()
    with pytest.raises(BackupError, match="MIGRATION_REQUIRED"):
        create_backup(db, tmp_path / "out")


# --------------------------------------------------------------------------- manifest (WS-C)


def test_runtime_manifest_validates() -> None:
    report = validate_manifest(build_manifest())
    assert report["valid"] is True
    assert report["source_count"] == 6
    assert report["schema_version"] == EXPECTED_SCHEMA_VERSION


def test_declared_manifest_validates_and_matches_runtime_except_revision() -> None:
    declared = load_manifest()
    runtime = build_manifest()
    assert validate_manifest(declared)["valid"] is True
    assert declared["versions"]["code_revision"] == "UNKNOWN"  # declaration truth
    for field in declared:
        if field == "versions":
            for version_field in declared["versions"]:
                if version_field == "code_revision":
                    continue
                assert declared["versions"][version_field] == runtime["versions"][version_field]
        elif field != "declaration_note":
            assert declared[field] == runtime[field], field


def test_manifest_capability_vocabulary_is_canonical(tmp_path: Path) -> None:
    manifest = build_manifest()
    manifest["capability_states"]["delivery"]["state"] = "totally-fine"
    with pytest.raises(Exception, match="canonical vocabulary"):
        validate_manifest(manifest)


def test_manifest_refuses_non_none_scheduler_authority() -> None:
    manifest = build_manifest()
    manifest["scheduler_authority"] = "cron"
    with pytest.raises(Exception, match="scheduler_authority"):
        validate_manifest(manifest)


# --------------------------------------------------------------------------- observer (WS-D)


def test_observer_surface_is_read_only_and_complete(tmp_path: Path) -> None:
    db = _populated_six_vendor_db(tmp_path)
    before = db.read_bytes()
    snapshot = full_snapshot(db)
    assert db.read_bytes() == before  # zero mutation
    # Contract v0.2 required core
    for method in ("identity", "capabilities", "status", "health", "last_run", "capability_states"):
        assert method in snapshot, method
    assert snapshot["identity"]["clank_id"] == CLANK_ID
    assert snapshot["identity"]["profile"] == "observer"
    assert snapshot["identity"]["deployed_source_sha"] == "UNKNOWN"
    assert snapshot["last_run"]["clock"] == "native_run_row"
    assert snapshot["status"]["mutating"] is False
    assert snapshot["health"]["mutating"] is False
    # Capability vocabulary + evidence refs
    for entry in snapshot["capability_states"].values():
        assert entry["state"] in {
            "active", "supported_unconfigured", "supported_undeployed",
            "unsupported_by_policy", "unsupported", "unknown_or_unverified",
        }
        assert entry["evidence"]
    assert snapshot["capability_states"]["delivery"]["state"] == "unsupported_by_policy"
    assert snapshot["capability_states"]["scheduler"]["state"] == "unsupported_by_policy"
    assert len(snapshot["source_summary"]) == 16  # six real + placeholders registered by fixtures


def test_observer_never_upgrades_unknown(tmp_path: Path) -> None:
    missing = tmp_path / "missing.db"
    snapshot = status(missing)
    assert snapshot["state"] == "UNKNOWN"
    assert health(missing)["overall"] == "UNKNOWN"
    assert last_run(missing) is None
    assert identity(missing)["deployed_source_sha"] == "UNKNOWN"


# --------------------------------------------------------------------------- CLI + drill


def test_cli_backup_restore_manifest_observe(tmp_path: Path) -> None:
    db = _populated_six_vendor_db(tmp_path)
    out_dir = tmp_path / "cli-backups"
    code, out = _run_pytool(["--db", str(db), "backup", "--out", str(out_dir)])
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "backed_up"
    backup_file = payload["database_path"]
    metadata_file = payload["metadata_path"]

    target = tmp_path / "cli-restored.db"
    code, out = _run_pytool(["restore", "--backup-file", backup_file, "--metadata", metadata_file, "--target", str(target), "--activate"])
    assert code == 0, out
    payload = json.loads(out)
    assert payload["status"] == "restored_activated"

    code, out = _run_pytool(["manifest"])
    assert code == 0, out
    assert json.loads(out)["valid"] is True

    code, out = _run_pytool(["manifest-declared"])
    assert code == 0, out
    assert json.loads(out)["valid"] is True

    code, out = _run_pytool(["--db", str(target), "observe"])
    assert code == 0, out
    snapshot = json.loads(out)
    assert snapshot["status"]["state"] == "COMPATIBLE"
    assert snapshot["last_run"] is not None

    # Existing-target refusal through the CLI
    code, out = _run_pytool(["restore", "--backup-file", backup_file, "--metadata", metadata_file, "--target", str(target), "--activate"])
    assert code == 3
    assert json.loads(out)["status"] == "refused"


def test_disaster_recovery_drill_machine_readable_report(tmp_path: Path) -> None:
    """End-to-end isolated drill: six-vendor state -> backup -> destroy
    working copy -> restore fresh -> integrity -> equivalence -> replay ->
    health/observer. Never touches real operator state."""
    report: dict = {"drill": "production-readiness-1", "steps": {}}

    # 1. populated six-vendor state
    db = _populated_six_vendor_db(tmp_path / "work")
    check_store = Store(db)
    board_count = check_store.count("boards")
    check_store.close()
    report["steps"]["populated"] = {"boards": board_count}

    # 2-3. backup + SHA-256
    result = create_backup(db, tmp_path / "backups", name="drill", code_revision="drill-rev")
    report["steps"]["backup"] = {"sha256": result.sha256, "metadata": result.metadata_path.name}

    # 4. destroy working copy (isolated location); equivalence baseline is
    # snapshotted from the live database BEFORE destruction
    before = durable_state_snapshot(db)
    db.unlink()
    assert not db.exists()
    report["steps"]["working_copy_destroyed"] = True

    # 5-7. restore fresh + integrity + equivalence
    restored = tmp_path / "fresh" / "restored.db"
    restore_report = restore_backup(result.database_path, result.metadata_path, restored, activate=True)
    assert restore_report["durable_state"] == before
    report["steps"]["restore"] = {"activated": True, "integrity": restore_report["integrity"]}

    # 8. replay same evidence against restored state
    store = Store(restored)
    pipeline = Pipeline(store)
    before = (store.count("boards"), store.count("events"), store.count("notifications"))
    for vendor, collect in (
        ("rpi", rpi_collect), ("opi", opi_collect), ("radxa", radxa_collect),
        ("bpi", bpi_collect), ("od", od_collect), ("p64", p64_collect),
    ):
        pipeline.accept_run(collect("baseline", run_id=f"drill-{vendor}", started_at="2026-09-26T00:00:00+00:00"))
    after = (store.count("boards"), store.count("events"), store.count("notifications"))
    assert before == after
    assert store.all("SELECT event_id FROM events WHERE event_type = 'FIELD_CHANGED'") == []
    report["steps"]["replay"] = {"boards": after[0], "events": after[1], "notifications": after[2], "false_novelty": False}

    # 10. health + observer against restored state
    code, out = _run_pytool(["--db", str(restored), "observe"])
    assert code == 0, out
    snapshot = json.loads(out)
    assert snapshot["status"]["state"] == "COMPATIBLE"
    assert snapshot["identity"]["deployed_source_sha"] == "UNKNOWN"
    report["steps"]["observer"] = {"state": snapshot["status"]["state"], "deployed_sha": "UNKNOWN"}

    report["pass"] = True
    (tmp_path / "recovery-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    assert report["pass"] is True


# --------------------------------------------------------------------------- six-vendor regression


def test_six_vendor_regression_idempotency_and_isolation(pipeline: Pipeline, store: Store) -> None:
    vendors = (
        ("rpi", rpi_collect), ("opi", opi_collect), ("radxa", radxa_collect),
        ("bpi", bpi_collect), ("od", od_collect), ("p64", p64_collect),
    )
    first_events = 0
    for index, (vendor, collect) in enumerate(vendors):
        r1 = pipeline.accept_run(collect("baseline", run_id=f"{vendor}-b", started_at=OBS))
        assert r1.baseline is True
        first_events += len(r1.events)
        r2 = pipeline.accept_run(
            collect("baseline", run_id=f"{vendor}-r", started_at=f"2026-09-24T0{index}:00:00+00:00")
        )
        assert len(r2.events) == 0
    assert first_events > 0
    assert store.all("SELECT event_id FROM events WHERE event_type = 'FIELD_CHANGED'") == []
    assert store.all("SELECT event_id FROM events WHERE event_type = 'NEW_BOARD' AND baseline_silent = 0") == []
    overlap = store.all(
        "SELECT a.board_key FROM boards a JOIN boards b ON a.board_slug = b.board_slug WHERE a.vendor_key != b.vendor_key"
    )
    assert overlap == []
    assert store.count("vendors") == 6
