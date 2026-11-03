"""Seven-source successor. All grants, clocks and transport here are SYNTHETIC."""
import json
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest
import test_production_runtime as old
from board_clank.production_policy import SOURCES, MOTHBALLED, digest

SEVEN = SOURCES[1:]
PROFILE = 'board-seven-production-v1'


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    old.offline_only.__wrapped__(monkeypatch)


@pytest.fixture
def seven_file(tmp_path):
    path = old.approval_file.__wrapped__(tmp_path)
    raw = json.loads(path.read_text())
    raw['profile_id'] = PROFILE
    raw['source_budgets'].pop(SOURCES[0])
    ref = json.loads((path.parent / 'diagnostics.json').read_text())['diagnostic_snapshot']
    snapshot = path.parent / ref['path']
    value = json.loads(snapshot.read_text())
    value['sources'] = list(SEVEN)
    snapshot.write_text(json.dumps(value))
    gate = path.parent / 'diagnostics.json'
    value = json.loads(gate.read_text())
    value['diagnostic_snapshot']['sha256'] = digest(snapshot.read_bytes())
    gate.write_text(json.dumps(value))
    raw['gates']['diagnostics']['sha256'] = digest(gate.read_bytes())
    path.write_text(json.dumps(raw))
    return path


def test_seven_admission_is_explicit_without_reinterpreting_eight(seven_file):
    a = old.load(seven_file)
    assert a.sources == SEVEN
    assert a.approval.profile_id == PROFILE
    for source in (SOURCES[0], MOTHBALLED, 'unknown-product'):
        with pytest.raises(ValueError):
            a.authorize(source)
    from board_clank.production_runtime import manifest
    assert manifest(PROFILE)['sources'] == list(SEVEN)
    assert manifest()['sources'] == list(SOURCES)  # Historical default stays eight.
    assert manifest(PROFILE)['campaign_id'] != manifest()['campaign_id']


@pytest.fixture
def campaign(seven_file, tmp_path, monkeypatch):
    from board_clank.eight_source_campaign import roster_hash
    from board_clank.production_runtime import initialize, run_once
    root = tmp_path / 'seven-runtime'
    raw = json.loads(seven_file.read_text())
    baseline = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    raw['approved_at'] = (baseline - timedelta(minutes=2)).isoformat()
    attempt = str(uuid4())
    def proof(name, value):
        p = seven_file.parent / name
        p.write_text(json.dumps(value))
        return {'path': name, 'sha256': digest(p.read_bytes())}
    common = {'attempt_id': attempt, 'root': str(root.resolve()), 'mode': 'SYNTHETIC',
              'evidence_references': ['SYNTHETIC, not operational authority']}
    spec = dict(common, format=1, profile_id=PROFILE, sources=list(SEVEN),
                roster_sha256=roster_hash(list(SEVEN)), revision=raw['revision'],
                code_sha256=raw['code_sha256'], admitted_at=(baseline-timedelta(minutes=1)).isoformat(),
                baseline_slot=baseline.strftime('%Y%m%dT%H0000Z'))
    spec.pop('evidence_references')
    spec['scheduler'] = proof('scheduler.json', dict(common, scheduler_id='SYNTHETIC', cadence_seconds=3600))
    spec['target'] = proof('target.json', dict(common, revision=raw['revision'], code_sha256=raw['code_sha256']))
    raw['campaign'] = proof('campaign.json', spec)
    seven_file.write_text(json.dumps(raw))
    a = old.load(seven_file)
    initialize(root, a)
    clock = [baseline + timedelta(seconds=5)]
    monkeypatch.setattr('board_clank.production_runtime.stamp', lambda: clock[0].isoformat())
    monkeypatch.setattr('board_clank.pipeline._now', lambda: clock[0].isoformat())
    monkeypatch.setattr('board_clank.production_ledger.time.time', lambda: clock[0].timestamp())
    seen = []
    def tick(hour, fault=None):
        from board_clank.collectors import get_adapter
        clock[0] = baseline + timedelta(hours=hour, seconds=5)
        slot = clock[0].strftime('%Y%m%dT%H0000Z')
        folder = root / 'scheduler'
        folder.mkdir(exist_ok=True)
        p = folder / (slot+'.json')
        if not p.exists():
            p.write_text(json.dumps(dict(attempt_id=attempt, approval_sha256=a.raw_hash,
                scheduler_id='SYNTHETIC', slot=slot, dispatch_id=str(uuid4()),
                dispatched_at=clock[0].isoformat(), role='baseline' if hour == 0 else 'scheduled', mode='SYNTHETIC')))
        def collect(root, admission, source, slot, directory):
            assert source in SEVEN
            seen.append(source)
            request = get_adapter(source, corpus='baseline').collect(slot+'-'+source, clock[0].isoformat())
            request.fixture_scenario = None  # Explicit synthetic transport, never natural.
            request.observations = [r for r in request.observations if not r.evidence_insufficient and not r.identity_conflict][:1]
            if source == SEVEN[0] and fault == 'new-uri':
                request.observations[0].page_url = 'https://www.orangepi.org/synthetic-known-model-new-uri'
            if source == SEVEN[0] and fault == 'signal':
                request.observations[0].spec.ethernet = 'synthetic-changed-2x2.5GbE'
            if source == SEVEN[0] and fault == 'missing-source':
                request.ok = False
                request.error = 'synthetic failure'
            elif source == SEVEN[0] and fault == 'wrong-source':
                request.source_key = SOURCES[0]
            return request
        return run_once(root, a, collect=collect, now=clock[0])
    return root, a, tick, seen


def test_complete_seven_producer_state_reconciler_and_duplicate(campaign):
    from board_clank.campaign_acceptance import reconcile
    from board_clank.store import Store
    root, a, tick, seen = campaign
    first = tick(0)
    assert first['status'] == 'COMPLETE'
    assert set(first['sources']) == set(SEVEN)
    assert seen == list(SEVEN)
    with Store(root/'board.sqlite', migrate=False) as store:
        assert {r[0] for r in store.all('SELECT source_key FROM sources WHERE enabled=1')} == set(SEVEN)
        assert not store.all('SELECT * FROM events WHERE baseline_silent=0')
        for source in (SOURCES[0], MOTHBALLED):
            row = store.one('SELECT enabled,promotion_state FROM sources WHERE source_key=?', (source,))
            assert not row[0] and row[1] == 'MOTHBALLED'
    assert tick(0)['status'] == 'ALREADY_CLAIMED'
    assert seen == list(SEVEN)
    assert tick(1)['status'] == 'COMPLETE'
    report = reconcile(root, a)
    assert report['profile_id'] == PROFILE and report['synthetic_slots'] == 1
    assert report['natural_credit'] == 0 and report['t0'] == 'UNKNOWN_NOT_ACTIVATED'
    assert len(first['sources']) == 7


@pytest.mark.parametrize('fault', ['missing-source', 'wrong-source'])
def test_partial_or_foreign_producer_cannot_count(campaign, fault):
    from board_clank.campaign_acceptance import reconcile
    root, a, tick, seen = campaign
    first = tick(0, fault)
    assert first['status'] == 'DEGRADED'
    assert seen == list(SEVEN)
    with pytest.raises(ValueError):
        reconcile(root, a)


def test_reconciler_refuses_durable_source_provenance_drift(campaign):
    from board_clank.campaign_acceptance import reconcile
    from board_clank.store import Store
    root, a, tick, seen = campaign
    tick(0)
    with Store(root/'board.sqlite', migrate=False) as store:
        store.execute("UPDATE sources SET vendor='foreign' WHERE source_key=?", (SEVEN[0],))
    with pytest.raises(ValueError, match='provenance'):
        reconcile(root, a)


def test_seven_diagnostic_export_matches_admission(campaign, tmp_path):
    from board_clank.production_diagnostics import export
    root, a, tick, seen = campaign
    tick(0)
    path = tmp_path/'seven-diagnostics.json'
    export(root/'board.sqlite', path, profile_id=PROFILE)
    assert json.loads(path.read_text())['sources'] == list(SEVEN)


@pytest.mark.parametrize('mutation', ['missing', 'extra-rpi', 'extra-odroid', 'implicit-eight', 'unknown-profile', 'bad-origin'])
def test_seven_grant_scope_is_exact(seven_file, mutation):
    raw = json.loads(seven_file.read_text())
    if mutation == 'missing':
        raw['source_budgets'].pop(SEVEN[0])
    elif mutation in ('extra-rpi', 'extra-odroid'):
        raw['source_budgets'][SOURCES[0] if mutation == 'extra-rpi' else MOTHBALLED] = raw['source_budgets'][SEVEN[0]]
    elif mutation == 'implicit-eight':
        raw.pop('profile_id')
    elif mutation == 'unknown-profile':
        raw['profile_id'] = 'board-six-production-v1'
    else:
        raw['source_budgets'][SEVEN[0]]['origins'] = ['https://pip.raspberrypi.com']
    seven_file.write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        old.load(seven_file)


@pytest.mark.parametrize('mutation', ['attempt', 'profile', 'roster', 'partial-roster', 'missing-result', 'approval', 'revision', 'native-source', 'source-enabled', 'request-source'])
def test_seven_receipt_and_native_contradictions_fail_closed(campaign, mutation):
    from board_clank.campaign_acceptance import reconcile
    from board_clank.store import Store
    root, a, tick, seen = campaign
    row = tick(0)
    path = root/'runs'/row['slot']/'cycle.json'
    if mutation == 'attempt':
        row['campaign']['attempt_id'] = str(uuid4())
    elif mutation == 'profile':
        row['campaign']['profile_id'] = 'board-eight-production-v1'
    elif mutation == 'roster':
        row['campaign']['sources'].reverse()
    elif mutation == 'partial-roster':
        row['campaign']['sources'].pop()
    elif mutation == 'missing-result':
        row['sources'].pop(SEVEN[-1])
    elif mutation == 'approval':
        row['approval_sha256'] = '0'*64
    elif mutation == 'revision':
        row['revision'] = '0'*40
    elif mutation in ('native-source', 'source-enabled'):
        with Store(root/'board.sqlite', migrate=False) as store:
            if mutation == 'source-enabled':
                store.execute('UPDATE sources SET enabled=1 WHERE source_key=?', (SOURCES[0],))
            else:
                store.execute('UPDATE collector_runs SET collector_key=? WHERE run_id=?',
                              (SOURCES[0], row['slot']+'-'+SEVEN[0]))
    else:
        ref = row['sources'][SEVEN[0]]['request']
        request_path = root/ref['path']
        value = json.loads(request_path.read_text())
        value['source_key'] = SOURCES[0]
        request_path.write_text(json.dumps(value))
        ref['sha256'] = digest(request_path.read_bytes())  # Hash consistency is not authority.
    path.write_text(json.dumps(row))
    with pytest.raises(ValueError):
        reconcile(root, a)


@pytest.mark.parametrize('mutation', ['profile', 'roster', 'order', 'roster-hash', 'attempt', 'revision'])
def test_campaign_config_does_not_reinterpret_old_scope(campaign, mutation):
    root, a, tick, seen = campaign
    raw = json.loads(a.path.read_text())
    path = a.path.parent/raw['campaign']['path']
    spec = json.loads(path.read_text())
    if mutation == 'profile':spec['profile_id'] = 'board-eight-production-v1'
    elif mutation == 'roster':spec['sources'] = list(SOURCES)
    elif mutation == 'order':spec['sources'].reverse()
    elif mutation == 'roster-hash':spec['roster_sha256'] = '0'*64
    elif mutation == 'attempt':spec['attempt_id'] = str(uuid4())
    else:spec['revision'] = '0'*40
    path.write_text(json.dumps(spec))
    raw['campaign']['sha256'] = digest(path.read_bytes())
    a.path.write_text(json.dumps(raw))
    with pytest.raises(ValueError):old.load(a.path)
    assert not seen


def test_seven_history_model_memory_backup_restore_and_signal(campaign, tmp_path):
    from board_clank.backup import create_backup, restore_backup, durable_state_snapshot
    from board_clank.store import Store
    root, a, tick, seen = campaign
    tick(0)
    before = durable_state_snapshot(root/'board.sqlite')
    tick(1, 'new-uri')
    with Store(root/'board.sqlite', migrate=False) as store:
        changes = store.all('SELECT event_type FROM events WHERE baseline_silent=0')
        # A new reference is allowed; it is never a new product/model.
        assert changes and {r[0] for r in changes} == {'NEW_REFERENCE'}
        assert store.count('boards') == int(before['boards'][1])
    backup = create_backup(root/'board.sqlite', tmp_path/'backups')
    restored = restore_backup(backup.database_path, backup.metadata_path, tmp_path/'restored.sqlite')
    assert durable_state_snapshot(restored['staging_path']) == durable_state_snapshot(root/'board.sqlite')
    tick(2, 'signal')
    with Store(root/'board.sqlite', migrate=False) as store:
        assert store.all("SELECT * FROM events WHERE baseline_silent=0 AND event_type='PORTS_CHANGED'")


def test_seven_transport_rejects_excluded_origins_before_request(campaign, monkeypatch):
    from board_clank.production_network import Guard
    from board_clank.production_ledger import Ledger
    from board_clank.collectors.base import CollectorError

    root, a, tick, seen = campaign
    ledger = Ledger(root/'operations.sqlite')
    guard = Guard(SEVEN[0], a.approval.source_budgets[SEVEN[0]], ledger, root)
    for url in ('https://pip.raspberrypi.com/synthetic', 'https://www.hardkernel.com/synthetic'):
        with pytest.raises(CollectorError):
            guard.open(lambda *a, **kw: pytest.fail('excluded transport invoked'), None, url)
    assert guard.count == 0 and guard.requests == []
    with ledger.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM requests').fetchone()[0] == 0


@pytest.mark.parametrize('source', [SOURCES[0], MOTHBALLED])
def test_excluded_child_never_reaches_lookup_or_permit(campaign, monkeypatch, source):
    from board_clank.production_runtime import child
    root, a, tick, seen = campaign
    monkeypatch.setattr('board_clank.collectors.get_adapter', lambda *a, **kw: pytest.fail('excluded adapter lookup'))
    with pytest.raises(ValueError, match='not approved'):
        child(root, a, source, '20261030T040000Z', root/'not-created')
    assert not (root/'operations.sqlite').exists()


@pytest.mark.parametrize('marker', ['PAUSED', 'HUMAN_REQUIRED.json'])
def test_seven_stop_precedes_producer(campaign, marker):
    root, a, tick, seen = campaign
    (root/marker).write_text('owned stop')
    with pytest.raises(ValueError):tick(0)
    assert seen == []


def test_versioned_manifest_and_packaging_closure():
    import tomllib
    from pathlib import Path
    from board_clank.source_profiles import profile_manifest, source_scope
    seven = profile_manifest(PROFILE)
    eight = profile_manifest()
    assert seven['sources'] == [s for s in eight['sources'] if s != SOURCES[0]]
    assert seven['excluded'] == [SOURCES[0]] and seven['mothballed'] == [SOURCES[0], MOTHBALLED]
    assert seven['enabled'] is False and seven['natural_credit'] == 0
    assert seven['acceptance_seconds'] == 604800 and seven['cadence_seconds'] == 3600
    project = tomllib.loads((Path(__file__).resolve().parents[1]/'pyproject.toml').read_text())
    assert {'seven-source-campaign.v1.json', 'eight-source-campaign.v1.json'} <= set(project['tool']['setuptools']['package-data']['board_clank'])
    with pytest.raises(ValueError):source_scope('unknown')


@pytest.mark.parametrize('source', ['raspberry-pi-product', 'raspberry-pi'])
def test_mothballed_rpi_lookup_refuses_before_original_body(source, monkeypatch):
    from board_clank.collectors import get_adapter
    from board_clank.collectors.base import CollectorError
    monkeypatch.setattr('board_clank.collectors.raspberry_pi.RaspberryPiProductAdapter',
                        lambda **kw: pytest.fail('excluded original constructor reached'))
    with pytest.raises(CollectorError, match='mothballed'):
        get_adapter(source, experimental_live=True)


def test_low_level_hold_binding_without_executing_rpi_parser():
    import ast
    from pathlib import Path
    from board_clank.collectors.holds import raspberry_pi_hold
    from board_clank.collectors.base import CollectorError
    tree = ast.parse((Path(__file__).resolve().parents[1]/'src/board_clank/collectors/raspberry_pi.py').read_text())
    guarded = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
               and any(isinstance(d, ast.Name) and d.id == 'raspberry_pi_hold' for d in n.decorator_list)}
    assert guarded == {'fetch_official', 'fetch_official_meta', 'collect', '_collect_live'}
    with pytest.raises(CollectorError, match='mothballed'):
        raspberry_pi_hold(lambda *a: pytest.fail('original body entered'))('synthetic no-source argument')
