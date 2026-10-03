"""Qualified discovery coverage, immutable admission, and honest RO compatibility."""
from pathlib import Path
import json
import re
import sqlite3
import tomllib

from packaging.requirements import Requirement
import pytest

from board_clank.collectors import forlinx as f, get_adapter
from board_clank.collectors.base import CollectorError
from board_clank.observer import full_snapshot, health, schema_revision, status
from board_clank.store import Store
from board_clank import sources

OBS = '2026-10-03T00:00:00Z'
MANIFEST = json.loads((f.CORPUS_DIR / 'manifest.json').read_text(encoding='utf-8'))


def all_rows(store):
    tables = [r[0] for r in store.all("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return {t: sorted((tuple(r) for r in store.all('SELECT * FROM ' + t)), key=repr) for t in tables}


def live_lookup():
    return {e['page_url']: (f.CORPUS_DIR / e['file']).read_text(encoding='utf-8')
            for e in MANIFEST['catalogues'] + MANIFEST['corpora']['baseline']}


@pytest.mark.parametrize('failure', ['pagination-loss', 'open-pagination', 'open-card', 'missing-card',
    'missing-number', 'wrong-active', 'wrong-boundary', 'new-page', 'too-many-pages', 'duplicate-product'])
def test_partial_discovery_never_resolves_missing_diagnostics(failure, monkeypatch, pipeline, store):
    pipeline.accept_run(get_adapter(f.SOURCE_KEY).collect('seed-' + failure, OBS))
    before = all_rows(store)
    lookup = live_lookup()
    body = lookup[f.INDEX]
    if failure == 'pagination-loss': body = re.sub(r'<ul class=.*?</ul>', '', body, flags=re.S)
    elif failure == 'open-pagination': body = body.replace('</ul>', '')
    elif failure == 'open-card': body = body.replace('</a>', '', 1)
    elif failure == 'missing-card': body = re.sub(r'<a[^>]*>\s*<h3.*?</h3></a>', '', body, count=1, flags=re.S)
    elif failure == 'missing-number': body = re.sub(r"<li name='dispsy' data2=3.*?</li>", '', body, flags=re.S)
    elif failure == 'wrong-active': body = body.replace('class="active"', '')
    elif failure == 'wrong-boundary': body = body.replace("name='nextli' disabled", "name='nextli'", 1)
    elif failure == 'new-page':
        second = f.BASE + '/product-list-2-2.html'
        lookup[second] = lookup[second].replace("<li class='prev'", "<li name='dispsy' data2=7 id=dis7><a href='/product-list-2-7.html'>7</a></li>\n<li class='prev'")
        # The newly discovered page itself is complete but contradicts the root.
        seventh = lookup[f.BASE + '/product-list-2-6.html']
        seventh = seventh.replace('class="active" ', '').replace("<li class='prev'", "<li name='dispsy' data2=7 id=dis7><a class='active' href='/product-list-2-7.html'>7</a></li>\n<li class='prev'")
        seventh = seventh.replace("data2= 5", "data2= 6").replace("href='/product-list-2-5.html' >Prev", "href='/product-list-2-6.html' >Prev")
        seventh = seventh.replace("href='/product-list-2-6.html' >Next", "href='/product-list-2-7.html' >Next")
        seventh = seventh.replace('/product/', '/product/requalified-').replace('<h3>OK', '<h3>OKFUTURE-')
        lookup[f.BASE + '/product-list-2-7.html'] = seventh
    elif failure == 'too-many-pages':
        extra = ''.join(f"<li><a href='/product-list-2-{n}.html'>{n}</a></li>" for n in range(7, 18))
        body = body.replace("<li class='prev'", extra + "<li class='prev'")
    elif failure == 'duplicate-product':
        second = f.BASE + '/product-list-2-2.html'
        root_card = re.search(r'<a[^>]*>\s*<h3.*?</h3></a>', body, re.S)[0]
        lookup[second] = re.sub(r'<a[^>]*>\s*<h3.*?</h3></a>', lambda _: root_card, lookup[second], count=1, flags=re.S)
    lookup[f.INDEX] = body
    fetched = []
    def fetch(url):
        fetched.append(url)
        return {'text': lookup[url], 'requested_url': url, 'final_url': url}
    monkeypatch.setattr(f, 'fetch', fetch)
    request = f.ForlinxProductAdapter(experimental_live=True).collect('failure-' + failure, OBS)
    assert not request.ok and request.observations == [] and request.diagnostics['errors']
    if failure == 'new-page':
        assert f.BASE + '/product-list-2-7.html' in fetched  # closure, not ignored links
        assert 'page sets at discovery closure' in request.diagnostics['errors'][-1]['error']
    assert pipeline.accept_run(request).status == 'failed'
    after = all_rows(store)
    assert all(after[t] == rows for t, rows in before.items() if t not in {'collector_runs', 'run_errors'})
    assert len(after['collector_runs']) == len(before['collector_runs']) + 1
    assert len(after['run_errors']) == len(before['run_errors']) + 1
    error = json.loads(store.one('SELECT message FROM run_errors WHERE run_id=?', (request.run_id,))[0])
    assert error['diagnostics'] == request.diagnostics


def test_qualified_live_discovery_fetches_exact_closed_catalogue(monkeypatch):
    lookup, fetched = live_lookup(), []
    def fetch(url):
        fetched.append(url)
        return {'text': lookup[url], 'requested_url': url, 'final_url': url}
    monkeypatch.setattr(f, 'fetch', fetch)
    request = f.ForlinxProductAdapter(experimental_live=True).collect('closed', OBS)
    assert request.ok and len(request.diagnostics['documents']) == 59
    assert set(fetched) == set(lookup) and len(fetched) == len(lookup) == 65
    assert len(request.observations) == 57


def test_qualified_catalogue_allows_retained_summary_inside_closed_card():
    html = live_lookup()[f.INDEX]
    # Actual raw OEM cards retain specification markup after their heading;
    # distilled fixtures intentionally omit that non-authoritative summary.
    html = html.replace('</h3></a>', '</h3><div class="stit"><p>CPU: RK3576</p></div></a>')
    cards, pages, excluded = f.catalogue(html, f.INDEX)
    assert len(cards) == 10 and len(pages) == 6 and excluded == []
    with pytest.raises(CollectorError, match='card structure'):
        f.catalogue(html.replace('</div></a>', '</div>', 1), f.INDEX)


@pytest.mark.parametrize('where', ['durable', 'registry'])
@pytest.mark.parametrize('field,value', [('enabled', True), ('promotion_state', 'PROMOTED'),
                                        ('placeholder', True), ('out_of_scope', True)])
@pytest.mark.parametrize('replay', [False, True])
def test_product_freeze_precedes_every_write_and_replay(where, field, value, replay, monkeypatch, pipeline, store):
    request = get_adapter(f.SOURCE_KEY).collect('freeze', OBS)
    if replay: pipeline.accept_run(request)
    if where == 'durable':
        store.execute(f'UPDATE sources SET {field}=? WHERE source_key=?', (value, f.SOURCE_KEY))
        store.commit()
    else:
        records = [r.model_copy(deep=True) for r in sources.load_sources()]
        setattr(next(r for r in records if r.source_key == f.SOURCE_KEY), field, value)
        monkeypatch.setattr(sources, 'load_sources', lambda: records)
    before = all_rows(store)
    with pytest.raises(ValueError, match='source|authority|registry'):
        pipeline.accept_run(request)
    assert before == all_rows(store)


@pytest.mark.parametrize('kind,state,version', [
    ('older', 'MIGRATION_REQUIRED', 2), ('newer', 'INCOMPATIBLE_NEWER', 99),
    ('partial', 'PARTIAL', 3), ('unstamped', 'UNKNOWN', 'UNKNOWN'),
    ('unmarked', 'UNKNOWN', 'UNKNOWN'), ('empty', 'FRESH', 'UNKNOWN'),
    ('corrupt', 'CORRUPT', 'UNKNOWN'), ('malformed-marker', 'UNKNOWN', 'UNKNOWN')])
def test_observer_honest_compatibility_is_read_only(tmp_path, kind, state, version):
    path = tmp_path / (kind + '.sqlite')
    if kind == 'corrupt': path.write_bytes(b'not a database')
    elif kind == 'empty': path.write_bytes(b'')
    else:
        s = Store(path); s.close()
        con = sqlite3.connect(path)
        if kind == 'older': con.execute('DELETE FROM schema_migrations WHERE version>2')
        elif kind == 'newer': con.execute("INSERT INTO schema_migrations(version,applied_at,name) VALUES(99,'future','future')")
        elif kind == 'partial': con.execute('DROP TABLE software_support')
        elif kind == 'unstamped': con.execute('DELETE FROM schema_migrations')
        elif kind == 'unmarked': con.execute('DROP TABLE schema_migrations')
        elif kind == 'malformed-marker':
            con.execute('DROP TABLE schema_migrations'); con.execute('CREATE TABLE schema_migrations (surprise TEXT)')
        con.commit(); con.close()
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    snapshot = full_snapshot(path)
    assert snapshot['status']['state'] == state
    assert snapshot['health']['overall'] == 'degraded'
    assert snapshot['health']['planes']['persistence']['state'] == state
    assert snapshot['schema_revision']['schema_version'] == version
    assert snapshot['schema_revision']['expected_schema_version'] == 3
    assert snapshot['schema_revision']['compatibility_state'] == state
    assert all(value == 'UNKNOWN' for value in snapshot['status']['counts'].values())
    assert snapshot['last_run'] is None and snapshot['source_summary'] == []
    assert snapshot['execution_evidence']['runs'] == 'UNKNOWN'
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert health(path) == snapshot['health'] and status(path) == snapshot['status']
    assert schema_revision(path) == snapshot['schema_revision']


def test_compatible_observer_reports_observed_schema_and_stays_read_only(db_path, store):
    store.close()
    before = db_path.read_bytes()
    snapshot = full_snapshot(db_path)
    assert snapshot['schema_revision']['schema_version'] == 3
    assert snapshot['schema_revision']['applied'][-1]['version'] == 3
    assert snapshot['health']['planes']['persistence']['state'] == 'ok'
    assert db_path.read_bytes() == before


def test_locked_runtime_versions_satisfy_project_requirements():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']
    locks = {Requirement(line).name.lower(): Requirement(line) for line in
             (root / 'requirements.lock').read_text(encoding='utf-8').splitlines()
             if line and not line.startswith('#')}
    for line in project['dependencies']:
        required = Requirement(line)
        locked = locks[required.name.lower()]
        version = next(iter(locked.specifier)).version
        assert required.specifier.contains(version), (required, locked)
