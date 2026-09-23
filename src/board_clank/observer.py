"""Board Clank read-only observer surface.

Observer Adapter Surface Contract v0.2 required core, exposed as pure
functions over a read-only SQLite connection:

    identity, capabilities, status, health, last_run, capability_states

plus the optional extensions Board Clank can honour honestly
(schema_revision, source_summary, diagnostic_summary, execution_evidence).

Laws honoured here:
- read-only: the database is opened with SQLite URI mode=ro;
- non-mutating: no INSERT/UPDATE/DDL anywhere in this module;
- bounded/deterministic: fixed-shape payloads, UNKNOWN never upgraded;
- deployment truth stays separate: runtime_state is reported from the
  database's own records, and deployed HEAD is only ever what an operator
  recorded externally — never inferred from CI or from source HEAD.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from board_clank._version import (
    CLANK_ID,
    EXPECTED_SCHEMA_VERSION,
    PACKAGE_VERSION,
    RELEASE_CHANNEL,
    SOURCE_REVISION,
)
from board_clank.compatibility import connect_readonly, inspect_compatibility
from board_clank.manifest import ADAPTER_CONTRACT_VERSION

OBSERVER_SURFACE_VERSION = ADAPTER_CONTRACT_VERSION


def _tables(con: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }


def identity(db_path: str | Path) -> dict[str, Any]:
    return {
        "clank_id": CLANK_ID,
        "instance": "default",
        "lane": "experimental-local",
        "deployed_source_sha": "UNKNOWN",
        "deployed_note": (
            "deployed HEAD is a separate deployment-observer fact; "
            "no deployment evidence exists"
        ),
        "code_revision": SOURCE_REVISION,
        "adapter": "board-clank-observer",
        "profile": "observer",
        "profile_version": OBSERVER_SURFACE_VERSION,
        "host_identity": "local workstation (operator-run)",
        "environment": "experimental",
        "maturity": "EXPERIMENTAL",
    }


def capabilities(db_path: str | Path) -> dict[str, Any]:
    return {
        "declared": [
            "discovery", "identity", "spec_extraction", "variant_handling",
            "replay", "backup", "restore", "observer_surface",
        ],
        "observer_surface_version": OBSERVER_SURFACE_VERSION,
        "stateless_collection": False,
        "persistent_state": "sqlite (single operator-provided database file)",
    }


def status(db_path: str | Path) -> dict[str, Any]:
    path = Path(db_path)
    if not path.exists():
        return {
            "state": "UNKNOWN",
            "reason": "database does not exist",
            "mutating": False,
            "discord_contact_possible": False,
        }
    con = connect_readonly(path)
    try:
        report = inspect_compatibility(con)
        counts: dict[str, Any] = {}
        tables = _tables(con)
        for table, query in (
            ("vendors", "vendors"),
            ("boards", "boards"),
            ("board_variants", "board_variants"),
            ("events", "events"),
            ("notifications", "notifications"),
            ("collector_runs", "collector_runs"),
            ("diagnostic_conditions", "diagnostic_conditions"),
        ):
            if query in tables:
                counts[table] = int(con.execute(f"SELECT COUNT(*) FROM {query}").fetchone()[0])
            else:
                counts[table] = "UNKNOWN"
        return {
            "state": report.state.value,
            "schema_version": report.observed_version,
            "counts": counts,
            "mutating": False,
            "discord_contact_possible": False,
        }
    finally:
        con.close()


def health(db_path: str | Path) -> dict[str, Any]:
    """Independent health planes; conservative aggregation (UNKNOWN never
    upgrades health). Scheduler/delivery planes are provably NONE."""
    path = Path(db_path)
    if not path.exists():
        return {
            "overall": "UNKNOWN",
            "planes": {},
            "mutating": False,
        }
    con = connect_readonly(path)
    try:
        tables = _tables(con)
        planes: dict[str, dict[str, str]] = {}

        persistence = "UNKNOWN"
        if "schema_migrations" in tables:
            state = inspect_compatibility(con)
            persistence = {
                "COMPATIBLE": "ok",
                "FRESH": "ok",
            }.get(state.state.value, state.state.value)
        planes["persistence"] = {"state": persistence, "evidence": "schema compatibility inspection"}

        if "collector_runs" in tables:
            total = int(con.execute("SELECT COUNT(*) FROM collector_runs").fetchone()[0])
            failed = int(
                con.execute("SELECT COUNT(*) FROM collector_runs WHERE status = 'failed'").fetchone()[0]
            )
            planes["execution"] = {
                "state": "ok" if total == 0 or failed < total else "degraded",
                "evidence": f"{total} recorded runs, {failed} failed",
            }
            planes["source"] = {
                "state": "ok",
                "evidence": "collector_runs expose per-source attempts and run_errors",
            }
        else:
            planes["execution"] = {"state": "UNKNOWN", "evidence": "no collector_runs table"}
            planes["source"] = {"state": "UNKNOWN", "evidence": "no collector_runs table"}

        if "diagnostic_conditions" in tables:
            open_conditions = int(
                con.execute("SELECT COUNT(*) FROM diagnostic_conditions WHERE status = 'OPEN'").fetchone()[0]
            )
            planes["semantic"] = {
                "state": "ok",
                "evidence": f"{open_conditions} open diagnostic conditions (durable, source-scoped)",
            }
        else:
            planes["semantic"] = {"state": "UNKNOWN", "evidence": "no diagnostic_conditions table"}

        planes["collection"] = {
            "state": "supported_unconfigured",
            "evidence": "adapters exist; all sources enabled=false by policy",
        }
        planes["coverage"] = {
            "state": "UNKNOWN",
            "evidence": "coverage canaries not implemented",
        }
        planes["delivery"] = {
            "state": "unsupported_by_policy",
            "evidence": "outbox-only; no send path exists; nothing delivered",
        }
        planes["scheduler"] = {
            "state": "unsupported_by_policy",
            "evidence": "no scheduler authority declared or implemented",
        }
        degraded = any(
            p["state"] in {"degraded", "failed", "CORRUPT", "PARTIAL"} for p in planes.values()
        )
        unknown = any(p["state"] == "UNKNOWN" for p in planes.values())
        overall = "degraded" if degraded else ("ok_with_unknowns" if unknown else "ok")
        return {
            "overall": overall,
            "planes": planes,
            "mutating": False,
            "discord_contact_possible": False,
        }
    finally:
        con.close()


def last_run(db_path: str | Path) -> dict[str, Any] | None:
    path = Path(db_path)
    if not path.exists():
        return None
    con = connect_readonly(path)
    try:
        if "collector_runs" not in _tables(con):
            return None
        row = con.execute(
            """
            SELECT run_id, source_key, collector_key, started_at, finished_at, status, fixture_scenario, error
            FROM collector_runs ORDER BY started_at DESC, rowid DESC LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        return {
            "clock": "native_run_row",
            "derived_from": "collector_runs",
            "run_id": row["run_id"],
            "source_key": row["source_key"],
            "collector_key": row["collector_key"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "status": row["status"],
            "fixture_scenario": row["fixture_scenario"],
            "error": row["error"],
        }
    finally:
        con.close()


def capability_states(db_path: str | Path) -> dict[str, dict[str, str]]:
    """Canonical CapabilityState vocabulary with evidence references."""
    return {
        "collection": {
            "state": "supported_unconfigured",
            "evidence": "six source adapters registered; every source enabled=false",
        },
        "health": {"state": "active", "evidence": "read-only health plane over persistent state"},
        "events": {
            "state": "active",
            "evidence": "event plane with baseline silence, diagnostic conditions, code-revision provenance",
        },
        "delivery": {
            "state": "unsupported_by_policy",
            "evidence": "outbox rows only; no send path; promotion_freeze=true",
        },
        "scheduler": {
            "state": "unsupported_by_policy",
            "evidence": "no scheduler authority declared or implemented",
        },
        "continuity": {
            "state": "active",
            "evidence": "source_baselines + processed_run_receipts + forward migrations",
        },
        "survivability": {
            "state": "supported_undeployed",
            "evidence": "operator-triggered verified backup/restore; no deployed runtime yet",
        },
        "deployment": {
            "state": "unknown_or_unverified",
            "evidence": "no deployment evidence exists; CI is not deployment",
        },
    }


def schema_revision(db_path: str | Path) -> dict[str, Any]:
    path = Path(db_path)
    if not path.exists():
        return {"schema_version": "UNKNOWN", "migrations": []}
    con = connect_readonly(path)
    try:
        tables = _tables(con)
        if "schema_migrations" not in tables:
            return {"schema_version": "UNKNOWN", "migrations": []}
        rows = con.execute("SELECT version, applied_at, name FROM schema_migrations ORDER BY version").fetchall()
        return {
            "schema_version": EXPECTED_SCHEMA_VERSION,
            "applied": [dict(zip(("version", "applied_at", "name"), row)) for row in rows],
        }
    finally:
        con.close()


def source_summary(db_path: str | Path) -> list[dict[str, Any]]:
    path = Path(db_path)
    if not path.exists():
        return []
    con = connect_readonly(path)
    try:
        if "sources" not in _tables(con):
            return []
        rows = con.execute(
            """
            SELECT source_key, vendor, plane, authority, enabled, promotion_state, registered_state
            FROM sources ORDER BY source_key
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        con.close()


def diagnostic_summary(db_path: str | Path) -> dict[str, Any]:
    path = Path(db_path)
    if not path.exists():
        return {"conditions": [], "sightings_total": "UNKNOWN"}
    con = connect_readonly(path)
    try:
        tables = _tables(con)
        if "diagnostic_conditions" not in tables:
            return {"conditions": [], "sightings_total": "UNKNOWN"}
        conditions = [
            dict(row)
            for row in con.execute(
                """
                SELECT source_key, diagnostic_type, status, reason, COUNT(*) AS n
                FROM diagnostic_conditions GROUP BY source_key, diagnostic_type, status, reason
                ORDER BY source_key, diagnostic_type, status
                """
            ).fetchall()
        ]
        sightings = int(con.execute("SELECT COUNT(*) FROM diagnostic_sightings").fetchone()[0])
        return {"conditions": conditions, "sightings_total": sightings}
    finally:
        con.close()


def execution_evidence(db_path: str | Path) -> dict[str, Any]:
    path = Path(db_path)
    if not path.exists():
        return {"runs": 0, "receipts": 0, "errors": 0}
    con = connect_readonly(path)
    try:
        tables = _tables(con)

        def count(table: str) -> Any:
            return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) if table in tables else "UNKNOWN"

        return {
            "runs": count("collector_runs"),
            "receipts": count("processed_run_receipts"),
            "errors": count("run_errors"),
            "occurrences": count("observation_occurrences"),
        }
    finally:
        con.close()


def full_snapshot(db_path: str | Path) -> dict[str, Any]:
    """Bounded, deterministic whole-surface snapshot (CLI `observe`)."""
    return {
        "identity": identity(db_path),
        "capabilities": capabilities(db_path),
        "status": status(db_path),
        "health": health(db_path),
        "last_run": last_run(db_path),
        "capability_states": capability_states(db_path),
        "schema_revision": schema_revision(db_path),
        "source_summary": source_summary(db_path),
        "diagnostic_summary": diagnostic_summary(db_path),
        "execution_evidence": execution_evidence(db_path),
        "versions": {
            "package": PACKAGE_VERSION,
            "release_channel": RELEASE_CHANNEL,
            "code_revision": SOURCE_REVISION,
            "observer_surface": OBSERVER_SURFACE_VERSION,
            "schema": EXPECTED_SCHEMA_VERSION,
        },
    }
