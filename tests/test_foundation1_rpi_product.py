from __future__ import annotations

import json
from pathlib import Path

from board_clank.cli import main
from board_clank.collectors.raspberry_pi import (
    RaspberryPiProductAdapter,
    _board_slug,
    _family_and_type,
    _is_in_scope_pip_category,
    collect_corpus,
    parse_product_html,
    raw_body_hash,
    semantic_evidence_hash,
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


def test_same_run_variant_enumeration_does_not_emit_board_field_changed(
    pipeline: Pipeline, store: Store
) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="rpi-base", started_at="2026-01-01T00:00:00+00:00"))
    field_changed = store.all("SELECT entity_kind, entity_key FROM events WHERE event_type = 'FIELD_CHANGED'")
    assert field_changed == []
    board_hashes = store.all(
        """
        SELECT entity_key, COUNT(DISTINCT content_hash) AS hashes
        FROM observation_occurrences
        WHERE entity_kind = 'BOARD'
        GROUP BY entity_key
        """
    )
    assert all(row["hashes"] == 1 for row in board_hashes)
    assert store.count("board_variants") == 42


def test_real_board_spec_change_still_emits_field_or_ports(pipeline: Pipeline, store: Store) -> None:
    from board_clank.collectors.raspberry_pi import collect_corpus
    from board_clank.models import CollectorRunRequest

    first = collect_corpus("baseline", run_id="rpi-base", started_at="2026-01-01T00:00:00+00:00")
    pipeline.accept_run(first)
    changed = next(obs for obs in first.observations if obs.board_slug == "raspberry-pi-5")
    changed.spec.ethernet = "2x 2.5g"
    changed.spec.usb = "changed-usb-matrix"
    request = CollectorRunRequest(
        run_id="rpi-ports-change",
        source_key="raspberry-pi-product",
        collector_key="raspberry-pi-product",
        started_at="2026-08-01T00:00:00+00:00",
        observations=[changed],
        fixture_scenario="rpi:ports-change",
    )
    pipeline.accept_run(request)
    live = _live_types(store)
    assert "PORTS_CHANGED" in live or "FIELD_CHANGED" in live
    assert "NEW_BOARD" not in live


def test_family_series_are_durable_and_not_one_board_one_family() -> None:
    pi5 = _family_and_type("Raspberry Pi 5")
    pi4 = _family_and_type("Raspberry Pi 4 Model B")
    pi3 = _family_and_type("Raspberry Pi 3 Model B")
    pi3plus = _family_and_type("Raspberry Pi 3 Model B+")
    zero = _family_and_type("Raspberry Pi Zero W")
    zero2 = _family_and_type("Raspberry Pi Zero 2 W")
    cm4 = _family_and_type("Raspberry Pi Compute Module 4")
    cm5 = _family_and_type("Raspberry Pi Compute Module 5")
    assert pi5[0] == "raspberry-pi-5"
    assert pi4[0] == "raspberry-pi-4"
    assert pi3[0] == pi3plus[0] == "raspberry-pi-3"
    assert zero[0] == zero2[0] == "raspberry-pi-zero"
    assert cm4[0] == cm5[0] == "compute-module"
    assert {pi5[0], pi4[0], zero2[0], cm4[0]} == {
        "raspberry-pi-5",
        "raspberry-pi-4",
        "raspberry-pi-zero",
        "compute-module",
    }


def test_family_identity_survives_replay_and_second_reference(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="rpi-fam-a", started_at="2026-01-01T00:00:00+00:00"))
    first = {
        row["board_slug"]: row["family_key"]
        for row in store.all(
            """
            SELECT b.board_slug, b.family_key
            FROM boards b
            """
        )
    }
    pipeline.accept_run(collect_corpus("baseline", run_id="rpi-fam-b", started_at="2026-01-02T00:00:00+00:00"))
    pipeline.accept_run(collect_corpus("second-reference", run_id="rpi-fam-c", started_at="2026-02-01T00:00:00+00:00"))
    second = {
        row["board_slug"]: row["family_key"]
        for row in store.all("SELECT board_slug, family_key FROM boards")
    }
    assert first["raspberry-pi-5"] == second["raspberry-pi-5"] == "raspberry-pi:raspberry-pi-5"
    assert first["raspberry-pi-4-model-b"] == "raspberry-pi:raspberry-pi-4"
    assert first["raspberry-pi-zero-2-w"] == "raspberry-pi:raspberry-pi-zero"
    assert first["raspberry-pi-compute-module-4"] == "raspberry-pi:compute-module"
    assert store.count("board_families") == 4


def test_baseline_new_board_is_audit_only_and_not_market_novelty(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="rpi-base", started_at="2026-01-01T00:00:00+00:00"))
    rows = store.all(
        """
        SELECT e.event_type, e.baseline_silent, e.payload_json, n.disposition
        FROM events e
        JOIN notifications n ON n.event_key = e.event_key
        WHERE e.event_type IN ('NEW_BOARD', 'NEW_VARIANT')
        """
    )
    assert rows
    assert all(row["baseline_silent"] == 1 for row in rows)
    assert all(row["disposition"] == "SUPPRESSED" for row in rows)
    assert all("baseline-inventory" in row["payload_json"] for row in rows)
    novelty = store.all("SELECT novelty_status FROM novelty_evidence")
    assert {row["novelty_status"] for row in novelty} <= {"EXISTING_PRODUCT", "HISTORICAL", "UNKNOWN"}
    assert "NEWLY_ANNOUNCED" not in {row["novelty_status"] for row in novelty}
    assert "NEWLY_AVAILABLE" not in {row["novelty_status"] for row in novelty}


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

    # Foundation 3A gave radxa a real adapter; the remaining vendors stay inert.
    for vendor in ("banana-pi", "hardkernel-odroid", "pine64"):
        adapter = get_adapter(f"{vendor}-product")
        assert isinstance(adapter, InertVendorAdapter)
        assert adapter.live_network is False


def test_pi3_wifi_controller_is_not_the_soc() -> None:
    html = Path("fixtures/rpi_product/html/pi3-wifi-controller.html").read_text(encoding="utf-8")
    drafts, info = parse_product_html(
        html,
        page_url="https://www.raspberrypi.com/products/raspberry-pi-3-model-b/",
        observed_at="2026-09-22T00:00:00+00:00",
    )
    assert info["status"] == "resolved"
    assert {item.soc_marketing_name for item in drafts} == {"BCM2837"}
    assert all("43438" not in item.soc_marketing_name for item in drafts)
    assert {item.board_slug for item in drafts} == {"raspberry-pi-3-model-b"}


def test_genuine_processor_conflict_still_fails_closed() -> None:
    html = Path("fixtures/rpi_product/html/conflicting-identity.html").read_text(encoding="utf-8")
    drafts, info = parse_product_html(
        html,
        page_url="https://www.raspberrypi.com/products/raspberry-pi-5/",
        observed_at="2026-07-01T00:00:00+00:00",
    )
    assert info["status"] == "identity-conflict"
    assert drafts[0].identity_conflict is True
    assert "BCM2712" in (info.get("soc_candidates") or drafts[0].raw_fields.get("soc_candidates") or [])


def test_zero2w_modern_template_resolves() -> None:
    html = Path("fixtures/rpi_product/html/zero2w-modern.html").read_text(encoding="utf-8")
    drafts, info = parse_product_html(
        html,
        page_url="https://www.raspberrypi.com/products/raspberry-pi-zero-2-w/",
        observed_at="2026-09-22T00:00:00+00:00",
    )
    assert info["status"] == "resolved"
    assert {item.board_slug for item in drafts} == {"raspberry-pi-zero-2-w"}
    assert {item.soc_marketing_name for item in drafts} == {"BCM2710A1"}
    assert {item.variant.ram for item in drafts} == {"512MB"}
    assert {item.family_slug for item in drafts} == {"raspberry-pi-zero"}


def test_compute_module_zero_identity_and_variants() -> None:
    html = Path("fixtures/rpi_product/html/compute-module-zero.html").read_text(encoding="utf-8")
    drafts, info = parse_product_html(
        html,
        page_url="https://www.raspberrypi.com/products/compute-module-zero/",
        observed_at="2026-09-22T00:00:00+00:00",
    )
    assert info["status"] == "resolved"
    assert {item.family_slug for item in drafts} == {"compute-module"}
    assert {item.board_slug for item in drafts} == {"raspberry-pi-compute-module-zero"}
    assert {item.soc_marketing_name for item in drafts} == {"RP3A0"}
    assert {item.soc_vendor for item in drafts} == {"raspberry-pi"}
    assert {item.variant.ram for item in drafts} == {"512MB"}
    assert {item.variant.storage for item in drafts} == {"none", "8GB", "16GB"}
    assert {item.variant.wireless for item in drafts} == {"none", "wifi"}


def test_cm4_and_cm5_share_family_and_stay_distinct(pipeline: Pipeline, store: Store) -> None:
    result = pipeline.accept_run(
        collect_corpus("expanded", run_id="rpi-expanded", started_at="2026-09-22T00:00:00+00:00")
    )
    assert result.status == "accepted"
    assert result.baseline is True
    slugs = {row["board_slug"] for row in store.all("SELECT board_slug FROM boards")}
    assert "raspberry-pi-compute-module-4" in slugs
    assert "raspberry-pi-compute-module-5" in slugs
    assert "raspberry-pi-compute-module-zero" in slugs
    families = {
        row["board_slug"]: row["family_key"]
        for row in store.all("SELECT board_slug, family_key FROM boards")
    }
    assert families["raspberry-pi-compute-module-4"] == families["raspberry-pi-compute-module-5"]
    assert families["raspberry-pi-compute-module-4"] == "raspberry-pi:compute-module"
    socs = {
        row["board_slug"]: row["marketing_name"]
        for row in store.all(
            """
            SELECT b.board_slug, s.marketing_name
            FROM boards b
            JOIN board_revisions r ON r.board_key = b.board_key
            JOIN socs s ON s.soc_key = r.soc_key
            """
        )
    }
    assert socs["raspberry-pi-compute-module-4"] == "BCM2711"
    assert socs["raspberry-pi-compute-module-5"] == "BCM2712"
    assert socs["raspberry-pi-compute-module-zero"] == "RP3A0"
    assert "NEW_BOARD" not in _live_types(store)
    assert _push_or_review(store) == []


def test_keyboard_computers_are_non_board_catalogue_items() -> None:
    for path, url in (
        ("fixtures/rpi_product/html/raspberry-pi-400.html", "https://www.raspberrypi.com/products/raspberry-pi-400/"),
        ("fixtures/rpi_product/html/raspberry-pi-500.html", "https://www.raspberrypi.com/products/raspberry-pi-500/"),
        ("fixtures/rpi_product/html/raspberry-pi-500-plus.html", "https://www.raspberrypi.com/products/raspberry-pi-500-plus/"),
    ):
        drafts, info = parse_product_html(
            Path(path).read_text(encoding="utf-8"),
            page_url=url,
            observed_at="2026-09-22T00:00:00+00:00",
        )
        assert drafts == []
        assert info["status"] == "ignored-non-computer"
        assert info["scope"] == "NON_BOARD_CATALOGUE_ITEM"


def test_pip_skus_are_references_not_boards(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="rpi-base", started_at="2026-01-01T00:00:00+00:00"))
    before = store.count("boards")
    html = Path("fixtures/rpi_product/html/pip-pi5.html").read_text(encoding="utf-8")
    drafts, info = parse_product_html(
        html,
        page_url="https://pip.raspberrypi.com/categories/892-raspberry-pi-5",
        observed_at="2026-09-22T00:00:00+00:00",
    )
    assert info["status"] == "resolved"
    assert "SC1110" not in info["skus"]
    assert "SC1111" in info["skus"]
    assert {item.board_slug for item in drafts} == {"raspberry-pi-5"}
    assert all(item.raw_fields.get("skus") == info["skus"] for item in drafts)
    request = collect_corpus("pip-identity", run_id="rpi-pip", started_at="2026-09-22T00:00:00+00:00")
    pipeline.accept_run(request)
    assert store.count("boards") == before
    slugs = {row["board_slug"] for row in store.all("SELECT board_slug FROM boards")}
    assert slugs == {
        "raspberry-pi-5",
        "raspberry-pi-4-model-b",
        "raspberry-pi-zero-2-w",
        "raspberry-pi-compute-module-4",
    }


def test_pip_computers_index_is_discovery_only() -> None:
    html = Path("fixtures/rpi_product/html/pip-computers.html").read_text(encoding="utf-8")
    drafts, info = parse_product_html(
        html,
        page_url="https://pip.raspberrypi.com/categories/505-computers",
        observed_at="2026-09-22T00:00:00+00:00",
    )
    assert drafts == []
    assert info["status"] == "lead-index"
    assert "DISCOVERY" in info["evidence_roles"]
    assert any("892-raspberry-pi-5" in href for href in info["lead_hrefs"])


def test_pip_pcn_listing_does_not_create_a_board() -> None:
    html = Path("fixtures/rpi_product/html/pip-pi4-pcn.html").read_text(encoding="utf-8")
    drafts, info = parse_product_html(
        html,
        page_url="https://pip.raspberrypi.com/categories/560-pcn",
        observed_at="2026-09-22T00:00:00+00:00",
    )
    assert drafts == []
    assert info["status"] == "pip-pcn"
    assert "CHANGE_EVIDENCE" in info["evidence_roles"]
    assert any("Rev 11" in title for title in info["pcns"])


def test_pcn_named_revision_is_recorded_under_existing_board(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="rpi-base", started_at="2026-01-01T00:00:00+00:00"))
    boards_before = store.count("boards")
    pipeline.accept_run(collect_corpus("pi4-pcn-rev", run_id="rpi-pcn", started_at="2026-09-22T00:00:00+00:00"))
    assert store.count("boards") == boards_before
    pi4 = store.one("SELECT board_key FROM boards WHERE board_slug = 'raspberry-pi-4-model-b'")
    tokens = {
        row["revision_token"]
        for row in store.all("SELECT revision_token FROM board_revisions WHERE board_key = ?", (pi4["board_key"],))
    }
    assert "11" in tokens
    assert "NEW_BOARD" not in _live_types(store)


def test_expanded_baseline_is_silent_and_replay_stable(pipeline: Pipeline, store: Store) -> None:
    first = collect_corpus("expanded", run_id="exp-a", started_at="2026-09-22T00:00:00+00:00")
    second = collect_corpus("expanded", run_id="exp-b", started_at="2026-09-23T00:00:00+00:00")
    r1 = pipeline.accept_run(first)
    boards = store.count("boards")
    variants = store.count("board_variants")
    r2 = pipeline.accept_run(second)
    assert r1.baseline is True
    assert r2.baseline is False
    assert store.count("boards") == boards
    assert store.count("board_variants") == variants
    assert "NEW_BOARD" not in _live_types(store)
    assert store.all("SELECT event_id FROM events WHERE event_type = 'FIELD_CHANGED'") == []
    assert _push_or_review(store) == []
    assert all(row["disposition"] == "SUPPRESSED" for row in store.all("SELECT disposition FROM notifications"))


def test_plus_models_keep_distinct_board_slugs() -> None:
    assert _board_slug("Raspberry Pi 3 Model B") == "raspberry-pi-3-model-b"
    assert _board_slug("Raspberry Pi 3 Model B+") == "raspberry-pi-3-model-b-plus"
    assert _board_slug("Raspberry Pi Compute Module 3+") == "raspberry-pi-compute-module-3-plus"


def test_pip_discovery_keeps_sbc_modules_and_rejects_keyboard_paths() -> None:
    assert _is_in_scope_pip_category("https://pip.raspberrypi.com/categories/892-raspberry-pi-5")
    assert _is_in_scope_pip_category("https://pip.raspberrypi.com/categories/634-raspberry-pi-compute-module-4")
    assert _is_in_scope_pip_category("https://pip.raspberrypi.com/categories/1286-raspberry-pi-compute-module-zero")
    assert not _is_in_scope_pip_category("https://pip.raspberrypi.com/categories/561-raspberry-pi-400")
    assert not _is_in_scope_pip_category("https://pip.raspberrypi.com/categories/1115-raspberry-pi-500")
    assert not _is_in_scope_pip_category("https://pip.raspberrypi.com/categories/756-raspberry-pi-compute-module-4-io-board")
    html = Path("fixtures/rpi_product/html/pip-computers.html").read_text(encoding="utf-8")
    _drafts, info = parse_product_html(
        html,
        page_url="https://pip.raspberrypi.com/categories/505-computers",
        observed_at="2026-09-22T00:00:00+00:00",
    )
    kept = [u for u in info["lead_hrefs"] if _is_in_scope_pip_category(u)]
    rejected = [u for u in info["lead_hrefs"] if not _is_in_scope_pip_category(u)]
    assert any("892-raspberry-pi-5" in u for u in kept)
    assert any("400" in u or "500" in u for u in rejected)


def test_csrf_tokens_change_raw_hash_not_semantic_or_identity() -> None:
    a = Path("fixtures/rpi_product/html/pip-pi5-csrf-a.html").read_text(encoding="utf-8")
    b = Path("fixtures/rpi_product/html/pip-pi5-csrf-b.html").read_text(encoding="utf-8")
    assert raw_body_hash(a) != raw_body_hash(b)
    assert semantic_evidence_hash(a) == semantic_evidence_hash(b)
    da, ia = parse_product_html(a, page_url="https://pip.raspberrypi.com/categories/892-raspberry-pi-5", observed_at="2026-09-22T00:00:00+00:00")
    db, ib = parse_product_html(b, page_url="https://pip.raspberrypi.com/categories/892-raspberry-pi-5", observed_at="2026-09-22T00:00:00+00:00")
    assert ia["status"] == ib["status"] == "resolved"
    assert {d.board_slug for d in da} == {d.board_slug for d in db} == {"raspberry-pi-5"}
    from board_clank.models import canonical_json

    assert [canonical_json(d.canonical_payload()) for d in da] == [canonical_json(d.canonical_payload()) for d in db]


def test_pip_identity_only_listing_admits_board_without_fabricating_spec() -> None:
    html = Path("fixtures/rpi_product/html/pip-cm5-identity.html").read_text(encoding="utf-8")
    drafts, info = parse_product_html(
        html,
        page_url="https://pip.raspberrypi.com/categories/944-raspberry-pi-compute-module-5",
        observed_at="2026-09-22T00:00:00+00:00",
    )
    assert info["status"] == "resolved-identity"
    assert {d.board_slug for d in drafts} == {"raspberry-pi-compute-module-5"}
    assert {d.family_slug for d in drafts} == {"compute-module"}
    assert {d.soc_marketing_name for d in drafts} == {"UNKNOWN"}


def test_pip_live_sim_baseline_silent_and_csrf_replay_has_no_field_changed(pipeline: Pipeline, store: Store) -> None:
    first = collect_corpus("pip-live-sim", run_id="pip-base", started_at="2026-09-22T12:00:00+00:00")
    second = collect_corpus("pip-live-sim", run_id="pip-replay", started_at="2026-09-22T13:00:00+00:00")
    r1 = pipeline.accept_run(first)
    boards = store.count("boards")
    r2 = pipeline.accept_run(second)
    assert r1.baseline is True
    assert r2.baseline is False
    slugs = {row["board_slug"] for row in store.all("SELECT board_slug FROM boards")}
    assert "raspberry-pi-5" in slugs
    assert "raspberry-pi-compute-module-5" in slugs
    assert store.count("boards") == boards
    assert "NEW_BOARD" not in _live_types(store)
    assert store.all("SELECT event_id FROM events WHERE event_type = 'FIELD_CHANGED'") == []
    assert _push_or_review(store) == []


def test_partial_unresolved_page_does_not_mutate_existing_board(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("pip-live-sim", run_id="pip-base", started_at="2026-09-22T12:00:00+00:00"))
    before = store.one("SELECT board_key FROM boards WHERE board_slug = 'raspberry-pi-5'")
    pipeline.accept_run(collect_corpus("insufficient", run_id="pip-stub", started_at="2026-09-22T14:00:00+00:00"))
    after = store.one("SELECT board_key FROM boards WHERE board_slug = 'raspberry-pi-5'")
    assert before["board_key"] == after["board_key"]
    slugs = {row["board_slug"] for row in store.all("SELECT board_slug FROM boards")}
    assert "raspberry-pi-6" not in slugs
    assert "NOVELTY_UNRESOLVED" in _event_types(store)
    assert "NEW_BOARD" not in _live_types(store)
