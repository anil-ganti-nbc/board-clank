from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from board_clank.compatibility import CompatibilityState, StateCompatibilityError, inspect_path
from board_clank.health import health_payload
from board_clank.store import Store, expected_table_names


def test_fresh_empty_path(tmp_path: Path) -> None:
    report = inspect_path(tmp_path / "missing.db")
    assert report.state is CompatibilityState.FRESH


def test_bootstrap_compatible(tmp_path: Path) -> None:
    path = tmp_path / "ok.db"
    Store(path)
    report = inspect_path(path)
    assert report.state is CompatibilityState.COMPATIBLE
    assert report.observed_version == 1


def test_unknown_without_marker(tmp_path: Path) -> None:
    path = tmp_path / "unknown.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE boards (board_key TEXT)")
    con.commit()
    con.close()
    assert inspect_path(path).state is CompatibilityState.UNKNOWN
    with pytest.raises(StateCompatibilityError):
        Store(path, migrate=True)


def test_incompatible_newer_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "newer.db"
    Store(path)
    con = sqlite3.connect(path)
    con.execute("INSERT INTO schema_migrations(version, applied_at, name) VALUES (99, 'now', 'future')")
    con.commit()
    con.close()
    assert inspect_path(path).state is CompatibilityState.INCOMPATIBLE_NEWER
    with pytest.raises(StateCompatibilityError):
        Store(path, migrate=True)


def test_partial_schema_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "partial.db"
    Store(path)
    con = sqlite3.connect(path)
    con.execute("DROP TABLE software_support")
    con.commit()
    con.close()
    assert inspect_path(path).state is CompatibilityState.PARTIAL
    with pytest.raises(StateCompatibilityError):
        Store(path, migrate=False)


def test_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.db"
    path.write_text("not sqlite", encoding="utf-8")
    assert inspect_path(path).state is CompatibilityState.CORRUPT


def test_health_is_non_mutating(tmp_path: Path) -> None:
    path = tmp_path / "health.db"
    Store(path)
    before = path.read_bytes()
    payload = health_payload(path)
    assert payload["mutating"] is False
    assert payload["discord_contact_possible"] is False
    assert path.read_bytes() == before


def test_expected_tables_cover_contract() -> None:
    names = expected_table_names()
    for required in (
        "schema_migrations",
        "sources",
        "vendors",
        "board_families",
        "boards",
        "board_revisions",
        "board_variants",
        "socs",
        "canonical_observations",
        "observation_occurrences",
        "current_entity_observations",
        "collector_runs",
        "processed_run_receipts",
        "run_errors",
        "events",
        "notifications",
        "delivery_policy",
    ):
        assert required in names
