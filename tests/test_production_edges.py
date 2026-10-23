"""Additional budget, recovery, diagnostic export and delivery boundaries."""
from datetime import datetime,timezone,timedelta
import hashlib
import json
from pathlib import Path
from urllib import request as http
from urllib.error import HTTPError

import pytest

from test_production_runtime import approval_file,offline_only,load,Response,REV
from test_discord_delivery import queue
from board_clank.collectors.base import CollectorError
from board_clank.production_diagnostics import export
from board_clank.production_ledger import Ledger
from board_clank.production_network import Guard,guarded_http
from board_clank.production_policy import SOURCES
from board_clank.production_runtime import initialize
from board_clank.discord_delivery import drain
from board_clank.store import Store


def test_body_limit_and_url_attempt_cap(approval_file,tmp_path,monkeypatch):
    a=load(approval_file);b=a.approval.source_budgets[SOURCES[0]].model_copy(update={'max_response_bytes':4,'retries':0})
    guard=Guard(SOURCES[0],b,Ledger(tmp_path/'ledger'),tmp_path)
    origin=b.origins[0]
    def fake(opener,req,data=None,timeout=None):
        return Response(req.full_url,b'User-agent: *' if req.full_url.endswith('/robots.txt') else b'12345')
    monkeypatch.setattr(http.OpenerDirector,'open',fake)
    # Robots is subject to the configured byte bound too; no request can run
    # under a truncated/partially parsed robots file.
    with pytest.raises(CollectorError):
        with guarded_http(guard):pytest.fail('truncated policy was accepted')
    assert guard.count==1


def test_definite_get_retry_counts_every_attempt(approval_file,tmp_path,monkeypatch):
    b=load(approval_file).approval.source_budgets[SOURCES[0]]
    t=[0.0];waits=[];calls=[]
    def sleep(n):waits.append(n);t[0]+=n
    guard=Guard(SOURCES[0],b,Ledger(tmp_path/'ledger'),tmp_path,clock=lambda:t[0],sleep=sleep)
    origin=b.origins[0]
    def fake(opener,req,data=None,timeout=None):
        calls.append(req.full_url)
        if req.full_url.endswith('robots.txt'):return Response(req.full_url,b'User-agent: *\nAllow: /')
        if calls.count(req.full_url)==1:raise HTTPError(req.full_url,429,'limited',{'Retry-After':'3'},None)
        return Response(req.full_url,b'ok')
    monkeypatch.setattr(http.OpenerDirector,'open',fake)
    with guarded_http(guard):assert http.build_opener().open(origin+'/product').read()==b'ok'
    assert guard.count==3 and waits==[3]


def test_denied_get_not_retried_and_cycle_budget_exhaustion(approval_file,tmp_path,monkeypatch):
    b=load(approval_file).approval.source_budgets[SOURCES[0]].model_copy(update={'max_requests_per_cycle':2})
    guard=Guard(SOURCES[0],b,Ledger(tmp_path/'ledger'),tmp_path);origin=b.origins[0];calls=[]
    def fake(opener,req,data=None,timeout=None):
        calls.append(req.full_url)
        if req.full_url.endswith('robots.txt'):return Response(req.full_url,b'User-agent: *\nAllow: /')
        raise HTTPError(req.full_url,403,'denied',{},None)
    monkeypatch.setattr(http.OpenerDirector,'open',fake)
    with guarded_http(guard):
        with pytest.raises(CollectorError):http.build_opener().open(origin+'/a')
        with pytest.raises(CollectorError):http.build_opener().open(origin+'/b')
    assert len(calls)==2


def test_diagnostic_export_preserves_database_bytes(approval_file,tmp_path):
    a=load(approval_file);root=tmp_path/'runtime';initialize(root,a)
    store=Store(root/'board.sqlite',migrate=False)
    store.execute("INSERT INTO diagnostic_conditions(condition_key,source_key,plane,diagnostic_type,entity_key,reason,state_hash,payload_json,status,first_observed_at,first_run_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        ('test',SOURCES[0],'PRODUCT','NOVELTY_UNRESOLVED','synthetic','insufficient','s'*64,'{}','OPEN','2026-01-01T00:00:00Z','synthetic'))
    store.close();p=root/'board.sqlite';before=hashlib.sha256(p.read_bytes()).hexdigest()
    report=tmp_path/'conditions.json';result=export(p,report)
    assert result['open_counts']=={'NOVELTY_UNRESOLVED':1}
    assert hashlib.sha256(p.read_bytes()).hexdigest()==before
    assert json.loads(report.read_text())['conditions'][0]['review']['decision']=='UNREVIEWED'
    with pytest.raises(FileExistsError):export(p,report)


def test_approval_mutation_and_fixture_production_bypass_refused(approval_file,tmp_path):
    from board_clank.pipeline import Pipeline
    from board_clank.fixtures import load_scenario,scenario_to_request
    a=load(approval_file);root=tmp_path/'runtime';initialize(root,a)
    store=Store(root/'board.sqlite',migrate=False)
    request=scenario_to_request(load_scenario('M'))[0]
    with pytest.raises(ValueError):Pipeline(store,production_admission=a).accept_fixture_run(request)
    a.approval.gates.pop('locked_ci')
    with pytest.raises(ValueError):a.authorize(SOURCES[0])
    store.close()


def test_non_utc_confirmation_does_not_backfill_old_events(queue):
    root,a,store,ledger,secret,policy,add=queue;add()
    # Same instant represented in another timezone must not change eligibility.
    begin=datetime.now(timezone.utc)+timedelta(seconds=1)
    from datetime import timezone as tz
    p=policy.model_copy(update={'not_before':begin.astimezone(tz(timedelta(hours=-7))).isoformat()})
    with pytest.raises(ValueError):drain(root,a,p,secret,send=lambda *args:pytest.fail('future confirmation'))


def test_stale_cycle_and_delivery_budget(queue):
    root,a,store,ledger,secret,policy,add=queue;add()
    with ledger.connect() as db:db.execute('UPDATE cycles SET finished=0')
    with pytest.raises(ValueError):drain(root,a,policy,secret,send=lambda *args:pytest.fail('stale cycle send'))


def test_current_wix_pattern_and_utf8_bom_are_respected():
    from board_clank.robots_policy import Robots
    wix=Robots('User-agent: *\nAllow: /\nDisallow: *?lightbox=')
    assert wix.allows('https://www.khadas.com/family')
    assert not wix.allows('https://www.khadas.com/family?lightbox=modal')
    assert not Robots('\ufeffUser-agent: *\nDisallow: /').allows('https://example.test/a')


def test_missing_robots_requires_explicit_policy_and_denials_persist(approval_file,tmp_path,monkeypatch):
    b=load(approval_file).approval.source_budgets[SOURCES[0]]
    ledger=Ledger(tmp_path/'ledger');origin=b.origins[0];calls=[]
    def missing(opener,req,data=None,timeout=None):
        calls.append(req.full_url)
        if req.full_url.endswith('/robots.txt'):raise HTTPError(req.full_url,404,'missing',{},None)
        return Response(req.full_url,b'allowed product')
    monkeypatch.setattr(http.OpenerDirector,'open',missing)
    with pytest.raises(CollectorError):
        with guarded_http(Guard(SOURCES[0],b,ledger,tmp_path)):pytest.fail('implicit missing-policy exception')
    opted=b.model_copy(update={'allow_missing_robots':True})
    with guarded_http(Guard(SOURCES[0],opted,ledger,tmp_path)):
        assert http.build_opener().open(origin+'/product').read()==b'allowed product'
    def denied(opener,req,data=None,timeout=None):
        calls.append(req.full_url)
        raise HTTPError(req.full_url,403,'denied',{},None)
    monkeypatch.setattr(http.OpenerDirector,'open',denied)
    with pytest.raises(CollectorError):
        with guarded_http(Guard(SOURCES[0],b,ledger,tmp_path)):pass
    before=len(calls)
    with pytest.raises(ValueError):
        with guarded_http(Guard(SOURCES[0],b,ledger,tmp_path)):pytest.fail('repeated denied source')
    assert len(calls)==before


def test_raw_capture_complete_and_total_byte_budget(approval_file,tmp_path,monkeypatch):
    b=load(approval_file).approval.source_budgets[SOURCES[0]].model_copy(update={'max_total_response_bytes':30})
    origin=b.origins[0]
    def fake(opener,req,data=None,timeout=None):
        return Response(req.full_url,b'User-agent: *' if req.full_url.endswith('/robots.txt') else b'0123456789')
    monkeypatch.setattr(http.OpenerDirector,'open',fake)
    guard=Guard(SOURCES[0],b,Ledger(tmp_path/'ledger'),tmp_path,capture_dir=tmp_path/'bodies')
    with guarded_http(guard):
        assert http.build_opener().open(origin+'/one').read()==b'0123456789'
        with pytest.raises(CollectorError):http.build_opener().open(origin+'/two').read()
    first=guard.requests[1]
    assert first['body_complete'] and first['body_sha256']==hashlib.sha256(b'0123456789').hexdigest()
    assert Path(first['body_file']).read_bytes()==b'0123456789'


def test_mothballed_cli_refuses_before_database_or_adapter(tmp_path,monkeypatch,capsys):
    from board_clank import cli
    monkeypatch.setattr(cli,'get_adapter',lambda *a,**kw:pytest.fail('mothballed live adapter selected'))
    db=tmp_path/'absent.db'
    assert cli.main(['--db',str(db),'collect','--source','hardkernel-odroid-product','--experimental-live'])==2
    assert not db.exists()
    assert json.loads(capsys.readouterr().out)['status']=='refused'


def test_retry_after_starts_at_response_receipt(queue):
    import time
    root,a,store,ledger,secret,policy,add=queue;add();clock=[time.time()]
    began=clock[0]
    def send(*args):
        clock[0]+=10
        return 429,{'Retry-After':'65'},b'{"retry_after":65}'
    assert drain(root,a,policy,secret,send=send,clock=lambda:clock[0])[0]['status']=='RETRY'
    with ledger.connect() as db:
        assert db.execute('SELECT next_at FROM deliveries').fetchone()[0]>=began+75


def test_transport_worker_never_returns_url_bearing_exception(monkeypatch):
    from board_clank import discord_delivery as delivery
    returned=[]
    class Connection:
        def send(self,value):returned.append(value)
        def close(self):pass
    monkeypatch.setattr(delivery,'_perform_post',lambda *args:(_ for _ in ()).throw(OSError('token-bearing SYNTHETIC exception')))
    delivery._post_worker('https://discord.com/api/webhooks/111111111111111111/SYNTHETIC_ONLY_'+('x'*50),{},Connection())
    assert returned==[None]
