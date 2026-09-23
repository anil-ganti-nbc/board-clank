from __future__ import annotations

import json
from pathlib import Path

from board_clank.cli import main
from board_clank.collectors.base import CollectorError
from board_clank.collectors.banana_pi import collect_corpus as bpi_collect_corpus
from board_clank.collectors.odroid import (
    OdroidProductAdapter,
    _assert_official_url,
    _board_slug,
    _canonical_page_url,
    _family_slug,
    _model_and_config,
    collect_corpus,
    parse_product_html,
    raw_body_hash,
    semantic_evidence_hash,
)
from board_clank.collectors.orange_pi import collect_corpus as opi_collect_corpus
from board_clank.collectors.radxa import collect_corpus as radxa_collect_corpus
from board_clank.collectors.raspberry_pi import collect_corpus as rpi_collect_corpus
from board_clank.pipeline import Pipeline
from board_clank.sources import assert_foundation_0_roster, load_sources
from board_clank.store import Store
from board_clank.taxonomy import Availability, BoardType, EventType

FIX = Path("fixtures/odroid_product/html")
BASE = "https://www.hardkernel.com/shop"
OBS = "2026-09-23T00:00:00+00:00"


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
            SELECT e.event_type FROM events e
            JOIN notifications n ON n.event_key = e.event_key
            WHERE e.baseline_silent = 0 AND n.disposition IN ('PUSH', 'REVIEW')
            ORDER BY e.event_id
            """
        )
    ]


def _parse(fname: str, url: str, observed_at: str = OBS):
    return parse_product_html((FIX / fname).read_text(encoding="utf-8"), page_url=url, observed_at=observed_at)


# --------------------------------------------------------------------- registration


def test_adapter_defaults_and_registration() -> None:
    from board_clank.collectors import get_adapter

    adapter = OdroidProductAdapter()
    assert adapter.live_network is False
    assert adapter.experimental_live is False
    assert adapter.source_key == "hardkernel-odroid-product"
    assert adapter.supports_experimental_live is True
    assert isinstance(get_adapter("hardkernel-odroid-product"), OdroidProductAdapter)


def test_source_roster_keeps_odroid_registered_experimental_disabled() -> None:
    assert_foundation_0_roster()
    record = next(row for row in load_sources() if row.source_key == "hardkernel-odroid-product")
    assert record.vendor == "hardkernel-odroid"
    assert record.enabled is False
    assert record.promotion_state == "EXPERIMENTAL"


# --------------------------------------------------------------------- discovery + URL policy


def test_shop_index_is_discovery_leads_only() -> None:
    drafts, info = _parse("shop-index.html", f"{BASE}/")
    assert drafts == []
    assert info["status"] == "lead-index"
    assert "DISCOVERY" in info["evidence_roles"]
    leads = info["lead_hrefs"]
    assert any(u.endswith("/shop/odroid-h4/") for u in leads)
    assert any(u.endswith("/shop/odroid-go-ultra-clear-white/") for u in leads)
    # Non-product surfaces are not leads.
    assert not any("/cart/" in u or "/blog/" in u for u in leads)
    assert not any("wiki.odroid.com" in u or "forum.odroid.com" in u for u in leads)


def test_official_url_policy() -> None:
    _assert_official_url(f"{BASE}/odroid-h4/")
    _assert_official_url(SHOP := "https://www.hardkernel.com/shop/")
    for bad in (
        "https://odroid.com/",
        "https://wiki.odroid.com/Main_Page",
        "https://forum.odroid.com/",
        "http://www.hardkernel.com/shop/odroid-h4/",
        "https://www.hardkernel.com/blog/",
        "https://example.com/shop/odroid-h4/",
    ):
        try:
            _assert_official_url(bad)
        except CollectorError:
            continue
        raise AssertionError(f"url should have been refused: {bad}")


# --------------------------------------------------------------------- identity + naming


def test_h1_is_identity_truth_over_slug() -> None:
    # The N2+ page's slug omits the plus and carries a WooCommerce suffix.
    drafts, info = _parse("odroid-n2-plus.html", f"{BASE}/odroid-n2-with-2gbyte-ram-2/")
    assert info["status"] == "resolved"
    assert {d.board_slug for d in drafts} == {"odroid-n2-plus"}
    assert {d.marketing_name for d in drafts} == {"ODROID-N2+"}
    assert {d.family_slug for d in drafts} == {"n2"}


def test_model_config_extraction() -> None:
    assert _model_and_config("ODROID-M1 with 4GByte RAM") == ("ODROID-M1", "4GB", "UNKNOWN")
    assert _model_and_config("ODROID-M1S Lite 2GB") == ("ODROID-M1S Lite", "2GB", "UNKNOWN")
    assert _model_and_config("ODROID-C4 with 2GByte RAM") == ("ODROID-C4", "2GB", "UNKNOWN")
    assert _model_and_config("ODROID-GO ULTRA Dim Gray") == ("ODROID-GO ULTRA", "UNKNOWN", "dim-gray")
    assert _model_and_config("ODROID-H4") == ("ODROID-H4", "UNKNOWN", "UNKNOWN")


def test_suffixes_do_not_collapse_boards() -> None:
    assert _board_slug("ODROID-N2") == "odroid-n2"
    assert _board_slug("ODROID-N2+") == "odroid-n2-plus"
    assert _board_slug("ODROID-H4 PLUS") == "odroid-h4-plus"
    assert _board_slug("ODROID-H4 ULTRA") == "odroid-h4-ultra"
    assert _board_slug("ODROID-M1S Lite") == "odroid-m1s-lite"
    assert _board_slug("ODROID-M1S") == "odroid-m1s"
    assert _family_slug("ODROID-H4 PLUS") == "h4"
    assert _family_slug("ODROID-H4 ULTRA") == "h4"
    assert _family_slug("ODROID-N2+") == "n2"
    assert _family_slug("ODROID-M1S Lite") == "m1"
    assert _board_slug("ODROID-N2") != _board_slug("ODROID-N2+")
    assert _board_slug("ODROID-M1S") != _board_slug("ODROID-M1S Lite")


def test_canonical_storefront_urls() -> None:
    assert _canonical_page_url(f"{BASE}/odroid-m1-with-4gbyte-ram/").endswith("/shop/odroid-m1/")
    assert _canonical_page_url(f"{BASE}/odroid-c4with2gbyteram/").endswith("/shop/odroid-c4/")
    assert _canonical_page_url(f"{BASE}/odroid-h4/") == f"{BASE}/odroid-h4/"


# --------------------------------------------------------------------- SoC model


def test_soc_extraction_across_three_vendors_and_column_tables() -> None:
    cases = {
        "odroid-h4.html": ("odroid-h4", "intel", "N97"),
        "odroid-h4-plus.html": ("odroid-h4-plus", "intel", "N97"),
        "odroid-h4-ultra.html": ("odroid-h4-ultra", "intel", "N305"),
        "odroid-h5.html": ("odroid-h5", "intel", "N300"),
        "odroid-m1-with-4gbyte-ram.html": ("odroid-m1", "rockchip", "RK3568"),
        "odroid-m1s-with-4gbyte-ram.html": ("odroid-m1s", "rockchip", "RK3566"),
        "odroid-m2-with-16gbyte-ram.html": ("odroid-m2", "rockchip", "RK3588S2"),
        "odroid-c5.html": ("odroid-c5", "amlogic", "S905X5M"),
        "odroid-n2-plus.html": ("odroid-n2-plus", "amlogic", "S922X"),
        "odroid-hc4.html": ("odroid-hc4", "amlogic", "S905X3"),
    }
    for fname, (slug, vendor, model) in cases.items():
        drafts, info = _parse(fname, f"{BASE}/{fname[:-5]}/")
        assert info["status"] == "resolved", fname
        assert info["board_slug"] == slug, fname
        assert {d.soc_vendor for d in drafts} == {vendor}, fname
        assert {d.soc_marketing_name for d in drafts} == {model}, fname


def test_comparison_table_furniture_never_leaks_other_models() -> None:
    # H4 pages list six CPUs across the whole H-series; each page resolves
    # only its own column's processor.
    drafts, _ = _parse("odroid-h4.html", f"{BASE}/odroid-h4/")
    assert {d.soc_marketing_name for d in drafts} == {"N97"}
    drafts, _ = _parse("odroid-h5.html", f"{BASE}/odroid-h5/")
    assert {d.soc_marketing_name for d in drafts} == {"N300"}


def test_ethernet_transceiver_is_not_the_soc() -> None:
    drafts, _ = _parse("odroid-m1-with-4gbyte-ram.html", f"{BASE}/odroid-m1-with-4gbyte-ram/")
    assert {d.soc_marketing_name for d in drafts} == {"RK3568"}
    drafts, _ = _parse("odroid-hc4.html", f"{BASE}/odroid-hc4/")
    assert {d.soc_marketing_name for d in drafts} == {"S905X3"}


# --------------------------------------------------------------------- variants + lifecycle


def test_ram_matrices_and_fixed_configs() -> None:
    drafts, _ = _parse("odroid-m1-with-4gbyte-ram.html", f"{BASE}/odroid-m1-with-4gbyte-ram/")
    assert sorted({d.variant.ram for d in drafts}) == ["4GB", "8GB"]
    drafts, _ = _parse("odroid-m1s-lite-2gb.html", f"{BASE}/odroid-m1s-lite-2gb/")
    assert {d.variant.ram for d in drafts} == {"2GB"}
    assert {d.variant.storage for d in drafts} == {"32GB"}
    drafts, _ = _parse("odroid-n2-plus.html", f"{BASE}/odroid-n2-with-2gbyte-ram-2/")
    assert sorted({d.variant.ram for d in drafts}) == ["2GB", "4GB"]


def test_h_series_user_fitted_memory_stays_unknown() -> None:
    # No soldered memory: the board has no RAM matrix.
    drafts, _ = _parse("odroid-h4.html", f"{BASE}/odroid-h4/")
    assert {d.variant.ram for d in drafts} == {"UNKNOWN"}
    assert {d.spec.ram_type for d in drafts} == {"DDR5"}


def test_storage_modules_are_accessories_not_board_identity() -> None:
    drafts, _ = _parse("odroid-c5.html", f"{BASE}/odroid-c5/")
    assert {d.variant.storage for d in drafts} == {"none", "module"}
    drafts, _ = _parse("odroid-m1s-with-4gbyte-ram.html", f"{BASE}/odroid-m1s-with-4gbyte-ram/")
    assert {d.variant.storage for d in drafts} == {"64GB"}


def test_io_header_bundle_is_variant_not_new_board() -> None:
    assert _model_and_config("ODROID-M1S with 4GByte RAM + IO Header") == ("ODROID-M1S", "4GB", "io-header")
    assert _model_and_config("ODROID-M1S Lite 2GB + IO Header") == ("ODROID-M1S Lite", "2GB", "io-header")
    assert _canonical_page_url(f"{BASE}/odroid-m1s-with-4gbyte-ram-io-header/").endswith("/shop/odroid-m1s/")
    assert _canonical_page_url(f"{BASE}/odroid-m1s-lite-2gb-io-header/").endswith("/shop/odroid-m1s-lite/")


def test_shop_stock_status_is_availability_evidence() -> None:
    drafts, _ = _parse("odroid-h4.html", f"{BASE}/odroid-h4/")
    assert {d.availability for d in drafts} == {Availability.OUT_OF_STOCK}


def test_historical_discovery_is_not_market_new(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="od-1", started_at="2026-09-23T01:00:00+00:00"))
    pipeline.accept_run(collect_corpus("historical", run_id="od-h", started_at="2026-09-23T02:00:00+00:00"))
    live = _live_types(store)
    assert "HISTORICAL_DISCOVERY" in live
    assert "FIRST_SEEN_BY_CLANK" in live
    assert "NEW_BOARD" not in live
    novelty = {
        row["novelty_status"]
        for row in store.all("SELECT novelty_status FROM novelty_evidence")
    }
    assert novelty <= {"EXISTING_PRODUCT", "HISTORICAL", "UNKNOWN"}


# --------------------------------------------------------------------- scope + failure


def test_non_board_corpus_creates_no_boards(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="od-1", started_at="2026-09-23T01:00:00+00:00"))
    before = store.count("boards")
    result = pipeline.accept_run(collect_corpus("non-board", run_id="od-nb", started_at="2026-09-23T02:00:00+00:00"))
    assert result.status == "accepted"
    assert store.count("boards") == before
    for d in result.diagnostics["documents"]:
        assert d["status"] == "ignored-non-computer"
        assert d["scope"] == "NON_BOARD_CATALOGUE_ITEM"
    slugs = {row["board_slug"] for row in store.all("SELECT board_slug FROM boards")}
    assert "odroid-go-ultra" not in slugs and "odroid-hc4-p-kit" not in slugs


def test_insufficient_teaser_fails_closed(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="od-1", started_at="2026-09-23T01:00:00+00:00"))
    before = store.count("boards")
    pipeline.accept_run(collect_corpus("insufficient", run_id="od-stub", started_at="2026-09-23T02:00:00+00:00"))
    assert store.count("boards") == before
    assert "NOVELTY_UNRESOLVED" in _event_types(store)
    assert "NEW_BOARD" not in _live_types(store)


def test_malformed_html_fails_observably(pipeline: Pipeline, store: Store) -> None:
    result = pipeline.accept_run(collect_corpus("malformed", run_id="od-bad", started_at="2026-09-23T01:00:00+00:00"))
    assert result.status == "failed"
    assert store.count("boards") == 0
    assert store.count("events") == 0
    assert store.count("run_errors") == 1


# --------------------------------------------------------------------- baseline + replay + diagnostics


def test_baseline_is_silent_and_replay_is_stable(pipeline: Pipeline, store: Store) -> None:
    first = pipeline.accept_run(collect_corpus("baseline", run_id="od-1", started_at="2026-09-23T01:00:00+00:00"))
    assert first.status == "accepted"
    assert first.baseline is True
    boards = store.count("boards")
    variants = store.count("board_variants")
    assert boards == 9
    slugs = {row["board_slug"] for row in store.all("SELECT board_slug FROM boards")}
    assert slugs == {
        "odroid-h4", "odroid-h4-plus", "odroid-h4-ultra", "odroid-h5",
        "odroid-m1", "odroid-m1s", "odroid-m1s-lite", "odroid-m2", "odroid-c5",
    }
    families = {row["family_key"] for row in store.all("SELECT family_key FROM boards")}
    assert families == {
        "hardkernel-odroid:h4", "hardkernel-odroid:h5", "hardkernel-odroid:m1",
        "hardkernel-odroid:m2", "hardkernel-odroid:c5",
    }
    assert "NEW_BOARD" in _event_types(store)
    assert "BASELINE_ENTITY" in _event_types(store)
    assert _push_or_review(store) == []
    assert all(row["disposition"] == "SUPPRESSED" for row in store.all("SELECT disposition FROM notifications"))

    replay = pipeline.accept_run(collect_corpus("baseline", run_id="od-1", started_at="2026-09-23T01:00:00+00:00"))
    assert replay.replayed is True
    events_before = store.count("events")
    pipeline.accept_run(collect_corpus("baseline", run_id="od-2", started_at="2026-09-23T02:00:00+00:00"))
    assert store.count("events") == events_before
    assert store.count("boards") == boards
    assert store.count("board_variants") == variants
    assert store.all("SELECT event_id FROM events WHERE event_type = 'FIELD_CHANGED'") == []
    board_hashes = store.all(
        "SELECT entity_key, COUNT(DISTINCT content_hash) AS h FROM observation_occurrences "
        "WHERE entity_kind = 'BOARD' GROUP BY entity_key"
    )
    assert all(row["h"] == 1 for row in board_hashes)


def test_config_storefronts_do_not_fork_or_churn(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="od-1", started_at="2026-09-23T01:00:00+00:00"))
    boards_before = store.count("boards")
    pipeline.accept_run(collect_corpus("config-storefronts", run_id="od-cs-1", started_at="2026-09-23T02:00:00+00:00"))
    assert store.count("boards") == boards_before + 1  # only odroid-c4 is new
    events_snapshot = store.count("events")
    variants_snapshot = store.count("board_variants")
    pipeline.accept_run(collect_corpus("config-storefronts", run_id="od-cs-2", started_at="2026-09-23T03:00:00+00:00"))
    assert store.count("events") == events_snapshot
    assert store.count("board_variants") == variants_snapshot
    assert store.all("SELECT event_id FROM events WHERE event_type = 'FIELD_CHANGED'") == []
    c4 = store.one("SELECT board_key FROM boards WHERE board_slug = 'odroid-c4'")
    rams = {row["ram"] for row in store.all("SELECT ram FROM board_variants WHERE board_key = ?", (c4["board_key"],))}
    assert rams == {"2GB", "4GB"}


def test_unchanged_diagnostics_create_sightings_only(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="od-1", started_at="2026-09-23T01:00:00+00:00"))
    pipeline.accept_run(collect_corpus("insufficient", run_id="od-s1", started_at="2026-09-23T02:00:00+00:00"))
    assert len(store.all("SELECT event_id FROM events WHERE event_type='NOVELTY_UNRESOLVED'")) == 1
    pipeline.accept_run(collect_corpus("insufficient", run_id="od-s2", started_at="2026-09-23T03:00:00+00:00"))
    assert len(store.all("SELECT event_id FROM events WHERE event_type='NOVELTY_UNRESOLVED'")) == 1
    condition = store.one(
        "SELECT status, open_occurrences, transition_count FROM diagnostic_conditions WHERE diagnostic_type='NOVELTY_UNRESOLVED'"
    )
    assert condition["status"] == "OPEN"
    assert condition["open_occurrences"] == 2
    assert condition["transition_count"] == 0
    sightings = {row["run_id"] for row in store.all("SELECT run_id FROM diagnostic_sightings")}
    assert sightings == {"od-s1", "od-s2"}


# --------------------------------------------------------------------- semantic hashing


def test_wpnonce_volatility_changes_raw_not_semantic_or_identity() -> None:
    a = (FIX / "odroid-m1-with-4gbyte-ram.html").read_text(encoding="utf-8")
    b = a.replace("window.wpNonce='a1b2c3d4e5';", "window.wpNonce='f6e5d4c3b2';")
    b = b.replace("_wpnonce=c62a492d4e", "_wpnonce=9988776655")
    assert raw_body_hash(a) != raw_body_hash(b)
    assert semantic_evidence_hash(a) == semantic_evidence_hash(b)
    da, ia = parse_product_html(a, page_url=f"{BASE}/odroid-m1-with-4gbyte-ram/", observed_at=OBS)
    db, ib = parse_product_html(b, page_url=f"{BASE}/odroid-m1-with-4gbyte-ram/", observed_at=OBS)
    assert ia["status"] == ib["status"] == "resolved"
    from board_clank.models import canonical_json

    assert [canonical_json(d.canonical_payload()) for d in da] == [canonical_json(d.canonical_payload()) for d in db]


# --------------------------------------------------------------------- five-vendor isolation


def test_five_vendor_isolation_and_shared_socs(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(rpi_collect_corpus("baseline", run_id="rpi-b", started_at="2026-09-23T01:00:00+00:00"))
    pipeline.accept_run(opi_collect_corpus("baseline", run_id="opi-b", started_at="2026-09-23T02:00:00+00:00"))
    pipeline.accept_run(radxa_collect_corpus("baseline", run_id="radxa-b", started_at="2026-09-23T03:00:00+00:00"))
    pipeline.accept_run(bpi_collect_corpus("baseline", run_id="bpi-b", started_at="2026-09-23T04:00:00+00:00"))
    snapshots = {
        vendor: [dict(r) for r in store.all("SELECT * FROM boards WHERE vendor_key=?", (vendor,))]
        for vendor in ("raspberry-pi", "orange-pi", "radxa", "banana-pi")
    }
    pipeline.accept_run(collect_corpus("baseline", run_id="od-b", started_at="2026-09-23T05:00:00+00:00"))

    for vendor, snap in snapshots.items():
        assert [dict(r) for r in store.all("SELECT * FROM boards WHERE vendor_key=?", (vendor,))] == snap
    vendors = {row["vendor_key"] for row in store.all("SELECT vendor_key FROM boards")}
    assert vendors == {"raspberry-pi", "orange-pi", "radxa", "banana-pi", "hardkernel-odroid"}

    # rockchip:rk3588s is shared by Radxa (5A/5C) and ODROID (M2 uses
    # RK3588S2 — distinct); allwinner:h618 and rockchip:rk3566 predate this
    # vendor. Cross-vendor sharing stays reference-only.
    overlap = store.all(
        "SELECT a.board_key FROM boards a JOIN boards b ON a.board_slug = b.board_slug WHERE a.vendor_key != b.vendor_key"
    )
    assert overlap == []
    assert store.all("SELECT event_id FROM events WHERE event_type = 'FIELD_CHANGED'") == []


def test_one_vendor_run_cannot_close_another_vendors_condition(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="od-b", started_at="2026-09-23T01:00:00+00:00"))
    pipeline.accept_run(collect_corpus("insufficient", run_id="od-s", started_at="2026-09-23T02:00:00+00:00"))
    pipeline.accept_run(opi_collect_corpus("baseline", run_id="opi-b2", started_at="2026-09-23T03:00:00+00:00"))
    row = store.one("SELECT status FROM diagnostic_conditions WHERE source_key='hardkernel-odroid-product' AND status='OPEN'")
    assert row is not None
    assert store.all("SELECT event_id FROM events WHERE event_type='DIAGNOSTIC_RESOLVED'") == []


# --------------------------------------------------------------------- CLI


def test_cli_offline_collect_works_for_odroid(tmp_path: Path, capsys) -> None:
    assert main(["collect", "--live"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "refused"
    db = tmp_path / "odroid.db"
    assert main(["--db", str(db), "collect", "--source", "hardkernel-odroid-product", "--run-id", "cli-od"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "corpus-fixture"
    assert payload["delivery_eligible"] is False
    assert payload["promoted"] is False
    assert payload["result"]["baseline"] is True
    assert main(["--db", str(db), "source-intel", "--source", "hardkernel-odroid-product"]) == 0
    intel = json.loads(capsys.readouterr().out)
    assert intel["enabled"] is False
    assert intel["promotion_state"] == "EXPERIMENTAL"
    assert main(["--db", str(db), "collect", "--source", "pine64-product", "--experimental-live"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "refused"
