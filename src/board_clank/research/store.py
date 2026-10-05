"""Separate research-lead database. It has no Board entity, event, or source tables."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS research_leads (
    lead_id TEXT PRIMARY KEY,
    cnx_candidate_id TEXT NOT NULL UNIQUE,
    cnx_run_id TEXT NOT NULL,
    canonical_oem_name TEXT NOT NULL,
    claimed_domain TEXT NOT NULL,
    candidate_urls_json TEXT NOT NULL,
    catalogue_url TEXT NOT NULL,
    envelope_hash TEXT NOT NULL UNIQUE,
    provenance_json TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    status TEXT NOT NULL,
    qualification_state TEXT NOT NULL,
    reason TEXT,
    evidence_json TEXT NOT NULL,
    envelope_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_dispositions (
    disposition_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    envelope_hash TEXT,
    cnx_candidate_id TEXT,
    cnx_run_id TEXT,
    detail_json TEXT NOT NULL
);
"""

FORBIDDEN_TABLES = frozenset({
    "boards", "board_families", "board_revisions", "board_variants", "events",
    "notifications", "sources", "canonical_observations", "vendors",
})


class ResearchStoreError(RuntimeError):
    pass


class ResearchStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if self.path.exists() and self.path.is_dir():
            raise ResearchStoreError("research database path is a directory")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.path)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)
        present = {row[0] for row in self.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        leaked = present & FORBIDDEN_TABLES
        if leaked:
            raise ResearchStoreError("research database contains canonical Board tables: " + ",".join(sorted(leaked)))

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> "ResearchStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def lead_by_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        row = self.con.execute("SELECT * FROM research_leads WHERE cnx_candidate_id=?", (candidate_id,)).fetchone()
        return dict(row) if row else None

    def lead_by_hash(self, digest: str) -> dict[str, Any] | None:
        row = self.con.execute("SELECT * FROM research_leads WHERE envelope_hash=?", (digest,)).fetchone()
        return dict(row) if row else None

    def lead(self, lead_id: str) -> dict[str, Any] | None:
        row = self.con.execute("SELECT * FROM research_leads WHERE lead_id=?", (lead_id,)).fetchone()
        return dict(row) if row else None

    def disposition(self, disposition_id: str) -> dict[str, Any] | None:
        row = self.con.execute("SELECT * FROM research_dispositions WHERE disposition_id=?", (disposition_id,)).fetchone()
        return dict(row) if row else None

    def insert_lead(self, row: dict[str, Any]) -> None:
        self.con.execute(
            """
            INSERT INTO research_leads(
                lead_id, cnx_candidate_id, cnx_run_id, canonical_oem_name, claimed_domain,
                candidate_urls_json, catalogue_url, envelope_hash, provenance_json, imported_at,
                status, qualification_state, reason, evidence_json, envelope_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["lead_id"], row["cnx_candidate_id"], row["cnx_run_id"], row["canonical_oem_name"],
                row["claimed_domain"], row["candidate_urls_json"], row["catalogue_url"], row["envelope_hash"],
                row["provenance_json"], row["imported_at"], row["status"], row["qualification_state"],
                row.get("reason"), row["evidence_json"], row["envelope_json"],
            ),
        )
        self.con.commit()

    def update_lead(self, lead_id: str, **fields: Any) -> None:
        assignments = ", ".join(f"{key}=?" for key in fields)
        self.con.execute(f"UPDATE research_leads SET {assignments} WHERE lead_id=?", (*fields.values(), lead_id))
        self.con.commit()

    def insert_disposition(self, row: dict[str, Any]) -> None:
        if self.disposition(row["disposition_id"]):
            return
        self.con.execute(
            """
            INSERT INTO research_dispositions(
                disposition_id, created_at, status, reason, envelope_hash, cnx_candidate_id, cnx_run_id, detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["disposition_id"], row["created_at"], row["status"], row["reason"],
                row.get("envelope_hash"), row.get("cnx_candidate_id"), row.get("cnx_run_id"),
                json.dumps(row.get("detail") or {}, sort_keys=True),
            ),
        )
        self.con.commit()

    def list_leads(self) -> list[dict[str, Any]]:
        rows = self.con.execute(
            "SELECT lead_id, cnx_candidate_id, cnx_run_id, canonical_oem_name, claimed_domain, status, qualification_state, reason, imported_at FROM research_leads ORDER BY lead_id"
        ).fetchall()
        return [dict(row) for row in rows]

    def counts(self) -> dict[str, int]:
        return {
            "leads": int(self.con.execute("SELECT COUNT(*) FROM research_leads").fetchone()[0]),
            "dispositions": int(self.con.execute("SELECT COUNT(*) FROM research_dispositions").fetchone()[0]),
        }
