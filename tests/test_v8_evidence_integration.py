"""Eight qualified PRODUCT vendors retain authority alongside supporting references."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from board_clank.backup import (
    BackupError, create_backup, durable_state_snapshot, restore_backup, sha256_file, verify_backup,
)
from board_clank.cli import main
from board_clank.collectors import get_adapter
from board_clank.collectors.radxa_documentation import (
    KIND, SOURCE_KEY, accept_documentation, source_definition,
)
from board_clank.manifest import ManifestError, build_manifest, validate_manifest
from board_clank.observer import full_snapshot
from board_clank.pipeline import Pipeline
from board_clank.sources import (
    assert_foundation_0_roster, load_sources, product_sources, supporting_sources,
)
from board_clank.store import Store
from board_clank.taxonomy import PHASE1_VENDORS, PHASE2_ADMITTED, SourcePlane

OBS = "2026-10-03T10:00:00Z"
HTML = Path("fixtures/radxa_documentation/rock5b-hardware.html").read_text(encoding="utf-8")
VENDORS = (*PHASE1_VENDORS, *PHASE2_ADMITTED)


def snapshot(store: Store) -> dict:
    tables = [r[0] for r in store.all("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return {table: [tuple(row) for row in store.all(f"SELECT * FROM {table} ORDER BY rowid")]
            for table in tables}


def product_snapshot(store: Store) -> dict:
    result = snapshot(store)
    for table in ("canonical_observations", "current_entity_observations", "observation_occurrences", "events"):
        result[table] = [tuple(row) for row in store.all(f"SELECT * FROM {table} WHERE entity_kind<>? ORDER BY rowid", (KIND,))]
    for table in ("collector_runs", "processed_run_receipts", "run_errors", "source_baselines", "diagnostic_conditions", "diagnostic_sightings"):
        result[table] = [tuple(row) for row in store.all(f"SELECT * FROM {table} WHERE source_key<>? ORDER BY rowid", (SOURCE_KEY,))]
    return result


def seed_eight(store: Store):
    requests = [get_adapter(vendor + "-product").collect(vendor + "-seed", OBS) for vendor in VENDORS]
    for request in requests:
        result = Pipeline(store).accept_run(request)
        assert result.status == "accepted" and result.baseline
    assert {r[0] for r in store.all("SELECT DISTINCT vendor_key FROM boards")} == set(VENDORS)
    assert not store.one("SELECT event_key FROM events WHERE baseline_silent<>1")
    assert not store.one("SELECT event_key FROM notifications WHERE disposition<>'SUPPRESSED' OR delivered_at IS NOT NULL")
    return requests


def test_supporting_roster_manifest_contract_and_factory_are_separate(tmp_path, capsys):
    assert len(product_sources()) == 8
    assert supporting_sources() == [source_definition()]
    assert len(load_sources()) == 17
    assert_foundation_0_roster()
    manifest = build_manifest()
    assert validate_manifest(manifest)["source_count"] == 8
    assert validate_manifest(manifest)["supporting_source_count"] == 1
    assert SOURCE_KEY not in manifest["sources"]
    manifest["sources"].append(SOURCE_KEY)
    with pytest.raises(ManifestError):
        validate_manifest(manifest)
    manifest = build_manifest()
    manifest["supporting_sources"][0]["enabled"] = True
    with pytest.raises(ManifestError, match="supporting"):
        validate_manifest(manifest)
    with pytest.raises(KeyError):
        get_adapter(SOURCE_KEY, experimental_live=True)
    db = tmp_path / "must-not-exist.db"
    assert main(["--db", str(db), "collect", "--source", SOURCE_KEY]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "refused"
    assert not db.exists()
    roster = yaml.safe_load(Path("config/sources.yaml").read_text(encoding="utf-8"))
    roster["sources"] = [row for row in roster["sources"] if row["source_key"] != "radxa-product"]
    custom = tmp_path / "missing-product.yaml"
    custom.write_text(yaml.safe_dump(roster), encoding="utf-8")
    with pytest.raises(Exception, match="vendors missing"):
        assert_foundation_0_roster(str(custom))


@pytest.mark.parametrize("forged", ["request", "draft", "both", "registry-authority"])
def test_supporting_authority_firewall_refuses_before_any_write(store, forged):
    seed_eight(store)
    request = get_adapter("radxa-product").collect("forged-supporting", OBS)
    if forged in {"request", "both", "registry-authority"}:
        request.source_key = SOURCE_KEY
    if forged in {"draft", "both"}:
        request.observations[0].source_key = SOURCE_KEY
        request.observations[0].plane = SourcePlane.PRODUCT  # forged plane cannot grant authority
    if forged == "registry-authority":
        store.execute("UPDATE sources SET authority='FIRST_PARTY_CANONICAL' WHERE source_key=?", (SOURCE_KEY,))
        store.commit()
    before = snapshot(store)
    with pytest.raises(ValueError, match="supporting evidence"):
        Pipeline(store).accept_run(request)
    assert snapshot(store) == before  # includes receipts, diagnostics and all occurrences


def test_eight_product_vendors_reference_replay_observer_backup_restore(store, db_path, tmp_path):
    requests = seed_eight(store)
    product = product_snapshot(store)
    first = accept_documentation(store, HTML, run_id="reference-1", observed_at=OBS)
    assert not first["unresolved"] and len(first["mappings"]) == 7
    assert {r["board_key"] for r in first["mappings"]} == {"radxa:rock-5b"}
    assert product_snapshot(store) == product
    before = snapshot(store)
    assert accept_documentation(store, HTML, run_id="reference-1", observed_at=OBS)["replayed"]
    assert snapshot(store) == before
    for run in ("reference-2", "reference-3"):
        assert accept_documentation(store, HTML, run_id=run, observed_at=OBS)["events"] == []
        assert product_snapshot(store) == product
    assert not store.one("SELECT event_key FROM events WHERE source_key=? AND (event_type<>'NEW_REFERENCE' OR baseline_silent<>1)", (SOURCE_KEY,))
    assert not store.one("SELECT n.event_key FROM notifications n JOIN events e ON e.event_key=n.event_key WHERE e.source_key=?", (SOURCE_KEY,))
    assert store.one("SELECT COUNT(*) FROM observation_occurrences WHERE entity_kind=?", (KIND,))[0] == 21
    for request in requests:
        before = snapshot(store)
        assert Pipeline(store).accept_run(request).replayed
        assert snapshot(store) == before
        request.run_id += "-new"
        result = Pipeline(store).accept_run(request)
        assert result.events == [] and result.notifications == 0
    byte_hash = sha256_file(db_path)
    observer = full_snapshot(db_path)
    assert observer["status"]["schema_version"] == 3 and observer["status"]["mutating"] is False
    assert len(observer["source_summary"]) == 17
    assert sha256_file(db_path) == byte_hash
    backup = create_backup(db_path, tmp_path / "backup", name="eight-product-reference")
    assert backup.metadata["integrity"] == "ok"
    restored_db = tmp_path / "restored.db"
    restored = restore_backup(backup.database_path, backup.metadata_path, restored_db, activate=True)
    assert restored["integrity"] == "ok"
    with Store(restored_db, migrate=False) as restored_store:
        assert snapshot(restored_store) == snapshot(store)
        before = snapshot(restored_store)
        assert accept_documentation(restored_store, HTML, run_id="reference-1", observed_at=OBS)["replayed"]
        assert snapshot(restored_store) == before
        assert restored_store.one("PRAGMA integrity_check")[0] == "ok"


def test_reference_diagnostics_cannot_close_any_product_condition(store):
    seed_eight(store)
    pine = get_adapter("pine64-product", corpus="insufficient").collect("pine-unresolved", OBS)
    Pipeline(store).accept_run(pine)
    before = [tuple(row) for row in store.all("SELECT * FROM diagnostic_conditions WHERE source_key='pine64-product'")]
    assert before
    for run, html in (("reference-bad", HTML.replace("id=hardware-design", "id=wrong")), ("reference-good", HTML)):
        accept_documentation(store, html, run_id=run, observed_at=OBS)
        assert [tuple(row) for row in store.all("SELECT * FROM diagnostic_conditions WHERE source_key='pine64-product'")] == before


@pytest.mark.parametrize("forged", ["documentation-plane", "mixed-source", "cross-vendor", "durable-plane", "durable-authority", "missing-row", "registered-state", "unknown-source"])
def test_generic_source_and_plane_consistency_fail_before_all_writes(store, forged):
    request = get_adapter("radxa-product").collect("invalid-source-binding", OBS)
    if forged == "documentation-plane":
        request.observations[0].plane = SourcePlane.DOCUMENTATION
    elif forged == "mixed-source":
        request.observations[0].source_key = "orange-pi-product"
    elif forged == "cross-vendor":
        request.observations[0].vendor_key = "raspberry-pi"
    elif forged == "durable-plane":
        store.execute("UPDATE sources SET plane='DOCUMENTATION' WHERE source_key='radxa-product'")
        request.observations[0].plane = SourcePlane.DOCUMENTATION
    elif forged == "durable-authority":
        store.execute("UPDATE sources SET authority='UNVERIFIED' WHERE source_key='radxa-product'")
    elif forged == "missing-row":
        store.execute("DELETE FROM sources WHERE source_key='radxa-product'")
    elif forged == "registered-state":
        store.execute("UPDATE sources SET registered_state='UNREGISTERED' WHERE source_key='radxa-product'")
    else:
        request.source_key = "unknown-product"
        for draft in request.observations:
            draft.source_key = request.source_key
    store.commit()
    before = snapshot(store)
    with pytest.raises(ValueError):
        Pipeline(store).accept_run(request)
    assert snapshot(store) == before
    request.ok = False  # failed attempts and receipt paths cannot bypass source validation
    with pytest.raises(ValueError):
        Pipeline(store).accept_run(request)
    assert snapshot(store) == before


def test_unregistered_legacy_fixtures_require_explicit_narrow_entry(store):
    from board_clank.fixtures import load_scenario, scenario_to_request
    pipeline = Pipeline(store)
    for scenario in ("E", "F", "M"):
        request = scenario_to_request(load_scenario(scenario))[-1]
        before = snapshot(store)
        with pytest.raises(ValueError, match="unregistered source"):
            pipeline.accept_run(request)
        assert snapshot(store) == before
        assert pipeline.accept_fixture_run(request).status == "accepted"
    request = scenario_to_request(load_scenario("F"))[0]
    request.run_id = "fixture-forgery"
    request.fixture_scenario = "E"
    before = snapshot(store)
    with pytest.raises(ValueError, match="fixture scenario"):
        pipeline.accept_fixture_run(request)
    assert snapshot(store) == before
    request.fixture_scenario = "F"
    request.source_key = "arbitrary-documentation"
    for draft in request.observations:
        draft.source_key = request.source_key
    with pytest.raises(ValueError, match="unregistered source"):
        pipeline.accept_fixture_run(request)
    assert snapshot(store) == before


def test_backup_metadata_occurrences_and_legacy_v1_coverage(store, db_path, tmp_path):
    seed_eight(store)
    accept_documentation(store, HTML, run_id="backup-reference", observed_at=OBS)
    backup = create_backup(db_path, tmp_path / "backup", name="coverage")
    count = store.count("observation_occurrences")
    assert count > 7 and backup.metadata["row_counts"]["observation_occurrences"] == count
    assert "observation_occurrences" in backup.metadata["durable_tables"]
    verified = verify_backup(backup.database_path, backup.metadata_path)
    assert verified["metadata_coverage"] == "COMPLETE" and verified["unverified_tables"] == []
    assert "observation_occurrences" in durable_state_snapshot(db_path)
    restored = restore_backup(backup.database_path, backup.metadata_path, tmp_path / "current.db", activate=True)
    assert restored["metadata_coverage"] == "COMPLETE"
    assert restored["row_counts"]["observation_occurrences"] == count
    assert restored["durable_state"] == durable_state_snapshot(db_path)
    legacy = json.loads(backup.metadata_path.read_text(encoding="utf-8"))
    legacy["row_counts"].pop("observation_occurrences")
    legacy["durable_tables"].remove("observation_occurrences")
    legacy_path = tmp_path / "legacy-v1.meta.json"
    legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
    verified = verify_backup(backup.database_path, legacy_path)
    assert verified["metadata_coverage"] == "LEGACY_PARTIAL"
    assert verified["unverified_tables"] == ["observation_occurrences"]
    legacy_restore = restore_backup(backup.database_path, legacy_path, tmp_path / "legacy-restored.db", activate=True)
    assert legacy_restore["metadata_coverage"] == "LEGACY_PARTIAL"
    assert legacy_restore["unverified_tables"] == ["observation_occurrences"]
    assert durable_state_snapshot(tmp_path / "legacy-restored.db") == durable_state_snapshot(db_path)
    legacy["row_counts"].pop("boards")  # only the genuine old v1 coverage set is accepted
    legacy["durable_tables"].remove("boards")
    legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
    with pytest.raises(BackupError, match="coverage"):
        verify_backup(backup.database_path, legacy_path)
    wrong = dict(backup.metadata)
    wrong["row_counts"] = dict(wrong["row_counts"], observation_occurrences=count + 1)
    wrong_path = tmp_path / "wrong-occurrences.meta.json"
    wrong_path.write_text(json.dumps(wrong), encoding="utf-8")
    with pytest.raises(BackupError, match="row counts"):
        verify_backup(backup.database_path, wrong_path)
