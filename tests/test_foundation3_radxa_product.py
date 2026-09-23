from __future__ import annotations

import json
from pathlib import Path

from board_clank.cli import main
from board_clank.collectors.base import CollectorError
from board_clank.collectors.orange_pi import collect_corpus as opi_collect_corpus
from board_clank.collectors.radxa import (
    RadxaProductAdapter,
    _assert_official_url,
    _board_slug,
    _category_and_model,
    _family_for_category,
    _is_in_scope_product_url,
    collect_corpus,
    parse_product_html,
    raw_body_hash,
    semantic_evidence_hash,
)
from board_clank.collectors.raspberry_pi import collect_corpus as rpi_collect_corpus
from board_clank.identity import board_key as make_board_key, soc_key as make_soc_key
from board_clank.pipeline import Pipeline
from board_clank.sources import assert_foundation_0_roster, load_sources
from board_clank.store import Store
from board_clank.taxonomy import BoardType, EventType

FIX = Path("fixtures/radxa_product/html")
BASE = "https://radxa.com/products"
OBS = "2026-09-22T00:00:00+00:00"


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

    adapter = RadxaProductAdapter()
    assert adapter.live_network is False
    assert adapter.experimental_live is False
    assert adapter.source_key == "radxa-product"
    assert adapter.supports_experimental_live is True
    assert isinstance(get_adapter("radxa-product"), RadxaProductAdapter)


def test_source_roster_keeps_radxa_registered_experimental_disabled() -> None:
    assert_foundation_0_roster()
    record = next(row for row in load_sources() if row.source_key == "radxa-product")
    assert record.vendor == "radxa"
    assert record.enabled is False
    assert record.promotion_state == "EXPERIMENTAL"
    assert record.registered_state == "REGISTERED"


# --------------------------------------------------------------------- discovery + URL policy


def test_index_is_discovery_leads_only() -> None:
    drafts, info = _parse("index.html", f"{BASE}/")
    assert drafts == []
    assert info["status"] == "lead-index"
    assert "DISCOVERY" in info["evidence_roles"]
    leads = info["lead_hrefs"]
    assert any(url.endswith("/rock5/5b/") for url in leads)
    assert any(url.endswith("/orion/o6/") for url in leads)
    # Accessories, IO boards, anchors, docs and wiki are not leads.
    assert not any("/accessories" in url for url in leads)
    assert not any("/io-board/" in url for url in leads)
    assert not any("#" in url for url in leads)
    assert not any("docs.radxa.com" in url or "wiki.radxa.com" in url for url in leads)
    # The site's duplicated products/products path bug normalizes away.
    assert not any("/products/products/" in url for url in leads)


def test_official_url_policy_refuses_docs_wiki_and_http() -> None:
    _assert_official_url(f"{BASE}/rock5/5b/")
    _assert_official_url(f"{BASE}/")
    for bad in (
        "https://docs.radxa.com/en/rock5/rock5b",
        "https://wiki.radxa.com/Home",
        "http://radxa.com/products/rock5/5b/",
        "https://radxa.com/products/accessories/emmc-module/",
        "https://example.com/products/rock5/5b/",
    ):
        try:
            _assert_official_url(bad)
        except CollectorError:
            continue
        raise AssertionError(f"url should have been refused: {bad}")


def test_scope_filter_rejects_accessories_and_carriers() -> None:
    assert _is_in_scope_product_url(f"{BASE}/rock5/5b/")
    assert _is_in_scope_product_url(f"{BASE}/zeros/zero3w/")
    assert not _is_in_scope_product_url(f"{BASE}/accessories/emmc-module/")
    assert not _is_in_scope_product_url(f"{BASE}/io-board/cm5-io-board/")
    assert not _is_in_scope_product_url("https://docs.radxa.com/en/")


# --------------------------------------------------------------------- identity + family


def test_plus_models_stay_distinct_boards() -> None:
    assert _board_slug("ROCK 5B") == "rock-5b"
    assert _board_slug("ROCK 5B+") == "rock-5b-plus"
    assert _board_slug("ROCK 5 ITX") == "rock-5-itx"
    assert _board_slug("ZERO 3W") == "zero-3w"
    assert _board_slug("ZERO 3E") == "zero-3e"
    assert _board_slug("ZERO 2 Pro") == "zero-2-pro"
    assert _board_slug("X4") == "x4"
    assert _board_slug("Orion O6") == "orion-o6"
    slugs = ["rock-5b", "rock-5b-plus", "rock-5-itx", "zero-3w", "zero-3e", "zero-2-pro", "x4", "orion-o6"]
    assert len(set(slugs)) == len(slugs)


def test_family_comes_from_first_party_category_not_name_surgery() -> None:
    assert _family_for_category("rock5")[0] == "rock-5"
    assert _family_for_category("zeros")[0] == "zero"
    assert _family_for_category("cm")[:2] == ("cm", "CM")
    assert _family_for_category("cm")[2] is BoardType.COMPUTE_MODULE
    assert _family_for_category("orion")[2] is BoardType.MINI_ITX_SBC
    assert _family_for_category("zeros")[2] is BoardType.ZERO_CLASS
    # X4's name carries no family token; the category supplies it.
    assert _category_and_model(f"{BASE}/x/x4/") == ("x", "x4")
    assert _family_for_category("x")[0] == "x"
    assert _category_and_model(f"{BASE}/rock5/5b/") == ("rock5", "5b")
    # The duplicated products/products path bug normalizes.
    assert _category_and_model(f"{BASE}/products/linkr/linkr") == ("linkr", "linkr")


def test_5bp_is_a_distinct_board_in_the_same_family(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="radxa-1", started_at="2026-09-22T01:00:00+00:00"))
    before = store.count("boards")
    pipeline.accept_run(collect_corpus("plus-model", run_id="radxa-bp", started_at="2026-09-22T02:00:00+00:00"))
    assert store.count("boards") == before + 1
    families = {
        row["board_slug"]: row["family_key"]
        for row in store.all("SELECT board_slug, family_key FROM boards WHERE board_slug LIKE 'rock-5%'")
    }
    assert families["rock-5b-plus"] == families["rock-5b"] == families["rock-5c"] == "radxa:rock-5"
    assert set(families) == {"rock-5b", "rock-5b-plus", "rock-5c", "rock-5a", "rock-5-itx"}


# --------------------------------------------------------------------- SoC model


def test_soc_extraction_across_four_vendors() -> None:
    cases = {
        "rock5_5b.html": (f"{BASE}/rock5/5b/", "rockchip", "RK3588"),
        "rock5_5a.html": (f"{BASE}/rock5/5a/", "rockchip", "RK3588S"),
        "zeros_zero3w.html": (f"{BASE}/zeros/zero3w/", "rockchip", "RK3566"),
        "zeros_zero2pro.html": (f"{BASE}/zeros/zero2pro/", "amlogic", "A311D"),
        "x_x4.html": (f"{BASE}/x/x4/", "intel", "N100"),
        "orion_o6.html": (f"{BASE}/orion/o6/", "cix", "P1"),
    }
    for fname, (url, vendor, model) in cases.items():
        drafts, info = _parse(fname, url)
        assert info["status"] == "resolved", fname
        assert {d.soc_vendor for d in drafts} == {vendor}, fname
        assert {d.soc_marketing_name for d in drafts} == {model}, fname
    # soc_keys stay vendor-scoped and distinct.
    assert make_soc_key("rockchip", "RK3588") != make_soc_key("rockchip", "RK3588S")
    assert make_soc_key("cix", "P1") == "cix:p1"


def test_companion_silicon_never_becomes_the_soc() -> None:
    # X4 names the RP2040 co-processor and 5B+ the RTL8852BE radio; both pages
    # resolve to their application processors.
    drafts, _ = _parse("x_x4.html", f"{BASE}/x/x4/")
    assert {d.soc_marketing_name for d in drafts} == {"N100"}
    drafts, _ = _parse("rock5_5bp.html", f"{BASE}/rock5/5bp/")
    assert {d.soc_marketing_name for d in drafts} == {"RK3588"}
    # A page naming only companion chips resolves no SoC and fails closed.
    html = """<html><head><meta name="description" content="Radxa trap board with RP2040 and RTL8852BE"></head>
    <body><h1>ROCK Trap</h1><div class="section"><h2>Peripherals</h2><p>RP2040 Co-Processor and RTL8852BE Wi-Fi module, Mali GPU, IMX214 camera.</p></div></body></html>"""
    drafts, info = parse_product_html(html, page_url=f"{BASE}/rock5/trap/", observed_at=OBS)
    assert info["status"] == "insufficient-evidence"
    assert {d.soc_marketing_name for d in drafts} == {"UNKNOWN"}


def test_cm5_two_soc_page_fails_closed() -> None:
    drafts, info = _parse("cm_cm5.html", f"{BASE}/cm/cm5/")
    assert info["status"] == "identity-conflict"
    # The page's own description says RK3588S while its spec table documents
    # CM5 (RK3588S2) and CM5 Lite (RK3582): genuine first-party inconsistency.
    assert set(info["soc_candidates"]) == {"RK3588S", "RK3588S2", "RK3582"}
    assert drafts[0].identity_conflict is True


def test_p1_alone_is_not_a_soc_without_cix_context() -> None:
    html = """<html><head><meta name="description" content="Radxa board P1 something"></head>
    <body><h1>ROCK P1 Trap</h1><div class="section"><h2>CPU</h2><p>P1 connector for power delivery.</p></div></body></html>"""
    drafts, info = parse_product_html(html, page_url=f"{BASE}/rock5/p1trap/", observed_at=OBS)
    assert info["status"] == "insufficient-evidence"
    assert {d.soc_marketing_name for d in drafts} == {"UNKNOWN"}


# --------------------------------------------------------------------- variants + revisions


def test_ram_and_emmc_matrices_are_variants_not_boards() -> None:
    drafts, info = _parse("rock5_5a.html", f"{BASE}/rock5/5a/")
    assert {d.variant.ram for d in drafts} == {"4GB", "8GB", "16GB", "32GB"}
    assert {d.board_slug for d in drafts} == {"rock-5a"}
    drafts, _ = _parse("zeros_zero2pro.html", f"{BASE}/zeros/zero2pro/")
    assert {d.variant.ram for d in drafts} == {"4GB"}
    assert {d.variant.storage for d in drafts} == {"16GB", "32GB", "64GB"}


def test_wireless_or_choice_is_a_variant_dimension() -> None:
    drafts, _ = _parse("x_x4.html", f"{BASE}/x/x4/")
    assert sorted({d.variant.wireless for d in drafts}) == ["wifi5", "wifi6"]
    drafts, _ = _parse("rock3_3c.html", f"{BASE}/rock3/3c/")
    assert sorted({d.variant.wireless for d in drafts}) == ["wifi5", "wifi6"]
    drafts, _ = _parse("zeros_zero3w.html", f"{BASE}/zeros/zero3w/")
    assert {d.variant.wireless for d in drafts} == {"wifi6"}


def test_5c_versioned_ram_types_are_revisions_not_board_churn(pipeline: Pipeline, store: Store) -> None:
    drafts, info = _parse("rock5_5c.html", f"{BASE}/rock5/5c/")
    assert info["status"] == "resolved"
    tokens = {(d.revision_kind.value, d.revision_token, d.spec.ram_type) for d in drafts}
    assert tokens == {("PCB", "1.1", "LPDDR4X"), ("PCB", "2.1", "LPDDR5")}
    # Replay stability: differing revision silicon must not churn BOARD scope.
    pipeline.accept_run(collect_corpus("baseline", run_id="radxa-1", started_at="2026-09-22T01:00:00+00:00"))
    events_before = store.count("events")
    pipeline.accept_run(collect_corpus("baseline", run_id="radxa-2", started_at="2026-09-22T02:00:00+00:00"))
    assert store.count("events") == events_before
    assert store.all("SELECT event_id FROM events WHERE event_type = 'FIELD_CHANGED'") == []
    board_hashes = store.all(
        """
        SELECT entity_key, COUNT(DISTINCT content_hash) AS hashes
        FROM observation_occurrences WHERE entity_kind = 'BOARD'
        GROUP BY entity_key
        """
    )
    assert all(row["hashes"] == 1 for row in board_hashes)


def test_zero_3w_and_3e_share_soc_but_stay_distinct(pipeline: Pipeline, store: Store) -> None:
    result = pipeline.accept_run(collect_corpus("baseline", run_id="radxa-1", started_at="2026-09-22T01:00:00+00:00"))
    assert result.baseline is True
    slugs = {row["board_slug"] for row in store.all("SELECT board_slug FROM boards")}
    assert {"zero-3w", "zero-3e"} <= slugs
    same_soc = store.all(
        """
        SELECT b.board_slug FROM boards b
        JOIN board_revisions r ON r.board_key = b.board_key
        JOIN socs s ON s.soc_key = r.soc_key
        WHERE s.soc_key = 'rockchip:rk3566'
        """
    )
    assert {row["board_slug"] for row in same_soc} >= {"zero-3w", "zero-3e", "rock-3c"}


# --------------------------------------------------------------------- scope + failure


def test_non_board_corpus_creates_no_boards(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="radxa-1", started_at="2026-09-22T01:00:00+00:00"))
    before = store.count("boards")
    result = pipeline.accept_run(collect_corpus("non-board", run_id="radxa-nb", started_at="2026-09-22T02:00:00+00:00"))
    assert result.status == "accepted"
    assert store.count("boards") == before
    for d in result.diagnostics["documents"]:
        assert d["status"] == "ignored-non-computer"
        assert d["scope"] == "NON_BOARD_CATALOGUE_ITEM"
    slugs = {row["board_slug"] for row in store.all("SELECT board_slug FROM boards")}
    assert "cm5-io-board" not in slugs and "wireless-module-a8" not in slugs and "emmc-module" not in slugs


def test_insufficient_teaser_fails_closed(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="radxa-1", started_at="2026-09-22T01:00:00+00:00"))
    before = store.count("boards")
    pipeline.accept_run(collect_corpus("insufficient", run_id="radxa-stub", started_at="2026-09-22T02:00:00+00:00"))
    assert store.count("boards") == before
    assert "NOVELTY_UNRESOLVED" in _event_types(store)
    assert "NEW_BOARD" not in _live_types(store)
    assert "rock-6" not in {row["board_slug"] for row in store.all("SELECT board_slug FROM boards")}


def test_malformed_html_fails_observably(pipeline: Pipeline, store: Store) -> None:
    result = pipeline.accept_run(collect_corpus("malformed", run_id="radxa-bad", started_at="2026-09-22T01:00:00+00:00"))
    assert result.status == "failed"
    assert store.count("boards") == 0
    assert store.count("events") == 0
    assert store.count("run_errors") == 1


# --------------------------------------------------------------------- baseline + replay + diagnostics


def test_baseline_is_silent_and_replay_is_stable(pipeline: Pipeline, store: Store) -> None:
    first = pipeline.accept_run(collect_corpus("baseline", run_id="radxa-1", started_at="2026-09-22T01:00:00+00:00"))
    assert first.status == "accepted"
    assert first.baseline is True
    boards = store.count("boards")
    variants = store.count("board_variants")
    assert boards == 10
    slugs = {row["board_slug"] for row in store.all("SELECT board_slug FROM boards")}
    assert slugs == {
        "rock-5b", "rock-5a", "rock-5c", "rock-5-itx", "rock-3c",
        "zero-3w", "zero-3e", "zero-2-pro", "x4", "orion-o6",
    }
    assert "NEW_BOARD" in _event_types(store)
    assert "BASELINE_ENTITY" in _event_types(store)
    assert "FIRST_SEEN_BY_CLANK" in _event_types(store)
    assert _push_or_review(store) == []
    assert all(row["disposition"] == "SUPPRESSED" for row in store.all("SELECT disposition FROM notifications"))
    novelty = {row["novelty_status"] for row in store.all("SELECT novelty_status FROM novelty_evidence")}
    assert novelty <= {"EXISTING_PRODUCT", "HISTORICAL", "UNKNOWN"}

    # Exact replay is a no-op; same evidence in a new run emits nothing.
    replay = pipeline.accept_run(collect_corpus("baseline", run_id="radxa-1", started_at="2026-09-22T01:00:00+00:00"))
    assert replay.replayed is True
    events_before = store.count("events")
    pipeline.accept_run(collect_corpus("baseline", run_id="radxa-2", started_at="2026-09-22T02:00:00+00:00"))
    assert store.count("events") == events_before
    assert store.count("boards") == boards
    assert store.count("board_variants") == variants
    assert store.all("SELECT event_id FROM events WHERE event_type = 'FIELD_CHANGED'") == []
    assert "NEW_BOARD" not in _live_types(store)


def test_conflict_diagnostics_are_idempotent_and_transitionable(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="radxa-1", started_at="2026-09-22T01:00:00+00:00"))
    pipeline.accept_run(collect_corpus("conflict", run_id="radxa-c1", started_at="2026-09-22T02:00:00+00:00"))
    anomaly = [dict(r) for r in store.all("SELECT event_type, payload_json FROM events WHERE event_type='IDENTITY_ANOMALY'")]
    assert len(anomaly) == 1
    pipeline.accept_run(collect_corpus("conflict", run_id="radxa-c2", started_at="2026-09-22T03:00:00+00:00"))
    assert len(store.all("SELECT event_id FROM events WHERE event_type='IDENTITY_ANOMALY'")) == 1
    # Unchanged condition stays durably present and sighted.
    conditions = [dict(r) for r in store.all(
        "SELECT status, open_occurrences, transition_count FROM diagnostic_conditions WHERE diagnostic_type='IDENTITY_ANOMALY'"
    )]
    assert conditions and conditions[0]["status"] == "OPEN"
    assert conditions[0]["open_occurrences"] == 2
    assert conditions[0]["transition_count"] == 0
    sightings = store.all("SELECT run_id FROM diagnostic_sightings")
    assert {row["run_id"] for row in sightings} == {"radxa-c1", "radxa-c2"}


def test_failed_run_does_not_close_conditions(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="radxa-1", started_at="2026-09-22T01:00:00+00:00"))
    pipeline.accept_run(collect_corpus("conflict", run_id="radxa-c1", started_at="2026-09-22T02:00:00+00:00"))
    pipeline.accept_run(collect_corpus("malformed", run_id="radxa-bad", started_at="2026-09-22T03:00:00+00:00"))
    row = store.one("SELECT status FROM diagnostic_conditions WHERE diagnostic_type='IDENTITY_ANOMALY'")
    assert row["status"] == "OPEN"


# --------------------------------------------------------------------- semantic hashing


def test_cloudflare_volatility_changes_raw_not_semantic_or_identity() -> None:
    a = (FIX / "rock5_5b.html").read_text(encoding="utf-8")
    b = a.replace("ray=abc123def456", "ray=zzz999yyy888")
    b = b.replace("/cdn-cgi/l/email-protection#ff8c9e939a8cbf8d9e9b879ed19c9092", "/cdn-cgi/l/email-protection#1122334455aabbccddeeff0011223344")
    assert raw_body_hash(a) != raw_body_hash(b)
    assert semantic_evidence_hash(a) == semantic_evidence_hash(b)
    da, ia = parse_product_html(a, page_url=f"{BASE}/rock5/5b/", observed_at=OBS)
    db, ib = parse_product_html(b, page_url=f"{BASE}/rock5/5b/", observed_at=OBS)
    assert ia["status"] == ib["status"] == "resolved"
    from board_clank.models import canonical_json

    assert [canonical_json(d.canonical_payload()) for d in da] == [canonical_json(d.canonical_payload()) for d in db]


# --------------------------------------------------------------------- cross-vendor isolation


def test_three_vendor_isolation_and_shared_socs(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(rpi_collect_corpus("baseline", run_id="rpi-b", started_at="2026-09-22T01:00:00+00:00"))
    pipeline.accept_run(opi_collect_corpus("baseline", run_id="opi-b", started_at="2026-09-22T02:00:00+00:00"))
    rpi_snapshot = [dict(r) for r in store.all("SELECT * FROM boards WHERE vendor_key='raspberry-pi'")]
    opi_snapshot = [dict(r) for r in store.all("SELECT * FROM boards WHERE vendor_key='orange-pi'")]
    pipeline.accept_run(collect_corpus("baseline", run_id="radxa-b", started_at="2026-09-22T03:00:00+00:00"))

    assert [dict(r) for r in store.all("SELECT * FROM boards WHERE vendor_key='raspberry-pi'")] == rpi_snapshot
    assert [dict(r) for r in store.all("SELECT * FROM boards WHERE vendor_key='orange-pi'")] == opi_snapshot
    vendors = {row["vendor_key"] for row in store.all("SELECT vendor_key FROM boards")}
    assert vendors == {"raspberry-pi", "orange-pi", "radxa"}

    # Family identities are vendor-scoped.
    families = {row["family_key"] for row in store.all("SELECT family_key FROM board_families")}
    assert "radxa:rock-5" in families and "orange-pi:orange-pi-5" in families and "raspberry-pi:raspberry-pi-5" in families

    # Common SoCs across vendors do not merge boards.
    shared = store.all(
        """
        SELECT r.soc_key, COUNT(DISTINCT b.vendor_key) AS vendors, COUNT(DISTINCT b.board_key) AS boards
        FROM board_revisions r JOIN boards b ON b.board_key = r.board_key
        GROUP BY r.soc_key HAVING vendors > 1
        """
    )
    shared_map = {row["soc_key"]: row["boards"] for row in shared}
    assert shared_map.get("rockchip:rk3588", 0) >= 3  # radxa 5b/5itx + orange-pi 5-plus/5-max
    assert shared_map.get("rockchip:rk3566", 0) >= 4  # radxa zero3/3c + orange-pi 3b/cm4
    overlap = store.all(
        """
        SELECT a.board_key FROM boards a JOIN boards b ON a.board_slug = b.board_slug
        WHERE a.vendor_key != b.vendor_key
        """
    )
    assert overlap == []
    assert store.all("SELECT event_id FROM events WHERE event_type = 'FIELD_CHANGED'") == []


def test_one_vendor_run_cannot_close_another_vendors_condition(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="radxa-b", started_at="2026-09-22T01:00:00+00:00"))
    pipeline.accept_run(collect_corpus("conflict", run_id="radxa-c", started_at="2026-09-22T02:00:00+00:00"))
    assert store.one("SELECT status FROM diagnostic_conditions WHERE source_key='radxa-product' AND status='OPEN'") is not None
    # An Orange Pi run without the radxa conflict must not close it.
    pipeline.accept_run(opi_collect_corpus("baseline", run_id="opi-b2", started_at="2026-09-22T03:00:00+00:00"))
    row = store.one("SELECT status FROM diagnostic_conditions WHERE source_key='radxa-product' AND status='OPEN'")
    assert row is not None
    assert store.all("SELECT event_id FROM events WHERE event_type='DIAGNOSTIC_RESOLVED'") == []


def test_board_key_vendor_scoping_prevents_slug_collisions() -> None:
    assert make_board_key("radxa", "zero") != make_board_key("orange-pi", "zero")
    assert make_board_key("radxa", "rock-5b") == "radxa:rock-5b"


# --------------------------------------------------------------------- CLI


def test_cli_offline_collect_works_for_radxa(tmp_path: Path, capsys) -> None:
    assert main(["collect", "--live"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "refused"
    db = tmp_path / "radxa.db"
    assert main(["--db", str(db), "collect", "--source", "radxa-product", "--run-id", "cli-radxa"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "corpus-fixture"
    assert payload["delivery_eligible"] is False
    assert payload["promoted"] is False
    assert payload["result"]["baseline"] is True
    assert main(["--db", str(db), "source-intel", "--source", "radxa-product"]) == 0
    intel = json.loads(capsys.readouterr().out)
    assert intel["enabled"] is False
    assert intel["promotion_state"] == "EXPERIMENTAL"
    assert intel["delivery_eligible"] is False
    # Sources without live adapters stay refused.
    assert main(["--db", str(db), "collect", "--source", "friendlyelec-product", "--experimental-live"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "refused"
