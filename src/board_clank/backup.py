"""Operator-triggered backup / restore for Board Clank persistent state.

Design (Production Readiness 1, Workstream A):

- Backups use SQLite's native online-backup API (``con.backup``), which is
  safe against an active writer; raw file copying of a live database is
  never used.
- A backup is TWO files: the database image and a sidecar metadata JSON
  recording clank identity, schema version, code revision, timestamp,
  integrity result, row counts per durable table, and the database image's
  SHA-256. The artifact pair is immutable: an existing backup is never
  overwritten.
- Backup fails closed on integrity failure: if the source database does
  not pass ``quick_check``, no artifact is produced.
- Restore validates metadata completeness, SHA-256, SQLite integrity and
  schema compatibility; restores into an isolated staging path first; only
  an explicit ``activate`` moves it onto the operator-named target, and an
  existing target is never overwritten without ``force``.

Deployed HEAD is never implied by a backup: the metadata records the
revision that RAN the backup, kept distinct from any deployment truth.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from board_clank._version import CLANK_ID, EXPECTED_SCHEMA_VERSION, SOURCE_REVISION
from board_clank.compatibility import inspect_path

BACKUP_FORMAT_VERSION = 1
BACKUP_SUFFIX = ".board-clank-backup.db"
META_SUFFIX = ".board-clank-backup.meta.json"

# Durable intelligence state compared for exact-restoration equivalence.
DURABLE_TABLES = (
    "schema_migrations",
    "delivery_policy",
    "sources",
    "vendors",
    "board_families",
    "socs",
    "boards",
    "board_revisions",
    "board_variants",
    "canonical_observations",
    "current_entity_observations",
    "collector_runs",
    "processed_run_receipts",
    "run_errors",
    "source_baselines",
    "events",
    "notifications",
    "board_classifications",
    "novelty_evidence",
    "price_observations",
    "software_support",
    "diagnostic_conditions",
    "diagnostic_sightings",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _row_counts(con: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in DURABLE_TABLES:
        row = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        counts[table] = int(row[0])
    return counts


def _integrity(con: sqlite3.Connection) -> str:
    return str(con.execute("PRAGMA integrity_check").fetchone()[0])


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class BackupResult:
    database_path: Path
    metadata_path: Path
    sha256: str
    metadata: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "database_path": str(self.database_path),
            "metadata_path": str(self.metadata_path),
            "sha256": self.sha256,
            "metadata": self.metadata,
        }


def create_backup(db_path: str | Path, out_dir: str | Path, *, name: str | None = None,
                  code_revision: str | None = None) -> BackupResult:
    """Create an immutable backup artifact pair from a live-capable database."""
    source = Path(db_path)
    if not source.exists():
        raise BackupError(f"source database does not exist: {source}")
    report = inspect_path(source)
    if report.state.name != "COMPATIBLE":
        raise BackupError(
            f"refusing to back up database in state {report.state.value}: {report.reason}"
        )

    src_con = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    try:
        integrity = _integrity(src_con)
        if integrity != "ok":
            raise BackupError(f"source database failed integrity check: {integrity}")
        counts = _row_counts(src_con)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        stem = name or f"{source.stem}-{stamp}"
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        backup_path = out / f"{stem}{BACKUP_SUFFIX}"
        meta_path = out / f"{stem}{META_SUFFIX}"
        if backup_path.exists() or meta_path.exists():
            raise BackupError(f"backup artifact already exists (immutable): {backup_path}")

        dst_con = sqlite3.connect(backup_path)
        try:
            src_con.backup(dst_con)
            dst_con.commit()
        finally:
            dst_con.close()
    finally:
        src_con.close()

    # Verify the artifact independently before metadata is written.
    art_con = sqlite3.connect(f"file:{backup_path.as_posix()}?mode=ro", uri=True)
    try:
        artifact_integrity = _integrity(art_con)
        artifact_counts = _row_counts(art_con)
    finally:
        art_con.close()
    if artifact_integrity != "ok":
        backup_path.unlink(missing_ok=True)
        raise BackupError(f"backup artifact failed integrity check: {artifact_integrity}")
    if artifact_counts != counts:
        backup_path.unlink(missing_ok=True)
        raise BackupError("backup artifact row counts diverge from source")

    digest = sha256_file(backup_path)
    metadata = {
        "backup_format_version": BACKUP_FORMAT_VERSION,
        "clank_id": CLANK_ID,
        "schema_version": EXPECTED_SCHEMA_VERSION,
        "code_revision": code_revision or SOURCE_REVISION,
        "created_at": _utcnow(),
        "source_database": str(source),
        "source_observed_version": report.observed_version,
        "integrity": artifact_integrity,
        "row_counts": artifact_counts,
        "durable_tables": list(DURABLE_TABLES),
        "sha256": digest,
        "deployment_truth": "NOT implied; deployed HEAD remains a separate observer fact",
    }
    meta_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        os.chmod(backup_path, 0o444)
        os.chmod(meta_path, 0o444)
    except OSError:  # pragma: no cover - best effort on filesystems without chmod
        pass
    return BackupResult(database_path=backup_path, metadata_path=meta_path, sha256=digest, metadata=metadata)


class BackupError(RuntimeError):
    pass


def _read_metadata(meta_path: Path) -> dict[str, Any]:
    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupError(f"backup metadata unreadable: {exc}") from exc
    required = (
        "backup_format_version", "clank_id", "schema_version", "code_revision",
        "created_at", "integrity", "row_counts", "sha256",
    )
    missing = [key for key in required if key not in metadata]
    if missing:
        raise BackupError(f"backup metadata incomplete; missing: {sorted(missing)}")
    if metadata["clank_id"] != CLANK_ID:
        raise BackupError(f"backup belongs to another clank: {metadata['clank_id']}")
    if metadata["backup_format_version"] != BACKUP_FORMAT_VERSION:
        raise BackupError(f"unsupported backup format version: {metadata['backup_format_version']}")
    return metadata


def verify_backup(backup_path: str | Path, meta_path: str | Path) -> dict[str, Any]:
    """Validate metadata completeness, SHA-256 and integrity. Read-only."""
    backup_path, meta_path = Path(backup_path), Path(meta_path)
    if not backup_path.exists() or not meta_path.exists():
        raise BackupError(f"backup artifact missing: {backup_path} / {meta_path}")
    metadata = _read_metadata(meta_path)
    digest = sha256_file(backup_path)
    if digest != metadata["sha256"]:
        raise BackupError(f"backup SHA-256 mismatch: metadata {metadata['sha256']} != actual {digest}")
    con = sqlite3.connect(f"file:{backup_path.as_posix()}?mode=ro", uri=True)
    try:
        integrity = _integrity(con)
        counts = _row_counts(con)
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"backup artifact is not a readable database: {exc}") from exc
    finally:
        con.close()
    if integrity != "ok":
        raise BackupError(f"backup failed integrity check: {integrity}")
    if counts != metadata["row_counts"]:
        raise BackupError("backup row counts diverge from metadata")
    observed = inspect_path(backup_path)
    return {
        "verified": True,
        "sha256": digest,
        "integrity": integrity,
        "schema_version": observed.observed_version,
        "row_counts": counts,
        "metadata": metadata,
    }


def durable_state_snapshot(db_path: str | Path) -> dict[str, list[str]]:
    """Deterministic per-table content hashes for equivalence proofs."""
    con = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    try:
        snapshot: dict[str, list[str]] = {}
        for table in DURABLE_TABLES:
            digest = hashlib.sha256()
            rows = con.execute(f"SELECT * FROM {table}").fetchall()
            for row in rows:
                digest.update(repr(row).encode("utf-8"))
            snapshot[table] = [digest.hexdigest(), str(len(rows))]
        return snapshot
    finally:
        con.close()


def restore_backup(backup_path: str | Path, meta_path: str | Path, target_path: str | Path,
                   *, activate: bool = False, force: bool = False) -> dict[str, Any]:
    """Restore a verified backup into an isolated staging path.

    Refuses on: missing/incomplete metadata, hash mismatch, integrity
    failure, schema incompatibility, or an existing target without
    ``force``. With ``activate`` the verified staging database replaces the
    target; without it, the staging path is returned for operator review.
    """
    backup_path, meta_path, target_path = Path(backup_path), Path(meta_path), Path(target_path)
    verification = verify_backup(backup_path, meta_path)
    metadata = verification["metadata"]
    declared_schema = metadata["schema_version"]
    if declared_schema != EXPECTED_SCHEMA_VERSION:
        raise BackupError(
            f"backup metadata declares schema version {declared_schema}, not compatible "
            f"with this binary's schema version {EXPECTED_SCHEMA_VERSION}"
        )
    if verification["schema_version"] != declared_schema:
        raise BackupError(
            f"backup metadata declares schema version {declared_schema} but the artifact "
            f"observes {verification['schema_version']}"
        )
    if target_path.exists() and not force:
        raise BackupError(
            f"target already exists; refusing to overwrite without explicit force: {target_path}"
        )

    target_path.parent.mkdir(parents=True, exist_ok=True)
    staging = target_path.with_name(target_path.name + ".restore-staging")
    if staging.exists():
        staging.unlink()
    staging.write_bytes(backup_path.read_bytes())

    check = sqlite3.connect(staging)
    try:
        integrity = _integrity(check)
        counts = _row_counts(check)
    finally:
        check.close()
    if integrity != "ok":
        staging.unlink(missing_ok=True)
        raise BackupError(f"restored staging database failed integrity check: {integrity}")
    if counts != metadata["row_counts"]:
        staging.unlink(missing_ok=True)
        raise BackupError("restored staging row counts diverge from metadata")
    restored_digest = sha256_file(staging)
    if restored_digest != metadata["sha256"]:
        staging.unlink(missing_ok=True)
        raise BackupError("restored staging SHA-256 diverges from metadata")

    report = {
        "restored": True,
        "staging_path": str(staging),
        "activated": False,
        "target_path": str(target_path),
        "sha256": restored_digest,
        "integrity": integrity,
        "schema_version": verification["schema_version"],
        "backup_created_at": metadata["created_at"],
        "backup_code_revision": metadata["code_revision"],
        "row_counts": counts,
        "durable_state": durable_state_snapshot(staging),
    }
    if activate:
        if target_path.exists():
            target_path.unlink()
        staging.replace(target_path)
        report["activated"] = True
        report["staging_path"] = None
    return report
