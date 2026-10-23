"""Mock destination only. No credentials or Discord requests are made."""
from datetime import datetime,timezone
import json
import os
import time

import pytest

from test_production_runtime import approval_file,offline_only,REV,load
from board_clank.discord_delivery import Secret,DeliveryPolicy,drain,load_secret,credential_entry,payload_for,NoRedirect
from board_clank.production_runtime import initialize
from board_clank.production_ledger import Ledger
from board_clank.production_policy import SOURCES
from board_clank.store import Store


@pytest.fixture
def queue(approval_file,tmp_path):
    admission=load(approval_file);root=tmp_path/'runtime';initialize(root,admission)
    store=Store(root/'board.sqlite',migrate=False)
    now=datetime.now(timezone.utc).isoformat()
    for source in SOURCES:
        store.execute('INSERT INTO source_baselines VALUES(?,?,?,?)',(source,'synthetic-'+source,now,1))
    run='synthetic-run'
    store.execute('INSERT INTO collector_runs(run_id,source_key,collector_key,started_at,finished_at,status,fixture_scenario,error) VALUES(?,?,?,?,?,?,?,?)',
        (run,SOURCES[0],SOURCES[0],now,now,'accepted',None,None))
    def add(key='test-event',source=SOURCES[0],baseline=0,kind='NEW_BOARD',disposition='PUSH'):
        store.execute('''INSERT INTO events(event_key,event_type,entity_kind,entity_key,board_key,revision_key,variant_key,source_key,run_id,from_hash,to_hash,baseline_silent,payload_json,created_at,code_revision)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (key,kind,'BOARD','synthetic @everyone board','board','revision','variant',source,run,'old','new',baseline,'{}',now,REV))
        store.execute('INSERT INTO notifications(event_key,disposition,channel,payload_json,created_at,delivered_at) VALUES(?,?,?,?,?,NULL)',
            (key,disposition,'outbox','{}',now))
    ledger=Ledger(root/'operations.sqlite');ledger.claim_cycle('synthetic',admission.raw_hash);ledger.finish_cycle('synthetic','COMPLETE')
    # This value is a clearly synthetic mock fixture, never an actual credential.
    secret=Secret('https://discord.com/api/webhooks/111111111111111111/SYNTHETIC_ONLY_'+('x'*50))
    policy=DeliveryPolicy(enabled=True,revision=REV,destination_sha256=secret.destination,
        credential_sha256=secret.fingerprint,
        destination_label='SYNTHETIC mock channel',confirmed_by='offline-test',confirmation_id='SYNTHETIC_ONLY',
        not_before=admission.approval.approved_at,expires_at=admission.approval.expires_at,
        event_types=('NEW_BOARD',),max_event_age_seconds=3600,max_messages_per_run=2,
        min_interval_seconds=1,max_attempts=3)
    yield root,admission,store,ledger,secret,policy,add
    store.close()


def test_secret_redaction_and_canonical_destination():
    first=Secret('https://discord.com/api/webhooks/111111111111111111/SYNTHETIC_ONLY_'+('x'*50))
    second=Secret('https://discord.com/api/v10/webhooks/111111111111111111/SYNTHETIC_ONLY_'+('x'*50))
    assert first.destination==second.destination
    assert first.fingerprint==second.fingerprint
    assert 'SYNTHETIC' not in str(first) and 'SYNTHETIC' not in repr(first)


@pytest.mark.parametrize('value',['http://discord.com/api/webhooks/x/y','https://evil.example/api/webhooks/x/y',
    'https://discord.com@evil.example/api/webhooks/x/y','https://discord.com/api/webhooks/111111111111111111/SYNTHETIC_ONLY_'+('x'*50)+'?wait=true'])
def test_secret_boundary(value):
    with pytest.raises(ValueError):Secret(value)


def test_disabled_delivery_does_not_read_or_send(queue):
    root,a,store,ledger,secret,policy,add=queue;add()
    with pytest.raises(ValueError):drain(root,a,policy.model_copy(update={'enabled':False}),secret,send=lambda *args:pytest.fail('disabled send'))


@pytest.mark.parametrize('drift',['registry','foreign-key'])
def test_delivery_state_preflight_prevents_post(queue,drift):
    root,a,store,ledger,secret,policy,add=queue;add()
    if drift=='registry':store.execute('UPDATE sources SET enabled=0 WHERE source_key=?',(SOURCES[-1],))
    else:
        store.execute('PRAGMA foreign_keys=OFF')
        store.execute('INSERT INTO diagnostic_sightings(condition_key,run_id,source_key,observed_at,state_hash) VALUES(?,?,?,?,?)',
                      ('missing','synthetic',SOURCES[0],'2026-01-01T00:00:00Z','state'))
    with pytest.raises(ValueError):drain(root,a,policy,secret,send=lambda *args:pytest.fail('delivery before state preflight'))
    with ledger.connect() as db:assert db.execute('SELECT COUNT(*) FROM deliveries').fetchone()[0]==0


def test_no_baseline_historical_or_other_source_messages(queue):
    root,a,store,ledger,secret,policy,add=queue
    add('baseline',baseline=1);add('odroid',source='hardkernel-odroid-product');add('review',disposition='REVIEW')
    assert drain(root,a,policy,secret,send=lambda *args:pytest.fail('ineligible message'))==[]


def test_confirmed_message_is_deduplicated_and_mentions_disabled(queue):
    root,a,store,ledger,secret,policy,add=queue;add()
    calls=[]
    def sender(s,p):calls.append(p);return 200,{},b'{"id":"123456789012345678"}'
    result=drain(root,a,policy,secret,send=sender)
    assert result[0]['status']=='SENT' and calls[0]['allowed_mentions']=={'parse':[]}
    assert drain(root,a,policy,secret,send=lambda *args:pytest.fail('duplicate post'))==[]
    assert store.one('SELECT delivered_at FROM notifications')[0] is None  # historical outbox not rewritten


@pytest.mark.parametrize('outcome',[500,204,'timeout','invalid-json'])
def test_ambiguous_post_never_auto_retries(queue,outcome):
    root,a,store,ledger,secret,policy,add=queue;add();calls=[]
    def sender(*args):
        calls.append(1)
        if outcome=='timeout':raise OSError('SYNTHETIC token-bearing exception must not be logged')
        if outcome=='invalid-json':return 200,{},b'not-json'
        return outcome,{},b''
    first=drain(root,a,policy,secret,send=sender)
    assert first[0]['status']=='UNKNOWN'
    assert drain(root,a,policy,secret,send=sender)==[] and len(calls)==1


def test_rate_limit_is_durable_bounded_and_global(queue):
    root,a,store,ledger,secret,policy,add=queue;add();clock=[time.time()]
    now=lambda:clock[0]
    result=drain(root,a,policy,secret,send=lambda *args:(429,{'Retry-After':'65'},b'{"retry_after":65,"global":true}'),clock=now)
    assert result[0]['status']=='RETRY'
    assert drain(root,a,policy,secret,send=lambda *args:pytest.fail('early retry'),clock=now,sleep=lambda n:pytest.fail('unbounded wait'))==[]
    with ledger.connect() as db:assert db.execute("SELECT next_at FROM delivery_limits WHERE destination='GLOBAL'").fetchone()[0]>=clock[0]+65
    clock[0]+=66
    assert drain(root,a,policy,secret,send=lambda *args:(200,{},b'{"id":"123"}'),clock=now)[0]['status']=='SENT'


def test_permanent_denial_disables_destination(queue):
    root,a,store,ledger,secret,policy,add=queue;add()
    assert drain(root,a,policy,secret,send=lambda *args:(404,{},b''))[0]['status']=='DISABLED'
    add('later-event')
    with pytest.raises(ValueError):drain(root,a,policy,secret,send=lambda *args:pytest.fail('denied destination reused'))


def test_interrupted_claim_is_not_auto_resubmitted(queue):
    root,a,store,ledger,secret,policy,add=queue;add()
    with ledger.connect() as db:db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?,?)',(secret.destination,'test-event','SENDING',1,0,None))
    assert drain(root,a,policy,secret,send=lambda *args:pytest.fail('uncertain claim resubmitted'))==[]


def test_changed_scope_destination_stop_or_stale_cycle_blocks(queue):
    root,a,store,ledger,secret,policy,add=queue;add()
    for changed in [policy.model_copy(update={'revision':'b'*40}),policy.model_copy(update={'destination_sha256':'b'*64}),policy.model_copy(update={'event_types':('UNREVIEWED',)})]:
        with pytest.raises(ValueError):drain(root,a,changed,secret,send=lambda *args:pytest.fail('unconfirmed send'))
    (root/'PAUSED').write_text('operator stop')
    with pytest.raises(ValueError):drain(root,a,policy,secret,send=lambda *args:pytest.fail('send while stopped'))


def test_no_noninteractive_credential_entry(tmp_path):
    with pytest.raises(ValueError):credential_entry(tmp_path/'secret')


def test_secret_file_rejects_unsafe_permissions_or_unsupported_platform(tmp_path):
    p=tmp_path/'synthetic';p.write_text('not a credential')
    if os.name=='posix':p.chmod(0o644)
    with pytest.raises(ValueError):load_secret(p)


def test_redirect_never_follows():
    with pytest.raises(ValueError):NoRedirect().redirect_request(None,None,302,'',{},'https://evil.example')
