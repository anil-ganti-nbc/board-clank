"""SQLite domain store. Compatibility is inspected read-only before any write handle."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from board_clank._version import EXPECTED_SCHEMA_VERSION
from board_clank.compatibility import (
    EXPECTED_TABLES,
    CompatibilityReport,
    StateCompatibilityError,
    inspect_compatibility,
    inspect_path,
)
from board_clank.policy import DEFAULT_POLICY
from board_clank.taxonomy import CompatibilityState

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
PACKAGED_SCHEMA = Path(__file__).resolve().parent / "schema.sql"


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_migration_sql(version: int = 1) -> str:
    if version == 1:
        candidates = [
            MIGRATIONS_DIR / "001_initial.sql",
            MIGRATIONS_DIR / f"{version:03d}_initial.sql",
            PACKAGED_SCHEMA,
        ]
    else:
        candidates = sorted(MIGRATIONS_DIR.glob(f"{version:03d}_*.sql"))
    for path in candidates:
        if path.exists():
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError(f"board-clank schema migration {version} is not packaged")


class Store:
    def __init__(self, path: str | Path, *, migrate: bool = True) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.name != ":memory:" and str(self.path) != ":memory:":
            report = inspect_path(self.path)
            self._admit(report, migrate=migrate)
        self.con = sqlite3.connect(self.path)
        self.con.row_factory = sqlite3.Row
        self.con.isolation_level = None
        self.con.execute("PRAGMA foreign_keys = ON")
        if str(self.path) == ":memory:" or self.path.name == ":memory:":
            if migrate:
                self._bootstrap()
            return
        report = inspect_compatibility(self.con)
        if report.state is CompatibilityState.FRESH:
            if not migrate:
                raise StateCompatibilityError(report)
            self._bootstrap()
        elif report.state is CompatibilityState.MIGRATION_REQUIRED:
            if not migrate:
                raise StateCompatibilityError(report)
            self._migrate(report)
        elif report.state is CompatibilityState.COMPATIBLE:
            return
        else:
            raise StateCompatibilityError(report)
        reverified = inspect_compatibility(self.con)
        if reverified.state is not CompatibilityState.COMPATIBLE:
            raise StateCompatibilityError(reverified)

    def _admit(self, report: CompatibilityReport, *, migrate: bool) -> None:
        if report.state in {CompatibilityState.FRESH, CompatibilityState.COMPATIBLE}:
            return
        if report.state is CompatibilityState.MIGRATION_REQUIRED and migrate:
            return
        raise StateCompatibilityError(report)

    def _stamp_migration(self, version: int, name: str) -> None:
        self.con.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at, name) VALUES (?, ?, ?)",
            (version, _utcnow(), name),
        )

    def _bootstrap(self) -> None:
        if MIGRATIONS_DIR.joinpath("002_diagnostic_conditions.sql").exists():
            # Repo layout: apply each migration in order so history matches
            # migrated databases exactly.
            for version in range(1, EXPECTED_SCHEMA_VERSION + 1):
                self.con.executescript(load_migration_sql(version))
                self._stamp_migration(version, f"{version:03d}")
        else:
            # Packaged install without migrations dir: full schema in one shot.
            self.con.executescript(PACKAGED_SCHEMA.read_text(encoding="utf-8"))
            self._stamp_migration(EXPECTED_SCHEMA_VERSION, "packaged")
        self._seed_delivery_policy()
        self.con.commit()

    def _migrate(self, report: CompatibilityReport) -> None:
        current = report.observed_version or 0
        if current >= EXPECTED_SCHEMA_VERSION:
            return
        if current < 1:
            raise StateCompatibilityError(
                CompatibilityReport(
                    CompatibilityState.UNKNOWN,
                    f"no canonical migration path from {current} to {EXPECTED_SCHEMA_VERSION}",
                    observed_version=current,
                )
            )
        # Append-only forward migrations; Foundation 2 adds v2 diagnostics.
        for version in range(current + 1, EXPECTED_SCHEMA_VERSION + 1):
            self.con.executescript(load_migration_sql(version))
            self._stamp_migration(version, f"{version:03d}")
        self.con.commit()

    def _seed_delivery_policy(self) -> None:
        for event_type, disposition in DEFAULT_POLICY.items():
            self.con.execute(
                """
                INSERT OR IGNORE INTO delivery_policy(event_type, disposition, notes)
                VALUES (?, ?, ?)
                """,
                (event_type.value, disposition.value, "foundation-0 initial policy"),
            )

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def execute(self, sql: str, params: tuple | list | dict = ()) -> sqlite3.Cursor:
        return self.con.execute(sql, params)

    def commit(self) -> None:
        self.con.commit()

    def rollback(self) -> None:
        self.con.rollback()

    def begin(self) -> None:
        self.con.execute("BEGIN IMMEDIATE")

    def one(self, sql: str, params: tuple | list | dict = ()) -> sqlite3.Row | None:
        return self.con.execute(sql, params).fetchone()

    def all(self, sql: str, params: tuple | list | dict = ()) -> list[sqlite3.Row]:
        return self.con.execute(sql, params).fetchall()

    def count(self, table: str) -> int:
        row = self.one(f"SELECT COUNT(*) AS n FROM {table}")
        return int(row["n"]) if row else 0


def expected_table_names() -> tuple[str, ...]:
    return EXPECTED_TABLES
