"""Synthetic boundary/failure probes and actual nine-vendor exact input replay."""
import importlib
import json
from pathlib import Path
import tomllib
from urllib.parse import urlparse
from urllib.request import Request

import pytest

from board_clank.collectors import get_adapter
from board_clank.collectors.base import CollectorError
from board_clank.manifest import build_manifest, load_manifest
from board_clank.models import CollectorRunRequest, content_hash
from board_clank.taxonomy import PHASE1_VENDORS, SourcePlane

OBS = '2026-10-03T00:00:00Z'
VENDORS = (*PHASE1_VENDORS, 'friendlyelec', 'khadas', 'forlinx')
MODULES = ('raspberry_pi', 'orange_pi', 'radxa', 'banana_pi', 'odroid', 'pine64')
ROOT_NAMES = {'raspberry_pi': ('PIP_COMPUTERS_URL', 'PIP_MODULES_URL'),
    'orange_pi': ('INDEX_URL',), 'radxa': ('PRODUCTS_URL',),
    'banana_pi': ('SBC_INDEX_URL', 'ROUTER_INDEX_URL'), 'odroid': ('SHOP_URL',), 'pine64': ('DEVICES_URL',)}


def snapshot(store):
    names = [r[0] for r in store.all("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return {name: sorted((tuple(r) for r in store.all('SELECT * FROM ' + name)), key=repr) for name in names}


@pytest.mark.parametrize('vendor', VENDORS)
def test_exact_input_receipt_same_fresh_and_transport_replay(vendor, pipeline, store):
    adapter = get_adapter(vendor + '-product')
    request = adapter.collect('exact-' + vendor, OBS)
    original = request.model_dump_json()
    assert pipeline.accept_run(request).status == 'accepted'
    assert request.model_dump_json() == original
    before = snapshot(store)
    assert pipeline.accept_run(request).replayed
    assert pipeline.accept_run(adapter.collect(request.run_id, OBS)).replayed
    request.diagnostics = {'fetches': [{'raw_body_hash': 'synthetic-transport-noise'}]}
    request.started_at = '2026-10-04T00:00:00Z'
    request.error = 'synthetic-operational-noise'
    for draft in request.observations:
        draft.observed_at = '2026-10-04T00:00:00Z'
        draft.novelty.first_seen_at = draft.observed_at
        draft.raw_fields['html_excerpt'] = '<script>synthetic-transport-noise</script>'
        if draft.price:
            draft.price.observed_at = draft.observed_at
    assert pipeline.accept_run(request).replayed
    assert snapshot(store) == before
    assert store.one('SELECT receipt_hash FROM processed_run_receipts')[0].startswith('product-input-v1:')


@pytest.mark.parametrize('mutation', ['spec', 'candidate', 'insufficient', 'conflict', 'historical',
    'novelty', 'node', 'collector', 'official-date', 'failed', 'order', 'multiplicity', 'cross-vendor'])
def test_accepted_id_rejects_changed_input_without_any_write(mutation, pipeline, store):
    request = get_adapter('forlinx-product').collect('bound-id', OBS)
    pipeline.accept_run(request)
    changed = request.model_copy(deep=True)
    draft = changed.observations[0]
    if mutation == 'spec': draft.spec.ethernet = 'synthetic-change'
    elif mutation == 'candidate': draft.raw_fields['soc_candidates'] = ['synthetic-new-candidate']
    elif mutation == 'insufficient': draft.evidence_insufficient = not draft.evidence_insufficient
    elif mutation == 'conflict': draft.identity_conflict = True; draft.identity_conflict_reason = 'synthetic-conflict'
    elif mutation == 'historical': draft.historical_known = not draft.historical_known
    elif mutation == 'novelty': draft.novelty.novelty_basis = 'synthetic-changed-basis'
    elif mutation == 'node': draft.process_node = 'synthetic-node'
    elif mutation == 'collector': changed.collector_key = 'synthetic-other-collector'
    elif mutation == 'official-date': draft.novelty.official_announcement_at = '2026-10-04T00:00:00Z'
    elif mutation == 'failed': changed.ok = False; changed.error = 'synthetic-error'
    elif mutation == 'order': changed.observations.reverse()
    elif mutation == 'multiplicity': changed.observations.append(draft.model_copy(deep=True))
    else: changed = get_adapter('khadas-product').collect(request.run_id, OBS)
    before = snapshot(store)
    with pytest.raises(ValueError, match='collision'):
        pipeline.accept_run(changed)
    assert snapshot(store) == before


@pytest.mark.parametrize('legacy', ['legacy-outcome-sha', 'product-input-v0:unknown'])
def test_legacy_or_unknown_receipt_never_infers_input_match(legacy, pipeline, store):
    request = get_adapter('forlinx-product').collect('legacy-id', OBS)
    pipeline.accept_run(request)
    store.execute('UPDATE processed_run_receipts SET receipt_hash=?', (legacy,)); store.commit()
    before = snapshot(store)
    with pytest.raises(ValueError, match='legacy'):
        pipeline.accept_run(request)
    assert snapshot(store) == before


def test_failed_attempt_id_rejected_and_diagnostics_durable(pipeline, store):
    request = get_adapter('forlinx-product').collect('failed-id', OBS)
    request.ok, request.error = False, 'synthetic required input failure'
    request.diagnostics = {'errors': [{'url': 'https://www.forlinx.net/product/probe-999.html', 'error': 'synthetic'}]}
    assert pipeline.accept_run(request).status == 'failed'
    report = json.loads(store.one('SELECT message FROM run_errors')[0])
    assert report['format'] == 'collector-failure-v1' and report['diagnostics'] == request.diagnostics
    before = snapshot(store)
    for repeat in (request, get_adapter('forlinx-product').collect(request.run_id, OBS)):
        with pytest.raises(ValueError, match='without an accepted receipt'):
            pipeline.accept_run(repeat)
        assert snapshot(store) == before


@pytest.mark.parametrize('name', MODULES)
@pytest.mark.parametrize('bad_kind', ['host', 'plane'])
def test_each_old_fetcher_blocks_intermediate_and_final_redirect(name, bad_kind, monkeypatch):
    module = importlib.import_module('board_clank.collectors.' + name)
    initial = getattr(module, ROOT_NAMES[name][0])
    bad = 'https://evil.example/products/' if bad_kind == 'host' else urlparse(initial)._replace(path='/documentation/private').geturl()
    handler = module.ValidatedRedirect(module._assert_official_url)
    assert handler.max_redirections == 5 and handler.max_repeats == 2
    with pytest.raises(CollectorError):
        handler.redirect_request(Request(initial), None, 302, 'Found', {}, bad)
    assert handler.redirect_request(Request(initial), None, 302, 'Found', {}, initial).full_url == initial

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def geturl(self): return bad
        def read(self): pytest.fail('out-of-scope final body must not be consumed')
    class Opener:
        def open(self, *_, **__): return Response()
    monkeypatch.setattr(module, 'build_opener', lambda *_: Opener())
    with pytest.raises(CollectorError):
        module.fetch_official_meta(initial)


@pytest.mark.parametrize('name', MODULES)
@pytest.mark.parametrize('failure', ['fetch', 'parse', 'detail-to-index', 'unexpected-detail',
                                      'empty-detail', 'blank-rejection', 'index-to-detail'])
def test_each_old_live_collector_success_then_failure_is_atomic(name, failure, monkeypatch, pipeline, store):
    module = importlib.import_module('board_clank.collectors.' + name)
    seed = module.collect_corpus('baseline', run_id='seed-' + name, started_at=OBS)
    valid = [d for d in seed.observations if not d.evidence_insufficient and not d.identity_conflict]
    pages = list(dict.fromkeys(d.page_url for d in valid))[:2]
    if name == 'raspberry_pi':
        pages = ['https://pip.raspberrypi.com/categories/100-raspberry-pi-4',
                 'https://pip.raspberrypi.com/categories/101-raspberry-pi-5']
    assert len(pages) == 2
    pending = valid[0].model_copy(deep=True)
    pending.board_slug, pending.marketing_name = 'synthetic-pending-condition', 'Synthetic pending condition'
    pending.evidence_insufficient = True
    pending.raw_fields['soc_candidates'] = ['synthetic-unresolved-application-cpu']
    seed.observations.append(pending)
    pipeline.accept_run(seed)
    assert store.count('diagnostic_conditions') > 0
    before = snapshot(store)
    roots = {getattr(module, attr) for attr in ROOT_NAMES[name]}
    parsed = []
    def fake_fetch(url):
        if url == pages[1] and failure == 'fetch':
            raise CollectorError('synthetic required detail fetch failure')
        final = next(iter(roots)) if url == pages[1] and failure == 'detail-to-index' else url
        if url in roots and failure == 'index-to-detail': final = pages[0]
        return {'text': 'synthetic labelled boundary probe', 'requested_url': url, 'final_url': final,
                'raw_body_hash': 'synthetic-raw', 'semantic_evidence_hash': 'synthetic-semantic', 'http_status': 200}
    def fake_parse(_html, *, page_url, observed_at):
        if page_url in roots:
            return [], {'status': 'lead-index', 'evidence_roles': ['DISCOVERY'], 'lead_hrefs': pages}
        if page_url == pages[1] and failure == 'parse':
            raise CollectorError('synthetic required detail parse failure')
        parsed.append(page_url)
        if page_url == pages[1] and failure == 'unexpected-detail':
            return [], {'status': 'ignored-unknown-surface', 'lead_hrefs': []}
        if page_url == pages[1] and failure == 'empty-detail':
            return [], {'status': 'resolved', 'lead_hrefs': []}
        if page_url == pages[1] and failure == 'blank-rejection':
            return [], {'status': 'ignored-non-computer', 'scope': 'NON_BOARD_CATALOGUE_ITEM',
                        'heading': 'UNKNOWN', 'lead_hrefs': []}
        return [valid[0].model_copy(deep=True)], {'status': 'resolved', 'lead_hrefs': []}
    monkeypatch.setattr(module, 'fetch_official_meta', fake_fetch)
    monkeypatch.setattr(module, 'parse_product_html', fake_parse)
    request = get_adapter(module.SOURCE_KEY, experimental_live=True).collect('partial-' + name + '-' + failure, OBS)
    assert parsed and not request.ok and request.observations == [], (request.error, request.diagnostics)
    if failure in {'fetch', 'parse'}: assert request.diagnostics['parser_errors']
    else: assert 'unexpected required' in request.error
    assert pipeline.accept_run(request).status == 'failed'
    after = snapshot(store)
    for table in before:
        if table not in {'collector_runs', 'run_errors'}:
            assert after[table] == before[table], table
    assert len(after['collector_runs']) == len(before['collector_runs']) + 1
    assert len(after['run_errors']) == len(before['run_errors']) + 1


def test_manifest_python_agrees_with_install_requirement():
    root = Path(__file__).resolve().parents[1]
    expected = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']['requires-python']
    assert expected == '>=3.12'
    for declaration in (build_manifest(), load_manifest(), json.loads((root / 'manifest.json').read_text(encoding='utf-8'))):
        assert declaration['architecture']['python'] == expected


@pytest.mark.parametrize('adapter', ['friendlyelec', 'khadas'])
@pytest.mark.parametrize('change', ['candidate', 'label'])
def test_unresolved_cpu_evidence_bound_in_receipt_and_condition(adapter, change, pipeline, store):
    if adapter == 'friendlyelec':
        from board_clank.collectors import friendlyelec as module
        initial = '<h1>NanoPi R9</h1><table><tr><td>CPU</td><td>Rockchip RK3568 / RK3399 CPU Cortex-A55 1.8GHz</td></tr><tr><td>RAM</td><td>2GB DDR4</td></tr><tr><td>Storage</td><td>8GB eMMC</td></tr></table>'
        def parse(body):
            return module.parse_product_html(body, page_url=module.BASE+'index.php?route=product/product&product_id=9999', observed_at=OBS)[0]
        changed = initial.replace('RK3399', 'RK3576') if change == 'candidate' else initial.replace('1.8GHz', '2.0GHz')
    else:
        from board_clank.collectors import khadas as module
        original = (module.CORPUS_DIR/'html/product-page-edge2.html').read_text(encoding='utf-8')
        product = module.product_data(original, module.BASE+'/product-page/edge2')
        product['description'] += '<p>CPU: Rockchip RK3576 SoC Cortex-A55 1.8GHz</p>'
        initial = '<h1>'+product['name']+'</h1><script id="wix-warmup-data">'+json.dumps({'product': product})+'</script>'
        marketing = module.marketing_evidence((module.CORPUS_DIR/'html/edge2.html').read_text(encoding='utf-8'), module.BASE+'/edge2')
        def parse(body):
            return module.parse_product_html(body, page_url=module.BASE+'/product-page/edge2', observed_at=OBS, marketing=marketing)[0]
        changed = initial.replace('RK3576', 'RK3568') if change == 'candidate' else initial.replace('1.8GHz', '2.0GHz')
    a, b = parse(initial), parse(changed)
    assert a and b and all(d.evidence_insufficient for d in a+b)
    assert all(d.raw_fields['cpu_evidence'] and len(d.raw_fields['soc_candidates']) == 2 for d in a+b)
    assert a[0].raw_fields['cpu_evidence'] != b[0].raw_fields['cpu_evidence']
    source = adapter + '-product'
    request = CollectorRunRequest(run_id='unresolved-'+adapter, source_key=source, collector_key=source,
                                  started_at=OBS, observations=a)
    pipeline.accept_run(request)
    before = snapshot(store)
    request.observations = b
    with pytest.raises(ValueError, match='collision'):
        pipeline.accept_run(request)
    assert snapshot(store) == before
    previous = {r['condition_key']: r['state_hash'] for r in store.all('SELECT condition_key,state_hash FROM diagnostic_conditions')}
    request.run_id += '-distinct'
    assert pipeline.accept_run(request).events
    conditions = store.all('SELECT * FROM diagnostic_conditions')
    assert all(r['state_hash'] != previous[r['condition_key']] and r['transition_count'] == 1 for r in conditions)
    assert store.count('boards') == store.count('socs') == 0


@pytest.mark.parametrize('name', MODULES)
def test_absent_cpu_evidence_preserves_legacy_diagnostic_projection(name, pipeline, store):
    module = importlib.import_module('board_clank.collectors.' + name)
    request = module.collect_corpus('baseline', run_id='legacy-projection-'+name, started_at=OBS)
    draft = request.observations[0].model_copy(deep=True)
    assert not draft.raw_fields.get('cpu_evidence')
    draft.evidence_insufficient, draft.identity_conflict = True, False
    request.observations = [draft]
    pipeline.accept_run(request)
    row = store.one('SELECT payload_json,state_hash FROM diagnostic_conditions')
    payload = json.loads(row['payload_json'])
    page = payload['pages'][0]
    assert set(page) == {'entity_key', 'diagnostic_type', 'reason', 'soc_candidates', 'marketing_name', 'page_url'}
    assert row['state_hash'] == content_hash(payload)
    request.run_id += '-later'
    assert pipeline.accept_run(request).events == []


@pytest.mark.parametrize('change', ['vendor', 'plane', 'draft-source', 'durable-supporting', 'unregistered'])
def test_source_authority_validated_before_replay_and_writes(change, pipeline, store):
    request = get_adapter('forlinx-product').collect('authority-bound-id', OBS)
    pipeline.accept_run(request)
    changed = request.model_copy(deep=True)
    if change == 'vendor': changed.observations[0].vendor_key = 'khadas'
    elif change == 'plane': changed.observations[0].plane = SourcePlane.DOCUMENTATION
    elif change == 'draft-source': changed.observations[0].source_key = 'khadas-product'
    elif change == 'unregistered':
        changed.source_key = 'synthetic-unregistered'
        for draft in changed.observations: draft.source_key = changed.source_key
    else:
        store.execute("UPDATE sources SET authority='FIRST_PARTY_SUPPORTING' WHERE source_key='forlinx-product'"); store.commit()
    before = snapshot(store)
    with pytest.raises(ValueError): pipeline.accept_run(changed)
    assert snapshot(store) == before


@pytest.mark.parametrize('name', MODULES)
@pytest.mark.parametrize('change', ['index-to-detail', 'detail-to-index'])
def test_fetch_selected_route_blocks_changed_role_or_model_before_body(name, change, monkeypatch):
    module = importlib.import_module('board_clank.collectors.' + name)
    root = getattr(module, ROOT_NAMES[name][0])
    seed = module.collect_corpus('baseline', run_id='route-probe', started_at=OBS)
    pages = list(dict.fromkeys(d.page_url for d in seed.observations if not d.evidence_insufficient and not d.identity_conflict))[:2]
    if name == 'raspberry_pi':
        pages = ['https://pip.raspberrypi.com/categories/100-raspberry-pi-4',
                 'https://pip.raspberrypi.com/categories/101-raspberry-pi-5']
    initial, bad = (root, pages[0]) if change == 'index-to-detail' else (pages[0], root if change == 'detail-to-index' else pages[1])
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def geturl(self): return bad
        def read(self): pytest.fail('unlinked final document must not be consumed')
    class Opener:
        def open(self, *_args, **_kwargs): return Response()
    def opener(handler):
        with pytest.raises(CollectorError, match='role changed'):
            handler.redirect_request(Request(initial), None, 302, 'Found', {}, bad)
        assert handler.redirect_request(Request(initial), None, 302, 'Found', {}, initial).full_url == initial
        return Opener()
    monkeypatch.setattr(module, 'build_opener', opener)
    with pytest.raises(CollectorError, match='role changed'):
        module.fetch_official_meta(initial)


@pytest.mark.parametrize('fallback', ['index', 'detail', 'empty'])
def test_required_rpi_pcn_cannot_turn_into_another_document_role(fallback, monkeypatch, pipeline, store):
    from board_clank.collectors import raspberry_pi as module
    seed = module.collect_corpus('baseline', run_id='pcn-seed', started_at=OBS)
    valid = next(d for d in seed.observations if not d.evidence_insufficient and not d.identity_conflict)
    pipeline.accept_run(seed)
    before = snapshot(store)
    detail = 'https://pip.raspberrypi.com/categories/100-raspberry-pi-4'
    pcn = detail + '-pcn'
    roots = {module.PIP_COMPUTERS_URL, module.PIP_MODULES_URL}
    def fetch(url):
        final = module.PIP_COMPUTERS_URL if url == pcn and fallback == 'index' else detail if url == pcn else url
        return {'text': 'synthetic PCN role probe', 'requested_url': url, 'final_url': final,
                'raw_body_hash': 'synthetic', 'semantic_evidence_hash': 'synthetic'}
    def parse(_body, *, page_url, observed_at):
        if page_url in roots: return [], {'status': 'lead-index', 'evidence_roles': ['DISCOVERY'], 'lead_hrefs': [detail]}
        if page_url == pcn: return [], {'status': 'pip-pcn', 'evidence_roles': ['CHANGE_EVIDENCE'], 'pcns': []}
        return [valid.model_copy(deep=True)], {'status': 'resolved', 'lead_hrefs': [pcn]}
    monkeypatch.setattr(module, 'fetch_official_meta', fetch)
    monkeypatch.setattr(module, 'parse_product_html', parse)
    request = get_adapter(module.SOURCE_KEY, experimental_live=True).collect('pcn-fallback-'+fallback, OBS)
    assert not request.ok and not request.observations
    assert 'unexpected required pcn' in request.diagnostics['parser_errors'][0]
    assert pipeline.accept_run(request).status == 'failed'
    after = snapshot(store)
    assert all(after[k] == v for k, v in before.items() if k not in {'collector_runs', 'run_errors'})


@pytest.mark.parametrize('status', ['identity-conflict', 'insufficient-evidence'])
def test_rpi_required_unresolved_detail_is_retained(status, monkeypatch):
    from board_clank.collectors import raspberry_pi as module
    seed = module.collect_corpus('baseline', run_id='unresolved-probe', started_at=OBS)
    draft = seed.observations[0].model_copy(deep=True)
    draft.evidence_insufficient, draft.identity_conflict = status == 'insufficient-evidence', status == 'identity-conflict'
    detail = 'https://pip.raspberrypi.com/categories/100-raspberry-pi-4'
    def fetch(url):
        return {'text': 'synthetic unresolved role probe', 'requested_url': url, 'final_url': url,
                'raw_body_hash': 'synthetic', 'semantic_evidence_hash': 'synthetic'}
    def parse(_body, *, page_url, observed_at):
        if page_url in {module.PIP_COMPUTERS_URL, module.PIP_MODULES_URL}:
            return [], {'status': 'lead-index', 'evidence_roles': ['DISCOVERY'], 'lead_hrefs': [detail]}
        return [draft.model_copy(deep=True)], {'status': status, 'lead_hrefs': []}
    monkeypatch.setattr(module, 'fetch_official_meta', fetch)
    monkeypatch.setattr(module, 'parse_product_html', parse)
    request = get_adapter(module.SOURCE_KEY, experimental_live=True).collect('unresolved-'+status, OBS)
    assert request.ok and len(request.observations) == 1
    assert request.observations[0].evidence_insufficient == draft.evidence_insufficient
    assert request.observations[0].identity_conflict == draft.identity_conflict


@pytest.mark.parametrize('name', MODULES)
@pytest.mark.parametrize('failure', ['blank', 'index-fallback'])
def test_real_detail_parser_after_good_document_fails_whole_run(name, failure, monkeypatch, pipeline, store):
    module = importlib.import_module('board_clank.collectors.' + name)
    manifest = json.loads((module.CORPUS_DIR / 'manifest.json').read_text(encoding='utf-8'))
    parse_real = module.parse_product_html
    details = []
    for doc in manifest['corpora']['baseline']['documents']:
        if doc['role'] != 'product': continue
        html = (module.CORPUS_DIR / doc['file']).read_text(encoding='utf-8')
        drafts, info = parse_real(html, page_url=doc['page_url'], observed_at=OBS)
        if drafts and info['status'] in {'resolved', 'resolved-identity'}:
            details.append((doc['page_url'], html))
        if len(details) == 2: break
    assert len(details) == 2
    if name == 'raspberry_pi':
        details = [('https://pip.raspberrypi.com/categories/100-raspberry-pi-4', details[0][1]),
                   ('https://pip.raspberrypi.com/categories/101-raspberry-pi-5', details[1][1])]
    pages = [d[0] for d in details]
    roots = {getattr(module, attr) for attr in ROOT_NAMES[name]}
    root = getattr(module, ROOT_NAMES[name][0])
    seed = module.collect_corpus('baseline', run_id='real-parser-seed-'+name, started_at=OBS)
    pipeline.accept_run(seed)
    before = snapshot(store)
    def fetch(url):
        final = root if url == pages[1] and failure == 'index-fallback' else url
        body = 'synthetic minimal discovery projection' if url in roots else dict(details)[url]
        if url == pages[1]: body = '<html><body></body></html>'
        return {'text': body, 'requested_url': url, 'final_url': final,
                'raw_body_hash': 'synthetic', 'semantic_evidence_hash': 'synthetic'}
    def parse(body, *, page_url, observed_at):
        if body == 'synthetic minimal discovery projection':
            return [], {'status': 'lead-index', 'evidence_roles': ['DISCOVERY'], 'lead_hrefs': pages}
        return parse_real(body, page_url=page_url, observed_at=observed_at)
    monkeypatch.setattr(module, 'fetch_official_meta', fetch)
    monkeypatch.setattr(module, 'parse_product_html', parse)
    request = get_adapter(module.SOURCE_KEY, experimental_live=True).collect('real-parser-failure-'+name+'-'+failure, OBS)
    assert request.diagnostics['resolved'] == 1, request.diagnostics
    assert not request.ok and not request.observations
    assert 'unexpected required detail' in request.error
    assert pipeline.accept_run(request).status == 'failed'
    after = snapshot(store)
    assert all(after[k] == v for k,v in before.items() if k not in {'collector_runs','run_errors'})


@pytest.mark.parametrize('name', MODULES)
def test_real_parser_explicit_nonboard_rejections_remain_valid_detail_outcomes(name):
    from board_clank.collectors._http import require_document_role
    module = importlib.import_module('board_clank.collectors.' + name)
    manifest = json.loads((module.CORPUS_DIR / 'manifest.json').read_text(encoding='utf-8'))
    corpora = ('scope-keyboard',) if name == 'raspberry_pi' else ('scope-rejection',) if name == 'pine64' else ('non-board',)
    guarded = []
    for corpus in corpora:
        for doc in manifest['corpora'][corpus]['documents']:
            drafts,info = module.parse_product_html((module.CORPUS_DIR/doc['file']).read_text(encoding='utf-8'),
                                                    page_url=doc['page_url'],observed_at=OBS)
            if info.get('status') == 'ignored-non-computer' and info.get('reason'):
                require_document_role(drafts,info,'detail')
                guarded.append(info)
    assert guarded


@pytest.mark.parametrize('name', MODULES)
def test_firstparty_detail_redirect_retains_actual_final_provenance(name, monkeypatch):
    from email.message import Message
    module = importlib.import_module('board_clank.collectors.' + name)
    seed = module.collect_corpus('baseline', run_id='detail-redirect-probe', started_at=OBS)
    pages = list(dict.fromkeys(d.page_url for d in seed.observations if not d.evidence_insufficient and not d.identity_conflict))[:2]
    if name == 'raspberry_pi':
        pages = ['https://pip.raspberrypi.com/categories/100-raspberry-pi-4',
                 'https://pip.raspberrypi.com/categories/101-raspberry-pi-5']
    headers = Message(); headers['Content-Type'] = 'text/html; charset=utf-8'
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def geturl(self): return pages[1]
        def read(self): return b'<html>synthetic first-party detail response</html>'
    Response.headers = headers
    class Opener:
        def open(self, *_args, **_kwargs): return Response()
    def opener(handler):
        assert handler.redirect_request(Request(pages[0]), None, 302, 'Found', {}, pages[1]).full_url == pages[1]
        return Opener()
    monkeypatch.setattr(module, 'build_opener', opener)
    meta = module.fetch_official_meta(pages[0])
    assert meta['requested_url'] == pages[0] and meta['final_url'] == pages[1] and meta['redirected']


@pytest.mark.parametrize('name', ['raspberry_pi','banana_pi'])
def test_required_distinct_discovery_root_cannot_replace_selected_coverage(name, monkeypatch):
    module = importlib.import_module('board_clank.collectors.' + name)
    roots = [getattr(module, attr) for attr in ROOT_NAMES[name]]
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def geturl(self): return roots[1]
        def read(self): pytest.fail('different discovery coverage must not be consumed')
    class Opener:
        def open(self, *_args, **_kwargs): return Response()
    def opener(handler):
        with pytest.raises(CollectorError,match='discovery/change route changed'):
            handler.redirect_request(Request(roots[0]),None,302,'Found',{},roots[1])
        return Opener()
    monkeypatch.setattr(module,'build_opener',opener)
    with pytest.raises(CollectorError,match='discovery/change route changed'):
        module.fetch_official_meta(roots[0])


@pytest.mark.parametrize('name', MODULES)
def test_actual_discovery_requires_nonempty_coverage(name):
    from board_clank.collectors._http import require_document_role
    module = importlib.import_module('board_clank.collectors.' + name)
    manifest = json.loads((module.CORPUS_DIR / 'manifest.json').read_text(encoding='utf-8'))
    doc = next(d for d in manifest['corpora']['baseline']['documents'] if d['role'] == 'lead')
    drafts,info = module.parse_product_html((module.CORPUS_DIR/doc['file']).read_text(encoding='utf-8'),
                                           page_url=doc['page_url'], observed_at=OBS)
    require_document_role(drafts,info,'index')
    drafts,info = module.parse_product_html('<html><body></body></html>',page_url=doc['page_url'],observed_at=OBS)
    with pytest.raises(CollectorError,match='unexpected required index'):
        require_document_role(drafts,info,'index')


def test_actual_pcn_requires_change_evidence_coverage():
    from board_clank.collectors._http import require_document_role
    from board_clank.collectors import raspberry_pi as module
    manifest = json.loads((module.CORPUS_DIR / 'manifest.json').read_text(encoding='utf-8'))
    doc = next(d for c in manifest['corpora'].values() for d in c['documents'] if d['role'] == 'pcn')
    drafts,info = module.parse_product_html((module.CORPUS_DIR/doc['file']).read_text(encoding='utf-8'),
                                           page_url=doc['page_url'], observed_at=OBS)
    require_document_role(drafts,info,'pcn')
    drafts,info = module.parse_product_html('<html><body></body></html>',page_url=doc['page_url'],observed_at=OBS)
    with pytest.raises(CollectorError,match='unexpected required pcn'):
        require_document_role(drafts,info,'pcn')
