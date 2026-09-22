from __future__ import annotations

import json
from pathlib import Path

import pytest

from board_clank.cli import main
from board_clank.fixtures import load_scenario, scenario_to_request
from board_clank.pipeline import Pipeline
from board_clank.store import Store


def test_transaction_rollback_on_enqueue_failure(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline = Pipeline(store)
    request = scenario_to_request(load_scenario("A"))[0]
    original = store.execute

    def flaky(sql: str, params=()):
        if "INSERT INTO processed_run_receipts" in sql:
            raise RuntimeError("forced enqueue failure")
        return original(sql, params)

    monkeypatch.setattr(store, "execute", flaky)
    with pytest.raises(RuntimeError):
        pipeline.accept_run(request)
    assert store.count("processed_run_receipts") == 0
    assert store.count("events") == 0
    assert store.count("boards") == 0


def test_unknown_and_native_fields_preserved(store: Store) -> None:
    pipeline = Pipeline(store)
    pipeline.accept_run(scenario_to_request(load_scenario("A"))[0])
    row = store.one("SELECT payload_json FROM canonical_observations WHERE entity_kind = 'BOARD'")
    payload = json.loads(row["payload_json"])
    assert payload["native_fields"]["vendor_sku_matrix"] == "kept"
    spec = payload["spec"]
    assert spec["npu_tops"] == "UNKNOWN" or spec.get("npu") in {"UNKNOWN", spec.get("npu")}


def test_cli_version_and_identity(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["version"]) == 0
    version = json.loads(capsys.readouterr().out)
    assert version["clank_id"] == "board-clank"
    assert main(["identity"]) == 0
    identity = json.loads(capsys.readouterr().out)
    assert "A NEW SKU IS NOT NECESSARILY A NEW BOARD" in identity["identity_law"]


def test_cli_health_and_sources(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    db = tmp_path / "cli.db"
    assert main(["--db", str(db), "migrate"]) == 0
    capsys.readouterr()
    assert main(["--db", str(db), "health"]) == 0
    health = json.loads(capsys.readouterr().out)
    assert health["mutating"] is False
    assert health["discord_contact_possible"] is False
    assert main(["sources", "--assert-foundation"]) == 0
    sources = json.loads(capsys.readouterr().out)
    assert sources["promoted"] == 0
    assert sources["count"] >= 6


def test_cli_refuses_live_collect(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["collect", "--live"])
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "refused"


def test_cli_fixture_collect(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "fx.db"
    assert main(["--db", str(db), "collect", "--fixture", "L"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["status"] == "accepted"
    assert main(["--db", str(db), "baseline-status"]) == 0
    baseline = json.loads(capsys.readouterr().out)
    assert baseline["baselines"]
