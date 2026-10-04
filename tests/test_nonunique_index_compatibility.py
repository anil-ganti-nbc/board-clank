"""Additive indexes must preserve canonical write compatibility."""
from __future__ import annotations

import sqlite3

import pytest

from board_clank.compatibility import (
    CompatibilityState,
    StateCompatibilityError,
    inspect_compatibility,
    inspect_path,
)
from board_clank.models import CollectorRunRequest
from board_clank.observer import full_snapshot
from board_clank.pipeline import Pipeline
from board_clank.sources import sync_sources_to_store
from board_clank.store import Store


@pytest.mark.parametrize("index_sql", [
    "CREATE INDEX unsupported_addition ON collector_runs(length(source_key))",
    "CREATE INDEX unsupported_addition ON collector_runs(source_key, lower(run_id))",
    "CREATE INDEX unsupported_addition ON collector_runs(source_key) WHERE source_key IS NOT NULL",
    "CREATE INDEX unsupported_addition ON collector_runs(source_key) WHERE 0",
    "CREATE INDEX unsupported_addition ON collector_runs(source_key COLLATE fixture_only)",
])
def test_unsupported_additive_index_refuses_direct_open(tmp_path, index_sql):
    path = tmp_path / "synthetic.db"
    Store(path).close()
    with sqlite3.connect(path) as con:
        con.create_collation("fixture_only", lambda left, right: (left > right) - (left < right))
        con.execute(index_sql)
        con.commit()
        report = inspect_compatibility(con)
        assert report.state is CompatibilityState.PARTIAL
        assert "unsupported additive index" in report.reason
    before = path.read_bytes()
    assert inspect_path(path).state is not CompatibilityState.COMPATIBLE
    assert full_snapshot(path)["health"]["overall"] == "degraded"
    with pytest.raises(StateCompatibilityError):
        Store(path, migrate=True)
    assert path.read_bytes() == before


@pytest.mark.parametrize("definition", [
    "source_key",
    "source_key COLLATE NOCASE, run_id DESC",
    "source_key COLLATE RTRIM",
    "future_note COLLATE BINARY",
])
def test_supported_ordinary_additive_indexes_remain_writable(tmp_path, definition):
    path = tmp_path / "synthetic.db"
    Store(path).close()
    with sqlite3.connect(path) as con:
        con.execute("ALTER TABLE collector_runs ADD COLUMN future_note TEXT")
        con.execute("CREATE INDEX ordinary_addition ON collector_runs(" + definition + ")")
    assert inspect_path(path).state is CompatibilityState.COMPATIBLE
    with Store(path, migrate=False) as store:
        sync_sources_to_store(store)
        result = Pipeline(store).accept_run(CollectorRunRequest(
            run_id="ordinary-index-fixture", source_key="raspberry-pi-product",
            collector_key="offline-index-regression", started_at="2026-10-04T00:00:00Z",
            ok=False, error="synthetic offline failure",
        ))
        assert result.status == "failed"
