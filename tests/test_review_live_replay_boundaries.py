"""Reviewed live boundaries and authenticated replay, using real fixture detail parsers."""
from __future__ import annotations

import importlib
import json
import tomllib
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse
from urllib.request import Request

import pytest

from board_clank.backup import create_backup, restore_backup
from board_clank.collectors import get_adapter
from board_clank.collectors.base import CollectorError
from board_clank.manifest import build_manifest, load_manifest
from board_clank.pipeline import Pipeline
from board_clank.sources import sync_sources_to_store
from board_clank.store import Store
from board_clank.taxonomy import PHASE1_VENDORS, PHASE2_ADMITTED, RevisionKind

SIX = ("raspberry_pi", "orange_pi", "radxa", "banana_pi", "odroid", "pine64")
EIGHT = (*PHASE1_VENDORS, *PHASE2_ADMITTED)
OBS = "2026-10-03T12:00:00Z"


def snapshot(store):
    return {row[0]: [tuple(r) for r in store.all(f'SELECT * FROM "{row[0]}" ORDER BY rowid')]
            for row in store.all("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def module(name):
    return importlib.import_module("board_clank.collectors." + name)


def documents(mod):
    corpus = "pip-live-sim" if mod.__name__.endswith("raspberry_pi") else "baseline"
    manifest = json.loads((mod.CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))
    return sorted((d for d in manifest["corpora"][corpus]["documents"] if d["role"] == "product"),
                  key=lambda d: d["page_url"])[:2]


@pytest.mark.parametrize("name", SIX)
@pytest.mark.parametrize("destination", ["cross-host", "same-host-excluded"])
def test_redirect_rejected_before_following_and_final_body_read(name, destination, monkeypatch):
    mod = module(name)
    initial = documents(mod)[0]["page_url"]
    parsed = urlparse(initial)
    bad = "https://third-party.invalid/product" if destination == "cross-host" else f"{parsed.scheme}://{parsed.netloc}/docs/excluded"
    # Per-hop guard, including a redirect after a valid hop.
    handler = mod._BoundedRedirect()
    hop = handler.redirect_request(Request(initial), None, 302, "", {}, initial)
    assert hop.full_url == initial
    with pytest.raises(CollectorError):
        handler.redirect_request(hop, None, 302, "", {}, bad)
    # Defense in depth: even a transport returning an invalid final URL cannot read its body.
    reads = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def geturl(self): return bad
        def read(self): reads.append(True); return b"third-party"
    monkeypatch.setattr(mod, "build_opener", lambda *args: SimpleNamespace(open=lambda *a, **kw: Response()))
    with pytest.raises(CollectorError):
        mod.fetch_official_meta(initial)
    assert reads == []


@pytest.mark.parametrize("name", SIX)
def test_allowed_final_url_is_actual_parser_provenance(name, monkeypatch):
    mod = module(name)
    initial, final = (d["page_url"] for d in documents(mod))
    body = (mod.CORPUS_DIR / documents(mod)[1]["file"]).read_bytes()
    headers = Message(); headers["Content-Type"] = "text/html; charset=utf-8"
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def geturl(self): return final
        def read(self): return body
    Response.headers = headers
    monkeypatch.setattr(mod, "build_opener", lambda *args: SimpleNamespace(open=lambda *a, **kw: Response()))
    meta = mod.fetch_official_meta(initial)
    assert meta["final_url"] == final and meta["redirected"]
    drafts, info = mod.parse_product_html(meta["text"], page_url=meta["final_url"], observed_at=OBS)
    assert drafts and info["page_url"] == final
    assert all(d.page_url == final for d in drafts)


@pytest.mark.parametrize("name", SIX)
@pytest.mark.parametrize("failure", ["fetch", "parser"])
@pytest.mark.parametrize("with_open_condition", [False, True])
def test_one_detail_success_then_required_failure_is_atomic(name, failure, with_open_condition, store, monkeypatch):
    mod = module(name)
    pipeline = Pipeline(store)
    if with_open_condition:
        prior = mod.collect_corpus("baseline", run_id="prior-conflict", started_at=OBS)
        prior.observations = prior.observations[:1]
        prior.observations[0].identity_conflict = True
        prior.observations[0].evidence_insufficient = True
        prior.observations[0].identity_conflict_reason = "controlled prior uncertainty"
        pipeline.accept_run(prior)
        assert store.one("SELECT condition_key FROM diagnostic_conditions WHERE source_key=? AND status='OPEN'", (mod.SOURCE_KEY,))
    docs = documents(mod)
    good, bad = (d["page_url"] for d in docs)
    html = {d["page_url"]: (mod.CORPUS_DIR / d["file"]).read_text(encoding="utf-8") for d in docs}
    parsed = []
    real_parse = mod.parse_product_html
    def parse(text, *, page_url, observed_at, **kwargs):
        if page_url not in html:
            return [], {"status": "lead-index", "lead_hrefs": [good, bad]}
        if page_url == bad and failure == "parser":
            raise CollectorError("required parser outage")
        drafts, info = real_parse(text, page_url=page_url, observed_at=observed_at, **kwargs)
        assert drafts
        parsed.append(page_url)
        # Avoid unrelated PCN pages; this test's required pages are the two details.
        info["lead_hrefs"] = []
        return drafts, info
    def fetch(url):
        if url == bad and failure == "fetch":
            raise CollectorError("required fetch outage")
        return {"requested_url": url, "final_url": url, "text": html.get(url, "<html>index</html>"),
                "raw_body_hash": "fixture-raw", "semantic_evidence_hash": "fixture-semantic"}
    monkeypatch.setattr(mod, "fetch_official_meta", fetch)
    monkeypatch.setattr(mod, "parse_product_html", parse)
    before = snapshot(store)
    request = get_adapter(mod.SOURCE_KEY, experimental_live=True).collect("partial-failure", OBS)
    assert parsed == [good]
    assert not request.ok and request.observations == []
    assert request.error and request.diagnostics["parser_errors"]
    result = pipeline.accept_run(request)
    assert result.status == "failed" and result.diagnostics == request.diagnostics
    after = snapshot(store)
    assert len(after.pop("collector_runs")) == len(before.pop("collector_runs")) + 1
    errors = after.pop("run_errors"); before.pop("run_errors")
    assert len(errors) == 1
    durable_error = json.loads(store.one("SELECT message FROM run_errors WHERE run_id='partial-failure'")[0])
    assert durable_error["format"] == "collector-failure-v1"
    assert durable_error["diagnostics"] == request.diagnostics
    assert after == before  # Includes receipt/baseline/conditions/events/current state/occurrences.


@pytest.mark.parametrize("vendor", EIGHT)
def test_all_eight_same_object_and_fresh_input_are_exact_noop_replay(vendor, store):
    key = "hardkernel-odroid-product" if vendor == "hardkernel-odroid" else vendor + "-product"
    # Roster uses vendor 'odroid' in this project's PHASE1_VENDORS.
    if vendor == "odroid": key = "hardkernel-odroid-product"
    request = get_adapter(key).collect(vendor + "-exact", OBS)
    original = request.model_dump(mode="json")
    assert Pipeline(store).accept_run(request).status == "accepted"
    assert request.model_dump(mode="json") == original
    before = snapshot(store)
    assert Pipeline(store).accept_run(request).replayed
    fresh = get_adapter(key).collect(vendor + "-exact", OBS)
    fresh.diagnostics["transport_note"] = "not admitted evidence"
    fresh.started_at = "2099-01-01T00:00:00Z"
    fresh.error = "operational prose is excluded"
    for draft in fresh.observations:
        draft.observed_at = fresh.started_at
        draft.novelty.first_seen_at = fresh.started_at
        draft.raw_fields["html_excerpt"] = "recapture transport noise"
        if draft.price: draft.price.observed_at = fresh.started_at
    assert Pipeline(store).accept_run(fresh).replayed
    assert snapshot(store) == before
    assert store.one("SELECT receipt_hash FROM processed_run_receipts WHERE run_id=?", (request.run_id,))[0].startswith("product-input-v1:")


@pytest.mark.parametrize("change", ["evidence", "collector", "failed", "source", "legacy", "unknown-prefix", "revision", "historical", "insufficient", "conflict", "native", "raw", "chronology", "order", "multiplicity"])
def test_product_collision_and_unverifiable_legacy_are_all_table_noops(change, store):
    req = get_adapter("radxa-product").collect("collision", OBS)
    pipeline = Pipeline(store)
    pipeline.accept_run(req)
    if change == "legacy":
        store.execute("UPDATE processed_run_receipts SET receipt_hash='old-output-hash' WHERE run_id='collision'")
        store.commit()
    elif change == "unknown-prefix":
        store.execute("UPDATE processed_run_receipts SET receipt_hash='unrecognized-v99:hash' WHERE run_id='collision'")
        store.commit()
    mutated = req.model_copy(deep=True)
    if change == "evidence": mutated.observations[0].spec.usb = "changed evidence"
    elif change == "collector": mutated.collector_key = "different collector"
    elif change == "failed": mutated.ok = False; mutated.error = "failed request"
    elif change == "source": mutated = get_adapter("raspberry-pi-product").collect("collision", OBS)
    elif change == "revision": mutated.observations[0].revision_token = "changed-revision"
    elif change == "historical": mutated.observations[0].historical_known = not mutated.observations[0].historical_known
    elif change == "insufficient": mutated.observations[0].evidence_insufficient = True
    elif change == "conflict": mutated.observations[0].identity_conflict = True
    elif change == "native": mutated.observations[0].native_fields["new_evidence"] = "changed"
    elif change == "raw": mutated.observations[0].raw_fields["soc_candidates"] = ["changed SoC"]
    elif change == "chronology": mutated.observations[0].novelty.official_sale_at = "2026-01-01"
    elif change == "order": mutated.observations.reverse()
    elif change == "multiplicity": mutated.observations.append(mutated.observations[0].model_copy(deep=True))
    before = snapshot(store)
    with pytest.raises(ValueError, match="collision|legacy"):
        pipeline.accept_run(mutated)
    assert snapshot(store) == before


def test_failed_attempt_id_cannot_be_reused_or_replayed(store):
    req = get_adapter("radxa-product").collect("failed-id", OBS)
    req.ok = False; req.error = "outage"; req.observations = []
    pipeline = Pipeline(store)
    assert pipeline.accept_run(req).status == "failed"
    before = snapshot(store)
    for attempted in (req, get_adapter("radxa-product").collect("failed-id", OBS),
                      get_adapter("raspberry-pi-product").collect("failed-id", OBS)):
        with pytest.raises(ValueError, match="without an accepted receipt"):
            pipeline.accept_run(attempted)
        assert snapshot(store) == before


def test_original_unknown_revision_request_survives_identity_mutation_and_restore(store, tmp_path):
    req = get_adapter("raspberry-pi-product").collect("original-input", OBS)
    # Resolution overwrites spec fields and, on a later run, revision echoes.
    original = req.model_dump(mode="json")
    Pipeline(store).accept_run(req)
    second = req.model_copy(deep=True); second.run_id = "second-input"
    second.observations[0].revision_kind = RevisionKind.UNKNOWN
    second.observations[0].revision_token = "UNKNOWN"
    second_original = second.model_dump(mode="json")
    Pipeline(store).accept_run(second)
    assert req.model_dump(mode="json") == original
    assert second.model_dump(mode="json") == second_original
    before = snapshot(store)
    assert Pipeline(store).accept_run(second).replayed
    assert snapshot(store) == before
    backup = create_backup(store.path, tmp_path / "backup")
    restored = tmp_path / "restored.db"
    report = restore_backup(backup.database_path, backup.metadata_path, restored)
    with Store(report["staging_path"], migrate=False) as copy:
        before = snapshot(copy)
        assert Pipeline(copy).accept_run(req).replayed
        assert Pipeline(copy).accept_run(second).replayed
        assert snapshot(copy) == before


def test_manifest_python_requirement_matches_distribution_metadata():
    expected = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]["requires-python"]
    for manifest in (build_manifest(), load_manifest(), load_manifest("src/board_clank/manifest.json")):
        assert manifest["architecture"]["python"] == expected == ">=3.12"


@pytest.mark.parametrize("adapter", ["friendlyelec", "khadas"])
@pytest.mark.parametrize("change", ["candidate", "label"])
def test_unresolved_cpu_evidence_is_retained_and_collision_is_noop(adapter, change, store):
    mod = module(adapter)
    def parse(changed):
        if adapter == "friendlyelec":
            extra = " RK3576" if changed and change == "candidate" else ""
            label = "option B" if changed and change == "label" else "option A"
            body = f'<h1>NanoPi R5S</h1><tr><td>CPU</td><td>RK3566 RK3588{extra} {label}</td></tr>'
            return mod.parse_product_html(body, page_url=mod.BASE+'index.php?route=product/product&product_id=999', observed_at=OBS)[0]
        url = mod.BASE+'/product-page/edge2'
        original = (mod.CORPUS_DIR/'html/product-page-edge2.html').read_text(encoding='utf-8')
        product = mod.product_data(original, url)
        extra = '<p>Amlogic A311D2 CPU option</p>' if changed and change == "candidate" else ""
        label = "option B" if changed and change == "label" else "option A"
        product['description'] = f'<p>Amlogic A311D application processor {label}</p><p>Rockchip RK3588 CPU option</p>{extra}'
        body = '<h1>'+product['name']+'</h1><script id="wix-warmup-data">'+json.dumps({'product':product})+'</script>'
        marketing = mod.marketing_evidence((mod.CORPUS_DIR/'html/edge2.html').read_text(encoding='utf-8'), mod.BASE+'/edge2')
        return mod.parse_product_html(body, page_url=url, observed_at=OBS, marketing=marketing)[0]
    from board_clank.models import CollectorRunRequest
    initial, changed = parse(False), parse(True)
    assert initial and all(d.evidence_insufficient and d.identity_conflict for d in initial)
    assert all(d.raw_fields['cpu_evidence'] and len(d.raw_fields['soc_candidates']) >= 2 for d in initial)
    assert initial[0].raw_fields['cpu_evidence'] != changed[0].raw_fields['cpu_evidence']
    assert all(':' in candidate for candidate in initial[0].raw_fields['soc_candidates'])
    req = CollectorRunRequest(run_id='cpu-options', source_key=mod.SOURCE_KEY, collector_key=mod.SOURCE_KEY,
                              started_at=OBS, observations=initial)
    pipeline = Pipeline(store); pipeline.accept_run(req)
    before = snapshot(store)
    collision = req.model_copy(deep=True); collision.observations = changed
    with pytest.raises(ValueError, match='collision'):
        pipeline.accept_run(collision)
    assert snapshot(store) == before
    # A genuinely new run records changed diagnostic evidence, without fabricating a Board.
    old_states = [r[0] for r in store.all('SELECT state_hash FROM diagnostic_conditions ORDER BY condition_key')]
    collision.run_id = 'cpu-options-next'
    pipeline.accept_run(collision)
    assert [r[0] for r in store.all('SELECT state_hash FROM diagnostic_conditions ORDER BY condition_key')] != old_states
    assert store.count('boards') == 0


def test_rollback_retry_keeps_original_input_immutable(store, monkeypatch):
    request = get_adapter('radxa-product').collect('rollback-retry', OBS)
    original = request.model_dump(mode='json'); before = snapshot(store)
    pipeline = Pipeline(store)
    upsert = pipeline._upsert_graph
    def fail(*args, **kwargs): raise RuntimeError('controlled admission failure after resolution')
    monkeypatch.setattr(pipeline, '_upsert_graph', fail)
    with pytest.raises(RuntimeError): pipeline.accept_run(request)
    assert request.model_dump(mode='json') == original and snapshot(store) == before
    monkeypatch.setattr(pipeline, '_upsert_graph', upsert)
    assert pipeline.accept_run(request).status == 'accepted'
    assert request.model_dump(mode='json') == original
