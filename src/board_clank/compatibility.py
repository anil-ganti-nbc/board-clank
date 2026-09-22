"""Read-only persistent-state compatibility barrier. Health never migrates."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from board_clank._version import EXPECTED_SCHEMA_VERSION
from board_clank.taxonomy import CompatibilityState

EXPECTED_TABLES = (
    "schema_migrations",
    "vendors",
    "board_families",
    "socs",
    "boards",
    "board_revisions",
    "board_variants",
    "sources",
    "source_baselines",
    "collector_runs",
    "canonical_observations",
    "observation_occurrences",
    "current_entity_observations",
    "events",
    "notifications",
    "delivery_policy",
    "processed_run_receipts",
    "run_errors",
    "board_classifications",
    "novelty_evidence",
    "price_observations",
    "software_support",
    "diagnostic_conditions",
    "diagnostic_sightings",
)


@dataclass
class CompatibilityReport:
    state: CompatibilityState
    reason: str
    observed_version: int | None = None
    expected_version: int = EXPECTED_SCHEMA_VERSION
    missing_tables: list[str] = field(default_factory=list)
    present_tables: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "reason": self.reason,
            "observed_version": self.observed_version,
            "expected_version": self.expected_version,
            "missing_tables": self.missing_tables,
            "present_tables": self.present_tables,
        }


class StateCompatibilityError(RuntimeError):
    def __init__(self, report: CompatibilityReport) -> None:
        super().__init__(report.reason)
        self.report = report


def connect_readonly(path: str | Path) -> sqlite3.Connection:
    target = Path(path)
    uri = f"file:{target.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _user_tables(con: sqlite3.Connection) -> list[str]:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [row[0] for row in rows]


def inspect_compatibility(con: sqlite3.Connection) -> CompatibilityReport:
    try:
        check = con.execute("PRAGMA quick_check").fetchone()
        if check is None or str(check[0]).lower() != "ok":
            return CompatibilityReport(
                CompatibilityState.CORRUPT,
                f"quick_check failed: {None if check is None else check[0]}",
            )
    except sqlite3.Error as exc:
        return CompatibilityReport(CompatibilityState.CORRUPT, f"not a readable sqlite file: {exc}")

    tables = _user_tables(con)
    if not tables:
        return CompatibilityReport(CompatibilityState.FRESH, "zero user tables", present_tables=[])

    if "schema_migrations" not in tables:
        return CompatibilityReport(
            CompatibilityState.UNKNOWN,
            "tables exist but schema_migrations marker is absent",
            present_tables=tables,
        )

    try:
        info = {row[1] for row in con.execute("PRAGMA table_info(schema_migrations)").fetchall()}
        if "version" not in info:
            return CompatibilityReport(
                CompatibilityState.UNKNOWN,
                "schema_migrations exists but has no version column",
                present_tables=tables,
            )
        versions = [
            int(row[0])
            for row in con.execute("SELECT version FROM schema_migrations").fetchall()
            if row[0] is not None
        ]
    except (sqlite3.Error, TypeError, ValueError) as exc:
        return CompatibilityReport(
            CompatibilityState.UNKNOWN,
            f"schema_migrations unreadable: {exc}",
            present_tables=tables,
        )

    if not versions:
        return CompatibilityReport(
            CompatibilityState.UNKNOWN,
            "schema_migrations present but never stamped",
            present_tables=tables,
        )

    observed = max(versions)
    if observed > EXPECTED_SCHEMA_VERSION:
        return CompatibilityReport(
            CompatibilityState.INCOMPATIBLE_NEWER,
            "state is newer than this binary; fail closed",
            observed_version=observed,
            present_tables=tables,
        )
    if observed < EXPECTED_SCHEMA_VERSION:
        return CompatibilityReport(
            CompatibilityState.MIGRATION_REQUIRED,
            "valid older state requires canonical migration",
            observed_version=observed,
            present_tables=tables,
        )

    missing = [name for name in EXPECTED_TABLES if name not in tables]
    if missing:
        return CompatibilityReport(
            CompatibilityState.PARTIAL,
            "marker at expected version but expected tables are missing",
            observed_version=observed,
            missing_tables=missing,
            present_tables=tables,
        )
    return CompatibilityReport(
        CompatibilityState.COMPATIBLE,
        "state matches expected schema version",
        observed_version=observed,
        present_tables=tables,
    )


def inspect_path(path: str | Path) -> CompatibilityReport:
    target = Path(path)
    if not target.exists():
        return CompatibilityReport(CompatibilityState.FRESH, "database file does not exist")
    if target.stat().st_size == 0:
        return CompatibilityReport(CompatibilityState.FRESH, "database file is empty")
    try:
        con = connect_readonly(target)
    except sqlite3.Error as exc:
        return CompatibilityReport(CompatibilityState.CORRUPT, f"cannot open read-only: {exc}")
    try:
        return inspect_compatibility(con)
    finally:
        con.close()
