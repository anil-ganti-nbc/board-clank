"""Reviewed sidecar seam, not an unchanged native delivery semantic claim.

No installed package edits or process-global source overrides. A private function
binding executes the exact pinned native drain bytecode with admission.sources
in its SOURCES slot. Native admission/state/diagnostic/lock/outbox/transport and
ledger guards remain authoritative. This file grants no delivery permission.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import types

from board_clank import discord_delivery as native
from board_clank._version import SOURCE_REVISION
from board_clank.production_policy import Admission, utc
from board_clank.source_profiles import SEVEN_PROFILE, SEVEN_SOURCES, EIGHT_SOURCES

NATIVE_SHA256='ea706ad3974d5a385125c7fd9d4a246a51452ec599c473ee558d4af3d6954bd2'
ALLOWED_EVENTS=frozenset({'NEW_BOARD','BOARD_REVISION','SOC_CHANGED','PORTS_CHANGED','EOL','NEW_VARIANT','PRICE_CHANGED'})

def drain(root, admission, policy, secret, **kwargs):
    if type(admission) is not Admission:
        raise ValueError('native file-bound Admission required')
    admission.validate()
    if admission.approval.profile_id!=SEVEN_PROFILE or tuple(admission.sources)!=SEVEN_SOURCES:
        raise ValueError('exact seven-source admission required')
    if not policy.event_types or not set(policy.event_types)<=ALLOWED_EVENTS:
        raise ValueError('only approved product event types permitted')
    if (hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest()!=NATIVE_SHA256
            or native.SOURCES!=EIGHT_SOURCES):
        raise ValueError('native delivery binding drift')
    # Private globals dependency injection: do not mutate the module or validators.
    bound=types.FunctionType(native.drain.__code__,dict(native.drain.__globals__,SOURCES=tuple(admission.sources)),
                             native.drain.__name__,native.drain.__defaults__,native.drain.__closure__)
    bound.__kwdefaults__=dict(native.drain.__kwdefaults__)
    return bound(root,admission,policy,secret,**kwargs)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--approval',type=Path,required=True)
    p.add_argument('--policy',type=Path,required=True)
    p.add_argument('--policy-sha256',required=True)
    p.add_argument('--secret-file',type=Path,required=True)
    p.add_argument('--receipts',type=Path,required=True)
    p.add_argument('--poll-seconds',type=int,default=60,choices=range(10,301))
    args=p.parse_args(argv)
    try:
        from board_clank.production_runtime import root_path
        from board_clank.campaign_acceptance import baseline_seal
        root=root_path(args.root)
        a=Admission(args.approval,SOURCE_REVISION)
        raw=args.policy.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=args.policy_sha256:
            raise ValueError('policy bytes changed')
        policy=native.DeliveryPolicy.model_validate_json(raw)
        if not policy.enabled:raise ValueError('delivery disabled')
        seal=baseline_seal(root,a)  # authenticates current durable seal/review, no collection
        end=utc(policy.expires_at).timestamp()
        if (end>utc(seal['last_due_utc']).timestamp()+3300+3600
                or end>utc(a.approval.expires_at).timestamp()):
            raise ValueError('delivery exceeds original campaign completion/freshness or grant')
        # No secret access until explicit active policy and authentic finite native seal.
        secret=native.load_secret(args.secret_file)
        policy.validate_active(a,secret,time.time())
        stop=time.monotonic()+max(0,end-time.time())
        if not args.receipts.is_dir():raise ValueError('existing receipt directory required')
        while time.time()<end and time.monotonic()<stop:
            if args.policy.read_bytes()!=raw:raise ValueError('policy bytes changed')
            try:
                results=drain(root,a,policy,secret)
                status='DELIVERY_PASS'
            except BlockingIOError as exc:
                # Linux nonblocking native runtime.lock contention only. No POST
                # transport exception escapes native drain as BlockingIOError.
                if exc.errno!=11:raise
                results=[];status='SKIPPED_LOCK'
            receipt={'status':status,'at':time.time(),'results':results,'natural_credit':0}
            with (args.receipts/(str(time.time_ns())+'.json')).open('x',encoding='utf-8') as out:
                json.dump(receipt,out,sort_keys=True)
            time.sleep(max(0,min(args.poll_seconds,end-time.time(),stop-time.monotonic())))
        return 0
    except Exception as exc:
        # Never serialize exception messages, URLs, credentials or HTTP responses.
        print(json.dumps({'status':'REFUSED','error_type':type(exc).__name__,'credential':'REDACTED'}),file=sys.stderr)
        return 2

if __name__=='__main__':raise SystemExit(main())
