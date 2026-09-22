from __future__ import annotations

import json
from pathlib import Path

from board_clank.cli import main
from board_clank.collectors.raspberry_pi import (
    RaspberryPiProductAdapter,
    collect_corpus,
    parse_product_html,
)
from board_clank.pipeline import Pipeline
from board_clank.store import Store
from board_clank.taxonomy import DeliveryDisposition, EventType
from board_clank.policy import disposition_for


def _event_types(store: Store) -> list[str]:
    return [row["event_type"] for row in store.all("SELECT event_type FROM events ORDER BY event_id")]


def _live_types(store: Store) -> list[str]:
    return [
        row["event_type"]
        for row in store.all("SELECT event_type FROM events WHERE baseline_silent = 0 ORDER BY event_id")
    ]


def _push_or_review(store: Store) -> list[str]:
    return [
        row["event_type"]
        for row in store.all(
            """
            SELECT e.event_type
            FROM events e
            JOIN notifications n ON n.event_key = e.event_key
            WHERE e.baseline_silent = 0 AND n.disposition IN ('PUSH', 'REVIEW')
            ORDER BY e.event_id
            """
        )
    ]


def test_adapter_defaults_are_offline_and_experimental() -> None:
    adapter = RaspberryPiProductAdapter()
    assert adapter.live_network is False
    assert adapter.experimental_live is False
    assert adapter.source_key == "raspberry-pi-product"


def test_index_page_is_leads_only() -> None:
    html = Path("fixtures/rpi_product/html/products-index.html").read_text(encoding="utf-8")
    drafts, info = parse_product_html(
        html,
        page_url="https://www.raspberrypi.com/products/",
        observed_at="2026-01-01T00:00:00+00:00",
    )
    assert drafts == []
    assert info["status"] == "lead-index"
    assert any("/products/raspberry-pi-5/" in href for href in info["lead_hrefs"])
    assert any("/products/raspberry-pi-5-case/" in href for href in info["lead_hrefs"])


def test_parser_pi5_variants_share_one_board() -> None:
    html = Path("fixtures/rpi_product/html/raspberry-pi-5.html").read_text(encoding="utf-8")
    drafts, info = parse_product_html(
        html,
        page_url="https://www.raspberrypi.com/products/raspberry-pi-5/",
        observed_at="2026-01-01T00:00:00+00:00",
    )
    assert info["status"] == "resolved"
    slugs = {item.board_slug for item in drafts}
    assert slugs == {"raspberry-pi-5"}
    rams = {item.variant.ram for item in drafts}
    assert rams == {"1GB", "2GB", "4GB", "8GB", "16GB"}
    assert all(item.soc_marketing_name == "BCM2712" for item in drafts)
    assert all(item.historical_known is False for item in drafts)


def test_parser_cm4_matrix_stays_one_board() -> None:
    html = Path("fixtures/rpi_product/html/compute-module-4.html").read_text(encoding="utf-8")
    drafts, _info = parse_product_html(
        html,
        page_url="https://www.raspberrypi.com/products/compute-module-4/",
        observed_at="2026-01-01T00:00:00+00:00",
    )
    assert {item.board_slug for item in drafts} == {"raspberry-pi-compute-module-4"}
    assert {item.board_type.value for item in drafts} == {"COMPUTE_MODULE"}
    rams = {item.variant.ram for item in drafts}
    storage = {item.variant.storage for item in drafts}
    wireless = {item.variant.wireless for item in drafts}
    assert rams == {"1GB", "2GB", "4GB", "8GB"}
    assert storage == {"none", "8GB", "16GB", "32GB"}
    assert wireless == {"none", "wifi"}
    assert len(drafts) == 4 * 4 * 2


def test_parser_revision_token_only_when_named() -> None:
    plain = Path("fixtures/rpi_product/html/raspberry-pi-4-model-b.html").read_text(encoding="utf-8")
    brief = Path("fixtures/rpi_product/html/pi4-pcb-rev15-brief.html").read_text(encoding="utf-8")
    plain_drafts, _ = parse_product_html(
        plain,
        page_url="https://www.raspberrypi.com/products/raspberry-pi-4-model-b/",
        observed_at="2026-01-01T00:00:00+00:00",
    )
    brief_drafts, _ = parse_product_html(
        brief,
        page_url="https://www.raspberrypi.com/products/raspberry-pi-4-model-b/",
        observed_at="2026-04-01T00:00:00+00:00",
    )
    assert {item.revision_token for item in plain_drafts} == {"UNKNOWN"}
    assert {item.revision_token for item in brief_drafts} == {"1.5"}
    assert {item.board_slug for item in plain_drafts} == {"raspberry-pi-4-model-b"}
    assert brief_drafts[0].board_slug == plain_drafts[0].board_slug


def test_parser_insufficient_and_conflict_fail_closed() -> None:
    stub = Path("fixtures/rpi_product/html/insufficient-new.html").read_text(encoding="utf-8")
    conflict = Path("fixtures/rpi_product/html/conflicting-identity.html").read_text(encoding="utf-8")
    stub_drafts, stub_info = parse_product_html(
        stub,
        page_url="https://www.raspberrypi.com/products/raspberry-pi-6/",
        observed_at="2026-06-01T00:00:00+00:00",
    )
    conflict_drafts, conflict_info = parse_product_html(
        conflict,
        page_url="https://www.raspberrypi.com/products/raspberry-pi-5/",
        observed_at="2026-07-01T00:00:00+00:00",
    )
    assert stub_info["status"] == "insufficient-evidence"
    assert stub_drafts[0].evidence_insufficient is True
    assert conflict_info["status"] == "identity-conflict"
    assert conflict_drafts[0].identity_conflict is True
    assert conflict_drafts[0].evidence_insufficient is True


def test_baseline_is_silent_and_creates_durable_entities(pipeline: Pipeline, store: Store) -> None:
    request = collect_corpus("baseline", run_id="rpi-baseline", started_at="2026-01-01T00:00:00+00:00")
    result = pipeline.accept_run(request)
    assert result.status == "accepted"
    assert result.baseline is True
    boards = {row["board_slug"] for row in store.all("SELECT board_slug FROM boards")}
    assert "raspberry-pi-5" in boards
    assert "raspberry-pi-4-model-b" in boards
    assert "raspberry-pi-zero-2-w" in boards
    assert "raspberry-pi-compute-module-4" in boards
    assert "raspberry-pi-6" not in boards
    assert store.count("vendors") == 1
    assert store.one("SELECT source_key FROM source_baselines")["source_key"] == "raspberry-pi-product"
    assert "NEW_BOARD" in _event_types(store)
    assert "BASELINE_ENTITY" in _event_types(store)
    assert "FIRST_SEEN_BY_CLANK" in _event_types(store)
    assert _push_or_review(store) == []
    assert all(row["disposition"] == "SUPPRESSED" for row in store.all("SELECT disposition FROM notifications"))


def test_replay_same_run_is_noop(pipeline: Pipeline, store: Store) -> None:
    request = collect_corpus("baseline", run_id="rpi-replay", started_at="2026-01-01T00:00:00+00:00")
    first = pipeline.accept_run(request)
    second = pipeline.accept_run(request)
    assert first.status == "accepted"
    assert second.replayed is True
    assert store.count("processed_run_receipts") == 1
    assert store.count("collector_runs") == 1


def test_replay_same_evidence_new_run_does_not_fork(pipeline: Pipeline, store: Store) -> None:
    first = collect_corpus("baseline", run_id="rpi-a", started_at="2026-01-01T00:00:00+00:00")
    second = collect_corpus("baseline", run_id="rpi-b", started_at="2026-01-02T00:00:00+00:00")
    pipeline.accept_run(first)
    boards_before = store.count("boards")
    variants_before = store.count("board_variants")
    pipeline.accept_run(second)
    assert store.count("boards") == boards_before
    assert store.count("board_variants") == variants_before
    assert "NEW_BOARD" not in _live_types(store)


def test_second_official_reference_does_not_fork(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="rpi-base", started_at="2026-01-01T00:00:00+00:00"))
    boards_before = store.count("boards")
    result = pipeline.accept_run(
        collect_corpus("second-reference", run_id="rpi-ref", started_at="2026-02-01T00:00:00+00:00")
    )
    assert result.status == "accepted"
    assert store.count("boards") == boards_before
    assert "NEW_REFERENCE" in _event_types(store)
    assert "NEW_BOARD" not in _live_types(store)
    assert disposition_for(EventType.NEW_REFERENCE) is DeliveryDisposition.SUPPRESSED


def test_historical_after_baseline_is_first_seen_not_market_new(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="rpi-base", started_at="2026-01-01T00:00:00+00:00"))
    result = pipeline.accept_run(
        collect_corpus("historical", run_id="rpi-hist", started_at="2026-03-01T00:00:00+00:00")
    )
    assert result.status == "accepted"
    pi3 = store.one("SELECT board_key FROM boards WHERE board_slug = 'raspberry-pi-3-model-b'")
    assert pi3 is not None
    types = _live_types(store)
    assert "FIRST_SEEN_BY_CLANK" in types
    assert "HISTORICAL_DISCOVERY" in types
    assert "NEW_BOARD" not in types
    novelty = store.one(
        "SELECT novelty_status FROM novelty_evidence WHERE entity_key = ?",
        (pi3["board_key"],),
    )
    assert novelty["novelty_status"] == "HISTORICAL"


def test_explicit_revision_is_distinct_under_same_board(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="rpi-base", started_at="2026-01-01T00:00:00+00:00"))
    pipeline.accept_run(collect_corpus("revision", run_id="rpi-rev", started_at="2026-04-01T00:00:00+00:00"))
    pi4 = store.all("SELECT board_key, board_slug FROM boards WHERE board_slug = 'raspberry-pi-4-model-b'")
    assert len(pi4) == 1
    revs = store.all("SELECT revision_token, revision_kind FROM board_revisions WHERE board_key = ?", (pi4[0]["board_key"],))
    tokens = {row["revision_token"] for row in revs}
    assert "UNKNOWN" in tokens
    assert "1-5" in tokens
    assert "BOARD_REVISION" in _event_types(store)


def test_malformed_html_fails_observably(pipeline: Pipeline, store: Store) -> None:
    result = pipeline.accept_run(
        collect_corpus("malformed", run_id="rpi-bad", started_at="2026-05-01T00:00:00+00:00")
    )
    assert result.status == "failed"
    assert store.count("boards") == 0
    assert store.count("events") == 0
    assert store.count("run_errors") == 1


def test_insufficient_new_item_does_not_create_board(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="rpi-base", started_at="2026-01-01T00:00:00+00:00"))
    before = store.count("boards")
    result = pipeline.accept_run(
        collect_corpus("insufficient", run_id="rpi-stub", started_at="2026-06-01T00:00:00+00:00")
    )
    assert result.status == "accepted"
    assert store.count("boards") == before
    assert "NOVELTY_UNRESOLVED" in _event_types(store)
    assert "NEW_BOARD" not in _live_types(store)
    slugs = {row["board_slug"] for row in store.all("SELECT board_slug FROM boards")}
    assert "raspberry-pi-6" not in slugs


def test_conflicting_soc_does_not_corrupt_existing_pi5(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="rpi-base", started_at="2026-01-01T00:00:00+00:00"))
    socs_before = store.count("socs")
    boards_before = store.count("boards")
    pipeline.accept_run(collect_corpus("conflict", run_id="rpi-conflict", started_at="2026-07-01T00:00:00+00:00"))
    assert store.count("boards") == boards_before
    assert store.count("socs") == socs_before
    assert "IDENTITY_ANOMALY" in _event_types(store)
    assert "NOVELTY_UNRESOLVED" in _event_types(store)
    pi5_soc = store.one(
        """
        SELECT s.marketing_name FROM socs s
        JOIN board_revisions r ON r.soc_key = s.soc_key
        JOIN boards b ON b.board_key = r.board_key
        WHERE b.board_slug = 'raspberry-pi-5'
        LIMIT 1
        """
    )
    assert pi5_soc["marketing_name"] == "BCM2712"


def test_cli_still_refuses_live_and_fixture_path_works(tmp_path: Path, capsys) -> None:
    assert main(["collect", "--live"]) == 2
    refused = json.loads(capsys.readouterr().out)
    assert refused["status"] == "refused"
    db = tmp_path / "rpi.db"
    assert main(["--db", str(db), "collect", "--source", "raspberry-pi-product", "--run-id", "cli-rpi"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "rpi-fixture"
    assert payload["delivery_eligible"] is False
    assert payload["promoted"] is False
    assert payload["result"]["baseline"] is True
    assert main(["--db", str(db), "source-intel", "--source", "raspberry-pi-product"]) == 0
    intel = json.loads(capsys.readouterr().out)
    assert intel["delivery_eligible"] is False
    assert intel["promotion_state"] == "EXPERIMENTAL"
    assert intel["enabled"] is False


def test_other_phase1_sources_remain_inert() -> None:
    from board_clank.collectors import InertVendorAdapter, get_adapter

    for vendor in ("orange-pi", "radxa", "banana-pi", "hardkernel-odroid", "pine64"):
        adapter = get_adapter(f"{vendor}-product")
        assert isinstance(adapter, InertVendorAdapter)
        assert adapter.live_network is False
