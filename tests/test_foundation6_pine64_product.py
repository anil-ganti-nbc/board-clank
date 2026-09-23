from __future__ import annotations

import json
from pathlib import Path

from board_clank.cli import main
from board_clank.collectors.base import CollectorError
from board_clank.collectors.banana_pi import collect_corpus as bpi_collect_corpus
from board_clank.collectors.odroid import collect_corpus as od_collect_corpus
from board_clank.collectors.orange_pi import collect_corpus as opi_collect_corpus
from board_clank.collectors.pine64 import (
    Pine64ProductAdapter,
    _assert_official_url,
    _board_slug,
    _family_slug,
    collect_corpus,
    parse_product_html,
    raw_body_hash,
    semantic_evidence_hash,
)
from board_clank.collectors.radxa import collect_corpus as radxa_collect_corpus
from board_clank.collectors.raspberry_pi import collect_corpus as rpi_collect_corpus
from board_clank.pipeline import Pipeline
from board_clank.sources import assert_foundation_0_roster, load_sources
from board_clank.store import Store
from board_clank.taxonomy import Availability, BoardType

FIX = Path("fixtures/pine64_product/html")
BASE = "https://pine64.org/devices"
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

    adapter = Pine64ProductAdapter()
    assert adapter.live_network is False
    assert adapter.experimental_live is False
    assert adapter.source_key == "pine64-product"
    assert adapter.supports_experimental_live is True
    assert isinstance(get_adapter("pine64-product"), Pine64ProductAdapter)


def test_all_six_phase1_vendors_have_real_adapters() -> None:
    from board_clank.collectors import (
        BananaPiProductAdapter,
        InertVendorAdapter,
        OdroidProductAdapter,
        OrangePiProductAdapter,
        Pine64ProductAdapter,
        RadxaProductAdapter,
        RaspberryPiProductAdapter,
        get_adapter,
    )
    from board_clank.taxonomy import PHASE1_VENDORS

    expected = {
        "raspberry-pi": RaspberryPiProductAdapter,
        "orange-pi": OrangePiProductAdapter,
        "radxa": RadxaProductAdapter,
        "banana-pi": BananaPiProductAdapter,
        "hardkernel-odroid": OdroidProductAdapter,
        "pine64": Pine64ProductAdapter,
    }
    for vendor in PHASE1_VENDORS:
        adapter = get_adapter(f"{vendor}-product")
        assert not isinstance(adapter, InertVendorAdapter), vendor
        assert isinstance(adapter, expected[vendor]), vendor
        assert adapter.live_network is False
        assert adapter.experimental_live is False


def test_source_roster_keeps_pine64_registered_experimental_disabled() -> None:
    assert_foundation_0_roster()
    record = next(row for row in load_sources() if row.source_key == "pine64-product")
    assert record.vendor == "pine64"
    assert record.enabled is False
    assert record.promotion_state == "EXPERIMENTAL"


# --------------------------------------------------------------------- discovery + scope


def test_devices_index_gates_scope_by_first_party_categories() -> None:
    drafts, info = _parse("devices-index.html", f"{BASE}/")
    assert drafts == []
    assert info["status"] == "lead-index"
    assert "DISCOVERY" in info["evidence_roles"]
    assert "SCOPE" in info["evidence_roles"]
    leads = info["lead_hrefs"]
    # SBC + compute module boxes are leads.
    assert any(u.endswith("/devices/star64/") for u in leads)
    assert any(u.endswith("/devices/quartz64-zero/") for u in leads)
    assert any(u.endswith("/devices/sopine/") for u in leads)
    # Laptops / phones / tablets / wearables / tools / IoT are NOT leads.
    for excluded in ("pinebook", "pinephone", "pinetab", "pinetime", "pinebuds",
                     "pinecil", "pinepower", "pinenut", "pinecube", "pinevoice", "pinecam"):
        assert not any(f"/devices/{excluded}" in u for u in leads), excluded
    # The index explicitly records the rejected categories as scope evidence.
    rejected = set(info["rejected_categories"])
    assert {"laptops", "phones-and-tablets", "wearables", "soldering-irons",
            "power-supplies", "iot", "ip-cameras", "smart-home"} <= rejected


def test_official_url_policy() -> None:
    _assert_official_url(f"{BASE}/star64/")
    _assert_official_url("https://pine64.org/devices/")
    for bad in (
        "https://store.pine64.org/",
        "https://pine64.com/",
        "https://wiki.pine64.org/wiki/Main_Page",
        "https://linux.pine64.org/",
        "http://pine64.org/devices/star64/",
        "https://pine64.org/news/",
        "https://example.com/devices/star64/",
    ):
        try:
            _assert_official_url(bad)
        except CollectorError:
            continue
        raise AssertionError(f"url should have been refused: {bad}")


# --------------------------------------------------------------------- identity + family


def test_board_slugs_and_families() -> None:
    assert _board_slug("Quartz64 Model A") == "quartz64-model-a"
    assert _board_slug("Quartz64 Model B") == "quartz64-model-b"
    assert _board_slug("Quartz64-Zero") == "quartz64-zero"
    assert _board_slug("PINE A64-LTS") == "pine-a64-lts"
    assert _family_slug("Quartz64 Model A") == "quartz"
    assert _family_slug("Quartz64-Zero") == "quartz"
    assert _family_slug("ROCK64") == "rock"
    assert _family_slug("ROCKPro64") == "rock"
    assert _family_slug("STAR64") == "star"
    assert _family_slug("PINE A64-LTS") == "pine-a64"
    assert _family_slug("SOPINE") == "sopine"
    assert _family_slug("SOQuartz") == "soquartz"
    # Model A/B stay distinct boards inside the quartz family.
    assert _board_slug("Quartz64 Model A") != _board_slug("Quartz64 Model B")


def test_soc_extraction_across_four_silicon_vendors() -> None:
    cases = {
        "star64.html": ("star64", "starfive", "JH-7110"),
        "quartz64_model_a.html": ("quartz64-model-a", "rockchip", "RK3566"),
        "quartz64-zero.html": ("quartz64-zero", "rockchip", "RK3566T"),
        "rockpro64.html": ("rockpro64", "rockchip", "RK3399"),
        "rock64.html": ("rock64", "rockchip", "RK3328"),
        "pine_a64.html": ("pine-a64", "allwinner", "A64"),
        "pine_a64-lts.html": ("pine-a64-lts", "allwinner", "R18"),
        "sopine.html": ("sopine", "allwinner", "A64"),
    }
    for fname, (slug, vendor, model) in cases.items():
        drafts, info = _parse(fname, f"{BASE}/{fname[:-5]}/")
        assert info["status"] == "resolved", fname
        assert info["board_slug"] == slug, fname
        assert {d.soc_vendor for d in drafts} == {vendor}, fname
        assert {d.soc_marketing_name for d in drafts} == {model}, fname


def test_a64_plus_is_an_option_not_a_board() -> None:
    # "PINE A64 and PINE A64+" is one board page; the plus is a configuration.
    drafts, info = _parse("pine_a64.html", f"{BASE}/pine_a64/")
    assert info["status"] == "resolved"
    assert {d.board_slug for d in drafts} == {"pine-a64"}
    assert {d.family_slug for d in drafts} == {"pine-a64"}


def test_lts_is_a_distinct_board_with_its_own_soc() -> None:
    drafts, _ = _parse("pine_a64-lts.html", f"{BASE}/pine_a64-lts/")
    assert {d.board_slug for d in drafts} == {"pine-a64-lts"}
    assert {d.soc_marketing_name for d in drafts} == {"R18"}


def test_ox64_multi_core_soc_is_one_soc_not_a_conflict() -> None:
    # The BL808 has heterogeneous cores; it is a single SoC identity.
    html = (FIX / "devices-index.html").read_text(encoding="utf-8")  # placeholder to satisfy FIX usage
    text = ("The Ox64 Single Board Computer features a Bouffalo Lab BL808 RISC-V SoC with "
            "single 64-bit 480MHz RV64 C906 core and two 32-bit 320MHz RV32 E907 + 150MHz E902 cores.")
    from board_clank.collectors.pine64 import _extract_soc

    vendor, model, candidates = _extract_soc(text)
    assert (vendor, model) == ("bouffalo", "BL808")
    assert candidates == ["BL808"]
    assert html  # FIX referenced


# --------------------------------------------------------------------- scope rejection


def test_non_board_products_are_rejected_explicitly(pipeline: Pipeline, store: Store) -> None:
    result = pipeline.accept_run(collect_corpus("scope-rejection", run_id="p64-scope", started_at="2026-09-23T01:00:00+00:00"))
    assert result.status == "accepted"
    for d in result.diagnostics["documents"]:
        if d["id"] == "soquartz":
            continue
        assert d["status"] == "ignored-non-computer", d["id"]
        assert d["scope"] == "NON_BOARD_CATALOGUE_ITEM", d["id"]
    slugs = {row["board_slug"] for row in store.all("SELECT board_slug FROM boards")}
    for excluded in ("pinephone", "pinebook-pro", "pinetime", "pinecil"):
        assert excluded not in slugs
    # SOQuartz is a real compute module and does get admitted.
    assert "soquartz" in slugs
    row = store.one("SELECT board_type, family_key FROM boards WHERE board_slug='soquartz'")
    assert row["board_type"] == "COMPUTE_MODULE"
    assert row["family_key"] == "pine64:soquartz"


def test_pinephone_naming_a_soc_still_rejected(pipeline: Pipeline, store: Store) -> None:
    # The PinePhone page names the Allwinner A64; SoC presence must not
    # defeat the category scope gate.
    pipeline.accept_run(collect_corpus("scope-rejection", run_id="p64-scope", started_at="2026-09-23T01:00:00+00:00"))
    assert "pinephone" not in {row["board_slug"] for row in store.all("SELECT board_slug FROM boards")}


# --------------------------------------------------------------------- variants + lifecycle


def test_ram_matrices_up_to_and_explicit() -> None:
    drafts, _ = _parse("quartz64_model_a.html", f"{BASE}/quartz64_model_a/")
    assert sorted({d.variant.ram for d in drafts}) == ["2GB", "4GB", "8GB"]
    assert {d.variant.storage for d in drafts} == {"none", "128GB"}
    assert {d.variant.wireless for d in drafts} == {"none", "wifi"}  # optional module
    drafts, _ = _parse("quartz64_model_b.html", f"{BASE}/quartz64_model_b/")
    assert {d.variant.wireless for d in drafts} == {"wifi"}  # built-in
    drafts, _ = _parse("quartz64-zero.html", f"{BASE}/quartz64-zero/")
    assert {d.variant.ram for d in drafts} == {"1GB"}
    drafts, _ = _parse("star64.html", f"{BASE}/star64/")
    assert {d.variant.ram for d in drafts} == {"8GB"}
    assert {d.variant.storage for d in drafts} == {"none", "128GB"}


def test_emmc_modules_are_separately_purchased_accessories() -> None:
    # "optional eMMC module (up to 128 GB)" → storage dimension none/128GB;
    # the module itself is never a board.
    drafts, _ = _parse("rockpro64.html", f"{BASE}/rockpro64/")
    assert {d.variant.storage for d in drafts} == {"none", "module"}
    assert "rockpro64-emmc" not in {d.board_slug for d in drafts}


def test_sopine_is_a_compute_module() -> None:
    drafts, _ = _parse("sopine.html", f"{BASE}/sopine/")
    assert {d.board_type for d in drafts} == {BoardType.COMPUTE_MODULE}
    assert {d.variant.ram for d in drafts} == {"2GB"}


def test_historical_first_sighting_is_not_market_new(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="p64-1", started_at="2026-09-23T01:00:00+00:00"))
    before = store.count("boards")
    pipeline.accept_run(collect_corpus("historical", run_id="p64-h", started_at="2026-09-23T02:00:00+00:00"))
    live = _live_types(store)
    assert "HISTORICAL_DISCOVERY" in live
    assert "FIRST_SEEN_BY_CLANK" in live
    # The late-discovered historical Ox64 is born, but never market-new.
    assert "NEW_BOARD" not in live
    assert store.count("boards") == before + 1
    ox = store.one("SELECT novelty_status FROM novelty_evidence WHERE entity_key='pine64:ox64'")
    assert ox["novelty_status"] == "HISTORICAL"
    novelty = {row["novelty_status"] for row in store.all("SELECT novelty_status FROM novelty_evidence")}
    assert novelty <= {"EXISTING_PRODUCT", "HISTORICAL", "UNKNOWN"}


# --------------------------------------------------------------------- failure


def test_insufficient_teaser_fails_closed(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="p64-1", started_at="2026-09-23T01:00:00+00:00"))
    before = store.count("boards")
    pipeline.accept_run(collect_corpus("insufficient", run_id="p64-stub", started_at="2026-09-23T02:00:00+00:00"))
    assert store.count("boards") == before
    assert "NOVELTY_UNRESOLVED" in _event_types(store)
    assert "pine-x" not in {row["board_slug"] for row in store.all("SELECT board_slug FROM boards")}


def test_malformed_html_fails_observably(pipeline: Pipeline, store: Store) -> None:
    result = pipeline.accept_run(collect_corpus("malformed", run_id="p64-bad", started_at="2026-09-23T01:00:00+00:00"))
    assert result.status == "failed"
    assert store.count("boards") == 0
    assert store.count("events") == 0
    assert store.count("run_errors") == 1


# --------------------------------------------------------------------- baseline + replay + diagnostics


def test_baseline_is_silent_and_replay_is_stable(pipeline: Pipeline, store: Store) -> None:
    first = pipeline.accept_run(collect_corpus("baseline", run_id="p64-1", started_at="2026-09-23T01:00:00+00:00"))
    assert first.status == "accepted"
    assert first.baseline is True
    boards = store.count("boards")
    variants = store.count("board_variants")
    assert boards == 9
    slugs = {row["board_slug"] for row in store.all("SELECT board_slug FROM boards")}
    assert slugs == {
        "star64", "quartz64-model-a", "quartz64-model-b", "quartz64-zero",
        "rockpro64", "rock64", "pine-a64", "pine-a64-lts", "sopine",
    }
    assert "NEW_BOARD" in _event_types(store)
    assert "BASELINE_ENTITY" in _event_types(store)
    assert _push_or_review(store) == []
    assert all(row["disposition"] == "SUPPRESSED" for row in store.all("SELECT disposition FROM notifications"))

    replay = pipeline.accept_run(collect_corpus("baseline", run_id="p64-1", started_at="2026-09-23T01:00:00+00:00"))
    assert replay.replayed is True
    events_before = store.count("events")
    pipeline.accept_run(collect_corpus("baseline", run_id="p64-2", started_at="2026-09-23T02:00:00+00:00"))
    assert store.count("events") == events_before
    assert store.count("boards") == boards
    assert store.count("board_variants") == variants
    assert store.all("SELECT event_id FROM events WHERE event_type = 'FIELD_CHANGED'") == []
    board_hashes = store.all(
        "SELECT entity_key, COUNT(DISTINCT content_hash) AS h FROM observation_occurrences "
        "WHERE entity_kind = 'BOARD' GROUP BY entity_key"
    )
    assert all(row["h"] == 1 for row in board_hashes)


def test_unchanged_diagnostics_create_sightings_only(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="p64-1", started_at="2026-09-23T01:00:00+00:00"))
    pipeline.accept_run(collect_corpus("insufficient", run_id="p64-s1", started_at="2026-09-23T02:00:00+00:00"))
    assert len(store.all("SELECT event_id FROM events WHERE event_type='NOVELTY_UNRESOLVED'")) == 1
    pipeline.accept_run(collect_corpus("insufficient", run_id="p64-s2", started_at="2026-09-23T03:00:00+00:00"))
    assert len(store.all("SELECT event_id FROM events WHERE event_type='NOVELTY_UNRESOLVED'")) == 1
    condition = store.one(
        "SELECT status, open_occurrences, transition_count FROM diagnostic_conditions WHERE diagnostic_type='NOVELTY_UNRESOLVED'"
    )
    assert condition["status"] == "OPEN"
    assert condition["open_occurrences"] == 2
    assert condition["transition_count"] == 0
    sightings = {row["run_id"] for row in store.all("SELECT run_id FROM diagnostic_sightings")}
    assert sightings == {"p64-s1", "p64-s2"}


# --------------------------------------------------------------------- semantic hashing


def test_static_pages_semantic_hash_is_whitespace_stable() -> None:
    a = (FIX / "star64.html").read_text(encoding="utf-8")
    b = a.replace("</h2>\n<", "</h2>   \n   <") + "\n\n\n"
    assert raw_body_hash(a) != raw_body_hash(b)
    assert semantic_evidence_hash(a) == semantic_evidence_hash(b)
    da, ia = parse_product_html(a, page_url=f"{BASE}/star64/", observed_at=OBS)
    db, ib = parse_product_html(b, page_url=f"{BASE}/star64/", observed_at=OBS)
    assert ia["status"] == ib["status"] == "resolved"
    from board_clank.models import canonical_json

    assert [canonical_json(d.canonical_payload()) for d in da] == [canonical_json(d.canonical_payload()) for d in db]


# --------------------------------------------------------------------- six-vendor isolation


def test_six_vendor_isolation_and_shared_socs(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(rpi_collect_corpus("baseline", run_id="rpi-b", started_at="2026-09-23T01:00:00+00:00"))
    pipeline.accept_run(opi_collect_corpus("baseline", run_id="opi-b", started_at="2026-09-23T02:00:00+00:00"))
    pipeline.accept_run(radxa_collect_corpus("baseline", run_id="radxa-b", started_at="2026-09-23T03:00:00+00:00"))
    pipeline.accept_run(bpi_collect_corpus("baseline", run_id="bpi-b", started_at="2026-09-23T04:00:00+00:00"))
    pipeline.accept_run(od_collect_corpus("baseline", run_id="od-b", started_at="2026-09-23T05:00:00+00:00"))
    snapshots = {
        vendor: [dict(r) for r in store.all("SELECT * FROM boards WHERE vendor_key=?", (vendor,))]
        for vendor in ("raspberry-pi", "orange-pi", "radxa", "banana-pi", "hardkernel-odroid")
    }
    pipeline.accept_run(collect_corpus("baseline", run_id="p64-b", started_at="2026-09-23T06:00:00+00:00"))

    for vendor, snap in snapshots.items():
        assert [dict(r) for r in store.all("SELECT * FROM boards WHERE vendor_key=?", (vendor,))] == snap
    vendors = {row["vendor_key"] for row in store.all("SELECT vendor_key FROM boards")}
    assert vendors == {"raspberry-pi", "orange-pi", "radxa", "banana-pi", "hardkernel-odroid", "pine64"}

    # Shared SoCs: rockchip:rk3566 is used by Orange Pi (3B, CM4) and
    # Pine64 (Quartz64 Model A/B) without merging boards.
    shared = store.all(
        """
        SELECT r.soc_key, COUNT(DISTINCT b.vendor_key) AS vendors, COUNT(DISTINCT b.board_key) AS boards
        FROM board_revisions r JOIN boards b ON b.board_key = r.board_key
        GROUP BY r.soc_key HAVING vendors > 1
        """
    )
    shared_map = {row["soc_key"]: (row["vendors"], row["boards"]) for row in shared}
    v, b = shared_map["rockchip:rk3566"]
    assert v >= 2 and b >= 4  # Orange Pi 3B + CM4 and Pine64 Quartz64 Model A/B
    # allwinner:a64 is pine64-only in these corpora (PINE A64-LTS resolves
    # to R18); rk3566t / rk3588s2 variant SoCs stay distinct keys.
    overlap = store.all(
        "SELECT a.board_key FROM boards a JOIN boards b ON a.board_slug = b.board_slug WHERE a.vendor_key != b.vendor_key"
    )
    assert overlap == []
    assert store.all("SELECT event_id FROM events WHERE event_type = 'FIELD_CHANGED'") == []


def test_one_vendor_run_cannot_close_another_vendors_condition(pipeline: Pipeline, store: Store) -> None:
    pipeline.accept_run(collect_corpus("baseline", run_id="p64-b", started_at="2026-09-23T01:00:00+00:00"))
    pipeline.accept_run(collect_corpus("insufficient", run_id="p64-s", started_at="2026-09-23T02:00:00+00:00"))
    pipeline.accept_run(od_collect_corpus("baseline", run_id="od-b2", started_at="2026-09-23T03:00:00+00:00"))
    row = store.one("SELECT status FROM diagnostic_conditions WHERE source_key='pine64-product' AND status='OPEN'")
    assert row is not None
    assert store.all("SELECT event_id FROM events WHERE event_type='DIAGNOSTIC_RESOLVED'") == []


# --------------------------------------------------------------------- CLI


def test_cli_fails_closed_on_unknown_source_and_collects_pine64(tmp_path: Path, capsys) -> None:
    assert main(["collect", "--live"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "refused"
    db = tmp_path / "p64.db"
    assert main(["--db", str(db), "collect", "--source", "pine64-product", "--run-id", "cli-p64"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "corpus-fixture"
    assert payload["delivery_eligible"] is False
    assert payload["promoted"] is False
    assert payload["result"]["baseline"] is True
    assert main(["--db", str(db), "source-intel", "--source", "pine64-product"]) == 0
    intel = json.loads(capsys.readouterr().out)
    assert intel["enabled"] is False
    assert intel["promotion_state"] == "EXPERIMENTAL"
    # All six Phase-1 vendors are live-capable now; an unregistered source
    # must fail closed with refused JSON (not crash).
    assert main(["--db", str(db), "collect", "--source", "friendlyelec-product", "--experimental-live"]) == 2
    refused = json.loads(capsys.readouterr().out)
    assert refused["status"] == "refused"
    assert "friendlyelec" in refused["reason"]
