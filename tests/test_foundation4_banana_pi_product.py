from __future__ import annotations

import json
from pathlib import Path

from board_clank.cli import main
from board_clank.collectors.banana_pi import (
    BananaPiProductAdapter,
    _assert_official_url,
    _board_slug,
    _family_slug,
    _soc_candidates,
    collect_corpus,
    parse_product_html,
    raw_body_hash,
    semantic_evidence_hash,
)
from board_clank.collectors.base import CollectorError
from board_clank.collectors.radxa import collect_corpus as radxa_collect_corpus
from board_clank.collectors.orange_pi import collect_corpus as opi_collect_corpus
from board_clank.collectors.raspberry_pi import collect_corpus as rpi_collect_corpus
from board_clank.pipeline import Pipeline
from board_clank.sources import assert_foundation_0_roster, load_sources
from board_clank.store import Store
from board_clank.taxonomy import BoardType, EventType

FIX = Path("fixtures/banana_pi_product/html")
BASE = "https://banana-pi.org/en"
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

    adapter = BananaPiProductAdapter()
    assert adapter.live_network is False
    assert adapter.experimental_live is False
    assert adapter.source_key == "banana-pi-product"
    assert adapter.supports_experimental_live is True
    assert isinstance(get_adapter("banana-pi-product"), BananaPiProductAdapter)


def test_source_roster_keeps_banana_pi_registered_experimental_disabled() -> None:
    assert_foundation_0_roster()
    record = next(row for row in load_sources() if row.source_key == "banana-pi-product")
    assert record.vendor == "banana-pi"
    assert record.enabled is False
    assert record.promotion_state == "EXPERIMENTAL"


# --------------------------------------------------------------------- discovery + URL policy


def test_index_is_discovery_leads_only() -> None:
    drafts, info = _parse("index-sbcs.html", f"{BASE}/banana-pi-sbcs/")
    assert drafts == []
    assert info["status"] == "lead-index"
    assert "DISCOVERY" in info["evidence_roles"]
    leads = info["lead_hrefs"]
    assert any(u.endswith("/banana-pi-sbcs/177.html") for u in leads)
    assert any(u.endswith("/bananapi-router/205.html") for u in leads)
    # Accessory, STEM, news, wiki and docs links are not board leads.
    assert not any("/banana-pi-ai-iot/" in u for u in leads)
    assert not any("/banana-pi-steam/" in u for u in leads)
    assert not any("wiki.banana-pi.org" in u or "docs.banana-pi.org" in u for u in leads)


def test_official_url_policy() -> None:
    _assert_official_url(f"{BASE}/banana-pi-sbcs/177.html")
    _assert_official_url(f"{BASE}/banana-pi-sbcs/")
    for bad in (
        "https://wiki.banana-pi.org/Main_Page",
        "https://docs.banana-pi.org/en/home",
        "http://banana-pi.org/en/banana-pi-sbcs/177.html",
        "https://banana-pi.org/en/bananapi-news/",
        "https://example.com/en/banana-pi-sbcs/177.html",
    ):
        try:
            _assert_official_url(bad)
        except CollectorError:
            continue
        raise AssertionError(f"url should have been refused: {bad}")


# --------------------------------------------------------------------- identity + family


def test_opaque_urls_mean_identity_comes_from_title() -> None:
    drafts, info = _parse("sbcs-177-bpi-m5-pro.html", f"{BASE}/banana-pi-sbcs/177.html")
    assert info["status"] == "resolved"
    assert {d.board_slug for d in drafts} == {"bpi-m5-pro"}
    assert {d.marketing_name for d in drafts} == {"BPI-M5 Pro"}


def test_board_slugs_stay_distinct() -> None:
    assert _board_slug("BPI-M5 Pro") == "bpi-m5-pro"
    assert _board_slug("BPI-M7S") == "bpi-m7s"
    assert _board_slug("BPI-M4 Berry") == "bpi-m4-berry"
    assert _board_slug("BPI-M4 Zero") == "bpi-m4-zero"
    assert _board_slug("BPI-M2+") == "bpi-m2-plus"
    assert _board_slug("BPI-CanMV-K230D-Zero") == "bpi-canmv-k230d-zero"
    assert _board_slug("BPI-R4 Pro") == "bpi-r4-pro"
    assert _board_slug("BPI-Forge1") == "bpi-forge1"


def test_family_shares_generations_without_collapsing_boards() -> None:
    assert _family_slug("BPI-M5 Pro") == "bpi-m5"
    assert _family_slug("BPI-M7S") == "bpi-m7"
    assert _family_slug("BPI-M7") == "bpi-m7"
    assert _family_slug("BPI-M4 Berry") == "bpi-m4"
    assert _family_slug("BPI-M4 Zero") == "bpi-m4"
    assert _family_slug("BPI-R4 Pro") == "bpi-r4"
    assert _family_slug("BPI-CanMV-K230D-Zero") == "bpi-canmv-k230d"
    assert _family_slug("BPI-F3") == "bpi-f3"
    assert _board_slug("BPI-M7") != _board_slug("BPI-M7S")
    assert _board_slug("BPI-M4 Berry") != _board_slug("BPI-M4 Zero")


# --------------------------------------------------------------------- SoC model


def test_soc_extraction_across_five_vendors() -> None:
    cases = {
        "sbcs-177-bpi-m5-pro.html": ("banana-pi-sbcs", "177", "rockchip", "RK3576"),
        "sbcs-211-bpi-m7s.html": ("banana-pi-sbcs", "211", "rockchip", "RK3588S"),
        "sbcs-169-bpi-m7.html": ("banana-pi-sbcs", "169", "rockchip", "RK3588"),
        "sbcs-213-bpi-m8.html": ("banana-pi-sbcs", "213", "allwinner", "A733"),
        "sbcs-167-bpi-m4-berry.html": ("banana-pi-sbcs", "167", "allwinner", "H618"),
        "sbcs-175-bpi-f3.html": ("banana-pi-sbcs", "175", "spacemit", "K1"),
        "sbcs-181-bpi-canmv-k230d-zero.html": ("banana-pi-sbcs", "181", "canaan", "K230D"),
        "router-205-bpi-r4-pro.html": ("bananapi-router", "205", "mediatek", "MT7988A"),
    }
    for fname, (cat, num, vendor, model) in cases.items():
        drafts, info = _parse(fname, f"{BASE}/{cat}/{num}.html")
        assert info["status"] == "resolved", fname
        assert {d.soc_vendor for d in drafts} == {vendor}, fname
        assert {d.soc_marketing_name for d in drafts} == {model}, fname


def test_title_furniture_never_leaks_other_products() -> None:
    # Every page carries BPI-R4 Pro / MT7615 / Forge1 names in furniture;
    # identity stays anchored to the page's own title.
    drafts, _ = _parse("sbcs-167-bpi-m4-berry.html", f"{BASE}/banana-pi-sbcs/167.html")
    assert {d.soc_marketing_name for d in drafts} == {"H618"}
    drafts, _ = _parse("sbcs-177-bpi-m5-pro.html", f"{BASE}/banana-pi-sbcs/177.html")
    assert {d.soc_marketing_name for d in drafts} == {"RK3576"}


def test_wifi_chipset_context_rejects_companion_radios() -> None:
    # OpenWrt One-style title: SoC followed by a wifi chipset.
    text = "OpenWrt One/AP-24.XY router board based on MediaTek MT7981B (Filogic 820) SoC and MediaTek MT7976C dual-band WiFi 6 chipset"
    assert [m for _v, m in _soc_candidates(text)] == ["MT7981B"]
    # A bare K1 without SpacemiT context is not admitted.
    assert _soc_candidates("Banana Pi board with K1 connector") == []
    # AP6275P / KEIIOT K038 / Triductor TR6560 never match the SoC shape.
    assert _soc_candidates("WIFI6 and BT5 AP6275P onboard KEIIOT K038 Triductor TR6560") == []


def test_multi_soc_option_page_fails_closed() -> None:
    drafts, info = _parse("sbcs-1-bpi-m2-zero.html", f"{BASE}/banana-pi-sbcs/1.html")
    assert info["status"] == "identity-conflict"
    assert set(info["soc_candidates"]) == {"H3", "H2+", "H5"}
    assert drafts[0].identity_conflict is True


# --------------------------------------------------------------------- variants


def test_ram_emmc_matrices_are_variants_not_boards() -> None:
    drafts, _ = _parse("sbcs-175-bpi-f3.html", f"{BASE}/banana-pi-sbcs/175.html")
    assert {d.board_slug for d in drafts} == {"bpi-f3"}
    assert sorted({d.variant.ram for d in drafts}) == ["16GB", "2GB", "4GB", "8GB"]
    assert sorted({d.variant.storage for d in drafts}) == ["16GB", "2GB", "4GB", "8GB"]
    assert len(drafts) == 16
    drafts, _ = _parse("sbcs-211-bpi-m7s.html", f"{BASE}/banana-pi-sbcs/211.html")
    assert len(drafts) == 15
    assert {d.spec.ram_type for d in drafts} == {"LPDDR4"}


def test_wifi_frequency_lists_never_become_ram() -> None:
    # "2.4G/5G WiFi" must not leak into RAM or storage options.
    drafts, _ = _parse("sbcs-167-bpi-m4-berry.html", f"{BASE}/banana-pi-sbcs/167.html")
    assert {d.variant.ram for d in drafts} == {"2GB"}
    assert {d.variant.storage for d in drafts} == {"8GB"}


def test_forge1_industrial_nand_shape() -> None:
    drafts, info = _parse("sbcs-199-bpi-forge1.html", f"{BASE}/banana-pi-sbcs/199.html")
    assert info["status"] == "resolved"
    assert {d.board_slug for d in drafts} == {"bpi-forge1"}
    assert {d.board_type for d in drafts} == {BoardType.INDUSTRIAL_SBC}
    assert {d.variant.ram for d in drafts} == {"512MB"}
    assert {d.variant.storage for d in drafts} == {"512MB-NAND"}
    assert {d.soc_marketing_name for d in drafts} == {"RK3506J"}


def test_r4_pro_is_a_router_board() -> None:
    drafts, _ = _parse("router-205-bpi-r4-pro.html", f"{BASE}/bananapi-router/205.html")
    assert {d.board_type for d in drafts} == {BoardType.ROUTER_BOARD}
    assert {d.variant.wireless for d in drafts} == {"wifi7"}


def test_risc_v_architecture_represented() -> None:
    drafts, _ = _parse("sbcs-175-bpi-f3.html", f"{BASE}/banana-pi-sbcs/175.html")
    assert {d.architecture.value for d in drafts} == {"RISCV"}
    drafts, _ = _parse("sbcs-181-bpi-canmv-k230d-zero.html", f"{BASE}/banana-pi-sbcs/181.html")
    assert {d.architecture.value for d in drafts} == {"RISCV"}


# --------------------------------------------------------------------- scope + failure


def test_non_board_corpus_creates_no_boards(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="bpi-1", started_at="2026-09-22T01:00:00+00:00"))
    before = store.count("boards")
    result = pipeline.accept_run(collect_corpus("non-board", run_id="bpi-nb", started_at="2026-09-22T02:00:00+00:00"))
    assert result.status == "accepted"
    assert store.count("boards") == before
    for d in result.diagnostics["documents"]:
        assert d["status"] == "ignored-non-computer"
        assert d["scope"] == "NON_BOARD_CATALOGUE_ITEM"
    slugs = {row["board_slug"] for row in store.all("SELECT board_slug FROM boards")}
    assert "bpi-mt7615" not in slugs and "bpi-bit" not in slugs


def test_insufficient_teaser_fails_closed(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="bpi-1", started_at="2026-09-22T01:00:00+00:00"))
    before = store.count("boards")
    pipeline.accept_run(collect_corpus("insufficient", run_id="bpi-stub", started_at="2026-09-22T02:00:00+00:00"))
    assert store.count("boards") == before
    assert "NOVELTY_UNRESOLVED" in _event_types(store)
    assert "NEW_BOARD" not in _live_types(store)
    assert "bpi-m9" not in {row["board_slug"] for row in store.all("SELECT board_slug FROM boards")}


def test_malformed_html_fails_observably(pipeline: Pipeline, store: Store) -> None:
    result = pipeline.accept_run(collect_corpus("malformed", run_id="bpi-bad", started_at="2026-09-22T01:00:00+00:00"))
    assert result.status == "failed"
    assert store.count("boards") == 0
    assert store.count("events") == 0
    assert store.count("run_errors") == 1


# --------------------------------------------------------------------- baseline + replay + diagnostics


def test_baseline_is_silent_and_replay_is_stable(pipeline: Pipeline, store: Store) -> None:
    first = pipeline.accept_run(collect_corpus("baseline", run_id="bpi-1", started_at="2026-09-22T01:00:00+00:00"))
    assert first.status == "accepted"
    assert first.baseline is True
    boards = store.count("boards")
    variants = store.count("board_variants")
    assert boards == 10
    slugs = {row["board_slug"] for row in store.all("SELECT board_slug FROM boards")}
    assert slugs == {
        "bpi-m5-pro", "bpi-m7s", "bpi-m7", "bpi-m8", "bpi-m4-berry", "bpi-m4-zero",
        "bpi-forge1", "bpi-f3", "bpi-canmv-k230d-zero", "bpi-r4-pro",
    }
    families = {row["family_key"] for row in store.all("SELECT family_key FROM boards")}
    assert "banana-pi:bpi-m7" in families and "banana-pi:bpi-m4" in families
    assert "NEW_BOARD" in _event_types(store)
    assert "BASELINE_ENTITY" in _event_types(store)
    assert _push_or_review(store) == []
    assert all(row["disposition"] == "SUPPRESSED" for row in store.all("SELECT disposition FROM notifications"))
    novelty = {row["novelty_status"] for row in store.all("SELECT novelty_status FROM novelty_evidence")}
    assert novelty <= {"EXISTING_PRODUCT", "HISTORICAL", "UNKNOWN"}

    replay = pipeline.accept_run(collect_corpus("baseline", run_id="bpi-1", started_at="2026-09-22T01:00:00+00:00"))
    assert replay.replayed is True
    events_before = store.count("events")
    pipeline.accept_run(collect_corpus("baseline", run_id="bpi-2", started_at="2026-09-22T02:00:00+00:00"))
    assert store.count("events") == events_before
    assert store.count("boards") == boards
    assert store.count("board_variants") == variants
    assert store.all("SELECT event_id FROM events WHERE event_type = 'FIELD_CHANGED'") == []
    assert "NEW_BOARD" not in _live_types(store)


def test_conflict_diagnostics_are_idempotent(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="bpi-1", started_at="2026-09-22T01:00:00+00:00"))
    pipeline.accept_run(collect_corpus("conflict", run_id="bpi-c1", started_at="2026-09-22T02:00:00+00:00"))
    assert len(store.all("SELECT event_id FROM events WHERE event_type='IDENTITY_ANOMALY'")) == 1
    pipeline.accept_run(collect_corpus("conflict", run_id="bpi-c2", started_at="2026-09-22T03:00:00+00:00"))
    assert len(store.all("SELECT event_id FROM events WHERE event_type='IDENTITY_ANOMALY'")) == 1
    conditions = [dict(r) for r in store.all(
        "SELECT status, open_occurrences, transition_count FROM diagnostic_conditions WHERE diagnostic_type='IDENTITY_ANOMALY'"
    )]
    assert conditions[0]["status"] == "OPEN"
    assert conditions[0]["open_occurrences"] == 2
    sightings = {row["run_id"] for row in store.all("SELECT run_id FROM diagnostic_sightings")}
    assert sightings == {"bpi-c1", "bpi-c2"}


# --------------------------------------------------------------------- semantic hashing


def test_cloudflare_volatility_changes_raw_not_semantic_or_identity() -> None:
    a = (FIX / "sbcs-177-bpi-m5-pro.html").read_text(encoding="utf-8")
    b = a.replace("ray=bpiaaa111bbb", "ray=zzz999yyy888")
    b = b.replace("/cdn-cgi/l/email-protection#addeccc1c8deedcfccc3ccc3cc80ddc483cec2c0", "/cdn-cgi/l/email-protection#1122334455aabbccddeeff00")
    assert raw_body_hash(a) != raw_body_hash(b)
    assert semantic_evidence_hash(a) == semantic_evidence_hash(b)
    da, ia = parse_product_html(a, page_url=f"{BASE}/banana-pi-sbcs/177.html", observed_at=OBS)
    db, ib = parse_product_html(b, page_url=f"{BASE}/banana-pi-sbcs/177.html", observed_at=OBS)
    assert ia["status"] == ib["status"] == "resolved"
    from board_clank.models import canonical_json

    assert [canonical_json(d.canonical_payload()) for d in da] == [canonical_json(d.canonical_payload()) for d in db]


# --------------------------------------------------------------------- cross-vendor isolation


def test_four_vendor_isolation_and_shared_socs(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(rpi_collect_corpus("baseline", run_id="rpi-b", started_at="2026-09-22T01:00:00+00:00"))
    pipeline.accept_run(opi_collect_corpus("baseline", run_id="opi-b", started_at="2026-09-22T02:00:00+00:00"))
    pipeline.accept_run(radxa_collect_corpus("baseline", run_id="radxa-b", started_at="2026-09-22T03:00:00+00:00"))
    snapshots = {
        vendor: [dict(r) for r in store.all("SELECT * FROM boards WHERE vendor_key=?", (vendor,))]
        for vendor in ("raspberry-pi", "orange-pi", "radxa")
    }
    pipeline.accept_run(collect_corpus("baseline", run_id="bpi-b", started_at="2026-09-22T04:00:00+00:00"))

    for vendor, snap in snapshots.items():
        assert [dict(r) for r in store.all("SELECT * FROM boards WHERE vendor_key=?", (vendor,))] == snap
    vendors = {row["vendor_key"] for row in store.all("SELECT vendor_key FROM boards")}
    assert vendors == {"raspberry-pi", "orange-pi", "radxa", "banana-pi"}

    # allwinner:h618 is shared by Orange Pi (zero 3/2 W) and Banana Pi
    # (M4 Berry/M4 Zero) without merging boards.
    shared = store.all(
        """
        SELECT r.soc_key, COUNT(DISTINCT b.vendor_key) AS vendors, COUNT(DISTINCT b.board_key) AS boards
        FROM board_revisions r JOIN boards b ON b.board_key = r.board_key
        GROUP BY r.soc_key HAVING vendors > 1
        """
    )
    shared_map = {row["soc_key"]: row["boards"] for row in shared}
    assert shared_map.get("allwinner:h618", 0) >= 3
    overlap = store.all(
        "SELECT a.board_key FROM boards a JOIN boards b ON a.board_slug = b.board_slug WHERE a.vendor_key != b.vendor_key"
    )
    assert overlap == []
    assert store.all("SELECT event_id FROM events WHERE event_type = 'FIELD_CHANGED'") == []


def test_one_vendor_run_cannot_close_another_vendors_condition(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="bpi-b", started_at="2026-09-22T01:00:00+00:00"))
    pipeline.accept_run(collect_corpus("conflict", run_id="bpi-c", started_at="2026-09-22T02:00:00+00:00"))
    pipeline.accept_run(opi_collect_corpus("baseline", run_id="opi-b2", started_at="2026-09-22T03:00:00+00:00"))
    row = store.one("SELECT status FROM diagnostic_conditions WHERE source_key='banana-pi-product' AND status='OPEN'")
    assert row is not None
    assert store.all("SELECT event_id FROM events WHERE event_type='DIAGNOSTIC_RESOLVED'") == []


# --------------------------------------------------------------------- CLI


def test_cli_offline_collect_works_for_banana_pi(tmp_path: Path, capsys) -> None:
    assert main(["collect", "--live"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "refused"
    db = tmp_path / "bpi.db"
    assert main(["--db", str(db), "collect", "--source", "banana-pi-product", "--run-id", "cli-bpi"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "corpus-fixture"
    assert payload["delivery_eligible"] is False
    assert payload["promoted"] is False
    assert payload["result"]["baseline"] is True
    assert main(["--db", str(db), "source-intel", "--source", "banana-pi-product"]) == 0
    intel = json.loads(capsys.readouterr().out)
    assert intel["enabled"] is False
    assert intel["promotion_state"] == "EXPERIMENTAL"
    assert main(["--db", str(db), "collect", "--source", "friendlyelec-product", "--experimental-live"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "refused"
