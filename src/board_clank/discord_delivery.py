"""Explicit Board-only delivery. No default destination, credentials or auto-send.

Discord execute uses wait=true. Ambiguous POST outcomes are never auto-retried;
only a definite429 response is retryable. An interrupted claim needs human review.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import json
import math
import multiprocessing
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import time
import threading
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import Field, StrictBool, StrictInt

from board_clank._version import SOURCE_REVISION
from board_clank.production_ledger import Ledger, assert_running, exclusive_lock
from board_clank.production_policy import Admission, SOURCES, StrictModel, utc

EVENTS={'NEW_BOARD','BOARD_REVISION','SOC_CHANGED','PORTS_CHANGED','EOL',
        'NEW_VARIANT','PRICE_CHANGED','IDENTITY_ANOMALY','NOVELTY_UNRESOLVED'}


class Secret:
    def __init__(self,value):
        p=urlsplit(value)
        if (p.scheme!='https' or p.netloc!='discord.com' or p.query or p.fragment
                or not re.fullmatch(r'/api(?:/v10)?/webhooks/[0-9]{15,22}/[A-Za-z0-9_-]{40,150}',p.path)):
            raise ValueError('invalid destination credential shape')
        self._url='https://discord.com/api/v10/webhooks/'+p.path.split('/webhooks/',1)[1]
        self.destination=hashlib.sha256(self._url.encode()).hexdigest()
    def __repr__(self):return '<Secret REDACTED>'
    def __str__(self):return 'REDACTED'


def load_secret(path):
    """Linux runtime secret file, owner-only. No environment/CLI token input."""
    if os.name!='posix':raise ValueError('live secret-file loading requires POSIX owner/mode verification')
    path=Path(path)
    if path.is_symlink():raise ValueError('linked secret refused')
    fd=os.open(path,os.O_RDONLY | getattr(os,'O_NOFOLLOW',0))
    try:
        info=os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid()
                or info.st_mode & 0o077 or info.st_nlink!=1 or info.st_size>2048):
            raise ValueError('secret file must be private, regular and owned by runtime user')
        raw=os.read(fd,2049)
        return Secret(raw.decode('utf-8').strip())
    finally:os.close(fd)


def credential_entry(path):
    """Operator-only interactive secure entry; never invoked by a collector."""
    if os.name!='posix' or not sys.stdin.isatty():
        raise ValueError('secure interactive POSIX terminal required')
    path=Path(path)
    if not path.parent.is_dir() or path.parent.is_symlink():raise ValueError('private operator directory required')
    parent=path.parent.stat()
    if parent.st_uid!=os.geteuid() or parent.st_mode & 0o077:
        raise ValueError('secret directory must be owner-only')
    value=getpass.getpass('Confirmed Board destination credential (hidden): ')
    secret=Secret(value)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            f.write(value+'\n');f.flush();os.fsync(f.fileno())
    finally:value=''
    return {'status':'CONFIGURED_NOT_SENT','destination_sha256':secret.destination}


class DeliveryPolicy(StrictModel):
    enabled: StrictBool = False
    revision: str
    destination_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    destination_label: str = Field(min_length=1,max_length=100)
    confirmed_by: str = Field(min_length=1)
    confirmation_id: str = Field(min_length=1)
    not_before: str
    expires_at: str
    event_types: tuple[str,...]
    max_event_age_seconds: StrictInt = Field(ge=1,le=3600)
    max_messages_per_run: StrictInt = Field(ge=1,le=20)
    min_interval_seconds: float = Field(ge=1,le=60,allow_inf_nan=False)
    max_attempts: StrictInt = Field(ge=1,le=3)

    def validate_active(self,admission,secret,now):
        admission.validate()
        if not self.enabled:raise ValueError('delivery disabled')
        if self.revision!=admission.revision or self.destination_sha256!=secret.destination:
            raise ValueError('delivery destination or candidate mismatch')
        if not self.event_types or len(set(self.event_types))!=len(self.event_types) or not set(self.event_types)<=EVENTS:
            raise ValueError('explicit supported event scope required')
        start,end=utc(self.not_before),utc(self.expires_at)
        if (not start.timestamp()<=now<end.timestamp()
                or start<utc(admission.approval.approved_at) or end>utc(admission.approval.expires_at)):
            raise ValueError('delivery confirmation expired, future or broader than admission')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('delivery redirect refused')


def _perform_post(secret,payload):
    """Private transport, called only by the bounded owned delivery process."""
    req=Request(secret._url+'?wait=true',data=json.dumps(payload).encode('utf-8'),method='POST',
                headers={'Content-Type':'application/json','User-Agent':'BoardClank/1.0'})
    try:
        with build_opener(NoRedirect()).open(req,timeout=15) as response:
            raw=response.read(8193)
            if len(raw)>8192:raise ValueError('delivery acknowledgement exceeds bound')
            return response.status,dict(response.headers),raw
    except HTTPError as exc:
        try:return exc.code,dict(exc.headers),exc.read(8192)
        finally:exc.close()
    except Exception:
        # Suppress URL-bearing urllib/proxy exception text and traceback chaining.
        raise OSError('delivery outcome unknown') from None


def _post_worker(url,payload,connection):
    # The credential is transferred in process memory, never argv/environment.
    # This worker never prints a URL-bearing exception or persists a credential.
    try:
        result=_perform_post(Secret(url),payload)
        result=(result[0],{k:v for k,v in result[1].items() if k.lower() in
            {'retry-after','x-ratelimit-remaining','x-ratelimit-reset-after','x-ratelimit-global'}},result[2])
        connection.send(result)
    except BaseException:
        try:connection.send(None)
        except BaseException:pass
    finally:connection.close()


def post(secret,payload):
    """Hard process deadline also bounds DNS resolution and slow response bodies."""
    ctx=multiprocessing.get_context('spawn')
    reader,writer=ctx.Pipe(duplex=False)
    process=ctx.Process(target=_post_worker,args=(secret._url,payload,writer),name='board-delivery-post')
    started=False;timer=None
    try:
        process.start();started=True;writer.close()
        timer=threading.Timer(15,lambda:process.kill() if process.is_alive() else None)
        timer.daemon=True;timer.start()
        result=reader.recv()
        if result is None:raise OSError('delivery outcome unknown')
        return result
    except Exception:
        raise OSError('delivery outcome unknown') from None
    finally:
        if timer:timer.cancel()
        reader.close();writer.close()
        if started:
            if process.is_alive():process.kill()
            process.join(timeout=2)


def payload_for(row):
    # Do not serialize native captures or arbitrary error text into public messages.
    content=f"Board {row['event_type']}: {row['entity_key']}\nSource: {row['source_key']}\nEvent: {row['event_key']}"
    content=''.join(c for c in content if c in '\n\t' or ord(c)>=32)[:1900]
    return {'content':content,'allowed_mentions':{'parse':[]},'tts':False}


def finite_delay(value):
    number=float(value)
    if not math.isfinite(number) or number<0:raise ValueError('invalid delivery rate delay')
    return number


def drain(root,admission,policy,secret,*,send=post,clock=time.time,sleep=time.sleep):
    """Durable at-most-one ambiguous attempt per event/destination; no fake exactly-once claim."""
    root=Path(root);assert_running(root)
    policy.validate_active(admission,secret,clock())
    ledger=Ledger(root/'operations.sqlite')
    results=[]
    deadline=clock()+60
    # Serialize with collection too, so state and diagnostic review cannot race.
    with exclusive_lock(root/'runtime.lock'):
        assert_running(root)
        from board_clank.store import Store
        store=Store(root/'board.sqlite',migrate=False)
        try:
            admission.check_diagnostics(store)
            marks=','.join('?' for _ in SOURCES)
            if len(store.all(f'SELECT source_key FROM source_baselines WHERE source_key IN ({marks})',SOURCES))!=len(SOURCES):
                raise ValueError('eight silent source baselines required before delivery')
            with ledger.connect() as db:
                latest=db.execute('SELECT * FROM cycles ORDER BY started DESC LIMIT 1').fetchone()
                if (not latest or latest['status']!='COMPLETE' or latest['approval']!=admission.raw_hash
                        or not 0<=clock()-latest['finished']<=3600):
                    raise ValueError('fresh complete production cycle required for delivery')
                if db.execute("SELECT 1 FROM deliveries WHERE destination=? AND status='DISABLED' LIMIT 1",(secret.destination,)).fetchone():
                    raise ValueError('destination disabled after permanent failure')
            placeholders=','.join('?' for _ in policy.event_types)
            rows=store.all(f'''SELECT e.* FROM events e JOIN notifications n ON e.event_key=n.event_key
                WHERE e.source_key IN ({marks}) AND e.event_type IN ({placeholders})
                AND e.baseline_silent=0 AND n.disposition='PUSH' AND n.channel='outbox'
                AND e.code_revision=? ORDER BY e.event_id''',(*SOURCES,*policy.event_types,admission.revision))
            for row in rows:
                now=clock();assert_running(root);policy.validate_active(admission,secret,now)
                event_time=utc(row['created_at']).timestamp()
                if (event_time<utc(policy.not_before).timestamp()
                        or not 0<=now-event_time<=policy.max_event_age_seconds):continue
                if len(results)>=policy.max_messages_per_run:break
                with ledger.connect() as db:
                    limits=db.execute('SELECT MAX(next_at) FROM delivery_limits WHERE destination IN (?,?)',
                                      (secret.destination,'GLOBAL')).fetchone()[0]
                wait=max(0,(limits or now)-now)
                if now+wait+17>=deadline:break
                if wait:
                    sleep(wait);now=clock();assert_running(root);policy.validate_active(admission,secret,now)
                if not 0<=now-event_time<=policy.max_event_age_seconds:continue
                with ledger.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    existing=db.execute('SELECT * FROM deliveries WHERE destination=? AND event_key=?',(secret.destination,row['event_key'])).fetchone()
                    if existing and existing['status']!='RETRY':continue
                    if existing and (existing['next_at']>now or existing['attempts']>=policy.max_attempts):continue
                    attempts=(existing['attempts'] if existing else 0)+1
                    db.execute('INSERT OR REPLACE INTO deliveries(destination,event_key,status,attempts,next_at,message_id) VALUES(?,?,?,?,?,?)',
                               (secret.destination,row['event_key'],'SENDING',attempts,0,None))
                # A crash after this committed claim is deliberately not auto-resubmitted.
                status='UNKNOWN';message_id=None;delay=policy.min_interval_seconds;global_limit=False
                try:
                    code,headers,raw=send(secret,payload_for(row))
                    headers={k.lower():v for k,v in headers.items()}
                    if code==200:
                        ack=json.loads(raw)
                        if not isinstance(ack.get('id'),str) or not re.fullmatch(r'[0-9]{1,22}',ack['id']):
                            raise ValueError('unconfirmed delivery acknowledgement')
                        status='SENT';message_id=ack['id']
                        if headers.get('x-ratelimit-remaining')=='0':
                            delay=max(delay,finite_delay(headers.get('x-ratelimit-reset-after',60)))
                    elif code==429:
                        body=json.loads(raw)
                        delay=max(delay,finite_delay(headers.get('retry-after',body.get('retry_after'))))
                        global_limit=body.get('global') is True
                        status='RETRY' if attempts<policy.max_attempts else 'RATE_LIMITED'
                    elif 400<=code<500:status='DISABLED'
                    # 5xx, redirects,204 and connection failures are ambiguous: no automatic retry.
                except Exception:
                    status='UNKNOWN'
                next_at=clock()+delay
                with ledger.connect() as db:
                    db.execute('UPDATE deliveries SET status=?,next_at=?,message_id=? WHERE destination=? AND event_key=?',
                               (status,next_at,message_id,secret.destination,row['event_key']))
                    db.execute('INSERT OR REPLACE INTO delivery_limits VALUES(?,?)',(secret.destination,next_at))
                    if global_limit:db.execute('INSERT OR REPLACE INTO delivery_limits VALUES(?,?)',('GLOBAL',next_at))
                results.append({'event_key':row['event_key'],'status':status,'message_id':message_id})
                if status!='SENT':break
        finally:store.close()
    return results


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='action',required=True)
    c=sub.add_parser('credential-entry');c.add_argument('--secret-file',type=Path,required=True)
    d=sub.add_parser('deliver');d.add_argument('--root',type=Path,required=True);d.add_argument('--approval',type=Path,required=True)
    d.add_argument('--policy',type=Path,required=True);d.add_argument('--secret-file',type=Path,required=True)
    args=p.parse_args(argv)
    try:
        if args.action=='credential-entry':result=credential_entry(args.secret_file)
        else:
            from board_clank.production_runtime import root_path
            admission=Admission(args.approval,SOURCE_REVISION)
            policy=DeliveryPolicy.model_validate_json(args.policy.read_bytes())
            if not policy.enabled:raise ValueError('delivery disabled')
            result=drain(root_path(args.root),admission,policy,load_secret(args.secret_file))
        print(json.dumps(result,sort_keys=True));return 0
    except Exception as exc:
        print(json.dumps({'status':'REFUSED','error_type':type(exc).__name__,'credential':'REDACTED'}),file=sys.stderr)
        return 2


if __name__=='__main__':raise SystemExit(main())
