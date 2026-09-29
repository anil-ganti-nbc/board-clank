"""Mechanical isolation checks from the seeder spec, including tests 18, 19, and 37."""

from __future__ import annotations

import ast
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from board_clank.compatibility import EXPECTED_TABLES
from board_clank.paths import default_db_path
from cnx_seeder.cli import main
from cnx_seeder.paths import REPO_ROOT, operational_db_path

SHA = "0123456789abcdef0123456789abcdef01234567"
NOW = "2026-09-29T00:00:00Z"
BANNED = {"subprocess", "fcntl", "msvcrt", "pty", "posix"}


def _modules(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _imported(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module.split(".")[0])
    return found


def test_19_ast_import_boundaries() -> None:
    seeder = REPO_ROOT / "src" / "cnx_seeder"
    for path in _modules(seeder):
        text = path.read_text(encoding="utf-8")
        assert "sync_sources_to_store" not in text
        imported = set(_imported(path))
        assert "board_clank" not in imported
        assert imported.isdisjoint(BANNED)
    for path in _modules(REPO_ROOT / "src" / "board_clank"):
        assert "cnx_seeder" not in set(_imported(path))


def test_19_path_guard_refuses_operational_locations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    existing = tmp_path / "operational.db"
    payload = b"already-here"
    existing.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setenv("BOARD_CLANK_DB", str(existing))
    rc = main(
        [
            "run",
            "--state-dir",
            str(existing),
            "--run-id",
            "blocked",
            "--code-revision",
            SHA,
            "--now",
            NOW,
            "--fixture",
            str(tmp_path / "missing-fixture"),
        ]
    )
    assert rc != 0
    assert hashlib.sha256(existing.read_bytes()).hexdigest() == digest
    repo_db = REPO_ROOT / "data" / "board_clank.db"
    assert not repo_db.exists()
    monkeypatch.delenv("BOARD_CLANK_DB", raising=False)
    rc = main(
        [
            "run",
            "--state-dir",
            str(repo_db),
            "--run-id",
            "blocked-repo",
            "--code-revision",
            SHA,
            "--now",
            NOW,
            "--fixture",
            str(tmp_path / "missing-fixture"),
        ]
    )
    assert rc != 0
    assert not repo_db.exists()


def _ordered(con: sqlite3.Connection, table: str) -> tuple[int, str]:
    rows = con.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
    blob = json.dumps([list(row) for row in rows]).encode()
    return len(rows), hashlib.sha256(blob).hexdigest()


def test_18_event_and_outbox_separation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    operational = tmp_path / "board.db"
    con = sqlite3.connect(operational)
    for name in EXPECTED_TABLES:
        if name == "notifications":
            con.execute(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY, channel TEXT, payload TEXT)")
        else:
            con.execute(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY, payload TEXT)")
    con.execute("INSERT INTO sources(payload) VALUES ('roster')")
    con.execute("INSERT INTO events(payload) VALUES ('seen')")
    con.execute("INSERT INTO notifications(channel, payload) VALUES ('outbox', 'pending')")
    con.execute("INSERT INTO canonical_observations(payload) VALUES ('obs')")
    con.execute("INSERT INTO novelty_evidence(payload) VALUES ('novel')")
    con.commit()
    before = {name: _ordered(con, name) for name in EXPECTED_TABLES}
    con.close()
    monkeypatch.setenv("BOARD_CLANK_DB", str(operational))
    fix = tmp_path / "fix"
    state = tmp_path / "seeder-state"
    url = "https://www.cnx-software.com/2026/09/29/sep/"
    fix.mkdir()
    manifest = {
        "routes": {
            "https://www.cnx-software.com/robots.txt": {
                "status": 200,
                "body": "User-agent: *\nAllow: /\n",
                "content_type": "text/plain",
            },
            "https://www.cnx-software.com/news/sbc/feed/": {
                "status": 200,
                "body": (
                    "<rss><channel><item><title>raspberry pi</title><link>"
                    + url
                    + "</link><description>notes</description></item></channel></rss>"
                ),
                "content_type": "application/rss+xml",
            },
            url: {
                "status": 200,
                "body": "<html><body><p>raspberry pi</p></body></html>",
                "content_type": "text/html",
            },
        }
    }
    (fix / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    config = (REPO_ROOT / "config" / "sources.yaml").read_bytes()
    packaged = (REPO_ROOT / "src" / "board_clank" / "sources.yaml").read_bytes()
    assert main(
        [
            "run",
            "--state-dir",
            str(state),
            "--run-id",
            "iso",
            "--code-revision",
            SHA,
            "--now",
            NOW,
            "--fixture",
            str(fix),
        ]
    ) == 0
    assert (REPO_ROOT / "config" / "sources.yaml").read_bytes() == config
    assert (REPO_ROOT / "src" / "board_clank" / "sources.yaml").read_bytes() == packaged
    assert hashlib.sha256(config).hexdigest() == hashlib.sha256(packaged).hexdigest()
    after_con = sqlite3.connect(f"file:{operational.as_posix()}?mode=ro", uri=True)
    after = {name: _ordered(after_con, name) for name in EXPECTED_TABLES}
    after_con.close()
    assert after == before
    queue = sqlite3.connect(f"file:{(state / 'queue.sqlite').as_posix()}?mode=ro", uri=True)
    names = {
        row[0]
        for row in queue.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    queue.close()
    for forbidden in ("events", "notifications", "sources", "canonical_observations", "novelty_evidence"):
        assert forbidden not in names


def test_37_copied_path_rules_stay_in_sync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "explicit.db"
    data = tmp_path / "data-dir"
    monkeypatch.setenv("BOARD_CLANK_DB", str(db))
    assert operational_db_path(REPO_ROOT) == default_db_path()
    monkeypatch.delenv("BOARD_CLANK_DB")
    monkeypatch.setenv("BOARD_CLANK_DATA_DIR", str(data))
    assert operational_db_path(REPO_ROOT) == default_db_path()
    monkeypatch.delenv("BOARD_CLANK_DATA_DIR")
    assert operational_db_path(REPO_ROOT) == default_db_path()
    path_mod = REPO_ROOT / "src" / "cnx_seeder" / "paths.py"
    assert "board_clank" not in set(_imported(path_mod))
