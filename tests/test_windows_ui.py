"""Windows-native operator GUI. Startup is read-only and ports stay on loopback."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import threading
import time
import urllib.parse
from pathlib import Path

import pytest

from board_clank.cli import main
from board_clank.compatibility import connect_readonly
from board_clank.research.export import export_jsonl, synthetic_envelope
from board_clank.research.fetch import FetchEvidence
from board_clank.research.paths import same_database
from board_clank.store import Store
from board_clank.ui.ports import CANDIDATE_PORTS, EXCLUDED_PORTS, LOOPBACK, PortOccupied, bind_loopback, select_bound_socket
from board_clank.ui.server import open_browser_when_ready, start_ui
from board_clank.ui.standards import STANDARDS_UI_COMMIT, STANDARDS_UI_TAG


def _fetch_ok(url: str, domain: str) -> FetchEvidence:
    body = b"board-research-oem: Northwind Boards\n"
    return FetchEvidence(url, url, 200, "sha256:" + hashlib.sha256(body).hexdigest(), len(body), body.decode())


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "Board Data"
    root.mkdir()
    canonical = root / "canon.sqlite"
    Store(canonical).close()
    return canonical, root / "research.sqlite"


def _request(ui, path: str, *, form: dict[str, str] | None = None) -> tuple[int, str]:
    target = urllib.parse.urlsplit(ui.url)
    connection = http.client.HTTPConnection(target.hostname, target.port, timeout=5)
    if form is None:
        connection.request("GET", path)
    else:
        payload = urllib.parse.urlencode(form)
        connection.request("POST", path, body=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
    response = connection.getresponse()
    body = response.read().decode("utf-8")
    status = response.status
    connection.close()
    return status, body


def _jsonl(path: Path) -> None:
    export_jsonl(path, [synthetic_envelope("run-ui")], run_id="run-ui")


@pytest.fixture
def ui(tmp_path: Path):
    canonical, research = _workspace(tmp_path)
    running = start_ui(
        canonical,
        research,
        open_browser=False,
        runtime_dir=tmp_path / "runtime",
        app_sha="TESTSHA",
        app_tree="TESTTREE",
    )
    try:
        assert running.ready
        yield running, canonical, research
    finally:
        running.close()


def test_equivalent_windows_paths_are_one_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    canonical, _research = _workspace(tmp_path)
    folder = canonical.parent
    monkeypatch.chdir(folder)
    assert same_database(canonical, canonical.resolve())
    assert same_database("canon.sqlite", canonical)
    assert same_database(Path("canon.sqlite"), Path(os.path.abspath(canonical)))
    assert not same_database(canonical, folder / "research.sqlite")
    if os.name == "nt":
        assert same_database(str(canonical), str(canonical).replace("\\", "/"))
        assert same_database(canonical, str(canonical).upper())
        extended = "\\\\?\\" + str(canonical)
        assert same_database(extended, canonical)
    jsonl = folder / "candidates.jsonl"
    _jsonl(jsonl)
    spellings = [str(canonical)]
    if os.name == "nt":
        spellings.append(str(canonical).replace("\\", "/"))
        spellings.append(str(canonical).upper())
    for spelling in spellings:
        assert main([
            "--db", str(canonical),
            "import-candidates",
            "--input", str(jsonl),
            "--research-db", spelling,
            "--research-only",
        ]) == 2


def test_readonly_sqlite_uri_opens_path_with_spaces(tmp_path: Path) -> None:
    canonical, _research = _workspace(tmp_path)
    reopened = Store(canonical)
    reopened.close()
    connection = connect_readonly(canonical)
    try:
        count = connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    finally:
        connection.close()
    assert count >= 1
    from board_clank.compatibility import readonly_uri

    uri = readonly_uri(canonical)
    assert "Board%20Data" in uri
    assert uri.startswith("file:")
    assert "mode=ro" in uri


def test_gui_startup_does_not_collect_or_fetch(monkeypatch: pytest.MonkeyPatch, ui) -> None:
    calls = {"fetch": 0, "import": 0}

    def forbid_fetch(*_args, **_kwargs):
        calls["fetch"] += 1
        raise AssertionError("startup fetched")

    def forbid_import(*_args, **_kwargs):
        calls["import"] += 1
        raise AssertionError("startup imported")

    monkeypatch.setattr("board_clank.research.bridge.fetch_first_party", forbid_fetch)
    monkeypatch.setattr("board_clank.ui.service.import_jsonl", forbid_import)
    running, _canonical, _research = ui
    for path in ("/healthz", "/", "/leads", "/archive", "/activity", "/about"):
        status, body = _request(running, path)
        assert status == 200
        assert "data-collection=\"idle\"" in body or path == "/healthz"
        if path == "/healthz":
            payload = json.loads(body)
            assert payload["collection"] is False
            assert payload["qualification"] is False
            assert payload["source_fetch"] is False
            assert payload["host"] == "127.0.0.1"
    assert calls == {"fetch": 0, "import": 0}


def test_statuses_timestamps_authority_and_no_promotion(ui) -> None:
    running, canonical, research = ui
    folder = canonical.parent
    jsonl = folder / "candidates.jsonl"
    _jsonl(jsonl)
    before = canonical.read_bytes()
    status, imported = _request(running, "/import", form={"jsonl": str(jsonl)})
    assert status == 200
    assert "data-outcome=\"success\"" in imported
    assert "import succeeded and committed" in imported
    status, leads = _request(running, "/leads")
    assert status == 200
    assert "○ IMPORTED" in leads
    assert "data-status=\"IMPORTED\"" in leads
    assert "UTC import time" in leads
    assert "non-authoritative" in leads
    assert "Runtime health: UNKNOWN" in leads
    assert "Source operational health: UNKNOWN" in leads
    assert "No promotion or source-enable control is available." in _request(running, "/")[1]
    overview = _request(running, "/")[1]
    assert ">Promote<" not in overview
    assert "Enable source" not in overview
    assert "run all" not in overview.lower()
    assert "0.0.0.0" not in overview
    assert "Delivery: out of scope" in overview
    lead_id = leads.split('href="/leads/')[1].split('"')[0]
    status, detail = _request(running, f"/leads/{lead_id}")
    assert status == 200
    assert "CNX discovery claim (non-authoritative)" in detail
    assert "Board independently observed first-party evidence" in detail
    assert 'data-timestamp-role="Import time"' in detail
    assert 'data-timezone="UTC"' in detail
    assert "experimental; sources stay disabled" in detail
    assert "data-outcome=\"success\"" not in detail
    about = _request(running, "/about")[1]
    assert STANDARDS_UI_TAG in about
    assert STANDARDS_UI_COMMIT in about
    assert "TESTSHA" in about
    assert "127.0.0.1:" in about
    assert "Enabled sources: 0" in overview or "Enabled sources: 0" in about
    assert canonical.read_bytes() == before
    assert research.exists()


def test_qualify_delegates_and_duplicate_posts_are_serialized(monkeypatch: pytest.MonkeyPatch, ui) -> None:
    running, canonical, _research = ui
    jsonl = canonical.parent / "candidates.jsonl"
    _jsonl(jsonl)
    before = hashlib.sha256(canonical.read_bytes()).hexdigest()
    assert _request(running, "/import", form={"jsonl": str(jsonl)})[0] == 200
    _status, leads = _request(running, "/leads")
    lead_id = leads.split('href="/leads/')[1].split('"')[0]
    state = {"inside": 0, "max": 0}
    gate = threading.Lock()
    from board_clank.research.bridge import qualify_lead

    def wrapped(store, lead_id_arg, fetch=None):
        assert fetch is None
        with gate:
            state["inside"] += 1
            state["max"] = max(state["max"], state["inside"])
        try:
            time.sleep(0.15)
            return qualify_lead(store, lead_id_arg, fetch=_fetch_ok)
        finally:
            with gate:
                state["inside"] -= 1

    monkeypatch.setattr("board_clank.ui.service.qualify_lead", wrapped)
    bodies = []

    def post() -> None:
        _status, body = _request(running, f"/leads/{lead_id}/qualify", form={})
        bodies.append(body)

    threads = [threading.Thread(target=post), threading.Thread(target=post)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert state["max"] == 1
    assert len(bodies) == 2
    assert all("data-outcome=\"success\"" in body for body in bodies)
    assert all("qualify succeeded and committed" in body for body in bodies)
    archive = _request(running, "/archive")[1]
    active = _request(running, "/leads")[1]
    assert lead_id in archive
    assert lead_id not in active
    assert "▣ QUALIFIED" in archive
    activity = _request(running, "/activity")[1]
    assert "fetch 1 HTTP status" in activity
    assert ">200<" in activity or "200" in activity
    assert "FAILED" not in activity
    missing, missing_body = _request(running, "/leads/lead_" + "ab" * 12 + "/reject", form={"reason": "no such lead"})
    assert missing == 200
    assert "data-outcome=\"refused\"" in missing_body
    assert "succeeded" not in missing_body
    assert hashlib.sha256(canonical.read_bytes()).hexdigest() == before
    replay_status, replay = _request(running, "/import", form={"jsonl": str(jsonl)})
    assert replay_status == 200
    assert "import succeeded and committed" in replay


def test_reject_leaves_the_active_queue(ui) -> None:
    running, canonical, _research = ui
    jsonl = canonical.parent / "other.jsonl"
    _jsonl(jsonl)
    _request(running, "/import", form={"jsonl": str(jsonl)})
    lead_id = _request(running, "/leads")[1].split('href="/leads/')[1].split('"')[0]
    status, rejected = _request(running, f"/leads/{lead_id}/reject", form={"reason": "operator closed the lead"})
    assert status == 200
    assert "reject succeeded and committed" in rejected
    assert "✖ REJECTED" in rejected
    assert lead_id not in _request(running, "/leads")[1]
    assert lead_id in _request(running, "/archive")[1]
    assert "History is not deleted" in _request(running, "/archive")[1]


def test_port_selection_skips_occupied_and_stays_on_loopback(tmp_path: Path) -> None:
    assert 8200 in EXCLUDED_PORTS
    assert 8200 not in CANDIDATE_PORTS
    held = select_bound_socket()
    other = select_bound_socket()
    try:
        assert held.getsockname()[0] == LOOPBACK
        assert other.getsockname()[0] == LOOPBACK
        assert held.getsockname()[1] != other.getsockname()[1]
        occupied = held.getsockname()[1]
        with pytest.raises(PortOccupied) as exc:
            bind_loopback(occupied)
        assert str(occupied) in str(exc.value)
        canonical, research = _workspace(tmp_path)
        with pytest.raises(PortOccupied) as explicit:
            start_ui(canonical, research, port=occupied, open_browser=False, runtime_dir=tmp_path / "rt-fail", app_sha="X", app_tree="Y")
        assert str(occupied) in str(explicit.value)
        running = start_ui(canonical, research, open_browser=False, runtime_dir=tmp_path / "rt-ok", app_sha="X", app_tree="Y")
        try:
            assert running.ready
            assert running.host == "127.0.0.1"
            assert running.port != occupied
            assert running.port in CANDIDATE_PORTS
            with pytest.raises(PortOccupied):
                bind_loopback(running.port)
        finally:
            running.close()
    finally:
        held.close()
        other.close()


def test_stale_receipt_does_not_block_startup(tmp_path: Path) -> None:
    canonical, research = _workspace(tmp_path)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    receipt = runtime / "board-clank-ui.json"
    receipt.write_text(json.dumps({
        "pid": 99_999_999,
        "host": "127.0.0.1",
        "port": 8200,
        "started_at_utc": "2000-01-01T00:00:00Z",
        "app_sha": "dead",
        "stale": False,
    }), encoding="utf-8")
    running = start_ui(canonical, research, open_browser=False, runtime_dir=runtime, app_sha="LIVE", app_tree="TREE")
    try:
        assert running.ready
        payload = json.loads(receipt.read_text(encoding="utf-8"))
        assert payload["pid"] == os.getpid()
        assert payload["host"] == "127.0.0.1"
        assert payload["port"] == running.port
        assert payload["app_sha"] == "LIVE"
        stale = json.loads((runtime / "board-clank-ui.json.stale").read_text(encoding="utf-8"))
        assert stale["stale"] is True
        assert stale["pid"] == 99_999_999
    finally:
        running.close()
    assert not receipt.exists()


def test_browser_opens_only_after_readiness(tmp_path: Path) -> None:
    opened: list[str] = []
    canonical, research = _workspace(tmp_path)
    blocked = start_ui(
        canonical,
        research,
        open_browser=True,
        browser_opener=opened.append,
        probe=lambda _host, _port: False,
        runtime_dir=tmp_path / "no-browser",
        app_sha="X",
        app_tree="Y",
    )
    try:
        assert blocked.ready is False
        assert opened == []
    finally:
        blocked.close()
    opened.clear()
    running = start_ui(
        canonical,
        research,
        open_browser=True,
        browser_opener=opened.append,
        runtime_dir=tmp_path / "browser",
        app_sha="X",
        app_tree="Y",
    )
    try:
        assert running.ready is True
        assert opened == [running.url]
    finally:
        running.close()
    assert open_browser_when_ready("127.0.0.1", 9, opener=opened.append, probe=lambda _host, _port: False) is False
