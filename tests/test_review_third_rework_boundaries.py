"""Exact review regressions: role provenance, replay receipts and fail-closed state."""
from __future__ import annotations

import importlib
import json
import sqlite3
from copy import deepcopy
from types import SimpleNamespace
from urllib.request import Request

import pytest

from board_clank.collectors import get_adapter
from board_clank.collectors.base import CollectorError
from board_clank.collectors import radxa_documentation as docs
from board_clank.observer import full_snapshot
from board_clank.pipeline import Pipeline
from board_clank.store import Store, load_migration_sql

OBS = '2026-10-03T16:00:00Z'


def snapshot(store):
    return {r[0]: [tuple(row) for row in store.all(f'SELECT * FROM "{r[0]}" ORDER BY rowid')]
            for r in store.all("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def module(name):
    return importlib.import_module('board_clank.collectors.' + name)


def details(mod):
    manifest = json.loads((mod.CORPUS_DIR / 'manifest.json').read_text())
    entries = manifest['corpora']['baseline']
    if isinstance(entries, dict):
        entries = entries['documents']
    if mod.SOURCE_KEY == 'khadas-product':
        entries = [d for d in entries if '/product-page/vim' in d['page_url']]
    return [dict(d, page_url=mod.official_url(d['page_url'])) for d in entries[:2]]


@pytest.mark.parametrize('name', ['friendlyelec', 'khadas'])
@pytest.mark.parametrize('bad_kind', ['cross-host', 'excluded', 'wrong-role'])
def test_two_adapters_guard_every_hop_and_final_before_body(name, bad_kind, monkeypatch):
    mod = module(name)
    initial = details(mod)[0]['page_url']
    bad = {'cross-host': 'https://third-party.invalid/product',
           'excluded': mod.BASE.rstrip('/') + '/docs/excluded', 'wrong-role': mod.INDEXES[0]}[bad_kind]
    handler = mod._Redirect(initial)
    hop = handler.redirect_request(Request(initial), None, 302, '', {}, initial)
    with pytest.raises(CollectorError):
        handler.redirect_request(hop, None, 302, '', {}, bad)
    reads = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def geturl(self): return bad
        def read(self, *args): reads.append(True); return b'wrong body'
    monkeypatch.setattr(mod, 'build_opener', lambda *a: SimpleNamespace(open=lambda *a, **k: Response()))
    with pytest.raises(CollectorError):
        mod.fetch(initial)
    assert reads == []


def test_khadas_marketing_cannot_cross_to_product_or_index():
    mod = module('khadas')
    for bad in (mod.INDEXES[0], details(mod)[0]['page_url']):
        with pytest.raises(CollectorError):
            mod._Redirect(mod.BASE + '/vim1').redirect_request(Request(mod.BASE + '/vim1'), None, 302, '', {}, bad)


@pytest.mark.parametrize('name', ['friendlyelec', 'khadas'])
def test_same_role_redirect_uses_final_product_and_marketing_provenance(name, monkeypatch):
    mod = module(name)
    initial, detail = details(mod)
    final = detail['page_url']
    body = (mod.CORPUS_DIR / detail['file']).read_text(encoding='utf-8')
    requested = initial['page_url']
    monkeypatch.setattr(mod, 'INDEXES', [mod.official_url(mod.INDEXES[0])])
    if name == 'friendlyelec':
        index_body = f'<a href="{requested}">board</a>'
        def fetch(url):
            return {'text': index_body if url in mod.INDEXES else body,
                    'final_url': url if url in mod.INDEXES else final, 'requested_url': url}
    else:
        product_name = mod.product_data(body, final)['name']
        first_market, final_market = mod.BASE + '/vim1', mod.BASE + '/vim2'
        index_body = f'<a href="{first_market}">board</a>'
        market_body = f'<h1>{product_name}</h1><a href="{requested}">Buy Now</a>'
        def fetch(url):
            html = index_body if url in mod.INDEXES else (market_body if url == first_market else body)
            return {'text': html, 'final_url': final_market if url == first_market else (url if url in mod.INDEXES else final), 'requested_url': url}
    monkeypatch.setattr(mod, 'fetch', fetch)
    request = get_adapter(mod.SOURCE_KEY, experimental_live=True).collect('final-provenance', OBS)
    assert request.ok, request.diagnostics
    assert request.observations and all(d.page_url == final for d in request.observations)
    assert all(d.native_fields.get('page_url', d.native_fields.get('product_url')) == final for d in request.observations)
    if name == 'khadas':
        assert all(d.native_fields['marketing_url'] == final_market for d in request.observations)


@pytest.mark.parametrize('name', ['friendlyelec', 'khadas'])
@pytest.mark.parametrize('failure', ['fetch', 'wrong-role', 'blank-body', 'parser', 'empty-drafts'])
def test_partial_live_success_never_exposes_or_admits_drafts(name, failure, store, monkeypatch):
    mod = module(name)
    good, bad = details(mod)
    good_url, bad_url = good['page_url'], bad['page_url']
    bodies = {d['page_url']: (mod.CORPUS_DIR / d['file']).read_text(encoding='utf-8') for d in (good, bad)}
    monkeypatch.setattr(mod, 'INDEXES', [mod.official_url(mod.INDEXES[0])])
    if name == 'friendlyelec':
        index_body = ''.join(f'<a href="{url}">board</a>' for url in bodies)
    else:
        markets = {mod.BASE + '/vim1': good, mod.BASE + '/vim2': bad}
        index_body = ''.join(f'<a href="{url}">board</a>' for url in markets)
    parsed, fetched = [], []
    original = mod.parse_product_html
    def parse(html, *, page_url, **kwargs):
        if page_url == bad_url and failure == 'parser':
            raise CollectorError('controlled required parser failure')
        if page_url == bad_url and failure == 'empty-drafts':
            return [], {'status': 'resolved', 'page_url': page_url}
        result = original(html, page_url=page_url, **kwargs)
        if result[0]: parsed.append(page_url)
        return result
    def fetch(url):
        if url == bad_url and failure == 'fetch': raise CollectorError('controlled required fetch failure')
        if url in mod.INDEXES: html = index_body
        elif name == 'khadas' and url in markets:
            entry = markets[url]
            heading = mod.product_data(bodies[entry['page_url']], entry['page_url'])['name']
            html = f'<h1>{heading}</h1><a href="{entry["page_url"]}">Buy Now</a>'
        else: html = '' if url == bad_url and failure == 'blank-body' else bodies[url]
        fetched.append(url)
        return {'text': html, 'requested_url': url, 'final_url': mod.INDEXES[0] if url == bad_url and failure == 'wrong-role' else url}
    monkeypatch.setattr(mod, 'fetch', fetch)
    monkeypatch.setattr(mod, 'parse_product_html', parse)
    request = get_adapter(mod.SOURCE_KEY, experimental_live=True).collect('partial', OBS)
    assert good_url in fetched
    assert not request.ok and request.observations == []
    before = snapshot(store)
    result = Pipeline(store).accept_run(request)
    assert result.status == 'failed'
    after = snapshot(store)
    for table in ('collector_runs', 'run_errors'): before.pop(table); after.pop(table)
    assert after == before


@pytest.mark.parametrize('field,value', [('enabled', 1), ('promotion_state', 'PROMOTED'), ('placeholder', 1), ('out_of_scope', 1)])
@pytest.mark.parametrize('trusted', [False, True])
def test_product_policy_drift_refused_before_fresh_failed_and_replay_writes(field, value, trusted, store, monkeypatch):
    request = get_adapter('radxa-product').collect('policy', OBS)
    Pipeline(store).accept_run(request)
    if trusted:
        from board_clank import sources as code
        sources = deepcopy(code.load_sources())
        setattr(next(s for s in sources if s.source_key == request.source_key), field, value)
        monkeypatch.setattr(code, 'load_sources', lambda: sources)
    else:
        store.execute(f'UPDATE sources SET {field}=? WHERE source_key=?', (value, request.source_key))
    before = snapshot(store)
    for run, ok in (('policy', True), ('fresh', True), ('failed', False)):
        request.run_id, request.ok = run, ok
        with pytest.raises(ValueError): Pipeline(store).accept_run(request)
        assert snapshot(store) == before


@pytest.mark.parametrize('changed', ['mapping-reason', 'mapping-eligible', 'mapping-rejected', 'ignored-models', 'artifacts', 'model', 'status'])
def test_supporting_semantic_collision_is_all_table_noop(changed, store, monkeypatch):
    html = docs._FIXTURE.read_text(encoding='utf-8').replace('id=hardware-design', 'id=missing')
    docs.accept_documentation(store, html, run_id='supporting', observed_at=OBS)
    before = snapshot(store)
    assert store.one("SELECT receipt_hash FROM processed_run_receipts WHERE run_id='supporting'")[0].startswith('supporting-input-v2:')
    if changed.startswith('mapping'):
        original = docs._resolve_board
        def resolve(s):
            target, mapping = original(s); mapping = deepcopy(mapping)
            key = {'mapping-reason': 'reason', 'mapping-eligible': 'eligible_targets', 'mapping-rejected': 'rejected_targets'}[changed]
            mapping[key] = 'different reason' if key == 'reason' else ['radxa:changed']
            return target, mapping
        monkeypatch.setattr(docs, '_resolve_board', resolve)
    else:
        original = docs.parse_hardware
        def parse(*args, **kwargs):
            claims, info = original(*args, **kwargs); info = deepcopy(info)
            info[{'ignored-models': 'ignored_models', 'artifacts': 'artifact_crosslinks', 'model': 'model', 'status': 'status'}[changed]] = ['changed'] if changed in ('ignored-models', 'artifacts') else 'changed'
            return claims, info
        monkeypatch.setattr(docs, 'parse_hardware', parse)
    with pytest.raises(CollectorError, match='run id reuse'):
        docs.accept_documentation(store, html, run_id='supporting', observed_at=OBS)
    assert snapshot(store) == before


def test_supporting_cosmetic_bytes_replay_but_legacy_receipt_is_refused(store):
    html = docs._FIXTURE.read_text(encoding='utf-8')
    docs.accept_documentation(store, html, run_id='supporting', observed_at=OBS)
    before = snapshot(store)
    assert docs.accept_documentation(store, html + '<!-- raw cosmetic -->', run_id='supporting', observed_at=OBS)['replayed']
    assert snapshot(store) == before
    store.execute("UPDATE processed_run_receipts SET receipt_hash='legacy' WHERE run_id='supporting'")
    before = snapshot(store)
    with pytest.raises(CollectorError): docs.accept_documentation(store, html, run_id='supporting', observed_at=OBS)
    assert snapshot(store) == before


@pytest.mark.parametrize('mode,version,state', [('v1',1,'MIGRATION_REQUIRED'), ('v2',2,'MIGRATION_REQUIRED'), ('current',3,'COMPATIBLE'), ('newer',4,'INCOMPATIBLE_NEWER'), ('empty',None,'UNKNOWN'), ('partial',3,'PARTIAL'), ('fresh',None,'FRESH'), ('corrupt',None,'CORRUPT')])
def test_observer_actual_compatibility_schema_and_readonly_bytes(tmp_path, mode, version, state):
    path = tmp_path / 'observer.db'
    if mode == 'corrupt': path.write_bytes(b'not sqlite')
    elif mode == 'current': Store(path).close()
    else:
        con = sqlite3.connect(path)
        if mode in ('v1','v2'):
            for v in range(1, version+1): con.executescript(load_migration_sql(v))
            for v in range(1, version+1): con.execute('INSERT INTO schema_migrations(version,applied_at,name) VALUES (?,?,?)', (v, OBS, 'test'))
        elif mode != 'fresh':
            con.execute('CREATE TABLE schema_migrations(version INTEGER, applied_at TEXT, name TEXT)')
            if version: con.execute('INSERT INTO schema_migrations VALUES (?, ?, ?)', (version,OBS,'test'))
        con.commit(); con.close()
    before = path.read_bytes()
    result = full_snapshot(path)
    assert path.read_bytes() == before
    assert result['status']['state'] == state
    assert result['schema_revision']['schema_version'] == (version if version is not None else 'UNKNOWN')
    assert result['schema_revision']['expected_schema_version'] == 3
    if state in ('MIGRATION_REQUIRED','INCOMPATIBLE_NEWER','PARTIAL','CORRUPT'):
        assert result['health']['overall'] == 'degraded'
    elif state in ('UNKNOWN','FRESH'):
        assert result['health']['overall'] == 'degraded'
    assert result['health']['mutating'] is False


def test_supporting_mapping_change_during_transaction_is_all_table_noop(store, monkeypatch):
    html = docs._FIXTURE.read_text(encoding='utf-8')
    original = docs._resolve_board
    calls = []
    def resolve(s):
        target, mapping = original(s)
        calls.append(True)
        if len(calls) == 2:
            mapping = dict(mapping, reason='same target but changed diagnostic mapping')
        return target, mapping
    monkeypatch.setattr(docs, '_resolve_board', resolve)
    before = snapshot(store)
    with pytest.raises(CollectorError, match='linkage changed'):
        docs.accept_documentation(store, html, run_id='transaction-drift', observed_at=OBS)
    assert snapshot(store) == before
