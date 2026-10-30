"""One hourly Board cycle. Installation/scheduling is a separate operator action.

No daemon, catch-up campaign, implicit promotion, credential lookup or delivery.
All live acquisition happens in bounded owned subprocesses with source budgets.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import json
import os
import re
import shutil
from pathlib import Path
import subprocess
import sys

from board_clank._version import SOURCE_REVISION
from board_clank.models import CollectorRunRequest
from board_clank.pipeline import Pipeline
from board_clank.production_ledger import Ledger, assert_running, exclusive_lock
from board_clank.production_network import Guard, guarded_http
from board_clank.production_policy import Admission, SOURCES, MOTHBALLED, code_digest, validate_state
from board_clank.sources import sync_sources_to_store
from board_clank.store import Store
from board_clank.campaign_acceptance import identity_for_root, cycle_binding, native_facts, file_ref, captures


def stamp():
    return datetime.now(timezone.utc).isoformat()


def immutable(path, value):
    """Never replace prior cycle/source evidence, including a failed attempt."""
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(value, f, indent=2, sort_keys=True)
        f.flush(); os.fsync(f.fileno())


def root_path(value):
    raw = Path(value).absolute()
    for p in (raw, *raw.parents):
        if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()):
            raise ValueError('linked runtime paths refused')
    return raw.resolve()


def manifest(profile_id='board-eight-production-v1'):
    from board_clank.eight_source_campaign import roster_hash
    from board_clank.source_profiles import profile_manifest, source_scope
    campaign = profile_manifest(profile_id)
    sources = source_scope(profile_id)
    return {'format':1,'component':'board-production-hourly','revision':SOURCE_REVISION,
        'campaign_id':campaign['campaign_id'],'roster_sha256':roster_hash(list(sources)),
        'natural_credit':0,
        'code_sha256':code_digest(),'sources':list(sources),'mothballed':campaign['mothballed'],
        'cadence_seconds':3600,'automatic_installation':False,'activation':'requires explicit hash-bound approval',
        'emergency_stops':['PAUSED','HUMAN_REQUIRED.json'],
        'discord':'separate opt-in command and separate confirmed destination policy; disabled by default'}


def initialize(root, admission):
    assert_running(root)
    admission.validate()
    campaign=identity_for_root(root,admission)
    root.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(root/'runtime.lock'):
        db = root/'board.sqlite'
        if db.exists():
            raise ValueError('initialization never overwrites existing state; use verified distinct staging restore')
        # Reserve identity before creating state; an interrupted init requires inspection.
        immutable(root/'initialization-start.json',{'at':stamp(),'approval':admission.raw_hash,'manifest':manifest(admission.approval.profile_id)})
        store=Store(db)
        try:
            sync_sources_to_store(store)
            from board_clank.production_policy import promote_registry
            promote_registry(store,admission)
            immutable(root/'initialization-complete.json',{'at':stamp(),'approval':admission.raw_hash,'baseline':'pending '+str(len(admission.sources))+' silent source baselines','campaign':campaign})
        finally:store.close()


def child(root, admission, source, slot, directory):
    """Dedicated process: guard all urllib openers, including Forlinx workers."""
    if admission.approval.initialization is not None:
        admission.initialization_spec(root)
        if source not in admission.sources:
            admission.authorize(source)
    else:
        admission.authorize(source)
    assert_running(root)
    token=sys.stdin.buffer.read(129).decode('ascii')
    try:
        with exclusive_lock(root/'runtime.lock'):
            pass
    except OSError:
        pass
    else:
        raise ValueError('source child requires a parent holding the runtime lock')
    Ledger(root/'operations.sqlite').consume_source(slot,source,admission.raw_hash,token,os.getppid())
    if admission.approval.initialization is not None:
        with Ledger(root/'operations.sqlite').connect() as db:
            active = db.execute('SELECT 1 FROM initialization_claims WHERE slot=? AND approval=? AND status=?',
                                (slot, admission.raw_hash, 'RUNNING')).fetchone()
        if active:
            admission._initialization_context = (root, slot)
            admission.stage_active()
    admission.authorize(source)
    # Retained by the child if its parent exits, preventing overlap with a new
    # parent's acquisition while this bounded child finishes.
    with exclusive_lock(root/'source.lock'):
        collect_child(root,admission,source,slot,directory)


def request_admission(root, admission, source):
    assert_running(root)
    admission.authorize(source)
    with Store(root/'board.sqlite',migrate=False) as store:
        validate_state(store,admission)


def collect_child(root, admission, source, slot, directory):
    request_admission(root, admission, source)
    with Store(root/'board.sqlite',migrate=False) as store:
        validate_state(store,admission)
    budget=admission.approval.source_budgets[source]
    guard=Guard(source,budget,Ledger(root/'operations.sqlite'),root,capture_dir=directory/(source+'-http'),
                admission_check=lambda: request_admission(root, admission, source))
    from board_clank.collectors import get_adapter
    try:
        with guarded_http(guard):
            request=get_adapter(source,experimental_live=True,
                capture_dir=directory/'captures' if source=='forlinx-product' else None).collect(slot+'-'+source,stamp())
        immutable(directory/(source+'.request.json'),request.model_dump(mode='json'))
    finally:
        immutable(directory/(source+'.http.json'),{'source':source,'requests':guard.requests,
            'request_count':guard.count,'response_bytes':guard.bytes,'robots':guard.robots_records,
            'budget':budget.model_dump(),'at':stamp()})


def execute_child(root, admission, source, slot, directory):
    budget=admission.approval.source_budgets[source]
    command=[sys.executable,'-B','-m','board_clank.production_runtime','--root',str(root),
        '--approval',str(admission.path),'child','--source',source,'--slot',slot]
    env={k:v for k,v in os.environ.items() if not any(secret in k.upper() for secret in ('DISCORD','WEBHOOK','TOKEN','PASSWORD','SECRET'))}
    env['PYTHONDONTWRITEBYTECODE']='1'
    permit=Ledger(root/'operations.sqlite').issue_source(slot,source,admission.raw_hash)
    with (directory/(source+'.stdout')).open('xb') as stdout, (directory/(source+'.stderr')).open('xb') as stderr:
        process=subprocess.Popen(command,env=env,stdin=subprocess.PIPE,stdout=stdout,stderr=stderr)
        try:
            process.stdin.write(permit.encode('ascii'))
            process.stdin.close()
        except (OSError, BrokenPipeError):
            process.stdin.close()
        try:code=process.wait(timeout=budget.cycle_timeout_seconds+10)
        except subprocess.TimeoutExpired:
            process.kill();process.wait(timeout=15)
            raise ValueError('owned source child exceeded deadline') from None
    if code!=0:raise ValueError('source child failed: '+str(code))
    path=directory/(source+'.request.json')
    if path.stat().st_size>64_000_000:raise ValueError('source request receipt exceeds bound')
    return CollectorRunRequest.model_validate_json(path.read_bytes())


def run_stage(root, admission, *, collect=execute_child, now=None):
    return run_once(root, admission, collect=collect, now=now, initialization_stage=True)


def run_once(root, admission, *, collect=execute_child, now=None, initialization_stage=False):
    native_execution=collect is execute_child and now is None
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError('UTC-aware cycle time required')
    slot=now.astimezone(timezone.utc).strftime('%Y%m%dT%H0000Z')
    assert_running(root)
    admission.validate()
    stage_spec = admission.initialization_spec(root) if initialization_stage else None
    if not initialization_stage and admission.approval.initialization is not None:
        from board_clank.campaign_acceptance import baseline_seal
        baseline_seal(root, admission)
    if not (root/'initialization-complete.json').exists():raise ValueError('production root not initialized')
    with exclusive_lock(root/'runtime.lock'):
        assert_running(root)
        admission.validate()
        if initialization_stage:
            campaign=cycle_binding(root,admission,slot,native_execution=native_execution,stage=True)
        else:
            if getattr(admission, '_initialization_context', None) is not None:
                raise ValueError('ordinary once cannot use staging context')
            campaign=cycle_binding(root,admission,slot,native_execution=native_execution)
            if admission.approval.initialization is not None:
                from board_clank.campaign_acceptance import baseline_seal
                from board_clank.production_policy import utc
                seal = baseline_seal(root, admission)
                due = utc(seal['sealed_utc'])+timedelta(hours=campaign['sequence'])
                if not due <= now < due+timedelta(hours=1):
                    raise ValueError('hourly work not yet due or stale; no catchup')
        initialized=json.loads((root/'initialization-complete.json').read_bytes())
        if initialized.get('campaign') != identity_for_root(root,admission) or initialized['approval'] != admission.raw_hash:
            raise ValueError('attempt/admission differs from initialized root')
        required=sum(b.max_total_response_bytes for b in admission.approval.source_budgets.values())+64_000_000
        if shutil.disk_usage(root).free<required:raise ValueError('insufficient free space for bounded retained source evidence')
        ledger=Ledger(root/'operations.sqlite')
        if initialization_stage:
            ledger.claim_initialization(slot, admission, root)
            admission._initialization_context = (root, slot)
            admission.stage_active()
        elif not (ledger.claim_scheduled(slot, admission, root) if admission.approval.initialization is not None
                  else ledger.claim_cycle(slot,admission.raw_hash)):
            return {'status':'ALREADY_CLAIMED','slot':slot,'collection_invoked':False}
        directory=root/'runs'/slot
        directory.mkdir(parents=True,exist_ok=False)
        receipt={'slot':slot,'started_utc':stamp(),'revision':SOURCE_REVISION,'approval_sha256':admission.raw_hash,
                 'sources':{},'delivery_invoked':False,'campaign':campaign}
        if initialization_stage:
            from board_clank.campaign_acceptance import predecessor_custody
            receipt.update(phase='INITIALIZATION_ACQUISITION', t0=None, natural_credit=0,
                           stage_authority=admission.approval.initialization.model_dump(),
                           recovery_sha256=stage_spec.recovery_sha256,
                           predecessor_custody=predecessor_custody(root, stage_spec))
        store=None
        try:
            store=Store(root/'board.sqlite',migrate=False)
            validate_state(store,admission)
            pipeline=Pipeline(store,production_admission=admission)
            for source in admission.sources:
                assert_running(root)
                admission.authorize(source)
                # Recheck global state outside per-source failure isolation.
                validate_state(store,admission)
                try:
                    request=collect(root,admission,source,slot,directory)
                    if (request.run_id!=slot+'-'+source or request.source_key!=source
                            or request.collector_key!=source or request.fixture_scenario is not None):
                        raise ValueError('source receipt binding mismatch')
                    result=pipeline.accept_run(request)
                    status='ACCEPTED' if result.status in {'accepted','replayed'} else 'FAILED'
                    receipt['sources'][source]={'status':status,'result':result.as_dict()}
                    if result.status == 'accepted':
                        request_path=directory/(source+'.accepted-request.json')
                        immutable(request_path,request.model_dump(mode='json'))
                        receipt['sources'][source].update(native=native_facts(store,request),
                            request=file_ref(request_path,root))
                        if native_execution:
                            receipt['sources'][source]['captures']=captures(root,directory,source)
                    # New/changed uncertain evidence remains in canonical diagnostics,
                    # but prevents any delivery or further acceptance declaration.
                    admission.check_diagnostics(store)
                except Exception as exc:
                    receipt['sources'][source]={'status':'FAILED','error_type':type(exc).__name__}
                    immutable(directory/(source+'.failure.json'),{'at':stamp(),'error_type':type(exc).__name__,
                        'reason':'source failure; inspect bounded public source receipts locally'})
                with ledger.connect() as db:
                    db.execute('INSERT INTO source_runs VALUES(?,?,?,?)',
                        (slot,source,receipt['sources'][source]['status'],str(directory)))
            receipt['status']='COMPLETE' if all(r['status']=='ACCEPTED' for r in receipt['sources'].values()) else 'DEGRADED'
            if initialization_stage:
                from board_clank.campaign_acceptance import store_fingerprint, condition_facts
                receipt['status'] = 'STAGED_PENDING_REVIEW' if receipt['status']=='COMPLETE' else 'STAGE_FAILED'
                receipt.update(store_sha256=store_fingerprint(store), conditions=condition_facts(store))
            receipt['integrity']=store.one('PRAGMA integrity_check')[0]
            receipt['foreign_key_errors']=len(store.all('PRAGMA foreign_key_check'))
            if receipt['integrity']!='ok' or receipt['foreign_key_errors']:
                raise ValueError('production state integrity failure')
        except Exception as exc:
            receipt.update(status='HUMAN_REQUIRED',error_type=type(exc).__name__)
            if not (root/'HUMAN_REQUIRED.json').exists():
                immutable(root/'HUMAN_REQUIRED.json',{'at':stamp(),'slot':slot,'reason':'runtime integrity/approval failure; inspect retained receipts'})
            raise
        finally:
            if store:store.close()
            receipt['finished_utc']=stamp()
            immutable(directory/'cycle.json',receipt)
            ledger.finish_cycle(slot,receipt.get('status','INTERRUPTED'))
            if initialization_stage:
                ledger.finish_initialization(stage_spec.attempt_id, receipt.get('status','INTERRUPTED'))
                del admission._initialization_context
        return receipt


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--approval',type=Path,required=True)
    sub=p.add_subparsers(dest='action',required=True)
    for action in ('check','init','once','stage','reconcile'):sub.add_parser(action)
    f=sub.add_parser('finalize'); f.add_argument('--review', type=Path, required=True)
    c=sub.add_parser('child');c.add_argument('--source',choices=SOURCES,required=True);c.add_argument('--slot',required=True)
    args=p.parse_args(argv)
    try:
        root=root_path(args.root)
        admission=Admission(args.approval,SOURCE_REVISION)
        if args.action!='reconcile':
            assert_running(root)
        if args.action=='check':result={'status':'CONFIG_VALID','manifest':manifest(admission.approval.profile_id),'collection_invoked':False}
        elif args.action=='reconcile':
            from board_clank.campaign_acceptance import reconcile
            result=reconcile(root,admission)
        elif args.action=='init':initialize(root,admission);result={'status':'INITIALIZED','collection_invoked':False}
        elif args.action=='stage':result=run_stage(root, admission)
        elif args.action=='finalize':
            from board_clank.campaign_acceptance import finalize_initialization
            result=finalize_initialization(root, admission, args.review)
        elif args.action=='child':
            if not re.fullmatch(r'\d{8}T\d{2}0000Z',args.slot):raise ValueError('invalid child slot')
            directory=root/'runs'/args.slot
            if not directory.is_dir():raise ValueError('child directory absent')
            child(root,admission,args.source,args.slot,directory);result={'status':'CHILD_COMPLETE'}
        else:result=run_once(root,admission)
        print(json.dumps(result,sort_keys=True));return 0 if result.get('status') not in {'DEGRADED','STAGE_FAILED'} else 1
    except Exception as exc:
        print(json.dumps({'status':'REFUSED','error_type':type(exc).__name__,'collection_or_delivery_claimed':'UNKNOWN',
                          'evidence':'inspect retained cycle and source receipts; failure can follow acquisition'}),file=sys.stderr)
        return 2


if __name__=='__main__':raise SystemExit(main())
