from __future__ import annotations

import json
from pathlib import Path

from board_clank.cli import main
from board_clank.collectors.orange_pi import (
    OrangePiProductAdapter,
    _assert_official_url,
    _board_slug,
    _canonical_page_url,
    _family_and_type,
    _is_in_scope_details_url,
    _normalize_name,
    collect_corpus,
    fetch_official_meta,
    parse_product_html,
    raw_body_hash,
    semantic_evidence_hash,
)
from board_clank.collectors.base import CollectorError
from board_clank.collectors.raspberry_pi import collect_corpus as rpi_collect_corpus
from board_clank.identity import board_key as make_board_key
from board_clank.identity import build_identity, family_key as make_family_key, soc_key as make_soc_key
from board_clank.pipeline import Pipeline
from board_clank.sources import assert_foundation_0_roster, load_sources
from board_clank.store import Store
from board_clank.taxonomy import BoardType, DeliveryDisposition, EventType
from board_clank.policy import disposition_for

FIX = Path("fixtures/orange_pi_product/html")
BASE_OBS = "2026-09-22T00:00:00+00:00"


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


def _parse(fname: str, url: str, observed_at: str = BASE_OBS):
    return parse_product_html(
        (FIX / fname).read_text(encoding="utf-8"),
        page_url=url,
        observed_at=observed_at,
    )


DETAILS = "http://www.orangepi.org/html/hardWare/computerAndMicrocontrollers/details"
INDEX = "http://www.orangepi.org/html/hardWare/computerAndMicrocontrollers/index.html"


# --------------------------------------------------------------------------- adapter + registration


def test_adapter_defaults_are_offline_and_experimental() -> None:
    adapter = OrangePiProductAdapter()
    assert adapter.live_network is False
    assert adapter.experimental_live is False
    assert adapter.source_key == "orange-pi-product"
    assert adapter.supports_experimental_live is True


def test_adapter_registered_for_orange_pi_product() -> None:
    from board_clank.collectors import get_adapter

    adapter = get_adapter("orange-pi-product")
    assert isinstance(adapter, OrangePiProductAdapter)
    assert adapter.live_network is False


def test_source_roster_keeps_orange_pi_registered_experimental_disabled() -> None:
    assert_foundation_0_roster()
    record = next(row for row in load_sources() if row.source_key == "orange-pi-product")
    assert record.vendor == "orange-pi"
    assert record.enabled is False
    assert record.promotion_state == "EXPERIMENTAL"
    assert record.registered_state == "REGISTERED"


# --------------------------------------------------------------------------- discovery


def test_index_page_is_discovery_leads_only() -> None:
    drafts, info = _parse("index.html", INDEX)
    assert drafts == []
    assert info["status"] == "lead-index"
    assert "DISCOVERY" in info["evidence_roles"]
    leads = info["lead_hrefs"]
    assert any(url.endswith("/Orange-Pi-5-Pro.html") for url in leads)
    assert any(url.endswith("/Orange-Pi-5-32GB.html") for url in leads)
    assert not any("Heat-sink" in url or "heat-sink" in url for url in leads)
    assert not any("Camera" in url or "camera" in url for url in leads)
    # The CN regional mirror link must not be followed.
    assert not any("orangepi.cn" in url for url in leads)


def test_details_scope_filter_rejects_accessories_and_uses_official_host_only() -> None:
    assert _is_in_scope_details_url(f"{DETAILS}/Orange-Pi-5.html")
    assert _is_in_scope_details_url(f"{DETAILS}/Orange-Pi-Zero-3.html")
    assert not _is_in_scope_details_url(f"{DETAILS}/Heat-sink-plus5.html")
    assert not _is_in_scope_details_url(f"{DETAILS}/13-MP-Camera-13850.html")
    assert not _is_in_scope_details_url(f"{DETAILS}/2W-expansion-board.html")
    assert not _is_in_scope_details_url(
        "http://www.orangepi.cn/html/hardWare/computerAndMicrocontrollers/details/Orange-Pi-5.html"
    )


def test_official_url_policy_allows_http_catalogue_and_refuses_mirrors() -> None:
    # The official Orange Pi catalogue is an HTTP-only first party.
    _assert_official_url(INDEX)
    _assert_official_url(f"{DETAILS}/Orange-Pi-5.html")
    for bad in (
        "http://www.orangepi.cn/html/hardWare/computerAndMicrocontrollers/index.html",
        "http://www.orangepi.org/html/aboutUs/index.html",
        "ftp://www.orangepi.org/html/hardWare/computerAndMicrocontrollers/index.html",
        "http://wiki.orangepi.org/index.php/Main_Page",
        "https://www.aliexpress.com/store/1100997172",
    ):
        try:
            _assert_official_url(bad)
        except CollectorError:
            continue
        raise AssertionError(f"url should have been refused: {bad}")


# --------------------------------------------------------------------------- identity + naming stress


def test_name_normalization_survives_source_spacing_variants() -> None:
    assert _normalize_name("Orange Pi Zero3") == ("Orange Pi Zero 3", "UNKNOWN")
    assert _normalize_name("OrangePi 6") == ("Orange Pi 6", "UNKNOWN")
    assert _normalize_name("OrangePi 5 Max") == ("Orange Pi 5 Max", "UNKNOWN")
    assert _normalize_name("Orange Pi 5(4GB/8GB/16GB)") == ("Orange Pi 5", "UNKNOWN")
    assert _normalize_name("Orange Pi 5(32GB)") == ("Orange Pi 5", "UNKNOWN")
    assert _normalize_name("Orange Pi R1 Plus LTS (With Metal Case)") == (
        "Orange Pi R1 Plus LTS",
        "with-metal-case",
    )


def test_board_slugs_stay_distinct_across_generations_and_suffixes() -> None:
    assert _board_slug("Orange Pi 5") == "orange-pi-5"
    assert _board_slug("Orange Pi 5 Plus") == "orange-pi-5-plus"
    assert _board_slug("Orange Pi 5 Pro") == "orange-pi-5-pro"
    assert _board_slug("Orange Pi 5 Max") == "orange-pi-5-max"
    assert _board_slug("Orange Pi 5B") == "orange-pi-5b"
    assert _board_slug("Orange Pi 3") == "orange-pi-3"
    assert _board_slug("Orange Pi 3B") == "orange-pi-3b"
    assert _board_slug("Orange Pi Zero 3") == "orange-pi-zero-3"
    assert _board_slug("Orange Pi Zero 2W") == "orange-pi-zero-2w"
    assert _board_slug("Orange Pi R1 Plus LTS") == "orange-pi-r1-plus-lts"
    names = [
        "Orange Pi 5", "Orange Pi 5 Plus", "Orange Pi 5 Pro", "Orange Pi 5 Max", "Orange Pi 5B",
        "Orange Pi 3", "Orange Pi 3B", "Orange Pi Zero 3", "Orange Pi Zero 2W", "Orange Pi Zero",
    ]
    slugs = [_board_slug(name) for name in names]
    assert len(set(slugs)) == len(slugs)


def test_storefront_url_canonicalization() -> None:
    assert _canonical_page_url(f"{DETAILS}/Orange-Pi-5-32GB.html").rsplit("/", 1)[-1] == "Orange-Pi-5.html"
    assert (
        _canonical_page_url(f"{DETAILS}/Orange-Pi-R1-Plus-LTS-With-Metal-Case.html").rsplit("/", 1)[-1].lower()
        == "orange-pi-r1-plus-lts.html"
    )
    assert _canonical_page_url(f"{DETAILS}/Orange-Pi-5.html") == f"{DETAILS}/Orange-Pi-5.html"


def test_families_share_generations_without_collapsing_boards() -> None:
    assert _family_and_type("Orange Pi 5")[0] == "orange-pi-5"
    assert _family_and_type("Orange Pi 5 Plus")[0] == "orange-pi-5"
    assert _family_and_type("Orange Pi 5 Pro")[0] == "orange-pi-5"
    assert _family_and_type("Orange Pi 5 Max")[0] == "orange-pi-5"
    assert _family_and_type("Orange Pi 3B")[0] == "orange-pi-3"
    assert _family_and_type("Orange Pi Zero 3")[0] == "orange-pi-zero"
    assert _family_and_type("Orange Pi Zero 3")[2] is BoardType.ZERO_CLASS
    assert _family_and_type("Orange Pi Zero 2W")[0] == "orange-pi-zero"
    assert _family_and_type("Orange Pi Compute Module 4")[2] is BoardType.COMPUTE_MODULE
    assert _family_and_type("Orange Pi R1 Plus LTS")[:2] == ("router", "Router")
    assert _family_and_type("Orange Pi R1 Plus LTS")[2] is BoardType.ROUTER_BOARD
    assert _family_and_type("Orange Pi 6")[0] == "orange-pi-6"


# --------------------------------------------------------------------------- parsing + SoC


def test_parser_5_pro_variants_share_one_board_with_revision() -> None:
    drafts, info = _parse("Orange-Pi-5-Pro.html", f"{DETAILS}/Orange-Pi-5-Pro.html")
    assert info["status"] == "resolved"
    assert {d.board_slug for d in drafts} == {"orange-pi-5-pro"}
    assert {d.variant.ram for d in drafts} == {"4GB", "8GB", "16GB"}
    assert {d.variant.storage for d in drafts} == {"none", "module"}
    assert {d.variant.wireless for d in drafts} == {"wifi"}
    assert len(drafts) == 6
    assert {d.soc_vendor for d in drafts} == {"rockchip"}
    assert {d.soc_marketing_name for d in drafts} == {"RK3588S"}
    assert {d.revision_kind.value for d in drafts} == {"PCB"}
    assert {d.revision_token for d in drafts} == {"1.2"}


def test_parser_5_ram_matrix_in_name_is_not_identity() -> None:
    drafts, info = _parse("Orange-Pi-5.html", f"{DETAILS}/Orange-Pi-5.html")
    assert info["status"] == "resolved"
    assert {d.board_slug for d in drafts} == {"orange-pi-5"}
    assert {d.variant.ram for d in drafts} == {"4GB", "8GB", "16GB"}
    assert {d.soc_marketing_name for d in drafts} == {"RK3588S"}


def test_parser_zero3_cpu_row_soc_and_half_gb_ram() -> None:
    drafts, info = _parse("Orange-Pi-Zero-3.html", f"{DETAILS}/Orange-Pi-Zero-3.html")
    assert info["status"] == "resolved"
    assert {d.board_slug for d in drafts} == {"orange-pi-zero-3"}
    assert {d.soc_vendor for d in drafts} == {"allwinner"}
    assert {d.soc_marketing_name for d in drafts} == {"H618"}
    assert {d.variant.ram for d in drafts} == {"1GB", "1.5GB", "2GB", "4GB"}
    assert {d.revision_token for d in drafts} == {"1.3"}


def test_parser_glued_soc_vendor_is_split() -> None:
    drafts, info = _parse("Orange-Pi-3B.html", f"{DETAILS}/Orange-Pi-3B.html")
    assert info["status"] == "resolved"
    assert {d.soc_vendor for d in drafts} == {"rockchip"}
    assert {d.soc_marketing_name for d in drafts} == {"RK3566"}
    assert {d.board_slug for d in drafts} == {"orange-pi-3b"}


def test_companion_silicon_never_becomes_the_soc() -> None:
    # 5 Pro page names PMU RK806-1, radio AP6256 and codec ES8388 in their own
    # rows; the SoC stays the Master Chip row's RK3588S.
    drafts, info = _parse("Orange-Pi-5-Pro.html", f"{DETAILS}/Orange-Pi-5-Pro.html")
    socs = {d.soc_marketing_name for d in drafts}
    assert socs == {"RK3588S"}
    # Zero 3 names AXP313A power management; the SoC comes from the CPU row.
    drafts, _ = _parse("Orange-Pi-Zero-3.html", f"{DETAILS}/Orange-Pi-Zero-3.html")
    assert {d.soc_marketing_name for d in drafts} == {"H618"}
    # A CPU row naming only companion chips resolves no SoC; the board can
    # still be admitted identity-only (UNKNOWN processor), never a fabricated
    # companion chip as the SoC.
    html = """<html><body>
    <h3>Orange Pi Companion Trap</h3>
    <div class="hardware-specification"><h3>Hardware specification</h3><table>
      <tr><td>CPU</td><td>RK806-1 power management, AP6256 Wi-Fi, YT8531C Ethernet PHY, ES8388 codec, AXP313A PMIC</td></tr>
      <tr><td>RAM</td><td>2GB LPDDR4</td></tr>
    </table></div></body></html>"""
    drafts, info = parse_product_html(html, page_url=f"{DETAILS}/Orange-Pi-Companion-Trap.html", observed_at=BASE_OBS)
    assert info["status"] == "resolved-identity"
    assert {d.soc_marketing_name for d in drafts} == {"UNKNOWN"}
    assert {d.board_slug for d in drafts} == {"orange-pi-companion-trap"}


def test_soc_keys_keep_similar_models_distinct() -> None:
    assert make_soc_key("Rockchip", "RK3588") == "rockchip:rk3588"
    assert make_soc_key("Rockchip", "RK3588S") == "rockchip:rk3588s"
    assert make_soc_key("Rockchip", "RK3588") != make_soc_key("Rockchip", "RK3588S")
    assert make_soc_key("Allwinner", "H618") == "allwinner:h618"


def test_conflicting_soc_page_fails_closed() -> None:
    drafts, info = _parse("Orange-Pi-6-Plus.html", f"{DETAILS}/Orange-Pi-6-Plus.html")
    assert info["status"] == "identity-conflict"
    assert drafts[0].identity_conflict is True
    assert drafts[0].evidence_insufficient is True
    assert set(info["soc_candidates"]) == {"CD8180", "CD8160"}


# --------------------------------------------------------------------------- scope: non-board items


def test_keyboard_computer_is_non_board_catalogue_item() -> None:
    drafts, info = _parse("orange-pi-800.html", f"{DETAILS}/orange-pi-800.html")
    assert drafts == []
    assert info["status"] == "ignored-non-computer"
    assert info["scope"] == "NON_BOARD_CATALOGUE_ITEM"
    assert info["reason"] == "integrated-consumer-computer-out-of-sbc-scope"


def test_carrier_boards_and_accessory_modules_are_non_board_items() -> None:
    for fname in (
        "Orange-Pi-CM4-Base-Board.html",
        "OrangePi-CM5-Base-Board.html",
        "Orange-Pi-emmc.html",
        "Orange-Pi-5-WiFi6-Module.html",
    ):
        drafts, info = _parse(fname, f"{DETAILS}/{fname}")
        assert drafts == [], fname
        assert info["status"] == "ignored-non-computer", fname
        assert info["scope"] == "NON_BOARD_CATALOGUE_ITEM", fname


def test_non_board_corpus_creates_no_boards(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="opi-base", started_at="2026-09-22T01:00:00+00:00"))
    before = store.count("boards")
    result = pipeline.accept_run(collect_corpus("non-board", run_id="opi-nonboard", started_at="2026-09-22T02:00:00+00:00"))
    assert result.status == "accepted"
    assert store.count("boards") == before
    slugs = {row["board_slug"] for row in store.all("SELECT board_slug FROM boards")}
    assert "orange-pi-800" not in slugs
    assert "orange-pi-cm4-base-board" not in slugs
    assert "orange-pi-cm5-base-board" not in slugs
    assert "orange-pi-emmc" not in slugs


# --------------------------------------------------------------------------- pipeline semantics


def test_baseline_is_silent_and_creates_durable_entities(pipeline: Pipeline, store: Store) -> None:
    request = collect_corpus("baseline", run_id="opi-baseline", started_at="2026-09-22T01:00:00+00:00")
    result = pipeline.accept_run(request)
    assert result.status == "accepted"
    assert result.baseline is True
    slugs = {row["board_slug"] for row in store.all("SELECT board_slug FROM boards")}
    assert slugs == {
        "orange-pi-5",
        "orange-pi-5-pro",
        "orange-pi-5-plus",
        "orange-pi-zero-3",
        "orange-pi-zero-2w",
        "orange-pi-3b",
        "orange-pi-compute-module-4",
    }
    assert store.count("vendors") == 1
    assert store.one("SELECT source_key FROM source_baselines")["source_key"] == "orange-pi-product"
    assert "NEW_BOARD" in _event_types(store)
    assert "BASELINE_ENTITY" in _event_types(store)
    assert "FIRST_SEEN_BY_CLANK" in _event_types(store)
    assert _push_or_review(store) == []
    assert all(row["disposition"] == "SUPPRESSED" for row in store.all("SELECT disposition FROM notifications"))
    novelty = {row["novelty_status"] for row in store.all("SELECT novelty_status FROM novelty_evidence")}
    assert novelty <= {"EXISTING_PRODUCT", "HISTORICAL", "UNKNOWN"}


def test_replay_same_run_is_noop(pipeline: Pipeline, store: Store) -> None:
    request = collect_corpus("baseline", run_id="opi-replay", started_at="2026-09-22T01:00:00+00:00")
    first = pipeline.accept_run(request)
    second = pipeline.accept_run(request)
    assert first.status == "accepted"
    assert second.replayed is True
    assert store.count("processed_run_receipts") == 1
    assert store.count("collector_runs") == 1


def test_replay_same_evidence_new_run_does_not_fork(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="opi-a", started_at="2026-09-22T01:00:00+00:00"))
    boards_before = store.count("boards")
    variants_before = store.count("board_variants")
    pipeline.accept_run(collect_corpus("baseline", run_id="opi-b", started_at="2026-09-23T00:00:00+00:00"))
    assert store.count("boards") == boards_before
    assert store.count("board_variants") == variants_before
    assert "NEW_BOARD" not in _live_types(store)
    assert "NEW_VARIANT" not in _live_types(store)


def test_config_storefront_page_is_a_variant_not_a_new_board(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="opi-base", started_at="2026-09-22T01:00:00+00:00"))
    boards_before = store.count("boards")
    variants_before = store.count("board_variants")
    result = pipeline.accept_run(
        collect_corpus("second-reference", run_id="opi-32gb", started_at="2026-09-22T02:00:00+00:00")
    )
    assert result.status == "accepted"
    assert store.count("boards") == boards_before
    assert store.count("board_variants") == variants_before + 1
    assert "NEW_BOARD" not in _live_types(store)
    live = _live_types(store)
    assert "NEW_VARIANT" in live
    assert "RAM_VARIANT_ADDED" in live
    five = store.one("SELECT board_key FROM boards WHERE board_slug = 'orange-pi-5'")
    rams = {
        row["ram"]
        for row in store.all("SELECT ram FROM board_variants WHERE board_key = ?", (five["board_key"],))
    }
    assert "32GB" in rams


def test_expanded_corpus_is_replay_stable_without_board_churn(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="opi-base", started_at="2026-09-22T01:00:00+00:00"))
    result = pipeline.accept_run(collect_corpus("expanded", run_id="opi-exp-1", started_at="2026-09-22T02:00:00+00:00"))
    assert result.status == "accepted"
    boards = store.count("boards")
    variants = store.count("board_variants")
    assert store.one("SELECT board_slug FROM boards WHERE board_slug = 'orange-pi-5-max'") is not None
    # The 32GB page joined the same run; the board did not fork.
    five_rows = store.all("SELECT board_key FROM boards WHERE board_slug = 'orange-pi-5'")
    assert len(five_rows) == 1
    # 5 Max is a genuine post-baseline discovery in this corpus: exactly one
    # live NEW_BOARD, and it is the only new board of the run.
    new_boards = store.all(
        "SELECT entity_key FROM events WHERE event_type = 'NEW_BOARD' AND baseline_silent = 0"
    )
    assert [row["entity_key"] for row in new_boards] == ["orange-pi:orange-pi-5-max"]
    events_after_first = store.count("events")
    pipeline.accept_run(collect_corpus("expanded", run_id="opi-exp-2", started_at="2026-09-22T03:00:00+00:00"))
    assert store.count("boards") == boards
    assert store.count("board_variants") == variants
    assert store.count("events") == events_after_first
    assert store.all("SELECT event_id FROM events WHERE event_type = 'FIELD_CHANGED'") == []


def test_same_run_variant_enumeration_does_not_emit_board_field_changed(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="opi-base", started_at="2026-09-22T01:00:00+00:00"))
    assert store.all("SELECT event_id FROM events WHERE event_type = 'FIELD_CHANGED'") == []
    board_hashes = store.all(
        """
        SELECT entity_key, COUNT(DISTINCT content_hash) AS hashes
        FROM observation_occurrences
        WHERE entity_kind = 'BOARD'
        GROUP BY entity_key
        """
    )
    assert all(row["hashes"] == 1 for row in board_hashes)


def test_bundle_page_shares_board_and_adds_bundle_variant(pipeline: Pipeline, store: Store) -> None:
    result = pipeline.accept_run(collect_corpus("bundle", run_id="opi-bundle", started_at="2026-09-22T01:00:00+00:00"))
    assert result.status == "accepted"
    rows = store.all("SELECT board_key FROM boards WHERE board_slug = 'orange-pi-r1-plus-lts'")
    assert len(rows) == 1
    variants = store.all(
        "SELECT bundle, ram FROM board_variants WHERE board_key = ?", (rows[0]["board_key"],)
    )
    assert {row["bundle"] for row in variants} == {"UNKNOWN", "with-metal-case"}
    assert {row["ram"] for row in variants} == {"1GB"}


def test_named_revision_then_absent_heading_reuses_identity(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="opi-base", started_at="2026-09-22T01:00:00+00:00"))
    pro = store.one("SELECT board_key FROM boards WHERE board_slug = 'orange-pi-5-pro'")
    revisions_before = store.all("SELECT revision_key FROM board_revisions WHERE board_key = ?", (pro["board_key"],))
    events_before = store.count("events")
    result = pipeline.accept_run(
        collect_corpus("revision-absent", run_id="opi-norev", started_at="2026-09-22T02:00:00+00:00")
    )
    assert result.status == "accepted"
    revisions_after = store.all("SELECT revision_key FROM board_revisions WHERE board_key = ?", (pro["board_key"],))
    assert {r["revision_key"] for r in revisions_after} == {r["revision_key"] for r in revisions_before}
    assert len(revisions_after) == 1
    assert store.count("events") == events_before
    tokens = {
        row["revision_token"]
        for row in store.all("SELECT revision_token FROM board_revisions WHERE board_key = ?", (pro["board_key"],))
    }
    assert tokens == {"1-2"}


def test_conflict_and_insufficient_fail_closed(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="opi-base", started_at="2026-09-22T01:00:00+00:00"))
    boards_before = store.count("boards")
    socs_before = store.count("socs")
    pipeline.accept_run(collect_corpus("conflict", run_id="opi-conflict", started_at="2026-09-22T02:00:00+00:00"))
    pipeline.accept_run(collect_corpus("insufficient", run_id="opi-stub", started_at="2026-09-22T03:00:00+00:00"))
    assert store.count("boards") == boards_before
    assert store.count("socs") == socs_before
    types = _event_types(store)
    assert "IDENTITY_ANOMALY" in types
    assert "NOVELTY_UNRESOLVED" in types
    slugs = {row["board_slug"] for row in store.all("SELECT board_slug FROM boards")}
    assert "orange-pi-6-plus" not in slugs
    assert "orange-pi-7" not in slugs


def test_malformed_html_fails_observably(pipeline: Pipeline, store: Store) -> None:
    result = pipeline.accept_run(collect_corpus("malformed", run_id="opi-bad", started_at="2026-09-22T01:00:00+00:00"))
    assert result.status == "failed"
    assert store.count("boards") == 0
    assert store.count("events") == 0
    assert store.count("run_errors") == 1


# --------------------------------------------------------------------------- families + references


def test_families_are_vendor_scoped_and_share_generations(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="opi-base", started_at="2026-09-22T01:00:00+00:00"))
    families = {
        row["board_slug"]: row["family_key"]
        for row in store.all("SELECT board_slug, family_key FROM boards")
    }
    assert families["orange-pi-5"] == families["orange-pi-5-plus"] == families["orange-pi-5-pro"]
    assert families["orange-pi-5"] == "orange-pi:orange-pi-5"
    assert families["orange-pi-zero-3"] == families["orange-pi-zero-2w"] == "orange-pi:orange-pi-zero"
    assert families["orange-pi-compute-module-4"] == "orange-pi:compute-module"
    assert families["orange-pi-3b"] == "orange-pi:orange-pi-3"
    assert store.count("board_families") == 4


def test_shared_soc_does_not_merge_boards(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="opi-base", started_at="2026-09-22T01:00:00+00:00"))
    # 3B and CM4 both run RK3566; the Zero boards share H618.
    boards_per_soc = {
        row["soc_key"]: row["n"]
        for row in store.all(
            """
            SELECT r.soc_key, COUNT(DISTINCT b.board_key) AS n
            FROM board_revisions r JOIN boards b ON b.board_key = r.board_key
            GROUP BY r.soc_key
            """
        )
    }
    assert boards_per_soc.get("rockchip:rk3566") == 2
    assert boards_per_soc.get("allwinner:h618") == 2
    assert boards_per_soc.get("rockchip:rk3588") == 1
    assert boards_per_soc.get("rockchip:rk3588s") == 2
    assert store.count("vendors") == 1


# --------------------------------------------------------------------------- cross-vendor isolation


def test_vendor_scoped_keys_prevent_cross_vendor_merges() -> None:
    # Identical slugs under different vendors stay different boards/families.
    assert make_board_key("orange-pi", "raspberry-pi-5") == "orange-pi:raspberry-pi-5"
    assert make_board_key("raspberry-pi", "raspberry-pi-5") == "raspberry-pi:raspberry-pi-5"
    assert make_board_key("orange-pi", "raspberry-pi-5") != make_board_key("raspberry-pi", "raspberry-pi-5")
    assert make_family_key("orange-pi", "zero") != make_family_key("raspberry-pi", "zero")
    assert build_identity(vendor="orange-pi", family="orange-pi-5", board_slug="x").vendor_key == "orange-pi"


def test_orange_pi_ingestion_leaves_raspberry_pi_corpus_unchanged(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(rpi_collect_corpus("baseline", run_id="rpi-base", started_at="2026-09-22T01:00:00+00:00"))
    rpi_snapshot = {
        table: [dict(row) for row in store.all(f"SELECT * FROM {table} WHERE vendor_key = 'raspberry-pi'" if table in {"vendors", "board_families", "boards"} else f"SELECT * FROM {table}")]
        for table in ("vendors", "board_families", "boards")
    }
    rpi_events = store.count("events")
    pipeline.accept_run(collect_corpus("baseline", run_id="opi-base", started_at="2026-09-22T02:00:00+00:00"))
    after = {
        table: [dict(row) for row in store.all(f"SELECT * FROM {table} WHERE vendor_key = 'raspberry-pi'" if table in {"vendors", "board_families", "boards"} else f"SELECT * FROM {table}")]
        for table in ("vendors", "board_families", "boards")
    }
    assert after == rpi_snapshot
    # New events exist only for the orange-pi source.
    new_events = store.all("SELECT source_key FROM events WHERE event_id > (SELECT MAX(event_id) FROM events WHERE source_key = 'raspberry-pi-product')")
    assert all(row["source_key"] == "orange-pi-product" for row in new_events)
    vendor_rows = {row["vendor_key"] for row in store.all("SELECT vendor_key FROM boards")}
    assert vendor_rows == {"raspberry-pi", "orange-pi"}
    # No board slug collisions between the vendors.
    overlapping = store.all(
        """
        SELECT a.board_key FROM boards a JOIN boards b ON a.board_slug = b.board_slug
        WHERE a.vendor_key != b.vendor_key
        """
    )
    assert overlapping == []
    assert rpi_events >= 1


def test_same_name_boards_across_vendors_stay_separate(pipeline: Pipeline, store: Store) -> None:
    # A synthetic draft with a Raspberry Pi board name under the Orange Pi
    # vendor must not touch the Raspberry Pi board.
    from board_clank.models import CollectorRunRequest, ObservationDraft
    from board_clank.identity import VariantDimensions

    pipeline.accept_run(rpi_collect_corpus("baseline", run_id="rpi-base", started_at="2026-09-22T01:00:00+00:00"))
    rpi_board = store.one("SELECT board_key FROM boards WHERE board_slug = 'raspberry-pi-5'")
    draft = ObservationDraft(
        source_key="orange-pi-product",
        plane="PRODUCT",
        observed_at="2026-09-22T02:00:00+00:00",
        vendor_key="orange-pi",
        vendor_name="Orange Pi",
        family_slug="orange-pi-5",
        family_name="Orange Pi 5",
        board_slug="raspberry-pi-5",
        marketing_name="Orange Pi Raspberry Pi 5",
        soc_vendor="rockchip",
        soc_marketing_name="RK3588S",
        variant=VariantDimensions(ram="8GB"),
    )
    pipeline.accept_run(
        CollectorRunRequest(
            run_id="opi-collision",
            source_key="orange-pi-product",
            collector_key="orange-pi-product",
            started_at="2026-09-22T02:00:00+00:00",
            observations=[draft],
        )
    )
    boards = store.all("SELECT board_key, vendor_key FROM boards WHERE board_slug = 'raspberry-pi-5'")
    assert len(boards) == 2
    assert {row["vendor_key"] for row in boards} == {"raspberry-pi", "orange-pi"}
    assert rpi_board["board_key"] == "raspberry-pi:raspberry-pi-5"
    rpi_variants = store.all(
        "SELECT variant_key FROM board_variants WHERE board_key = ?", (rpi_board["board_key"],)
    )
    assert rpi_variants  # untouched corpus still there


# --------------------------------------------------------------------------- hashing


def test_whitespace_and_volatile_tokens_change_raw_hash_not_semantic_or_identity() -> None:
    a = (FIX / "Orange-Pi-5.html").read_text(encoding="utf-8")
    b = a.replace("<head>", '<head><meta name="csrf-token" content="token-xyz-123">')
    b = b.replace("(8nm LP process)", "(8nm   LP    process)")
    assert raw_body_hash(a) != raw_body_hash(b)
    assert semantic_evidence_hash(a) == semantic_evidence_hash(b)
    da, ia = parse_product_html(a, page_url=f"{DETAILS}/Orange-Pi-5.html", observed_at=BASE_OBS)
    db, ib = parse_product_html(b, page_url=f"{DETAILS}/Orange-Pi-5.html", observed_at=BASE_OBS)
    assert ia["status"] == ib["status"] == "resolved"
    assert [d.board_slug for d in da] == [d.board_slug for d in db]
    from board_clank.models import canonical_json

    assert [canonical_json(d.canonical_payload()) for d in da] == [canonical_json(d.canonical_payload()) for d in db]


# --------------------------------------------------------------------------- CLI + governance


def test_cli_offline_collect_and_gates(tmp_path: Path, capsys) -> None:
    assert main(["collect", "--live"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "refused"
    db = tmp_path / "opi.db"
    assert (
        main(["--db", str(db), "collect", "--source", "orange-pi-product", "--run-id", "cli-opi"]) == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "corpus-fixture"
    assert payload["delivery_eligible"] is False
    assert payload["promoted"] is False
    assert payload["result"]["baseline"] is True
    assert main(["--db", str(db), "source-intel", "--source", "orange-pi-product"]) == 0
    intel = json.loads(capsys.readouterr().out)
    assert intel["delivery_eligible"] is False
    assert intel["promotion_state"] == "EXPERIMENTAL"
    assert intel["enabled"] is False
    # Experimental live stays refused for sources without a live adapter.
    assert (
        main(
            [
                "--db",
                str(db),
                "collect",
                "--source",
                "friendlyelec-product",
                "--experimental-live",
            ]
        )
        == 2
    )
    refused = json.loads(capsys.readouterr().out)
    assert refused["status"] == "refused"


def test_raspberry_pi_regression_suite_semantics_hold(pipeline: Pipeline, store: Store) -> None:
    # The reference adapter still behaves identically in a shared store.
    first = pipeline.accept_run(rpi_collect_corpus("baseline", run_id="rpi-a", started_at="2026-09-22T01:00:00+00:00"))
    second = pipeline.accept_run(rpi_collect_corpus("baseline", run_id="rpi-b", started_at="2026-09-22T02:00:00+00:00"))
    assert first.baseline is True
    assert second.baseline is False
    assert store.all("SELECT event_id FROM events WHERE event_type = 'FIELD_CHANGED'") == []
    assert _push_or_review(store) == []
    assert disposition_for(EventType.NEW_BOARD, baseline_silent=True) is DeliveryDisposition.SUPPRESSED
