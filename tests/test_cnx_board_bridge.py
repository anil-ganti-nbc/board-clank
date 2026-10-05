"""CNX envelopes are research leads. Importing one must not admit Board PRODUCT state."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from board_clank.cli import main
from board_clank.research.baseline import BASELINE_VERSION, baseline_hash
from board_clank.research.bridge import import_jsonl, qualify_lead
from board_clank.research.envelope import CONTRACT_HASH, canonical_bytes, envelope_hash, line_bytes, seal
from board_clank.research.export import export_jsonl, make_envelope, synthetic_envelope
from board_clank.research.fetch import FetchEvidence, FetchRejected
from board_clank.research.store import ResearchStore
from board_clank.sources import sync_sources_to_store
from board_clank.store import Store

CANONICAL = (
    "boards", "board_families", "board_revisions", "board_variants", "events", "notifications", "sources",
)


def _ok_page(oem: str) -> FetchEvidence:
    body = f"board-research-oem: {oem}\nNorthwind single board computer\n".encode()
    return FetchEvidence(
        requested_url="https://northwind.example/catalogue",
        final_url="https://northwind.example/catalogue",
        status=200,
        body_sha256="sha256:" + hashlib.sha256(body).hexdigest(),
        byte_length=len(body),
        body_text=body.decode(),
    )


def _fetch_ok(url: str, domain: str) -> FetchEvidence:
    assert domain == "northwind.example"
    assert url.startswith("https://northwind.example/")
    body = "board-research-oem: Northwind Boards\n".encode()
    return FetchEvidence(url, url, 200, "sha256:" + hashlib.sha256(body).hexdigest(), len(body), body.decode())


def _write(path: Path, *envelopes: dict) -> None:
    path.write_bytes(b"".join(line_bytes(seal(item)) for item in envelopes))


def _snapshot(path: Path) -> dict:
    import sqlite3
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        tables = [row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {table: con.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall() for table in tables}
    finally:
        con.close()


def test_fetch_does_not_send_a_custom_product_token(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def geturl(self):
            return "https://northwind.example/catalogue"

        def read(self, limit):
            return b"board-research-oem: Northwind Boards\n"

        def getcode(self):
            return 200

    class Opener:
        def open(self, request, timeout=None):
            captured["user_agent"] = request.get_header("User-agent")
            return Response()

    monkeypatch.setattr("board_clank.research.fetch.build_opener", lambda *args, **kwargs: Opener())
    from board_clank.research.fetch import fetch_first_party
    evidence = fetch_first_party("https://northwind.example/catalogue", "northwind.example")
    assert evidence.status == 200
    assert captured["user_agent"] in (None, "Python-urllib/3.12")


def test_canonical_serialization_is_order_independent() -> None:
    envelope = synthetic_envelope("run-1")
    swapped = {key: envelope[key] for key in reversed(envelope)}
    assert canonical_bytes(envelope) == canonical_bytes(swapped)
    assert envelope_hash(envelope) == envelope_hash(swapped)
    assert envelope["cnx_contract_hash"] == CONTRACT_HASH
    assert envelope["dedup_baseline_version"] == BASELINE_VERSION
    assert envelope["dedup_baseline_hash"] == baseline_hash()


def test_envelope_hash_changes_when_content_changes() -> None:
    envelope = synthetic_envelope("run-1")
    other = dict(envelope, discovery_reason="different reason")
    assert envelope_hash(envelope) != envelope_hash(other)


def test_schema_version_rejection(tmp_path: Path) -> None:
    envelope = synthetic_envelope("run-1")
    envelope["schema_version"] = "cnx-board-candidate-v0"
    path = tmp_path / "bad.jsonl"
    _write(path, envelope)
    with ResearchStore(tmp_path / "research.sqlite") as store:
        report = import_jsonl(store, path)
    assert report["exit_code"] == 2
    assert report["results"][0]["reason"] == "schema_version"
    assert report["counts"]["leads"] == 0


def test_malformed_json_is_quarantined(tmp_path: Path) -> None:
    path = tmp_path / "broken.jsonl"
    path.write_bytes(b"{this is not json\n")
    with ResearchStore(tmp_path / "research.sqlite") as store:
        report = import_jsonl(store, path)
        assert report["results"][0]["status"] == "quarantined"
        assert report["results"][0]["reason"] == "malformed_json"
        assert store.counts()["leads"] == 0
        assert store.counts()["dispositions"] == 1


def test_valid_import_replay_and_cross_run_duplicate(tmp_path: Path) -> None:
    first = synthetic_envelope("run-1")
    path = tmp_path / "one.jsonl"
    _write(path, first)
    research = tmp_path / "research.sqlite"
    with ResearchStore(research) as store:
        imported = import_jsonl(store, path)
        assert imported["exit_code"] == 0
        assert imported["results"][0]["status"] == "imported"
        lead = imported["results"][0]["lead"]
        assert lead["status"] == "IMPORTED"
        assert lead["provenance"]["provenance_hashes"]["article"].startswith("sha256:")
        replay = import_jsonl(store, path)
        assert replay["exit_code"] == 0
        assert replay["results"][0]["status"] == "replayed"
        assert replay["results"][0]["lead"]["lead_id"] == lead["lead_id"]
        assert store.counts()["leads"] == 1
        other = make_envelope(
            run_id="run-2",
            candidate_id=first["cnx_candidate_id"],
            oem=first["canonical_oem_name"],
            domain=first["candidate_first_party_domain"],
            product_url=first["candidate_product_urls"][0],
            catalogue_url=first["candidate_catalogue_url"],
            discovery_reason="same candidate from a later CNX run",
        )
        second = tmp_path / "two.jsonl"
        _write(second, other)
        crossed = import_jsonl(store, second)
        assert crossed["exit_code"] == 2
        assert crossed["results"][0]["reason"] == "cross_run_duplicate"
        assert store.counts()["leads"] == 1


@pytest.mark.parametrize("oem,domain,reason", [
    ("Forlinx", "forlinx.net", "admitted_vendor_duplicate"),
    ("UP Board", "up-board.example", "placeholder_duplicate"),
])
def test_roster_dedup(tmp_path: Path, oem: str, domain: str, reason: str) -> None:
    product = f"https://{domain}/products/sbc" if domain != "forlinx.net" else "https://www.forlinx.net/product-list-2.html"
    catalogue = product
    envelope = make_envelope(
        run_id="run-dedup",
        candidate_id="cand-" + reason,
        oem=oem,
        domain=domain,
        product_url=product,
        catalogue_url=catalogue,
    )
    path = tmp_path / "dedup.jsonl"
    _write(path, envelope)
    with ResearchStore(tmp_path / "research.sqlite") as store:
        report = import_jsonl(store, path)
        assert report["exit_code"] == 2
        assert report["results"][0]["reason"] == reason
        assert store.counts()["leads"] == 0


def test_stale_and_unknown_baseline_rejected(tmp_path: Path) -> None:
    stale = synthetic_envelope("run-stale")
    stale["dedup_baseline_hash"] = "sha256:" + "cd" * 32
    unknown = synthetic_envelope("run-unknown")
    unknown["dedup_baseline_version"] = "cnx-private-baseline"
    path = tmp_path / "baseline.jsonl"
    _write(path, stale, unknown)
    with ResearchStore(tmp_path / "research.sqlite") as store:
        report = import_jsonl(store, path)
    assert [item["reason"] for item in report["results"]] == ["stale_baseline", "unknown_baseline"]
    assert report["counts"]["leads"] == 0


def test_invalid_missing_domain_and_third_party(tmp_path: Path) -> None:
    invalid = synthetic_envelope("run-domain")
    invalid["candidate_first_party_domain"] = "localhost"
    invalid["candidate_product_urls"] = ["https://localhost/products/sbc"]
    invalid["candidate_catalogue_url"] = "https://localhost/catalogue"
    missing = synthetic_envelope("run-missing")
    del missing["candidate_first_party_domain"]
    third = synthetic_envelope("run-third")
    third["cnx_candidate_id"] = "cand-third"
    third["candidate_product_urls"] = ["https://reseller.example/buy"]
    third["candidate_catalogue_url"] = "https://reseller.example/shop"
    path = tmp_path / "domains.jsonl"
    _write(path, invalid, missing, third)
    with ResearchStore(tmp_path / "research.sqlite") as store:
        report = import_jsonl(store, path)
    assert [item["reason"] for item in report["results"]] == ["invalid_domain", "missing_domain", "third_party_only"]
    assert report["counts"]["leads"] == 0


def test_hash_and_provenance_failures(tmp_path: Path) -> None:
    envelope = synthetic_envelope("run-hash")
    record = seal(envelope)
    record["envelope_hash"] = "sha256:" + "ef" * 32
    broken = synthetic_envelope("run-prov")
    broken["cnx_candidate_id"] = "cand-prov"
    broken["provenance_hashes"] = {"article": "not-a-hash"}
    path = tmp_path / "hash.jsonl"
    path.write_bytes(line_bytes(record) + line_bytes(seal(broken)))
    with ResearchStore(tmp_path / "research.sqlite") as store:
        report = import_jsonl(store, path)
    assert [item["reason"] for item in report["results"]] == ["invalid_envelope_hash", "malformed_provenance"]


def test_redirect_mismatch_and_board_disagreement(tmp_path: Path) -> None:
    envelope = synthetic_envelope("run-qual")
    path = tmp_path / "qual.jsonl"
    _write(path, envelope)
    research = tmp_path / "research.sqlite"
    with ResearchStore(research) as store:
        lead_id = import_jsonl(store, path)["results"][0]["lead"]["lead_id"]
        def redirect(url: str, domain: str) -> FetchEvidence:
            raise FetchRejected("redirect_domain_mismatch")
        refused = qualify_lead(store, lead_id, fetch=redirect)
        assert refused["reason"] == "redirect_domain_mismatch"
        assert store.lead(lead_id)["status"] == "QUARANTINED"
        store.update_lead(lead_id, status="IMPORTED", qualification_state="unreviewed", reason=None, evidence_json="[]")
        def disagree(url: str, domain: str) -> FetchEvidence:
            body = "board-research-oem: OtherCo\n"
            return FetchEvidence(url, url, 200, "sha256:" + "11" * 32, len(body), body)
        conflict = qualify_lead(store, lead_id, fetch=disagree)
        assert conflict["reason"] == "board_evidence_disagrees"
        saved = conflict["lead"]["evidence"]["disagreement"]
        assert saved["cnx_oem"] == "Northwind Boards"
        assert saved["board_oem"] == "OtherCo"
        assert saved["url"].startswith("https://northwind.example/")


def test_qualify_records_first_party_evidence_without_canonical_admission(tmp_path: Path) -> None:
    envelope = synthetic_envelope("run-ok")
    path = tmp_path / "ok.jsonl"
    _write(path, envelope)
    with ResearchStore(tmp_path / "research.sqlite") as store:
        lead_id = import_jsonl(store, path)["results"][0]["lead"]["lead_id"]
        result = qualify_lead(store, lead_id, fetch=_fetch_ok)
        assert result["exit_code"] == 0
        assert result["lead"]["status"] == "QUALIFIED"
        assert result["lead"]["qualification_state"] == "first_party_observed"
        assert result["lead"]["evidence"][0]["final_url"] == "https://northwind.example/catalogue"
        assert "sources" not in {row[0] for row in store.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_import_does_not_change_canonical_board_state(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical.sqlite"
    with Store(canonical) as store:
        sync_sources_to_store(store)
    before_bytes = canonical.read_bytes()
    before_rows = _snapshot(canonical)
    config = Path("config/sources.yaml").read_bytes()
    packaged = Path("src/board_clank/sources.yaml").read_bytes()
    exported = tmp_path / "candidates.jsonl"
    export_jsonl(exported, [synthetic_envelope("run-demo")], run_id="run-demo")
    research = tmp_path / "research.sqlite"
    with ResearchStore(research) as store:
        report = import_jsonl(store, exported)
        assert report["exit_code"] == 0
        qualify_lead(store, report["results"][0]["lead"]["lead_id"], fetch=_fetch_ok)
    assert canonical.read_bytes() == before_bytes
    assert _snapshot(canonical) == before_rows
    assert Path("config/sources.yaml").read_bytes() == config
    assert Path("src/board_clank/sources.yaml").read_bytes() == packaged
    for table in CANONICAL:
        assert table in before_rows
        assert before_rows[table] == _snapshot(canonical)[table]


def _out(capsys: pytest.CaptureFixture[str]) -> dict:
    return json.loads(capsys.readouterr().out)


def test_cli_exit_codes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "candidates.jsonl"
    assert main(["cnx-export-candidates", "--run", "run-cli", "--output", str(output)]) == 0
    capsys.readouterr()
    research = tmp_path / "research.sqlite"
    canonical = tmp_path / "canonical.sqlite"
    Store(canonical).close()
    assert main(["import-candidates", "--input", str(output), "--research-db", str(research)]) == 2
    assert main(["--db", str(canonical), "import-candidates", "--input", str(output), "--research-db", str(canonical), "--research-only"]) == 2
    assert main(["import-candidates", "--input", str(output), "--research-db", str(research), "--research-only"]) == 0
    assert main(["import-candidates", "--input", str(output), "--research-db", str(research), "--research-only"]) == 0
    capsys.readouterr()
    assert main(["research-leads", "list", "--research-db", str(research)]) == 0
    payload = _out(capsys)
    assert len(payload["leads"]) == 1
    lead_id = payload["leads"][0]["lead_id"]
    assert main(["research-leads", "show", lead_id, "--research-db", str(research)]) == 0
    assert _out(capsys)["lead"]["status"] == "IMPORTED"
    monkeypatch.setattr("board_clank.research.bridge.fetch_first_party", _fetch_ok)
    assert main(["research-leads", "qualify", lead_id, "--research-db", str(research)]) == 0
    qualified = _out(capsys)["lead"]
    assert qualified["status"] == "QUALIFIED"
    assert qualified["evidence"][0]["final_url"].startswith("https://northwind.example/")
    assert main(["research-leads", "reject", lead_id, "--reason", "operator closed the lead", "--research-db", str(research)]) == 0
    rejected = _out(capsys)["lead"]
    assert rejected["status"] == "REJECTED"
    assert rejected["reason"] == "operator closed the lead"
    assert main(["research-leads", "show", "lead_missing", "--research-db", str(research)]) == 2
    capsys.readouterr()
    broken = tmp_path / "third.jsonl"
    _write(broken, make_envelope(
        run_id="run-cli",
        candidate_id="cand-shop",
        oem="Shop Front",
        domain="shopfront.example",
        product_url="https://marketplace.example/item",
        catalogue_url="https://marketplace.example/list",
    ))
    assert main(["import-candidates", "--input", str(broken), "--research-db", str(research), "--research-only"]) == 2
    assert _out(capsys)["results"][0]["reason"] == "third_party_only"


def test_operator_demo_sequence(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Bounded synthetic candidate: export, import, replay, qualify, quarantine, unchanged Board."""
    canonical = tmp_path / "board.sqlite"
    with Store(canonical) as store:
        sync_sources_to_store(store)
    before = _snapshot(canonical)
    exported = tmp_path / "candidates.jsonl"
    assert main(["cnx-export-candidates", "--run", "run-demo", "--output", str(exported)]) == 0
    research = tmp_path / "research.sqlite"
    assert main(["--db", str(canonical), "import-candidates", "--input", str(exported), "--research-db", str(research), "--research-only"]) == 0
    assert main(["import-candidates", "--input", str(exported), "--research-db", str(research), "--research-only"]) == 0
    capsys.readouterr()
    assert main(["research-leads", "list", "--research-db", str(research)]) == 0
    leads = _out(capsys)
    assert len(leads["leads"]) == 1
    assert leads["leads"][0]["status"] == "IMPORTED"
    with ResearchStore(research) as store:
        result = qualify_lead(store, leads["leads"][0]["lead_id"], fetch=_fetch_ok)
    assert result["lead"]["evidence"][0]["status"] == 200
    bad = tmp_path / "bad.jsonl"
    bad.write_bytes(b"not-json\n")
    assert main(["import-candidates", "--input", str(bad), "--research-db", str(research), "--research-only"]) == 2
    assert _snapshot(canonical) == before
    assert _out(capsys)["results"][0]["status"] == "quarantined"
