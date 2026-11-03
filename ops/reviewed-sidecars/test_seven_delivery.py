"""Synthetic-only qualification. No source collectors or live transport invoked."""
import sys
from pathlib import Path
ROOT=Path('C:/Users/anil/Clanks/_worktrees/hermes-board-eight-20261028')
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests'),str(Path(__file__).parent)]
import json, socket, types, time
from datetime import datetime,timezone,timedelta
import pytest
import board_clank.discord_delivery as native
from board_clank.production_policy import Admission,code_digest,digest
from board_clank.production_runtime import initialize
from board_clank.production_ledger import Ledger,exclusive_lock
from board_clank.source_profiles import SEVEN_SOURCES,SEVEN_PROFILE,EIGHT_SOURCES
from board_clank.store import Store
from test_production_runtime import approval_file as legacy_approval,REV

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a,**k): raise AssertionError('NETWORK DENIED')
    monkeypatch.setattr(socket.socket,'connect',deny)
    monkeypatch.setattr(socket,'create_connection',deny)
    monkeypatch.setattr(native,'post',deny)

@pytest.fixture
def queue(tmp_path):
    # Reuse only the metadata approval producer, not collectors/fixture bodies.
    factory=legacy_approval.__wrapped__
    g=dict(factory.__globals__,SOURCES=SEVEN_SOURCES)
    path=types.FunctionType(factory.__code__,g)(tmp_path)
    raw=json.loads(path.read_text());raw['profile_id']=SEVEN_PROFILE
    # Preserve reviewed uncertainty rather than obtaining green via empty diagnostics.
    dispositions=[]
    for i in range(101):
        key=f'synthetic-condition-{i}';p=path.parent/f'review-{i}.txt';p.write_text('SYNTHETIC retained uncertainty')
        dispositions.append(dict(condition_key=key,source_key=SEVEN_SOURCES[i%7],state_hash='s'*64,
            payload_sha256=digest(b'{}'),decision='accepted_uncertainty',rationale='Synthetic retained uncertainty not natural production credit',reviewed_by='offline',
            evidence=dict(path=p.name,sha256=digest(p.read_bytes()))))
    raw['dispositions']=dispositions;path.write_text(json.dumps(raw))
    a=Admission(path,REV);root=tmp_path/'runtime';initialize(root,a)
    store=Store(root/'board.sqlite',migrate=False);now=time.time()
    stamp=lambda n:datetime.fromtimestamp(n,timezone.utc).isoformat()
    for d in dispositions:
        store.execute('INSERT INTO diagnostic_conditions(condition_key,source_key,plane,diagnostic_type,entity_key,reason,state_hash,payload_json,status,first_observed_at,first_run_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (d['condition_key'],d['source_key'],'PRODUCT','NOVELTY_UNRESOLVED','synthetic','insufficient',d['state_hash'],'{}','OPEN',stamp(now),'synthetic'))
    for source in SEVEN_SOURCES:store.execute('INSERT INTO source_baselines VALUES(?,?,?,?)',(source,'synthetic',stamp(now),1))
    store.execute('INSERT INTO collector_runs(run_id,source_key,collector_key,started_at,finished_at,status,fixture_scenario,error) VALUES(?,?,?,?,?,?,?,?)',('synthetic',SEVEN_SOURCES[0],SEVEN_SOURCES[0],stamp(now),stamp(now),'accepted',None,None))
    def add(key='event',source=SEVEN_SOURCES[0],baseline=0,kind='NEW_BOARD',disposition='PUSH',age=0,revision=REV,channel='outbox'):
        store.execute('INSERT INTO events(event_key,event_type,entity_kind,entity_key,board_key,revision_key,variant_key,source_key,run_id,from_hash,to_hash,baseline_silent,payload_json,created_at,code_revision) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
          (key,kind,'BOARD','synthetic @everyone','board','revision','variant',source,'synthetic','old','new',baseline,'{}',stamp(now-age),revision))
        store.execute('INSERT INTO notifications(event_key,disposition,channel,payload_json,created_at,delivered_at) VALUES(?,?,?,?,?,NULL)',(key,disposition,channel,'{}',stamp(now)))
    ledger=Ledger(root/'operations.sqlite');ledger.claim_cycle('synthetic',a.raw_hash);ledger.finish_cycle('synthetic','COMPLETE')
    secret=native.Secret('https://discord.com/api/webhooks/111111111111111111/SYNTHETIC_ONLY_'+('x'*50))
    policy=native.DeliveryPolicy(enabled=True,revision=REV,destination_sha256=secret.destination,credential_sha256=secret.fingerprint,destination_label='SYNTHETIC',confirmed_by='offline',confirmation_id='SYNTHETIC',not_before=stamp(now-60),expires_at=a.approval.expires_at,event_types=('NEW_BOARD',),max_event_age_seconds=3600,max_messages_per_run=2,min_interval_seconds=1,max_attempts=3)
    yield root,a,store,ledger,secret,policy,add
    store.close()

def invoke(q,**kw):
    from seven_delivery import drain
    root,a,s,l,secret,p,add=q
    return drain(root,a,p,secret,**kw)

def deny(*a,**kw):pytest.fail('unexpected send')

def test_native_reproduces_false_eighth_dependency(queue):
    root,a,s,l,secret,p,add=queue
    with pytest.raises(ValueError,match='eight silent'):native.drain(root,a,p,secret,send=deny)

def test_seven_noop_keeps_101_open_and_legacy_binding(queue):
    before=code_digest()
    assert invoke(queue,send=deny)==[]
    assert native.SOURCES==EIGHT_SOURCES
    assert code_digest()==before
    assert queue[2].one("SELECT count(*) FROM diagnostic_conditions WHERE status='OPEN'")[0]==101

def test_fresh_event_preserved_mentions_and_dedup(queue):
    queue[-1]();calls=[]
    def send(s,p):calls.append(p);return 200,{},b'{"id":"123"}'
    assert invoke(queue,send=send)[0]['status']=='SENT'
    assert calls[0]['allowed_mentions']=={'parse':[]}
    assert invoke(queue,send=deny)==[]

@pytest.mark.parametrize('changes',[dict(baseline=1),dict(age=120),dict(age=4000),dict(age=-20),dict(kind='NOVELTY_UNRESOLVED'),dict(kind='IDENTITY_ANOMALY'),dict(disposition='REVIEW'),dict(revision='b'*40),dict(channel='other'),dict(source=EIGHT_SOURCES[0])])
def test_ineligible_events_never_send(queue,changes):
    queue[-1](**changes);assert invoke(queue,send=deny)==[]

@pytest.mark.parametrize('drift',['excluded-source','diagnostic','baseline','stale','pause','approval'])
def test_native_refusals_preserved(queue,drift):
    root,a,s,l,secret,p,add=queue;add()
    if drift=='excluded-source':s.execute('UPDATE sources SET enabled=1 WHERE source_key=?',(EIGHT_SOURCES[0],))
    elif drift=='diagnostic':s.execute("UPDATE diagnostic_conditions SET state_hash='changed' WHERE condition_key='synthetic-condition-0'")
    elif drift=='baseline':s.execute('DELETE FROM source_baselines WHERE source_key=?',(SEVEN_SOURCES[0],))
    elif drift=='stale':
        with l.connect() as db:db.execute('UPDATE cycles SET finished=?',(time.time()-4000,))
    elif drift=='pause':(root/'PAUSED').write_text('stop')
    else:a.path.write_text('{}')
    with pytest.raises(ValueError):invoke(queue,send=deny)

@pytest.mark.parametrize('status',[500,204,'timeout'])
def test_ambiguity_never_retries(queue,status):
    queue[-1]();calls=[]
    def send(*a):
        calls.append(1)
        if status=='timeout':raise OSError('synthetic')
        return status,{},b''
    assert invoke(queue,send=send)[0]['status']=='UNKNOWN'
    assert invoke(queue,send=send)==[] and len(calls)==1

def test_rate_limit_reused(queue):
    queue[-1]();now=time.time()
    assert invoke(queue,send=lambda *a:(429,{'Retry-After':'65'},b'{"retry_after":65,"global":true}'),clock=lambda:now)[0]['status']=='RETRY'
    assert invoke(queue,send=deny,clock=lambda:now,sleep=deny)==[]

def test_lock_serialization(queue):
    with exclusive_lock(queue[0]/'runtime.lock'):
        with pytest.raises(OSError):invoke(queue,send=deny)

def test_finite_launcher_skips_lock_without_retrying_post(queue,tmp_path,monkeypatch):
    import seven_delivery as seam
    import board_clank.campaign_acceptance as campaign
    root,a,s,l,secret,p,add=queue
    now=float(int(time.time()));p=p.model_copy(update={'expires_at':datetime.fromtimestamp(now+20,timezone.utc).isoformat()})
    policy=tmp_path/'policy.json';policy.write_text(p.model_dump_json())
    receipts=tmp_path/'receipts';receipts.mkdir()
    # Launcher-only scaffolding: not real campaign seal qualification.
    monkeypatch.setattr(seam,'SOURCE_REVISION',REV)
    monkeypatch.setattr(campaign,'baseline_seal',lambda *a:{'last_due_utc':datetime.fromtimestamp(now,timezone.utc).isoformat()})
    monkeypatch.setattr(native,'load_secret',lambda *a:secret)
    tick=[now];calls=[]
    monkeypatch.setattr(seam,'time',types.SimpleNamespace(time=lambda:tick[0],monotonic=lambda:tick[0],time_ns=lambda:int(tick[0]*1e9),sleep=lambda n:tick.__setitem__(0,tick[0]+n)))
    actual=seam.drain
    def attempt(*args,**kwargs):
        calls.append(1)
        if len(calls)==1:raise BlockingIOError(11,'synthetic native lock contention')
        return actual(*args,**kwargs,send=deny)
    monkeypatch.setattr(seam,'drain',attempt)
    argv=['--root',str(root),'--approval',str(a.path),'--policy',str(policy),'--policy-sha256',digest(policy.read_bytes()),'--secret-file',str(tmp_path/'never-read'),'--receipts',str(receipts),'--poll-seconds','10']
    assert seam.main(argv)==0
    assert len(calls)==2
    statuses=[json.loads(f.read_text())['status'] for f in sorted(receipts.glob('*.json'))]
    assert statuses==['SKIPPED_LOCK','DELIVERY_PASS']
