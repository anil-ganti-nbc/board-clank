"""Read-only persistent-state compatibility barrier. Health never migrates."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from functools import lru_cache
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


def _quoted(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _sql_words(sql: str) -> list[str]:
    """Ignore quoted names/data and comments when inspecting constraint keywords."""
    tokens = re.finditer(
        r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`|\[[^\]]*\]|"
        r"--[^\n]*|/\*[\s\S]*?\*/|[A-Za-z_][A-Za-z_0-9]*", sql
    )
    return [token.group().upper() for token in tokens if re.match(r"[A-Za-z_]", token.group())]


def _safe_literal_default(value: str, *, nullable: bool) -> bool:
    text = value.strip()
    while text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    if text.upper() == "NULL":
        return nullable
    return bool(
        text.upper() in ("TRUE", "FALSE")
        or re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", text)
        or re.fullmatch(r"'(?:''|[^'])*'", text)
        or re.fullmatch(r"[xX]'(?:[0-9A-Fa-f]{2})*'", text)
    )


def _table_structure(con: sqlite3.Connection, table: str) -> dict[str, object]:
    """Read material structure, including hidden columns and write constraints."""
    columns = {
        row[1]: (str(row[2]).upper(), row[3], row[4], row[5], row[6])
        for row in con.execute(f"PRAGMA table_xinfo({_quoted(table)})")
    }
    foreign_keys: dict[int, list[tuple[object, ...]]] = {}
    for row in con.execute(f"PRAGMA foreign_key_list({_quoted(table)})"):
        foreign_keys.setdefault(row[0], []).append(tuple(row)[1:])
    keys = {tuple(sorted(group)) for group in foreign_keys.values()}
    indexes = {}
    for row in con.execute(f"PRAGMA index_list({_quoted(table)})"):
        columns_in_key = tuple(
            (part[2], part[3], part[4])
            for part in con.execute(f"PRAGMA index_xinfo({_quoted(row[1])})")
            if part[5]
        )
        indexes[row[1]] = (row[2], row[3], row[4], columns_in_key)
    sql = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    words = _sql_words(str(sql[0])) if sql else []
    mode = next(((row[2], row[4], row[5]) for row in con.execute("PRAGMA table_list")
                 if row[0] == "main" and row[1] == table), None)
    if mode is None:
        raise ValueError(f"table mode cannot be verified: {table}")
    return {"columns": columns, "foreign_keys": keys, "indexes": indexes, "mode": mode,
            "autoincrement": "AUTOINCREMENT" in words,
            "constraints": tuple(words.count(word) for word in ("CHECK", "COLLATE", "DEFERRABLE", "CONFLICT"))}


@lru_cache(maxsize=1)
def _expected_structure() -> dict[str, dict[str, object]]:
    # The packaged v3 contract is built in memory; the target is never migrated.
    con = sqlite3.connect(":memory:")
    try:
        con.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
        if set(_user_tables(con)) != set(EXPECTED_TABLES):
            raise ValueError("packaged schema table contract is inconsistent")
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='trigger'").fetchone():
            raise ValueError("canonical v3 schema must not define triggers")
        return {table: _table_structure(con, table) for table in EXPECTED_TABLES}
    finally:
        con.close()


def _structural_issues(con: sqlite3.Connection) -> list[str]:
    # No trigger is part of canonical v3. An extra-table trigger can also mutate
    # canonical rows indirectly, so unknown trigger programs fail closed.
    issues = [f"{row[0]}: unexpected trigger on {row[1]}" for row in con.execute(
        "SELECT name, tbl_name FROM sqlite_master WHERE type='trigger' ORDER BY name"
    )]
    for table, expected in _expected_structure().items():
        actual = _table_structure(con, table)
        for column, shape in expected["columns"].items():
            if actual["columns"].get(column) != shape:
                issues.append(f"{table}.{column}: required column/type/nullability/default/key differs")
        for column, shape in actual["columns"].items():
            if column in expected["columns"]:
                continue
            nullable = not shape[1]
            safe_default = nullable if shape[2] is None else _safe_literal_default(shape[2], nullable=nullable)
            if shape[3] or shape[4] or not safe_default:
                issues.append(f"{table}.{column}: extra column is not safe for canonical inserts")
        if expected["foreign_keys"] != actual["foreign_keys"]:
            issues.append(f"{table}: foreign-key contract differs")
        if expected["mode"] != actual["mode"] or expected["constraints"] != actual["constraints"]:
            issues.append(f"{table}: table mode/check/collation/deferred constraints differ")
        if expected["autoincrement"] != actual["autoincrement"]:
            issues.append(f"{table}: required row-id allocation differs")
        actual_indexes = set(actual["indexes"].values())
        expected_unique = {shape for shape in expected["indexes"].values() if shape[0]}
        if any(shape[0] and shape not in expected_unique for shape in actual_indexes):
            issues.append(f"{table}: unexpected uniqueness constraint")
        for name, shape in expected["indexes"].items():
            if (shape[1] in ("pk", "u") and shape not in actual_indexes) or (
                shape[1] == "c" and actual["indexes"].get(name) != shape
            ):
                issues.append(f"{table}.{name}: required index/uniqueness differs")
    return issues


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
    try:
        issues = _structural_issues(con)
    except (sqlite3.Error, OSError, ValueError) as exc:
        return CompatibilityReport(
            CompatibilityState.UNKNOWN,
            f"schema structure could not be verified: {exc}",
            observed_version=observed,
            present_tables=tables,
        )
    if issues:
        return CompatibilityReport(
            CompatibilityState.PARTIAL,
            "schema-v3 structure differs: " + "; ".join(issues[:10]),
            observed_version=observed,
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
