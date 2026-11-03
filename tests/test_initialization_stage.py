"""Additive initialization: synthetic authority/transport, zero operational credit."""
import json
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest
import test_production_runtime as old
from test_seven_source_campaign import seven_file, offline, SEVEN, PROFILE  # noqa: F401
from board_clank.production_policy import digest
from board_clank.production_ledger import Ledger
from board_clank.store import Store
from board_clank import production_runtime as runtime


@pytest.fixture
def staged_root(seven_file, tmp_path):
    raw = json.loads(seven_file.read_text())
    root = tmp_path/'init-runtime'
    now = datetime.now(timezone.utc)
    expiry = (now+timedelta(days=8)).isoformat()
    raw['expires_at'] = expiry
    def proof(name, value):
        p = seven_file.parent/name
        p.write_text(json.dumps(value), encoding='utf-8')
        return {'path': name, 'sha256': digest(p.read_bytes())}
    for b in raw['source_budgets'].values():
        p = seven_file.parent/b['access_evidence']['path']
        v = json.loads(p.read_text()); v['valid_until'] = expiry
        b['access_evidence'] = proof(p.name, v)
    from board_clank.eight_source_campaign import roster_hash
    attempt = str(uuid4())
    slot = now.strftime('%Y%m%dT%H0000Z')
    common = {'attempt_id': attempt, 'root': str(root.resolve()), 'mode': 'SYNTHETIC',
              'evidence_references': ['SYNTHETIC ONLY']}
    spec = dict(common, format=1, profile_id=PROFILE, sources=list(SEVEN),
                roster_sha256=roster_hash(list(SEVEN)), revision=raw['revision'],
                code_sha256=raw['code_sha256'], admitted_at=now.isoformat(), baseline_slot=slot)
    spec.pop('evidence_references')
    spec['scheduler'] = proof('scheduler.json', dict(common, scheduler_id='synthetic', cadence_seconds=3600))
    spec['target'] = proof('target.json', dict(common, revision=raw['revision'], code_sha256=raw['code_sha256'], image_sha256='f'*64))
    raw['campaign'] = proof('campaign.json', spec)
    raw['initialization'] = proof('stage-authority.json', dict(
        format=1, enabled=True, phase='INITIALIZATION_ACQUISITION', attempt_id=attempt,
        root=str(root.resolve()), revision=raw['revision'], code_sha256=raw['code_sha256'],
        image_sha256='f'*64,
        profile_id=PROFILE, sources=list(SEVEN), expires_at=expiry,
        aggregate_reservations=170, predecessor_consumed=1, baseline_reservations=1,
        future_slots=168, predecessor_slot='20260101T000000Z', charged_requests=92,
        reviewers=['SYNTHETIC reviewer'], approved_by='SYNTHETIC owner', decision_id='synthetic-init',
        recovery_sha256=digest(b'SYNTHETIC paired recovery')))
    seven_file.write_text(json.dumps(raw), encoding='utf-8')
    a = old.load(seven_file)
    runtime.initialize(root, a)
    (root/'state-preserving-recovery.json').write_text(json.dumps(dict(
        input_manifest_sha256=digest(b'SYNTHETIC paired recovery'), approval_sha256=a.raw_hash,
        status='PREPARED_PAUSED', requests_retained=92, quota_refund=0,
        old_failed_slot_preserved=True, collection_invoked=False, t0=None)))
    ledger = Ledger(root/'operations.sqlite')
    ledger.claim_cycle('20260101T000000Z', 'predecessor')
    ledger.finish_cycle('20260101T000000Z', 'HUMAN_REQUIRED')
    history = root/'runs'/'20260101T000000Z'; history.mkdir(parents=True)
    (history/'cycle.json').write_text(json.dumps({'status':'HUMAN_REQUIRED', 'mode':'SYNTHETIC predecessor'}))
    with ledger.connect() as db:
        db.executemany('INSERT INTO requests VALUES(?,?,?)', [(SEVEN[0], 1., 'old')]*92)
    folder = root/'scheduler'; folder.mkdir()
    (folder/(slot+'.json')).write_text(json.dumps(dict(attempt_id=attempt, approval_sha256=a.raw_hash,
        scheduler_id='synthetic', slot=slot, dispatch_id=str(uuid4()), dispatched_at=now.isoformat(),
        role='baseline', mode='SYNTHETIC')))
    seen = []
    def collect(root, admission, source, slot, directory):
        from board_clank.collectors import get_adapter
        seen.append(source)
        req = get_adapter(source, corpus='baseline').collect(slot+'-'+source, runtime.stamp())
        req.fixture_scenario = None
        req.observations = [d for d in req.observations if not d.evidence_insufficient and not d.identity_conflict][:1]
        if source == SEVEN[0]:
            req.observations[0].soc_marketing_name = 'UNKNOWN'
            req.observations[0].evidence_insufficient = True
        return req
    return root, a, collect, seen


def test_new_first_source_uncertainty_stages_remaining_six(staged_root):
    root, a, collect, seen = staged_root
    result = runtime.run_stage(root, a, collect=collect)
    assert result['status'] == 'STAGED_PENDING_REVIEW'
    assert seen == list(SEVEN)
    assert result['natural_credit'] == 0 and result['t0'] is None
    assert not (root/'baseline-seal.json').exists()
    with Store(root/'board.sqlite', migrate=False) as store:
        assert store.all("SELECT * FROM diagnostic_conditions WHERE status='OPEN'")
        assert not store.all('SELECT * FROM events WHERE baseline_silent=0')
    with pytest.raises(ValueError):
        runtime.run_stage(root, a, collect=lambda *args: pytest.fail('second stage fetch'))


def exact_review(root, a, stage):
    """Synthetic human decision over exact native state; no validator replacement."""
    from board_clank.campaign_acceptance import file_ref
    review = dict(format=1, reviewed_by='SYNTHETIC reviewer', decision_id='synthetic-exact-review',
                  approval_sha256=a.raw_hash, attempt_id=stage['campaign']['attempt_id'],
                  stage=file_ref(root/'runs'/stage['slot']/'cycle.json', root),
                  store_sha256=stage['store_sha256'], conditions=stage['conditions'], dispositions=[])
    proof = root/'review-evidence.txt'
    proof.write_text('SYNTHETIC exact UNKNOWN facts retained OPEN without alert; no launch truth claimed.')
    for c in stage['conditions']:
        if c['status']=='OPEN':
            review['dispositions'].append(dict(condition_key=c['condition_key'], source_key=c['source_key'],
                state_hash=c['state_hash'], payload_sha256=c['payload_sha256'], decision='accepted_uncertainty',
                rationale='Synthetic unresolved identity remains unknown, no alert and no launch assertion.',
                reviewed_by=review['reviewed_by'], evidence=file_ref(proof, root)))
    path = root/'review.json'; path.write_text(json.dumps(review), encoding='utf-8')
    return path


def test_exact_review_finalizes_without_fetch_or_second_reservation(staged_root):
    from board_clank.campaign_acceptance import finalize_initialization
    root, a, collect, seen = staged_root
    stage = runtime.run_stage(root, a, collect=collect)
    path = exact_review(root, a, stage)
    before = datetime.now(timezone.utc)
    seal = finalize_initialization(root, a, path)
    after = datetime.now(timezone.utc)
    assert before <= datetime.fromisoformat(seal['sealed_utc']) <= after
    assert seal['t0'] is None and seal['natural_credit'] == 0
    assert datetime.fromisoformat(seal['first_due_utc']) == datetime.fromisoformat(seal['sealed_utc'])+timedelta(hours=1)
    assert len(seen) == 7 and seal['collection_invoked'] is False
    with Ledger(root/'operations.sqlite').connect() as db:
        assert db.execute('SELECT COUNT(*) FROM cycles').fetchone()[0] == 2
        assert db.execute('SELECT COUNT(*) FROM requests').fetchone()[0] == 92
        assert db.execute('SELECT status FROM initialization_claims').fetchone()[0] == 'FINALIZED'
    with Store(root/'board.sqlite', migrate=False) as store:
        assert store.all("SELECT * FROM diagnostic_conditions WHERE status='OPEN'")
    with pytest.raises(ValueError):
        finalize_initialization(root, a, path)


def test_finalized_review_allows_only_subsequent_future_hourly_work(staged_root, monkeypatch):
    from board_clank.campaign_acceptance import finalize_initialization, baseline_seal
    root, a, collect, seen = staged_root
    stage = runtime.run_stage(root, a, collect=collect)
    seal = finalize_initialization(root, a, exact_review(root, a, stage))
    with Store(root/'board.sqlite', migrate=False) as store:
        a.check_diagnostics(store)
    with pytest.raises(ValueError):
        runtime.run_once(root, a, collect=lambda *args: pytest.fail('before first due fetch'))
    clock = datetime.fromisoformat(seal['first_due_utc'])+timedelta(seconds=1)
    monkeypatch.setattr(runtime, 'stamp', lambda: clock.isoformat())
    monkeypatch.setattr('board_clank.pipeline._now', lambda: clock.isoformat())
    monkeypatch.setattr('board_clank.production_ledger.time.time', lambda: clock.timestamp())
    slot = clock.strftime('%Y%m%dT%H0000Z')
    (root/'scheduler'/(slot+'.json')).write_text(json.dumps(dict(attempt_id=stage['campaign']['attempt_id'],
        approval_sha256=a.raw_hash, scheduler_id='synthetic', slot=slot, dispatch_id=str(uuid4()),
        dispatched_at=clock.isoformat(), role='scheduled', mode='SYNTHETIC', sequence=1,
        baseline_seal_sha256=digest((root/'baseline-seal.json').read_bytes()))))
    result = runtime.run_once(root, a, collect=collect, now=clock)
    assert result['status'] == 'COMPLETE'
    assert len(seen) == 14 and baseline_seal(root, a) == seal
    from board_clank.campaign_acceptance import reconcile
    report = reconcile(root, a)
    assert report['synthetic_slots'] == 1 and report['natural_credit'] == 0
    assert report['t0'] is None and report['window_complete'] is False


@pytest.mark.parametrize('fault', ['disabled', 'missing-authority', 'wrong-phase', 'overbudget', 'wrong-attempt', 'wrong-image'])
def test_stage_authority_not_a_caller_flag(staged_root, fault):
    from board_clank.campaign_acceptance import identity_for_root
    root, a, collect, seen = staged_root
    raw = json.loads(a.path.read_text())
    p = a.path.parent/raw['initialization']['path']
    spec = json.loads(p.read_text())
    if fault == 'disabled': spec['enabled'] = False
    elif fault == 'wrong-phase': spec['phase'] = 'HOURLY'
    elif fault == 'overbudget': spec['aggregate_reservations'] = 171
    elif fault == 'wrong-attempt': spec['attempt_id'] = str(uuid4())
    elif fault == 'wrong-image': spec['image_sha256'] = '0'*64
    if fault == 'missing-authority': raw.pop('initialization')
    else:
        p.write_text(json.dumps(spec)); raw['initialization']['sha256'] = digest(p.read_bytes())
    a.path.write_text(json.dumps(raw)); a = old.load(a.path)
    # Synthetic independently admitted variant; do not hide behind stale init hash.
    p = root/'initialization-complete.json'; v = json.loads(p.read_text())
    v.update(approval=a.raw_hash, campaign=identity_for_root(root, a)); p.write_text(json.dumps(v))
    with pytest.raises(ValueError): runtime.run_stage(root, a, collect=collect)
    assert not seen
    with Ledger(root/'operations.sqlite').connect() as db:
        assert db.execute('SELECT COUNT(*) FROM cycles').fetchone()[0] == 1


def test_forged_context_does_not_allow_ordinary_unknown(seven_file, tmp_path):
    a = old.load(seven_file); root = tmp_path/'ordinary'; runtime.initialize(root, a)
    with Store(root/'board.sqlite', migrate=False) as store:
        store.execute("INSERT INTO diagnostic_conditions(condition_key,source_key,plane,diagnostic_type,entity_key,reason,state_hash,payload_json,status,first_observed_at,first_run_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            ('synthetic-condition',SEVEN[0],'PRODUCT','NOVELTY_UNRESOLVED','unknown','insufficient','s'*64,'{}','OPEN',runtime.stamp(),'synthetic'))
        with pytest.raises(ValueError): a.check_diagnostics(store)
        a._initialization_context = (root, '20260101T000000Z')
        with pytest.raises(ValueError): a.check_diagnostics(store)
    with pytest.raises(ValueError):
        runtime.run_once(root, a, collect=lambda *args: pytest.fail('forged mode fetched'))


@pytest.mark.parametrize('fault', ['partial', 'corrupt-native', 'foreign-request', 'changed-condition',
    'new-condition', 'missing-disposition', 'wrong-reviewer', 'changed-evidence', 'changed-stage', 'expired-lease', 'old-charge', 'old-history'])
def test_finalize_refuses_unreviewed_or_changed_facts(staged_root, fault, monkeypatch):
    from board_clank import campaign_acceptance as acceptance
    root, a, collect, seen = staged_root
    if fault == 'partial':
        original = collect
        def collect(root, a, source, slot, directory):
            request = original(root, a, source, slot, directory)
            if source == SEVEN[-1]: request.ok = False; request.error = 'synthetic partial'
            return request
    stage = runtime.run_stage(root, a, collect=collect)
    path = exact_review(root, a, stage)
    if fault in {'corrupt-native', 'changed-condition', 'new-condition'}:
        with Store(root/'board.sqlite', migrate=False) as store:
            if fault == 'corrupt-native':
                store.execute("UPDATE collector_runs SET collector_key='foreign' WHERE run_id=?", (stage['slot']+'-'+SEVEN[0],))
            elif fault == 'changed-condition':
                store.execute("UPDATE diagnostic_conditions SET state_hash='changed'")
            else:
                store.execute("INSERT INTO diagnostic_conditions(condition_key,source_key,plane,diagnostic_type,entity_key,reason,state_hash,payload_json,status,first_observed_at,first_run_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    ('new-synthetic-condition',SEVEN[-1],'PRODUCT','NOVELTY_UNRESOLVED','unknown','insufficient','s'*64,'{}','OPEN',runtime.stamp(),'synthetic'))
    elif fault == 'foreign-request':
        ref = stage['sources'][SEVEN[0]]['request']; p = root/ref['path']
        v = json.loads(p.read_text()); v['source_key'] = SEVEN[-1]; p.write_text(json.dumps(v))
    elif fault in {'missing-disposition', 'wrong-reviewer'}:
        v = json.loads(path.read_text())
        if fault == 'missing-disposition': v['dispositions'].clear()
        else: v['reviewed_by'] = 'not approved'
        path.write_text(json.dumps(v))
    elif fault == 'old-charge':
        with Ledger(root/'operations.sqlite').connect() as db:
            db.execute("UPDATE requests SET url_hash='rewritten' WHERE rowid=1")
    elif fault == 'old-history':
        (root/'runs'/'20260101T000000Z'/'cycle.json').write_text('{}')
    elif fault == 'changed-evidence': (root/'review-evidence.txt').write_text('changed')
    elif fault == 'changed-stage':
        p = root/'runs'/stage['slot']/'cycle.json'; p.write_text('{}')
    elif fault == 'expired-lease':
        real = acceptance.datetime
        class Later(real):
            @classmethod
            def now(cls, tz=None): return real.now(tz)+timedelta(days=2)
        monkeypatch.setattr(acceptance, 'datetime', Later)
    with pytest.raises((ValueError, KeyError)):
        acceptance.finalize_initialization(root, a, path)
    assert not (root/'baseline-seal.json').exists() and len(seen) == 7
    with Ledger(root/'operations.sqlite').connect() as db:
        assert db.execute('SELECT COUNT(*) FROM cycles').fetchone()[0] == 2


def test_stage_disabled_source_and_stop_preserve_consumption(staged_root):
    root, a, original, seen = staged_root
    def collect(root, a, source, slot, directory):
        request = original(root, a, source, slot, directory)
        if source == SEVEN[0]:
            with Store(root/'board.sqlite', migrate=False) as store:
                store.execute('UPDATE sources SET enabled=0 WHERE source_key=?', (SEVEN[1],))
        return request
    with pytest.raises(ValueError): runtime.run_stage(root, a, collect=collect)
    assert seen == [SEVEN[0]]
    assert (root/'HUMAN_REQUIRED.json').exists()
    with Ledger(root/'operations.sqlite').connect() as db:
        assert db.execute('SELECT status FROM initialization_claims').fetchone()[0] == 'HUMAN_REQUIRED'


def test_direct_stage_producer_needs_active_authority(staged_root):
    root, a, collect, seen = staged_root
    directory = root/'direct'; directory.mkdir()
    with pytest.raises(ValueError):
        runtime.collect_child(root, a, SEVEN[0], '20260101T000000Z', directory)
    assert not list(directory.iterdir())


def test_request_admission_rechecks_disabled_and_retains_charge(staged_root):
    from board_clank.production_network import Guard
    root, a, collect, seen = staged_root
    stage_slot = json.loads(a.approval.campaign.read(a.path.parent))['baseline_slot']
    ledger = Ledger(root/'operations.sqlite')
    ledger.claim_initialization(stage_slot, a, root)
    a._initialization_context = (root, stage_slot)
    guard = Guard(SEVEN[0], a.approval.source_budgets[SEVEN[0]], ledger, root,
                  admission_check=lambda: runtime.request_admission(root, a, SEVEN[0]))
    guard.reserve(a.approval.source_budgets[SEVEN[0]].origins[0]+'/robots.txt', 0)
    with Store(root/'board.sqlite', migrate=False) as store:
        store.execute('UPDATE sources SET enabled=0 WHERE source_key=?', (SEVEN[0],))
    with pytest.raises(ValueError):
        guard.reserve(a.approval.source_budgets[SEVEN[0]].origins[0]+'/next', 0)
    with ledger.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM requests').fetchone()[0] == 93


def test_normal_once_still_stops_after_new_first_source_condition(seven_file, tmp_path):
    a = old.load(seven_file); root = tmp_path/'ordinary-dynamic'; runtime.initialize(root, a)
    seen = []
    def collect(root, admission, source, slot, directory):
        from board_clank.collectors import get_adapter
        seen.append(source)
        req = get_adapter(source, corpus='baseline').collect(slot+'-'+source, runtime.stamp())
        req.fixture_scenario = None
        req.observations = req.observations[:1]
        req.observations[0].evidence_insufficient = True
        return req
    with pytest.raises(ValueError): runtime.run_once(root, a, collect=collect)
    assert seen == [SEVEN[0]] and (root/'HUMAN_REQUIRED.json').exists()


def test_stage_corrupt_uncertainty_is_not_a_pending_review_exception(staged_root):
    root, a, original, seen = staged_root
    def collect(root, a, source, slot, directory):
        request = original(root, a, source, slot, directory)
        if source == SEVEN[1]:
            with Store(root/'board.sqlite', migrate=False) as store:
                store.execute("UPDATE diagnostic_conditions SET payload_json='{}'")
        return request
    with pytest.raises(ValueError): runtime.run_stage(root, a, collect=collect)
    assert seen == list(SEVEN[:2]) and not (root/'baseline-seal.json').exists()


def test_future_reservation_cap_is_enforced_atomically(staged_root):
    from board_clank.campaign_acceptance import finalize_initialization
    root, a, collect, seen = staged_root
    stage = runtime.run_stage(root, a, collect=collect)
    finalize_initialization(root, a, exact_review(root, a, stage))
    ledger = Ledger(root/'operations.sqlite')
    with ledger.connect() as db:
        db.executemany('INSERT INTO cycles VALUES(?,?,?,?,?)',
                       [('reserved-'+str(i), a.raw_hash, 'INTERRUPTED', 1., 2.) for i in range(168)])
    with pytest.raises(ValueError):
        ledger.claim_scheduled('next', a, root)
    with ledger.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM cycles').fetchone()[0] == 170


@pytest.mark.parametrize('fault', ['lease', 'publisher-budget'])
def test_successor_helper_binds_predecessor_lease_and_caps(staged_root, tmp_path, fault):
    import importlib.util
    import sqlite3
    from contextlib import closing
    from pathlib import Path
    from board_clank.backup import create_backup
    root, a, collect, seen = staged_root
    packet = tmp_path/'paired'; packet.mkdir()
    backup = create_backup(root/'board.sqlite', packet, name='synthetic-pair')
    with closing(sqlite3.connect(root/'operations.sqlite')) as src, closing(sqlite3.connect(packet/'operations.sqlite')) as dst:
        src.backup(dst)
    raw = json.loads(a.path.read_text()); prior = json.loads(a.path.read_text())
    if fault == 'lease': prior['expires_at'] = '2000-01-01T00:00:00+00:00'
    else: prior['source_budgets'][SEVEN[0]]['max_requests_per_cycle'] += 1
    history = packet/'predecessor/approval/approval.json'; history.parent.mkdir(parents=True)
    history.write_text(json.dumps(prior))
    members = {p.relative_to(packet).as_posix(): {'sha256':digest(p.read_bytes()), 'bytes':p.stat().st_size}
               for p in packet.rglob('*') if p.is_file()}
    manifest = dict(files=members, domain=backup.database_path.name, domain_meta=backup.metadata_path.name,
                    operations='operations.sqlite', charged_requests=92, failed_slot='20260101T000000Z',
                    history=['predecessor/approval/approval.json'])
    mp = packet/'recovery-manifest.json'; mp.write_text(json.dumps(manifest))
    target = tmp_path/'new-successor'
    cp = a.path.parent/raw['campaign']['path']; campaign = json.loads(cp.read_text())
    campaign['root'] = str(target.resolve())
    for role in ('scheduler', 'target'):
        p = a.path.parent/campaign[role]['path']; v = json.loads(p.read_text()); v['root'] = str(target.resolve())
        p.write_text(json.dumps(v)); campaign[role]['sha256'] = digest(p.read_bytes())
    cp.write_text(json.dumps(campaign)); raw['campaign']['sha256'] = digest(cp.read_bytes())
    sp = a.path.parent/raw['initialization']['path']; stage = json.loads(sp.read_text())
    stage.update(root=str(target.resolve()), recovery_sha256=digest(mp.read_bytes()))
    sp.write_text(json.dumps(stage)); raw['initialization']['sha256'] = digest(sp.read_bytes())
    a.path.write_text(json.dumps(raw))
    path = Path(__file__).resolve().parents[1]/'scripts/successor_prepare.py'
    spec = importlib.util.spec_from_file_location('owned_successor_prepare', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    module.SOURCE_REVISION = a.revision  # Explicit synthetic candidate identity, not a validator replacement.
    with pytest.raises(ValueError): module.prepare(target, a.path, packet)
    assert not target.exists()


def test_pure_window_kernel_cannot_grant_manual_credit():
    from board_clank.campaign_acceptance import assess_initialized_window
    origin = datetime(2026,1,1,tzinfo=timezone.utc)
    seal = dict(sealed_utc=origin.isoformat(), mode='OPERATIONAL')
    rows = [dict(status='COMPLETE', campaign={'sequence':i},
                 started_utc=(origin+timedelta(hours=i)).isoformat()) for i in range(1,169)]
    report = assess_initialized_window(seal, rows, observed_at=origin+timedelta(seconds=604800))
    assert report['eligible_slots']==168 and report['window_complete'] is True
    assert report['natural_credit']==0 and report['t0'] is None
    assert not assess_initialized_window(seal, rows, observed_at=origin+timedelta(seconds=604799))['window_complete']
    assert not assess_initialized_window(seal, rows[:-1], observed_at=origin+timedelta(days=7))['window_complete']
    with pytest.raises(ValueError): assess_initialized_window(seal, rows+[rows[-1]], observed_at=origin+timedelta(days=7))


def test_stage_doubleclaim_and_actual_reservation_exhaustion(staged_root):
    root, a, collect, seen = staged_root
    with Ledger(root/'operations.sqlite').connect() as db:
        db.execute('INSERT INTO cycles VALUES(?,?,?,?,?)', ('extra', a.raw_hash, 'INTERRUPTED', 1., 2.))
    with pytest.raises(ValueError): runtime.run_stage(root, a, collect=collect)
    assert not seen
