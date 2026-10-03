"""Semantic namespace and first-party linkage laws, entirely offline."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from board_clank.backup import create_backup, restore_backup, sha256_file
from board_clank.cli import main as board_cli
from board_clank.collectors.base import CollectorError
from board_clank.collectors.orange_pi import collect_corpus as orange_corpus
from board_clank.collectors.radxa import collect_corpus
from board_clank.collectors.radxa_documentation import (
    DOCS_URL, KIND, SOURCE_KEY, _BoundedRedirect, _url, accept_documentation,
    fetch_page, main, parse_hardware, record_fetch_failure, register_source, source_definition,
)
from board_clank.compatibility import inspect_path
from board_clank.models import EventRecord, content_hash
from board_clank.observer import full_snapshot
from board_clank.pipeline import Pipeline
from board_clank.store import Store
from board_clank.taxonomy import EntityKind, SourcePlane

HTML = Path("fixtures/radxa_documentation/rock5b-hardware.html").read_text(encoding="utf-8")
OBS = "2026-10-03T07:00:00Z"


def _snapshot(store: Store, *, product_only: bool = False) -> dict:
    tables = [r[0] for r in store.all("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    if product_only:
        tables = ["vendors","board_families","socs","boards","board_revisions","board_variants",
                  "novelty_evidence","notifications","board_classifications","software_support","price_observations"]
    result = {t: [tuple(r) for r in store.all(f"SELECT * FROM {t} ORDER BY rowid")] for t in tables}
    if product_only:
        for t in ("canonical_observations","current_entity_observations","observation_occurrences"):
            result[t] = [tuple(r) for r in store.all(f"SELECT * FROM {t} WHERE entity_kind<>? ORDER BY rowid", (KIND,))]
    return result


@pytest.fixture
def seeded(store: Store) -> Store:
    Pipeline(store).accept_run(collect_corpus("baseline",run_id="product",started_at=OBS))
    register_source(store)
    return store


def _accept(store: Store, run: str = "docs1", html: str = HTML):
    return accept_documentation(store,html,run_id=run,observed_at=OBS)


def _new_revision(html: str) -> str:
    needle = "0.7mm</div>"
    assert needle in html
    return html.replace(needle,"0.7mm<h3 id=new-revision>V1.47</h3><p>New connector package documented.</p></div>")


def test_actual_fixture_retains_seven_revision_assertions_not_seven_artifacts():
    claims,info = parse_hardware(HTML)
    assert info["errors"] == []
    assert info["ignored_models"] == ["ROCK 5B+"]
    assert [c.hardware_label for c in claims] == ["V1.3","V1.41","V1.42","V1.423","V1.44","V1.45","V1.46"]
    assert set(claims[3].artifacts) <= set(claims[2].artifacts)
    assert "changed the package" in claims[-1].notes.lower()
    assert all(c.payload()["effective_at"] == c.payload()["document_revision"] == "UNKNOWN" for c in claims)
    assert all("5b+" not in url for c in claims for url in c.artifacts)
    assert Path("src/board_clank/fixture_data/radxa_documentation/rock5b-hardware.html").read_text(encoding="utf-8") == HTML


def test_historical_backfill_preserves_product_graph_current_novelty_and_outbox(seeded: Store):
    before = _snapshot(seeded,product_only=True)
    result = _accept(seeded)
    assert result["unresolved"] is False and len(result["mappings"]) == 7
    assert {m["board_key"] for m in result["mappings"]} == {"radxa:rock-5b"}
    assert _snapshot(seeded,product_only=True) == before
    rows = seeded.all("SELECT * FROM events WHERE source_key=?", (SOURCE_KEY,))
    assert len(rows) == 7 and all(r["event_type"] == "NEW_REFERENCE" and r["baseline_silent"] == 1 for r in rows)
    assert all(r["entity_kind"] == KIND and r["entity_key"].startswith("reference:") for r in rows)
    assert not seeded.all("SELECT * FROM notifications WHERE event_key IN (SELECT event_key FROM events WHERE source_key=?)", (SOURCE_KEY,))
    for row in rows:
        data = dict(row)
        data["payload"] = json.loads(data.pop("payload_json"))
        assert EventRecord.model_validate(data).entity_kind == EntityKind.DOCUMENTATION_REFERENCE


def test_exact_replay_is_complete_sql_noop(seeded: Store):
    _accept(seeded)
    before = _snapshot(seeded)
    assert _accept(seeded)["replayed"] is True
    assert _snapshot(seeded) == before


def test_stable_separate_passes_only_add_occurrences(seeded: Store):
    _accept(seeded)
    events = seeded.count("events")
    payloads = seeded.count("canonical_observations")
    current = [tuple(r) for r in seeded.all("SELECT * FROM current_entity_observations ORDER BY entity_key")]
    for run in ("docs2","docs3"):
        assert _accept(seeded,run)["events"] == []
    assert seeded.count("events") == events and seeded.count("canonical_observations") == payloads
    assert [tuple(r) for r in seeded.all("SELECT * FROM current_entity_observations ORDER BY entity_key")] == current
    assert seeded.one("SELECT count(*) FROM observation_occurrences WHERE entity_kind=?", (KIND,))[0] == 21


def test_new_historical_revision_after_baseline_remains_reference_and_silent(seeded: Store):
    _accept(seeded)
    before = _snapshot(seeded,product_only=True)
    result = _accept(seeded,"new-revision",_new_revision(HTML))
    assert len(result["events"]) == 1 and len(result["mappings"]) == 8
    assert result["baseline"] is False
    row = seeded.one("SELECT * FROM events WHERE run_id='new-revision'")
    assert row["baseline_silent"] == 1 and row["event_type"] == "NEW_REFERENCE"
    assert _snapshot(seeded,product_only=True) == before


def test_genuine_reference_transition_and_recurrence_are_deterministic(seeded: Store):
    _accept(seeded)
    before = _snapshot(seeded,product_only=True)
    changed = HTML.replace("0.7mm","0.8mm")
    for run,html in (("b1",changed),("a2",HTML),("b2",changed)):
        assert len(_accept(seeded,run,html)["events"]) == 1
    rows = seeded.all("SELECT from_hash,to_hash,event_key,payload_json FROM events WHERE run_id IN ('b1','a2','b2') ORDER BY event_id")
    assert rows[0]["from_hash"] == rows[1]["to_hash"] and rows[0]["to_hash"] == rows[1]["from_hash"]
    assert rows[0]["from_hash"] == rows[2]["from_hash"] and rows[0]["to_hash"] == rows[2]["to_hash"]
    assert len({r["event_key"] for r in rows}) == 3
    assert all(json.loads(r["payload_json"])["transition"] == "reference_evidence_updated" for r in rows)
    assert _snapshot(seeded,product_only=True) == before


def test_duplicate_links_cosmetic_html_heading_anchors_and_download_query_do_not_churn(seeded: Store):
    _accept(seeded)
    link = '<a href=https://dl.radxa.com/rock5/5b/docs/hw/radxa_rock5b_v13_sch.pdf>Alias label</a>'
    cosmetic = HTML.replace('id=v144','id=cosmetic-v144').replace('When EKEY','When   EKEY')
    cosmetic = cosmetic.replace('radxa_rock5b_v13_sch.pdf target','radxa_rock5b_v13_sch.pdf?download=1#pdf target')
    cosmetic = cosmetic.replace('v1.3 SMD pdf</a>', 'v1.3 SMD pdf</a>'+link)
    cosmetic = cosmetic.replace('<body>','<body><nav>Historical announcement: ROCK 5B launched years ago</nav><script>timestamp=123</script>')
    assert parse_hardware(cosmetic)[1]["semantic_hash"] == parse_hardware(HTML)[1]["semantic_hash"]
    assert _accept(seeded,"cosmetic",cosmetic)["events"] == []


@pytest.mark.parametrize("bad",[
    HTML.replace('ROCK 5B<li','ROCK 5B+<li'),
    HTML.replace('ROCK 5B+</ul>','ROCK 5B</ul>'),
    HTML.replace('/rock5/5b/docs/hw/','/rock5/5b+/docs/hw/'),
    HTML.replace('id=hardware-design','id=software'),
    HTML.replace('id=v146>V1.46','id=v146>V1.45'),
    HTML[:HTML.index('0.7mm')],
])
def test_ambiguous_missing_or_wrong_model_structure_fail_closed(seeded: Store,bad: str):
    before = _snapshot(seeded,product_only=True)
    result = _accept(seeded,html=bad)
    assert result["unresolved"] and result["events"] == [] and result["mappings"] == []
    assert _snapshot(seeded,product_only=True) == before
    assert seeded.one("SELECT status FROM diagnostic_conditions WHERE source_key=?",(SOURCE_KEY,))[0] == "OPEN"


def test_missing_product_target_cannot_mint_board(store: Store):
    register_source(store)
    result = _accept(store)
    assert result["unresolved"] and store.count("boards") == 0
    assert not store.one("SELECT * FROM source_baselines WHERE source_key=?", (SOURCE_KEY,))


def test_nonboard_target_cannot_be_used(seeded: Store):
    seeded.execute("UPDATE boards SET board_type='OTHER' WHERE board_key='radxa:rock-5b'")
    before = _snapshot(seeded,product_only=True)
    assert _accept(seeded)["unresolved"]
    assert _snapshot(seeded,product_only=True) == before


def test_another_vendor_same_marketing_name_is_not_linked_or_modified(store: Store):
    Pipeline(store).accept_run(orange_corpus("baseline",run_id="orange",started_at=OBS))
    store.execute("UPDATE boards SET marketing_name='ROCK 5B'")
    register_source(store)
    before = _snapshot(store,product_only=True)
    result = _accept(store)
    assert result["unresolved"] and result["diagnostics"]["mapping"]["eligible_targets"] == []
    assert _snapshot(store,product_only=True) == before


def test_multiple_explicit_product_targets_fail_closed(seeded: Store):
    row = dict(seeded.one("SELECT * FROM boards WHERE board_key='radxa:rock-5b'"))
    row.update(board_key="radxa:rock-5b-duplicate",board_slug="rock-5b-duplicate")
    seeded.execute(f"INSERT INTO boards({','.join(row)}) VALUES ({','.join('?' for _ in row)})",tuple(row.values()))
    old = seeded.one("SELECT * FROM current_entity_observations WHERE entity_kind='BOARD' AND entity_key='radxa:rock-5b'")
    observation = dict(seeded.one("SELECT * FROM canonical_observations WHERE observation_id=?",(old["observation_id"],)))
    observation.pop('observation_id')
    payload = json.loads(observation['payload_json'])
    payload['board_slug'] = row['board_slug']
    observation.update(entity_key=row['board_key'],board_key=row['board_key'],payload_json=json.dumps(payload,sort_keys=True),content_hash=content_hash(payload))
    new_id = seeded.execute(f"INSERT INTO canonical_observations({','.join(observation)}) VALUES ({','.join('?' for _ in observation)})",tuple(observation.values())).lastrowid
    seeded.execute("INSERT INTO current_entity_observations VALUES (?,?,?,?,?,?)",
        ("BOARD",row["board_key"],new_id,observation["content_hash"],OBS,"product"))
    before = _snapshot(seeded,product_only=True)
    result = _accept(seeded)
    assert result["unresolved"] and result["diagnostics"]["mapping"]["reason"] == "multiple PRODUCT targets"
    assert _snapshot(seeded,product_only=True) == before


@pytest.mark.parametrize("url",[
    "http://docs.radxa.com/en/rock5/rock5b/download", "https://docs.radxa.com.evil/en/rock5/rock5b/download",
    "https://docs.radxa.com@evil.test/en/rock5/rock5b/download", "https://docs.radxa.com:443/en/rock5/rock5b/download",
    "https://docs.radxa.com/en/rock5/rock5b/%2e%2e/download", "https://docs.radxa.com/en/rock5/rock5b/../download",
    "https://docs.radxa.com/en/rock5/rock5b/download?model=other", "https://radxa.com/blog/old-launch/",
    "https://wiki.radxa.com/Rock5/hardware/5b-revision", "https://docs.radxa.com/en/rock5/rock5b/download\\evil",
])
def test_malicious_wrong_plane_and_historical_announcement_urls_refused_without_writes(seeded: Store,url: str):
    before = _snapshot(seeded)
    with pytest.raises(CollectorError):
        accept_documentation(seeded,HTML,run_id="bad-url",observed_at=OBS,page_url=url)
    assert _snapshot(seeded) == before


@pytest.mark.parametrize("url",[
    "https://dl.radxa.com.evil/rock5/5b/docs/hw/a.pdf", "https://dl.radxa.com@evil.test/rock5/5b/docs/hw/a.pdf",
    "https://dl.radxa.com:443/rock5/5b/docs/hw/a.pdf", "https://dl.radxa.com/rock5/5b/docs/hw/../a.pdf",
    "https://dl.radxa.com/rock5/5b/docs/hw/%2e%2e/a.pdf", "https://dl.radxa.com/rock5/5b/docs/hw/a.pdf?token=secret",
    "https://dl.radxa.com/rock5/5b+/docs/hw/a.pdf", "https://example.test/a.pdf",
])
def test_unverified_artifact_urls_fail_closed(url: str):
    with pytest.raises(CollectorError):
        _url(url,artifact=True)
    broken = HTML.replace('https://dl.radxa.com/rock5/5b/docs/hw/radxa_rock5b_v13_sch.pdf',url)
    assert parse_hardware(broken)[0] == []


def test_cross_host_redirect_is_rejected_before_following():
    from urllib.request import Request
    with pytest.raises(CollectorError):
        _BoundedRedirect().redirect_request(Request(DOCS_URL),None,302,'Found',{},'https://evil.test/')


def test_live_capture_preserves_exact_response_bytes_and_hash_on_windows(tmp_path: Path,monkeypatch):
    from email.message import Message
    raw = '<html>Radxa\r\nμ\n</html>'.encode('utf-8')
    headers = Message(); headers['Content-Type']='text/html; charset=utf-8'
    class Response:
        url=DOCS_URL; status=200
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self,limit): return raw
    response = Response(); response.headers=headers
    class Opener:
        def open(self,*args,**kwargs): return response
    monkeypatch.setattr('board_clank.collectors.radxa_documentation.build_opener',lambda *args:Opener())
    destination=tmp_path/'response.html'
    text,meta=fetch_page(DOCS_URL,capture_to=destination)
    assert text.encode('utf-8') == destination.read_bytes() == raw
    assert sha256_file(destination) == meta['raw_sha256']
    assert destination.stat().st_size == meta['size']


@pytest.mark.parametrize("charset", ["utf-8-sig", "windows-1252"])
def test_decoded_text_hash_does_not_claim_raw_byte_provenance(tmp_path, monkeypatch, seeded, charset):
    import hashlib
    from email.message import Message
    decoded = HTML.replace('<body>', '<body><nav>café</nav>')
    raw = decoded.encode(charset, errors="xmlcharrefreplace")
    headers = Message()
    headers['Content-Type'] = 'text/html; charset=' + charset
    class Response:
        url = DOCS_URL
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): return raw
    response = Response()
    response.headers = headers
    class Opener:
        def open(self, *args, **kwargs): return response
    monkeypatch.setattr('board_clank.collectors.radxa_documentation.build_opener', lambda *args: Opener())
    destination = tmp_path / 'encoded-response.html'
    text, meta = fetch_page(DOCS_URL, capture_to=destination)
    assert destination.read_bytes() == raw
    assert meta['raw_sha256'] == hashlib.sha256(raw).hexdigest()
    claims, info = parse_hardware(text)
    assert len(claims) == 7 and 'raw_body_hash' not in info
    assert info['decoded_text_sha256'] == hashlib.sha256(text.encode('utf-8')).hexdigest()
    assert info['decoded_text_sha256'] != meta['raw_sha256']
    assert info['semantic_hash'] == parse_hardware(HTML)[1]['semantic_hash']
    _accept(seeded, 'raw-distinct', text)
    assert _accept(seeded, 'raw-original', HTML)['events'] == []
    bad = text.replace('id=hardware-design', 'id=wrong')
    _accept(seeded, 'encoded-unresolved', bad)
    state = seeded.one('SELECT state_hash,transition_count FROM diagnostic_conditions WHERE source_key=?', (SOURCE_KEY,))
    _accept(seeded, 'original-unresolved', HTML.replace('id=hardware-design', 'id=wrong'))
    later = seeded.one('SELECT state_hash,transition_count FROM diagnostic_conditions WHERE source_key=?', (SOURCE_KEY,))
    assert tuple(state) == tuple(later)  # presentation hash is excluded from diagnostic identity


@pytest.mark.parametrize("assignment",["vendor='orange-pi'","plane='PRODUCT'","enabled=1","promotion_state='PROMOTED'","authority='UNVERIFIED'"])
def test_source_validation_never_repairs_or_bypasses_unapproved_state(seeded: Store,assignment: str):
    seeded.execute(f"UPDATE sources SET {assignment} WHERE source_key=?",(SOURCE_KEY,))
    before = _snapshot(seeded)
    with pytest.raises(CollectorError):
        _accept(seeded)
    with pytest.raises(CollectorError):
        register_source(seeded)
    assert _snapshot(seeded) == before


def test_unregistered_source_and_bad_product_provenance_refused_without_writes(store: Store):
    store.execute("DELETE FROM sources WHERE source_key=?", (SOURCE_KEY,))
    store.commit()
    before = _snapshot(store)
    with pytest.raises(CollectorError):
        _accept(store)
    assert _snapshot(store) == before
    register_source(store)
    store.execute("UPDATE sources SET authority='UNVERIFIED' WHERE source_key='radxa-product'")
    with pytest.raises(CollectorError):
        _accept(store)


@pytest.mark.parametrize('assignment',["first_source_key='orange-pi-product'","entity_kind='VARIANT'","content_hash='fakehash'"])
def test_forged_current_product_provenance_is_not_identity_evidence(seeded: Store,assignment: str):
    oid = seeded.one("SELECT observation_id FROM current_entity_observations WHERE entity_kind='BOARD' AND entity_key='radxa:rock-5b'")[0]
    seeded.execute(f"UPDATE canonical_observations SET {assignment} WHERE observation_id=?",(oid,))
    before = _snapshot(seeded,product_only=True)
    assert _accept(seeded)["unresolved"]
    assert _snapshot(seeded,product_only=True) == before


def test_run_id_reuse_conflicts_rejected_and_transaction_failure_rolls_back(seeded: Store,monkeypatch):
    _accept(seeded)
    before = _snapshot(seeded)
    with pytest.raises(CollectorError):
        _accept(seeded,html=_new_revision(HTML))
    with pytest.raises(CollectorError):
        _accept(seeded,"product")
    assert _snapshot(seeded) == before
    original = seeded.execute
    def failing(sql,params=()):
        if 'INSERT INTO events' in sql:
            raise RuntimeError('injected persistence failure')
        return original(sql,params)
    monkeypatch.setattr(seeded,'execute',failing)
    with pytest.raises(RuntimeError):
        _accept(seeded,"rollback",_new_revision(HTML))
    assert _snapshot(seeded) == before


def test_unresolved_diagnostic_replay_resolution_and_fetch_failure_are_honest(seeded: Store):
    bad = HTML.replace('id=hardware-design','id=wrong')
    _accept(seeded,"unresolved1",bad)
    before = _snapshot(seeded)
    assert _accept(seeded,"unresolved1",bad)["replayed"]
    assert _snapshot(seeded) == before
    _accept(seeded,"unresolved2",bad)
    diag = seeded.one("SELECT * FROM diagnostic_conditions WHERE source_key=?",(SOURCE_KEY,))
    assert diag["transition_count"] == 1 and diag["total_occurrences"] == 2
    _accept(seeded,"resolved")
    assert seeded.one("SELECT status FROM diagnostic_conditions WHERE source_key=?",(SOURCE_KEY,))[0] == 'RESOLVED'
    product = _snapshot(seeded,product_only=True)
    record_fetch_failure(seeded,run_id="fetch-failed",observed_at=OBS,error="HTTP 403")
    assert _snapshot(seeded,product_only=True) == product
    assert seeded.one("SELECT status FROM collector_runs WHERE run_id='fetch-failed'")[0] == 'failed'
    assert not seeded.one("SELECT * FROM processed_run_receipts WHERE run_id='fetch-failed'")


def test_legacy_consumers_current_projection_product_replay_and_backup_restore(seeded: Store,db_path: Path,tmp_path: Path,capsys):
    _accept(seeded)
    before_hash = sha256_file(db_path)
    observer = full_snapshot(db_path)
    assert observer["status"]["state"] == "COMPATIBLE"
    assert observer["status"]["schema_version"] == 3
    assert len(observer["source_summary"]) == 17
    assert all(s["enabled"] == 0 and s["promotion_state"] != 'PROMOTED' for s in observer["source_summary"])
    for command in ('report','status','events','source-intel','observe','health','check-state','manifest'):
        args = ['--db',str(db_path),command]
        if command == 'source-intel':
            args += ['--source',SOURCE_KEY]
        assert board_cli(args) == 0
        output = capsys.readouterr().out
        parsed = json.loads(output)
        if command == 'report':
            assert all(not b['board_key'].startswith('reference:') for b in parsed['boards'])
            assert len(parsed['boards']) == seeded.count('boards')
    assert sha256_file(db_path) == before_hash
    assert inspect_path(db_path).state.value == 'COMPATIBLE'
    refs = seeded.all("""SELECT c.entity_key,c.content_hash,o.content_hash AS canonical_hash,o.payload_json
        FROM current_entity_observations c JOIN canonical_observations o ON c.observation_id=o.observation_id
        WHERE c.entity_kind=?""",(KIND,))
    assert len(refs) == 7 and all(r['content_hash'] == r['canonical_hash'] == content_hash(json.loads(r['payload_json'])) for r in refs)
    backup = create_backup(db_path,tmp_path/'backup',name='reference-poc')
    restored = restore_backup(backup.database_path,backup.metadata_path,tmp_path/'restored.db',activate=True)
    assert restored['integrity'] == 'ok'
    with Store(tmp_path/'restored.db',migrate=False) as restore:
        assert _snapshot(restore) == _snapshot(seeded)  # explicitly includes occurrences, omitted by legacy backup metadata
        before = _snapshot(restore)
        assert _accept(restore)["replayed"]
        assert _snapshot(restore) == before
    before = _snapshot(seeded,product_only=True)
    result = Pipeline(seeded).accept_run(collect_corpus('baseline',run_id='product-repeat',started_at=OBS))
    assert result.events == []
    after = _snapshot(seeded,product_only=True)
    after.pop('observation_occurrences'); before.pop('observation_occurrences')
    assert after == before


def test_manual_cli_is_isolated_offline_by_default_and_retains_captures(tmp_path: Path,capsys,monkeypatch):
    def network_forbidden(*args,**kwargs):
        raise AssertionError('network in offline path')
    monkeypatch.setattr('board_clank.collectors.radxa_documentation.fetch_page',network_forbidden)
    root = tmp_path/'new-isolated'
    assert main(['--qualification-root',str(root),'--run-id','offline1']) == 0
    capsys.readouterr()
    assert (root/'offline1/documentation.html').exists() and (root/'offline1/result.json').exists()
    assert main(['--qualification-root',str(root),'--run-id','offline2']) == 0
    assert json.loads((root/'offline2/result.json').read_text(encoding='utf-8'))['events'] == []
    assert main(['--qualification-root',str(root),'--run-id','offline1']) == 2
    existing = tmp_path/'existing'; existing.mkdir()
    assert main(['--qualification-root',str(existing),'--run-id','bad']) == 2
    assert not (existing/'qualification.db').exists()
