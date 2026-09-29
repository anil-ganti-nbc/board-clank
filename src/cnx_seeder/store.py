"""Seeder-owned SQLite queue. Never opens Board's operational database."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from cnx_seeder.bounds import ALIAS_TABLE_VERSION
from cnx_seeder.normalize import is_cnx_host, public_url
from cnx_seeder.paths import PathGuardError, assert_state_dir_allowed

SCHEMA = """
CREATE TABLE IF NOT EXISTS seeder_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    run_id               TEXT PRIMARY KEY,
    started_at           TEXT NOT NULL,
    finished_at          TEXT,
    code_revision        TEXT NOT NULL,
    alias_table_version  TEXT NOT NULL,
    roster_sha256        TEXT NOT NULL,
    sample_source        TEXT NOT NULL,
    listing_url          TEXT NOT NULL,
    sample_window_start  TEXT,
    sample_window_end    TEXT,
    article_urls_json    TEXT NOT NULL,
    max_listing_pages    INTEGER NOT NULL,
    max_articles         INTEGER NOT NULL,
    status               TEXT NOT NULL,
    CHECK (length(code_revision) = 40)
);
CREATE TABLE IF NOT EXISTS fetches (
    fetch_id        INTEGER PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES runs(run_id),
    url             TEXT NOT NULL,
    attempt         INTEGER NOT NULL,
    fetched_at      TEXT NOT NULL,
    http_status     INTEGER,
    content_sha256  TEXT,
    byte_length     INTEGER,
    elapsed_ms      INTEGER,
    robots_decision TEXT NOT NULL,
    outcome         TEXT NOT NULL,
    error           TEXT,
    UNIQUE (run_id, url, attempt)
);
CREATE TABLE IF NOT EXISTS leads (
    lead_key                  TEXT PRIMARY KEY,
    cnx_article_url           TEXT NOT NULL,
    article_title             TEXT NOT NULL,
    discovered_name           TEXT NOT NULL,
    normalized_name           TEXT NOT NULL,
    comparison_mentions_json  TEXT NOT NULL,
    classification            TEXT NOT NULL,
    reason_code               TEXT NOT NULL,
    primary_url               TEXT,
    primary_domain            TEXT,
    primary_host              TEXT,
    homepage_url              TEXT,
    homepage_host             TEXT,
    board_surface_url         TEXT,
    qualified                 INTEGER NOT NULL DEFAULT 0 CHECK (qualified IN (0, 1)),
    CHECK (primary_url IS NULL OR primary_url <> cnx_article_url),
    CHECK (homepage_url IS NULL OR homepage_url <> cnx_article_url)
);
CREATE TABLE IF NOT EXISTS lead_sightings (
    run_id    TEXT NOT NULL REFERENCES runs(run_id),
    lead_key  TEXT NOT NULL REFERENCES leads(lead_key),
    seen_at   TEXT NOT NULL,
    PRIMARY KEY (run_id, lead_key)
);
CREATE TABLE IF NOT EXISTS article_sightings (
    run_id           TEXT NOT NULL REFERENCES runs(run_id),
    candidate_key    TEXT NOT NULL,
    cnx_article_url  TEXT NOT NULL,
    seen_at          TEXT NOT NULL,
    PRIMARY KEY (run_id, candidate_key, cnx_article_url)
);
CREATE TABLE IF NOT EXISTS qualified_candidates (
    candidate_key      TEXT PRIMARY KEY,
    first_run_id       TEXT NOT NULL,
    cnx_article_url    TEXT NOT NULL,
    article_title      TEXT NOT NULL,
    primary_url        TEXT NOT NULL,
    primary_domain     TEXT NOT NULL,
    primary_host       TEXT NOT NULL,
    homepage_url       TEXT NOT NULL,
    homepage_host      TEXT NOT NULL,
    board_surface_url  TEXT NOT NULL,
    normalized_name    TEXT NOT NULL,
    inserted_at        TEXT NOT NULL,
    content_sha256     TEXT NOT NULL,
    CHECK (primary_url <> cnx_article_url),
    CHECK (homepage_url <> cnx_article_url),
    CHECK (board_surface_url = primary_url),
    CHECK (length(cnx_article_url) > 0),
    CHECK (length(primary_url) > 0),
    CHECK (length(homepage_url) > 0),
    CHECK (primary_host <> 'cnx-software.com'),
    CHECK (homepage_host <> 'cnx-software.com'),
    CHECK (primary_domain <> 'cnx-software.com'),
    CHECK (primary_host NOT LIKE '%.cnx-software.com'),
    CHECK (homepage_host NOT LIKE '%.cnx-software.com'),
    CHECK (primary_domain NOT LIKE '%.cnx-software.com')
);
CREATE TRIGGER IF NOT EXISTS qualified_reject_cnx
BEFORE INSERT ON qualified_candidates
FOR EACH ROW
WHEN NEW.primary_host = 'cnx-software.com'
  OR NEW.primary_host LIKE '%.cnx-software.com'
  OR NEW.homepage_host = 'cnx-software.com'
  OR NEW.homepage_host LIKE '%.cnx-software.com'
  OR NEW.primary_domain = 'cnx-software.com'
  OR NEW.primary_domain LIKE '%.cnx-software.com'
BEGIN
  SELECT RAISE(ABORT, 'cnx host is discovery provenance only');
END;
CREATE TRIGGER IF NOT EXISTS leads_reject_cnx_primary
BEFORE INSERT ON leads
FOR EACH ROW
WHEN (NEW.primary_host IS NOT NULL AND (NEW.primary_host = 'cnx-software.com' OR NEW.primary_host LIKE '%.cnx-software.com'))
  OR (NEW.homepage_host IS NOT NULL AND (NEW.homepage_host = 'cnx-software.com' OR NEW.homepage_host LIKE '%.cnx-software.com'))
  OR (NEW.primary_domain IS NOT NULL AND (NEW.primary_domain = 'cnx-software.com' OR NEW.primary_domain LIKE '%.cnx-software.com'))
BEGIN
  SELECT RAISE(ABORT, 'cnx host is discovery provenance only');
END;
"""


class CnxHostRejected(RuntimeError):
    pass


def _stored_url(value: str | None) -> str | None:
    if not value:
        return value
    return public_url(value)


class Queue:
    def __init__(self, state_dir: Path, repo_root: Path | None = None) -> None:
        self.state_dir = assert_state_dir_allowed(state_dir, repo_root)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "bodies").mkdir(exist_ok=True)
        self.path = self.state_dir / "queue.sqlite"
        self.con = sqlite3.connect(self.path)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys = ON")
        self.con.executescript(SCHEMA)
        self.con.execute(
            "INSERT OR IGNORE INTO seeder_meta(key, value) VALUES ('schema_version', '1')"
        )
        self.con.execute(
            "INSERT OR IGNORE INTO seeder_meta(key, value) VALUES ('alias_table_version', ?)",
            (ALIAS_TABLE_VERSION,),
        )
        self.con.execute(
            "INSERT OR IGNORE INTO seeder_meta(key, value) VALUES ('source_plane', 'DISCOVERY_ONLY')"
        )
        self.con.execute(
            "INSERT OR IGNORE INTO seeder_meta(key, value) VALUES ('source_authority', 'THIRD_PARTY_DISCOVERY')"
        )
        self.con.commit()

    def close(self) -> None:
        self.con.close()

    def has_run(self, run_id: str) -> bool:
        row = self.con.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return row is not None

    def latest_completed(self, exclude: str) -> str | None:
        row = self.con.execute(
            """
            SELECT run_id FROM runs
            WHERE run_id <> ? AND status = 'completed'
            ORDER BY started_at DESC, run_id DESC
            LIMIT 1
            """,
            (exclude,),
        ).fetchone()
        return None if row is None else str(row["run_id"])

    def write_body(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        target = self.state_dir / "bodies" / f"{digest}.bin"
        if not target.exists():
            target.write_bytes(data)
        return digest

    def read_body(self, digest: str) -> bytes:
        return (self.state_dir / "bodies" / f"{digest}.bin").read_bytes()

    def add_fetch(self, row: dict) -> None:
        self.con.execute(
            """
            INSERT INTO fetches(
                run_id, url, attempt, fetched_at, http_status, content_sha256,
                byte_length, elapsed_ms, robots_decision, outcome, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["run_id"],
                _stored_url(row["url"]),
                row["attempt"],
                row["fetched_at"],
                row.get("http_status"),
                row.get("content_sha256"),
                row.get("byte_length"),
                row.get("elapsed_ms"),
                row["robots_decision"],
                row["outcome"],
                row.get("error"),
            ),
        )

    def add_lead(self, row: dict, seen_at: str, run_id: str) -> None:
        for field in ("primary_host", "homepage_host", "primary_domain"):
            value = row.get(field)
            if value and is_cnx_host(value):
                raise CnxHostRejected(field)
        self.con.execute(
            """
            INSERT INTO leads(
                lead_key, cnx_article_url, article_title, discovered_name, normalized_name,
                comparison_mentions_json, classification, reason_code, primary_url,
                primary_domain, primary_host, homepage_url, homepage_host, board_surface_url,
                qualified
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["lead_key"],
                _stored_url(row["cnx_article_url"]),
                row["article_title"],
                row["discovered_name"],
                row["normalized_name"],
                json.dumps(row.get("mentions") or []),
                row["classification"],
                row["reason_code"],
                _stored_url(row.get("primary_url")),
                row.get("primary_domain"),
                row.get("primary_host"),
                _stored_url(row.get("homepage_url")),
                row.get("homepage_host"),
                _stored_url(row.get("board_surface_url")),
                1 if row.get("qualified") else 0,
            ),
        )
        self.con.execute(
            "INSERT OR IGNORE INTO lead_sightings(run_id, lead_key, seen_at) VALUES (?, ?, ?)",
            (run_id, row["lead_key"], seen_at),
        )

    def add_candidate(self, row: dict, seen_at: str, run_id: str) -> bool:
        for field in ("primary_host", "homepage_host", "primary_domain"):
            if is_cnx_host(row[field]):
                raise CnxHostRejected(field)
        existing = self.con.execute(
            "SELECT candidate_key FROM qualified_candidates WHERE candidate_key = ?",
            (row["candidate_key"],),
        ).fetchone()
        self.con.execute(
            """
            INSERT OR IGNORE INTO article_sightings(run_id, candidate_key, cnx_article_url, seen_at)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, row["candidate_key"], _stored_url(row["cnx_article_url"]), seen_at),
        )
        if existing:
            return False
        self.con.execute(
            """
            INSERT INTO qualified_candidates(
                candidate_key, first_run_id, cnx_article_url, article_title, primary_url,
                primary_domain, primary_host, homepage_url, homepage_host, board_surface_url,
                normalized_name, inserted_at, content_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["candidate_key"],
                run_id,
                _stored_url(row["cnx_article_url"]),
                row["article_title"],
                _stored_url(row["primary_url"]),
                row["primary_domain"],
                row["primary_host"],
                _stored_url(row["homepage_url"]),
                row["homepage_host"],
                _stored_url(row["primary_url"]),
                row["normalized_name"],
                seen_at,
                row["content_sha256"],
            ),
        )
        return True

    def commit(self) -> None:
        self.con.commit()


def open_queue(state_dir: Path, repo_root: Path | None = None) -> Queue:
    try:
        return Queue(state_dir, repo_root)
    except PathGuardError:
        raise
