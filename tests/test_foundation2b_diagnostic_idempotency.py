from __future__ import annotations

import json
from pathlib import Path

from board_clank._version import EXPECTED_SCHEMA_VERSION
from board_clank.cli import main
from board_clank.collectors.orange_pi import collect_corpus, parse_product_html, raw_body_hash
from board_clank.collectors.raspberry_pi import collect_corpus as rpi_collect_corpus
from board_clank.models import CollectorRunRequest
from board_clank.pipeline import Pipeline
from board_clank.store import Store
from board_clank.taxonomy import EventType

FIX = Path("fixtures/orange_pi_product/html")
DETAILS = "http://www.orangepi.org/html/hardWare/computerAndMicrocontrollers/details"
OBS = "2026-09-22T00:00:00+00:00"


def _events(store: Store, event_type: str) -> list[dict]:
    return [
        dict(row)
        for row in store.all(
            "SELECT event_type, run_id, baseline_silent, payload_json FROM events WHERE event_type = ? ORDER BY event_id",
            (event_type,),
        )
    ]


def _notifications(store: Store, event_type: str) -> int:
    return len(
        store.all(
            """
            SELECT n.notification_id FROM notifications n
            JOIN events e ON e.event_key = n.event_key
            WHERE e.event_type = ?
            """,
            (event_type,),
        )
    )


def _conditions(store: Store, diagnostic_type: str) -> list[dict]:
    return [
        dict(row)
        for row in store.all(
            """
            SELECT condition_key, status, reason, state_hash, transition_count,
                   open_occurrences, total_occurrences, resolved_at, last_run_id
            FROM diagnostic_conditions WHERE diagnostic_type = ?
            """,
            (diagnostic_type,),
        )
    ]


def _sightings(store: Store) -> list[dict]:
    return [dict(row) for row in store.all("SELECT run_id, condition_key, emitted_event_key FROM diagnostic_sightings ORDER BY sighting_id")]


def _accept(pipeline: Pipeline, drafts: list, run_id: str, *, source: str = "orange-pi-product",
            started_at: str = OBS, ok: bool = True, error: str | None = None):
    return pipeline.accept_run(
        CollectorRunRequest(
            run_id=run_id,
            source_key=source,
            collector_key=source,
            started_at=started_at,
            observations=drafts,
            ok=ok,
            error=error,
            fixture_scenario=None,
        )
    )


def _drafts(fname: str, url: str | None = None, observed_at: str = OBS) -> list:
    page_url = url or f"{DETAILS}/{fname}"
    drafts, _info = parse_product_html(
        (FIX / fname).read_text(encoding="utf-8"), page_url=page_url, observed_at=observed_at
    )
    return drafts


# ------------------------------------------------------- unchanged conditions


def test_unchanged_unresolved_is_state_not_perpetual_novelty(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(rpi_collect_corpus("baseline", run_id="rpi-base", started_at="2026-09-22T01:00:00+00:00"))
    first = pipeline.accept_run(rpi_collect_corpus("insufficient", run_id="rpi-stub-1", started_at="2026-09-22T02:00:00+00:00"))
    assert first.status == "accepted"
    assert first.events
    events_after_first = _events(store, "NOVELTY_UNRESOLVED")
    assert len(events_after_first) == 1
    outbox_after_first = _notifications(store, "NOVELTY_UNRESOLVED")

    second = pipeline.accept_run(rpi_collect_corpus("insufficient", run_id="rpi-stub-2", started_at="2026-09-22T03:00:00+00:00"))
    assert second.status == "accepted"
    assert _events(store, "NOVELTY_UNRESOLVED") == events_after_first
    assert _notifications(store, "NOVELTY_UNRESOLVED") == outbox_after_first

    conditions = _conditions(store, "NOVELTY_UNRESOLVED")
    assert len(conditions) == 1
    assert conditions[0]["status"] == "OPEN"
    assert conditions[0]["open_occurrences"] == 2
    assert conditions[0]["total_occurrences"] == 2
    assert conditions[0]["transition_count"] == 0
    sightings = _sightings(store)
    assert {row["run_id"] for row in sightings} == {"rpi-stub-1", "rpi-stub-2"}
    assert all(row["emitted_event_key"] for row in sightings if row["run_id"] == "rpi-stub-1")
    assert all(not row["emitted_event_key"] for row in sightings if row["run_id"] == "rpi-stub-2")
    # Fail-closed semantics unchanged: no board minted.
    assert "raspberry-pi-6" not in {row["board_slug"] for row in store.all("SELECT board_slug FROM boards")}


def test_unchanged_identity_anomaly_is_idempotent(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="opi-base", started_at="2026-09-22T01:00:00+00:00"))
    pipeline.accept_run(collect_corpus("conflict", run_id="opi-conf-1", started_at="2026-09-22T02:00:00+00:00"))
    anomaly_events = _events(store, "IDENTITY_ANOMALY")
    unresolved_events = _events(store, "NOVELTY_UNRESOLVED")
    assert len(anomaly_events) == 1
    assert len(unresolved_events) == 1
    outbox_anomaly = _notifications(store, "IDENTITY_ANOMALY")

    pipeline.accept_run(collect_corpus("conflict", run_id="opi-conf-2", started_at="2026-09-22T03:00:00+00:00"))
    assert _events(store, "IDENTITY_ANOMALY") == anomaly_events
    assert _events(store, "NOVELTY_UNRESOLVED") == unresolved_events
    assert _notifications(store, "IDENTITY_ANOMALY") == outbox_anomaly

    for diagnostic_type in ("IDENTITY_ANOMALY", "NOVELTY_UNRESOLVED"):
        conditions = _conditions(store, diagnostic_type)
        assert len(conditions) == 1
        assert conditions[0]["status"] == "OPEN"
        assert conditions[0]["open_occurrences"] == 2
    # Both runs recorded operational sightings for both conditions.
    assert len(_sightings(store)) == 4
    assert "orange-pi-6-plus" not in {row["board_slug"] for row in store.all("SELECT board_slug FROM boards")}


# ------------------------------------------------------- raw-only vs semantic change


def test_raw_only_change_does_not_create_new_diagnostic_event(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="opi-base", started_at="2026-09-22T01:00:00+00:00"))
    html_a = (FIX / "Orange-Pi-6-Plus.html").read_text(encoding="utf-8")
    html_b = html_a.replace("<head>", '<head><meta name="csrf-token" content="token-abc-999">')
    html_b = html_b.replace("12-core 64-bit processor", "12-core   64-bit    processor")
    assert raw_body_hash(html_a) != raw_body_hash(html_b)
    drafts_a, _ = parse_product_html(html_a, page_url=f"{DETAILS}/Orange-Pi-6-Plus.html", observed_at="2026-09-22T02:00:00+00:00")
    drafts_b, _ = parse_product_html(html_b, page_url=f"{DETAILS}/Orange-Pi-6-Plus.html", observed_at="2026-09-22T03:00:00+00:00")
    _accept(pipeline, drafts_a, "opi-raw-a")
    anomaly_events = _events(store, "IDENTITY_ANOMALY")
    assert len(anomaly_events) == 1
    _accept(pipeline, drafts_b, "opi-raw-b")
    assert _events(store, "IDENTITY_ANOMALY") == anomaly_events
    assert _notifications(store, "IDENTITY_ANOMALY") == 1
    conditions = _conditions(store, "IDENTITY_ANOMALY")
    assert conditions[0]["transition_count"] == 0


def test_semantic_evidence_change_creates_transition_event(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="opi-base", started_at="2026-09-22T01:00:00+00:00"))
    html = (FIX / "Orange-Pi-6-Plus.html").read_text(encoding="utf-8")
    drafts_a, _ = parse_product_html(html, page_url=f"{DETAILS}/Orange-Pi-6-Plus.html", observed_at="2026-09-22T02:00:00+00:00")
    _accept(pipeline, drafts_a, "opi-sem-a")
    assert len(_events(store, "IDENTITY_ANOMALY")) == 1
    state_before = _conditions(store, "IDENTITY_ANOMALY")[0]["state_hash"]

    # The conflicting candidate set itself changes: CD8160 becomes CD8150.
    html_changed = html.replace("CD8160", "CD8150")
    drafts_b, _ = parse_product_html(html_changed, page_url=f"{DETAILS}/Orange-Pi-6-Plus.html", observed_at="2026-09-22T03:00:00+00:00")
    _accept(pipeline, drafts_b, "opi-sem-b")
    events = _events(store, "IDENTITY_ANOMALY")
    assert len(events) == 2
    payload = json.loads(events[-1]["payload_json"])
    assert payload["transition"] == "evidence-changed"
    assert payload["from_state_hash"] == state_before
    assert payload["to_state_hash"] != state_before
    condition = _conditions(store, "IDENTITY_ANOMALY")[0]
    assert condition["state_hash"] == payload["to_state_hash"]
    assert condition["transition_count"] == 1
    assert condition["status"] == "OPEN"


def test_reason_transition_is_visible(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="opi-base", started_at="2026-09-22T01:00:00+00:00"))
    # Run 1: insufficient evidence for Orange Pi 7.
    _accept(pipeline, _drafts("Orange-Pi-7.html"), "opi-seven-1")
    unresolved = _events(store, "NOVELTY_UNRESOLVED")
    assert len(unresolved) == 1
    rows = [dict(r) for r in store.all("SELECT entity_key, reason FROM diagnostic_conditions WHERE diagnostic_type='NOVELTY_UNRESOLVED'")]
    assert rows[0]["entity_key"] == "orange-pi:orange-pi-7"
    assert rows[0]["reason"] == "insufficient-evidence"

    # Run 2: the same candidate now produces a genuine conflict.
    conflict_html = """<html><body>
    <h3>Orange Pi 7</h3>
    <div class="hardware-specification"><h3>Hardware specification</h3><table>
      <tr><td>SoC</td><td>CIX CD8180/CD8160</td></tr>
      <tr><td>RAM</td><td>8GB LPDDR5</td></tr>
    </table></div></body></html>"""
    drafts, _ = parse_product_html(conflict_html, page_url=f"{DETAILS}/Orange-Pi-7.html", observed_at="2026-09-22T03:00:00+00:00")
    _accept(pipeline, drafts, "opi-seven-2")
    events = _events(store, "NOVELTY_UNRESOLVED")
    assert len(events) == 2
    payload = json.loads(events[-1]["payload_json"])
    assert payload["transition"] == "evidence-changed"
    assert payload["reason"] != "insufficient-evidence"
    rows = [dict(r) for r in store.all("SELECT reason FROM diagnostic_conditions WHERE diagnostic_type='NOVELTY_UNRESOLVED'")]
    assert rows[0]["reason"] != "insufficient-evidence"
    # The conflict also opens the anomaly class for the same candidate.
    assert len(_events(store, "IDENTITY_ANOMALY")) == 1


# ------------------------------------------------------- resolution + reappearance


def test_resolution_closes_condition_and_normal_novelty_laws_apply(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="opi-base", started_at="2026-09-22T01:00:00+00:00"))
    _accept(pipeline, _drafts("Orange-Pi-7.html"), "opi-seven-stub")
    assert _conditions(store, "NOVELTY_UNRESOLVED")[0]["status"] == "OPEN"

    # The page gains a full specification table: the candidate resolves.
    resolved_html = (FIX / "Orange-Pi-5.html").read_text(encoding="utf-8").replace(
        "Orange Pi 5(4GB/8GB/16GB)", "Orange Pi 7"
    )
    drafts, _ = parse_product_html(resolved_html, page_url=f"{DETAILS}/Orange-Pi-7.html", observed_at="2026-09-22T03:00:00+00:00")
    _accept(pipeline, drafts, "opi-seven-resolved")

    condition = _conditions(store, "NOVELTY_UNRESOLVED")[0]
    assert condition["status"] == "RESOLVED"
    assert condition["resolved_at"] is not None
    resolved_events = _events(store, "DIAGNOSTIC_RESOLVED")
    assert len(resolved_events) == 1
    assert json.loads(resolved_events[0]["payload_json"])["transition"] == "resolved"
    assert _notifications(store, "DIAGNOSTIC_RESOLVED") == 1

    # The board itself is subject to normal novelty laws: first-seen by Clank,
    # existing product, never market-new by resolution.
    board = store.one("SELECT board_key, marketing_name FROM boards WHERE board_slug = 'orange-pi-7'")
    assert board is not None
    novelty = store.one(
        "SELECT novelty_status FROM novelty_evidence WHERE entity_key = ?", (board["board_key"],)
    )
    assert novelty["novelty_status"] in {"EXISTING_PRODUCT", "UNKNOWN"}
    live_new = store.all(
        "SELECT event_type FROM events WHERE event_type = 'NEW_BOARD' AND baseline_silent = 0"
    )
    assert live_new  # normal first-seen admission path, not retroactive market-new
    novelty_rows = {row["novelty_status"] for row in store.all("SELECT novelty_status FROM novelty_evidence")}
    assert not novelty_rows & {"NEWLY_ANNOUNCED", "NEWLY_AVAILABLE"}


def test_reappearance_after_resolution_is_observable(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="opi-base", started_at="2026-09-22T01:00:00+00:00"))
    _accept(pipeline, _drafts("Orange-Pi-7.html"), "opi-seven-1")
    resolved_html = (FIX / "Orange-Pi-5.html").read_text(encoding="utf-8").replace(
        "Orange Pi 5(4GB/8GB/16GB)", "Orange Pi 7"
    )
    drafts, _ = parse_product_html(resolved_html, page_url=f"{DETAILS}/Orange-Pi-7.html", observed_at="2026-09-22T02:00:00+00:00")
    _accept(pipeline, drafts, "opi-seven-ok")
    assert _conditions(store, "NOVELTY_UNRESOLVED")[0]["status"] == "RESOLVED"

    # The ambiguity later reappears: new occurrence, observable.
    _accept(pipeline, _drafts("Orange-Pi-7.html", observed_at="2026-09-22T04:00:00+00:00"), "opi-seven-again")
    condition = _conditions(store, "NOVELTY_UNRESOLVED")[0]
    assert condition["status"] == "OPEN"
    assert condition["transition_count"] == 1
    events = _events(store, "NOVELTY_UNRESOLVED")
    assert len(events) == 2
    payload = json.loads(events[-1]["payload_json"])
    assert payload["transition"] == "reappeared"
    assert payload["previously_resolved_at"]


def test_failed_run_does_not_close_conditions(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="opi-base", started_at="2026-09-22T01:00:00+00:00"))
    pipeline.accept_run(collect_corpus("conflict", run_id="opi-conf-1", started_at="2026-09-22T02:00:00+00:00"))
    assert _conditions(store, "IDENTITY_ANOMALY")[0]["status"] == "OPEN"
    failed = pipeline.accept_run(
        CollectorRunRequest(
            run_id="opi-failed",
            source_key="orange-pi-product",
            collector_key="orange-pi-product",
            started_at="2026-09-22T03:00:00+00:00",
            observations=[],
            ok=False,
            error="collector failed",
        )
    )
    assert failed.status == "failed"
    assert _conditions(store, "IDENTITY_ANOMALY")[0]["status"] == "OPEN"
    assert _events(store, "DIAGNOSTIC_RESOLVED") == []


# ------------------------------------------------------- Raspberry Pi regressions


def test_rpi_conflict_is_idempotent_and_still_fails_closed(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(rpi_collect_corpus("baseline", run_id="rpi-base", started_at="2026-09-22T01:00:00+00:00"))
    socs_before = store.count("socs")
    pipeline.accept_run(rpi_collect_corpus("conflict", run_id="rpi-conf-1", started_at="2026-09-22T02:00:00+00:00"))
    pipeline.accept_run(rpi_collect_corpus("conflict", run_id="rpi-conf-2", started_at="2026-09-22T03:00:00+00:00"))
    assert len(_events(store, "IDENTITY_ANOMALY")) == 1
    assert len(_events(store, "NOVELTY_UNRESOLVED")) == 1
    assert store.count("socs") == socs_before
    pi5_soc = store.one(
        """
        SELECT s.marketing_name FROM socs s
        JOIN board_revisions r ON r.soc_key = s.soc_key
        JOIN boards b ON b.board_key = r.board_key
        WHERE b.board_slug = 'raspberry-pi-5'
        """
    )
    assert pi5_soc["marketing_name"] == "BCM2712"


def test_rpi_parser_failure_records_run_error_only(pipeline: Pipeline, store: Store) -> None:
    result = pipeline.accept_run(rpi_collect_corpus("malformed", run_id="rpi-bad", started_at="2026-09-22T01:00:00+00:00"))
    assert result.status == "failed"
    assert store.count("run_errors") == 1
    assert store.count("diagnostic_conditions") == 0
    assert store.count("events") == 0


def test_rpi_historical_first_seen_and_pip_replay_unchanged(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(rpi_collect_corpus("baseline", run_id="rpi-base", started_at="2026-09-22T01:00:00+00:00"))
    pipeline.accept_run(rpi_collect_corpus("historical", run_id="rpi-hist", started_at="2026-09-22T02:00:00+00:00"))
    types = {row["event_type"] for row in store.all("SELECT event_type FROM events")}
    assert "HISTORICAL_DISCOVERY" in types
    assert "FIRST_SEEN_BY_CLANK" in types
    pi3 = store.one("SELECT board_key FROM boards WHERE board_slug = 'raspberry-pi-3-model-b'")
    novelty = store.one("SELECT novelty_status FROM novelty_evidence WHERE entity_key = ?", (pi3["board_key"],))
    assert novelty["novelty_status"] == "HISTORICAL"
    pipeline.accept_run(rpi_collect_corpus("pip-live-sim", run_id="rpi-pip-1", started_at="2026-09-22T03:00:00+00:00"))
    events_after_first_pip = store.count("events")
    pipeline.accept_run(rpi_collect_corpus("pip-live-sim", run_id="rpi-pip-2", started_at="2026-09-22T04:00:00+00:00"))
    assert store.count("events") == events_after_first_pip
    assert store.count("diagnostic_conditions") == 0


def test_multiple_ambiguous_pages_for_one_candidate_are_stable(pipeline: Pipeline, store: Store) -> None:
    """Live regression: Orange Pi publishes two AIpro pages ((20t) and
    (8-12t)) that normalise onto one candidate name. Their evidence must
    aggregate into one condition whose state is stable across runs, not
    flip-flop per page."""
    pipeline.accept_run(collect_corpus("baseline", run_id="opi-base", started_at="2026-09-22T01:00:00+00:00"))
    page_a = """<html><body>
    <h3>Orange Pi AIpro(20T)</h3>
    <div class="hardware-specification"><h3>Hardware specification</h3><table>
      <tr><td>Processor</td><td>Ascend 310, 20TOPS AI processor</td></tr>
    </table></div></body></html>"""
    page_b = page_a.replace("AIpro(20T)", "AIpro(8T)").replace("20TOPS", "8TOPS")
    drafts_a, _ = parse_product_html(page_a, page_url=f"{DETAILS}/Orange-Pi-AIpro(20t).html", observed_at="2026-09-22T02:00:00+00:00")
    drafts_b, _ = parse_product_html(page_b, page_url=f"{DETAILS}/Orange-Pi-AIpro(8-12t).html", observed_at="2026-09-22T02:00:00+00:00")
    assert drafts_a and drafts_b and drafts_a[0].evidence_insufficient and drafts_b[0].evidence_insufficient

    _accept(pipeline, drafts_a + drafts_b, "opi-aipro-1")
    unresolved = _events(store, "NOVELTY_UNRESOLVED")
    assert len(unresolved) == 1
    payload = json.loads(unresolved[0]["payload_json"])
    assert payload["pages"] == 2

    _accept(pipeline, drafts_b + drafts_a, "opi-aipro-2")  # order must not matter
    assert _events(store, "NOVELTY_UNRESOLVED") == unresolved
    conditions = _conditions(store, "NOVELTY_UNRESOLVED")
    assert len(conditions) == 1
    assert conditions[0]["transition_count"] == 0
    assert conditions[0]["open_occurrences"] == 2
    assert len(_sightings(store)) == 4

    # One of the two pages later resolves: the aggregate changes once.
    _accept(pipeline, drafts_a, "opi-aipro-3")
    events = _events(store, "NOVELTY_UNRESOLVED")
    assert len(events) == 2
    assert json.loads(events[-1]["payload_json"])["transition"] == "evidence-changed"
    assert json.loads(events[-1]["payload_json"])["pages"] == 1


# ------------------------------------------------------- operational plane + schema


def test_source_intel_reports_diagnostic_condition_counts(tmp_path: Path, capsys) -> None:
    db = tmp_path / "intel.db"
    assert main(["--db", str(db), "collect", "--source", "orange-pi-product", "--run-id", "i1"]) == 0
    capsys.readouterr()
    assert main(["--db", str(db), "collect", "--source", "orange-pi-product", "--corpus", "conflict", "--run-id", "i2"]) == 0
    capsys.readouterr()
    assert main(["--db", str(db), "source-intel", "--source", "orange-pi-product"]) == 0
    intel = json.loads(capsys.readouterr().out)
    by_type = {(row["diagnostic_type"], row["status"]): row["conditions"] for row in intel["diagnostic_conditions"]}
    assert by_type.get(("IDENTITY_ANOMALY", "OPEN")) == 1
    assert by_type.get(("NOVELTY_UNRESOLVED", "OPEN")) == 1
    assert intel["delivery_eligible"] is False
    assert intel["enabled"] is False


def test_baseline_diagnostic_birth_is_suppressed(pipeline: Pipeline, store: Store) -> None:
    # First-ever run of a source is its baseline: even the diagnostic births
    # are baseline-silent and suppressed.
    result = pipeline.accept_run(collect_corpus("conflict", run_id="opi-first", started_at="2026-09-22T01:00:00+00:00"))
    assert result.baseline is True
    anomaly = _events(store, "IDENTITY_ANOMALY")
    assert len(anomaly) == 1
    assert anomaly[0]["baseline_silent"] == 1
    assert all(
        row["disposition"] == "SUPPRESSED"
        for row in store.all("SELECT disposition FROM notifications")
    )


def test_schema_v2_and_forward_migration_path(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "v2.db"
    Store(path)
    con = sqlite3.connect(path)
    versions = [row[0] for row in con.execute("SELECT version FROM schema_migrations ORDER BY version")]
    assert versions == [1, 2]
    con.close()
    report = __import__("board_clank.compatibility", fromlist=["inspect_path"]).inspect_path(path)
    assert report.state.value == "COMPATIBLE"
    assert report.observed_version == EXPECTED_SCHEMA_VERSION

    # Simulate a Foundation 2A (v1) database and migrate it forward.
    legacy = tmp_path / "v1.db"
    Store(legacy)
    con = sqlite3.connect(legacy)
    con.execute("DROP TABLE diagnostic_sightings")
    con.execute("DROP TABLE diagnostic_conditions")
    con.execute("DELETE FROM schema_migrations WHERE version = 2")
    con.commit()
    con.close()
    inspected = __import__("board_clank.compatibility", fromlist=["inspect_path"]).inspect_path(legacy)
    assert inspected.state.value == "MIGRATION_REQUIRED"
    Store(legacy, migrate=True)  # applies 002 and stamps
    con = sqlite3.connect(legacy)
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert {"diagnostic_conditions", "diagnostic_sightings"} <= tables
    assert __import__("board_clank.compatibility", fromlist=["inspect_path"]).inspect_path(legacy).state.value == "COMPATIBLE"
