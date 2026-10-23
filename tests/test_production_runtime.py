"""Synthetic offline production capability tests; no live gate approval is made."""
import copy
from datetime import datetime,timezone,timedelta
import hashlib
import io
import json
from pathlib import Path
import socket
from urllib import request as http

import pytest

from board_clank.collectors import get_adapter
from board_clank.collectors.base import CollectorError
from board_clank.pipeline import Pipeline
from board_clank.production_ledger import Ledger,exclusive_lock
from board_clank.production_network import Guard,guarded_http
from board_clank.production_policy import Admission,Approval,SourceBudget,SOURCES,MOTHBALLED,HOSTS,GATES,code_digest,digest
from board_clank.production_runtime import initialize,run_once
from board_clank.robots_policy import Robots
from board_clank.store import Store

REV='a'*40


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def blocked(*args,**kwargs):raise AssertionError('test attempted live network')
    monkeypatch.setattr(socket.socket,'connect',blocked)
    monkeypatch.setattr('board_clank.pipeline.SOURCE_REVISION',REV)
    monkeypatch.setattr('board_clank.production_runtime.SOURCE_REVISION',REV)


@pytest.fixture
def approval_file(tmp_path):
    folder=tmp_path/'approval';folder.mkdir()
    now=datetime.now(timezone.utc)
    raw={'format':1,'revision':REV,'code_sha256':code_digest(),'approved_by':'SYNTHETIC TEST ONLY',
        'decision_id':'offline-test-not-deployable','approved_at':(now-timedelta(minutes=2)).isoformat(),
        'expires_at':(now+timedelta(hours=1)).isoformat(),'source_budgets':{},'gates':{},'dispositions':[]}
    def evidence(name,value):
        p=folder/name;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps(value),encoding='utf-8')
        return {'path':name,'sha256':digest(p.read_bytes())}
    for source in SOURCES:
        b={'origins':['https://'+sorted(HOSTS[source])[0]],'max_requests_per_cycle':20,
           'max_requests_per_hour':20,'max_requests_per_day':480,'min_interval_seconds':0,
           'timeout_seconds':10,'cycle_timeout_seconds':100,'max_response_bytes':1000000,
           'max_total_response_bytes':20000000,'allow_missing_robots':False,'retries':2}
        ref=evidence(source+'.json',{'source':source,'approved_budget':b,
            'permission_basis':'SYNTHETIC fixture; not source permission','valid_until':raw['expires_at']})
        raw['source_budgets'][source]=dict(b,access_evidence=ref)
    snapshot=evidence('synthetic-diagnostics.json',{'sources':list(SOURCES),'read_only':True,'conditions':[]})
    for gate in GATES:
        proof={'gate':gate,'revision':REV,'code_sha256':raw['code_sha256'],
            'status':'PASS','reviewed_by':'SYNTHETIC TEST ONLY','evidence_references':['offline fixture only']}
        if gate=='diagnostics':proof['diagnostic_snapshot']=snapshot
        raw['gates'][gate]=evidence(gate+'.json',proof)
    path=folder/'approval.json';path.write_text(json.dumps(raw),encoding='utf-8')
    return path


def load(path):return Admission(path,REV)


@pytest.mark.parametrize('mutation',['odroid','missing-source','missing-gate','expired','future','wrong-revision','wrong-code','origin','hourly-budget','deadline','extra-key'])
def test_unverified_scope_budget_and_gates_refused(approval_file,mutation):
    raw=json.loads(approval_file.read_text())
    if mutation=='odroid':raw['source_budgets'][MOTHBALLED]=raw['source_budgets'][SOURCES[0]]
    elif mutation=='missing-source':raw['source_budgets'].pop(SOURCES[0])
    elif mutation=='missing-gate':raw['gates'].pop('locked_ci')
    elif mutation=='expired':raw['expires_at']='2000-01-01T00:00:00+00:00'
    elif mutation=='future':raw['approved_at']='2100-01-01T00:00:00+00:00'
    elif mutation=='wrong-revision':raw['revision']='b'*40
    elif mutation=='wrong-code':raw['code_sha256']='b'*64
    elif mutation=='origin':raw['source_budgets'][SOURCES[0]]['origins']=['https://evil.example']
    elif mutation=='hourly-budget':raw['source_budgets'][SOURCES[0]]['max_requests_per_day']=1
    elif mutation=='deadline':
        for b in raw['source_budgets'].values():b['cycle_timeout_seconds']=1800
    else:raw['automatic_promotion']=True
    approval_file.write_text(json.dumps(raw))
    with pytest.raises(ValueError):load(approval_file)


def test_evidence_hash_and_approval_drift_refused(approval_file):
    admission=load(approval_file)
    (approval_file.parent/'tests.json').write_text('{}')
    with pytest.raises(ValueError):admission.authorize(SOURCES[0])
    with pytest.raises(ValueError):load(approval_file)


def test_init_and_hourly_replay_keep_odroid_mothballed(approval_file,tmp_path):
    admission=load(approval_file);root=tmp_path/'runtime'
    initialize(root,admission)
    seen=[]
    def collect(root,a,source,slot,directory):
        seen.append(source)
        request=get_adapter(source).collect(slot+'-'+source,datetime.now(timezone.utc).isoformat())
        request.fixture_scenario=None
        # Synthetic success path: one resolved fixture record per source. Full
        # live catalogue completeness is a separate, still-unverified gate.
        request.observations=[d for d in request.observations if not d.evidence_insufficient and not d.identity_conflict][:1]
        return request
    result=run_once(root,admission,collect=collect)
    assert result['status']=='COMPLETE',result
    assert seen==list(SOURCES) and MOTHBALLED not in seen
    assert not result['delivery_invoked']
    again=run_once(root,admission,collect=lambda *a:pytest.fail('duplicate acquisition'))
    assert again['status']=='ALREADY_CLAIMED'
    store=Store(root/'board.sqlite',migrate=False)
    assert store.one('SELECT enabled,promotion_state FROM sources WHERE source_key=?',(MOTHBALLED,))['promotion_state']=='MOTHBALLED'
    assert {r['source_key'] for r in store.all('SELECT source_key FROM sources WHERE enabled=1')}==set(SOURCES)
    assert not store.all('SELECT * FROM events WHERE baseline_silent=0')
    request=get_adapter(MOTHBALLED).collect('inert-odroid',datetime.now(timezone.utc).isoformat())
    request.fixture_scenario=None
    with pytest.raises(ValueError):Pipeline(store,production_admission=admission).accept_run(request)
    store.close()
    with pytest.raises(ValueError):initialize(root,admission)


def test_source_failure_does_not_commit_partial_inventory_or_skip_other_sources(approval_file,tmp_path):
    admission=load(approval_file);root=tmp_path/'runtime';initialize(root,admission)
    def collect(root,a,source,slot,directory):
        request=get_adapter(source).collect(slot+'-'+source,datetime.now(timezone.utc).isoformat())
        request.fixture_scenario=None
        request.observations=[d for d in request.observations if not d.evidence_insufficient and not d.identity_conflict][:1]
        if source==SOURCES[0]:request.ok=False;request.error='synthetic late source failure'
        return request
    result=run_once(root,admission,collect=collect)
    assert result['status']=='DEGRADED'
    assert result['sources'][SOURCES[0]]['status']=='FAILED'
    assert sum(r['status']=='ACCEPTED' for r in result['sources'].values())==7
    store=Store(root/'board.sqlite',migrate=False)
    assert not store.all('SELECT * FROM boards WHERE vendor_key=?',('raspberry-pi',))
    store.close()


@pytest.mark.parametrize('marker',['PAUSED','HUMAN_REQUIRED.json'])
def test_emergency_stop_precedes_any_acquisition(approval_file,tmp_path,marker):
    admission=load(approval_file);root=tmp_path/'runtime';initialize(root,admission)
    (root/marker).write_text('do not remove')
    with pytest.raises(ValueError):run_once(root,admission,collect=lambda *a:pytest.fail('acquisition under stop'))
    assert (root/marker).read_text()=='do not remove'


def test_diagnostic_review_is_bound_to_actual_open_state(approval_file,tmp_path):
    admission=load(approval_file);root=tmp_path/'runtime';initialize(root,admission)
    store=Store(root/'board.sqlite',migrate=False)
    # Synthetic condition remains visible; no status or payload is rewritten by review.
    store.execute("INSERT INTO diagnostic_conditions(condition_key,source_key,plane,diagnostic_type,entity_key,reason,state_hash,payload_json,status,first_observed_at,first_run_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        ('test-condition',SOURCES[0],'PRODUCT','NOVELTY_UNRESOLVED','synthetic','insufficient','s'*64,'{}','OPEN','2026-01-01T00:00:00Z','synthetic'))
    with pytest.raises(ValueError):admission.check_diagnostics(store)
    raw=json.loads(approval_file.read_text());proof=approval_file.parent/'review.txt';proof.write_text('SYNTHETIC documented uncertainty, not a correction')
    raw['dispositions']=[{'condition_key':'test-condition','source_key':SOURCES[0],'state_hash':'s'*64,
        'payload_sha256':digest(b'{}'),'decision':'accepted_uncertainty','rationale':'Synthetic missing evidence retained explicitly','reviewed_by':'offline-test',
        'evidence':{'path':'review.txt','sha256':digest(proof.read_bytes())}}]
    approval_file.write_text(json.dumps(raw));admission=load(approval_file)
    admission.check_diagnostics(store)
    assert store.one('SELECT status FROM diagnostic_conditions')[0]=='OPEN'
    store.execute("UPDATE diagnostic_conditions SET state_hash='changed'")
    with pytest.raises(ValueError):admission.check_diagnostics(store)
    store.close()


@pytest.mark.parametrize('text,url,allowed',[
    ('User-agent: *\nDisallow: /*?*','https://example.test/shop?a=1',False),
    ('User-agent: *\nDisallow: /private\nAllow: /private/public','https://example.test/private/public/a',True),
    ('User-agent: *\nDisallow: /a$','https://example.test/ab',True),
    ('User-agent: *\nDisallow: /a$','https://example.test/a',False),
    ('User-agent: *\nDisallow: /%7Eprivate','https://example.test/~private',False),
    ('User-agent: *\nDisallow: /a%2fb','https://example.test/a/b',True),
    ('User-agent: *\nDisallow: /\nUser-agent: BoardClank\nAllow: /','https://example.test/a',True),
])
def test_robots_matching(text,url,allowed):assert Robots(text).allows(url)==allowed


def test_robots_cadence_and_invalid_values():
    assert Robots('User-agent: *\nCrawl-delay: 30\nRequest-rate: 1/60').min_interval==60
    with pytest.raises(ValueError):Robots('User-agent: *\nCrawl-delay: nan')


class Response(io.BytesIO):
    status=200;headers={'Content-Type':'text/plain'}
    def __init__(self,url,body):super().__init__(body);self.url=url
    def geturl(self):return self.url


def test_every_thread_and_redirect_uses_persistent_request_budget(approval_file,tmp_path,monkeypatch):
    a=load(approval_file);source=SOURCES[0];budget=a.approval.source_budgets[source]
    origin=budget.origins[0];seen=[]
    def fake(opener,req,data=None,timeout=None):
        seen.append(req.full_url)
        return Response(req.full_url,b'User-agent: *\nDisallow: /*?*' if req.full_url.endswith('robots.txt') else b'ok')
    monkeypatch.setattr(http.OpenerDirector,'open',fake)
    ledger=Ledger(tmp_path/'ops.db');guard=Guard(source,budget,ledger,tmp_path)
    with guarded_http(guard):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(lambda n:http.build_opener().open(origin+'/product'+str(n)).read(),[1,2]))==[b'ok',b'ok']
        with pytest.raises(CollectorError):http.build_opener().open(origin+'/product?forbidden=1')
        with pytest.raises(CollectorError):http.build_opener().open('https://evil.example/a')
    assert guard.count==3 and len(seen)==3
    with ledger.connect() as db:assert db.execute('SELECT COUNT(*) FROM requests').fetchone()[0]==3


def test_cycle_hour_day_caps_and_clock_rollback(approval_file,tmp_path):
    b=load(approval_file).approval.source_budgets[SOURCES[0]]
    ledger=Ledger(tmp_path/'ops.db')
    for n in range(b.max_requests_per_hour):ledger.reserve(SOURCES[0],b,str(n),now=10000)
    with pytest.raises(ValueError):ledger.reserve(SOURCES[0],b,'x',now=10001)
    with pytest.raises(ValueError):ledger.reserve(SOURCES[0],b,'x',now=9000)


def test_process_lock_cannot_be_taken_twice(tmp_path):
    with exclusive_lock(tmp_path/'runtime.lock'):
        with pytest.raises(OSError):
            with exclusive_lock(tmp_path/'runtime.lock'):pytest.fail('overlap admitted')
