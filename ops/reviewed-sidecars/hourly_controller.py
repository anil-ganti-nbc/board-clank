import pathlib,json,datetime,hashlib,os,fcntl,time,subprocess,uuid,sys
from board_clank.production_policy import Admission,utc
from board_clank._version import SOURCE_REVISION
from board_clank.campaign_acceptance import baseline_seal
from board_clank.production_runtime import validate_state
from board_clank.production_ledger import assert_running
from board_clank.store import Store
r=pathlib.Path('/state/runtime');c=pathlib.Path('/state/controller');a=Admission(pathlib.Path('/approval/approval.json'),SOURCE_REVISION)
f=(c/'controller.lock').open('a');fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
def save(name,value):
 p=c/name;tmp=c/(name+'.tmp');tmp.write_text(json.dumps(value,indent=2));os.replace(tmp,p)
def now():return datetime.datetime.now(datetime.UTC)
try:
 assert_running(r);a.validate();seal=baseline_seal(r,a)
 with Store(r/'board.sqlite',migrate=False) as store:validate_state(store,a)
 origin=utc(seal['t0']);end=origin+datetime.timedelta(hours=168);expiry=utc(seal['expires_at']);sealhash=hashlib.sha256((r/'baseline-seal.json').read_bytes()).hexdigest()
 scheduler=json.loads(pathlib.Path('/approval/scheduler.json').read_bytes())
 statepath=c/'progress.json';progress=json.loads(statepath.read_bytes()) if statepath.exists() else {'completed':0,'inflight':None}
 assert progress['inflight'] is None,'previous in-flight slot; no automatic retry'
 assert 0<=progress['completed']<=168
 save('startup-'+str(time.time_ns())+'.json' if (c/'activation.json').exists() else 'activation.json',dict(status='ENABLED_PROBATION',at=now().isoformat(),pid=os.getpid(),uid=os.getuid(),source_revision=SOURCE_REVISION,baseline_seal_sha256=sealhash,t0=origin.isoformat(),first_due=seal['first_due_utc'],last_due=end.isoformat(),expiry=expiry.isoformat(),natural_credit_at_activation=0,collection_at_activation=False,scheduler_id=scheduler['scheduler_id'],cadence_seconds=3600,slots=168,network='bridge',delivery=False))
 for seq in range(progress['completed']+1,169):
  due=origin+datetime.timedelta(hours=seq)
  while now()<due:
   assert_running(r)
   if now()>=expiry:raise ValueError('absolute expiry')
   time.sleep(min(15,max(.01,(due-now()).total_seconds())))
  assert_running(r)
  if now()>=expiry or now()>due+datetime.timedelta(seconds=120):raise ValueError('missed due; no catchup')
  if due>end:raise ValueError('campaign end cutoff')
  a.validate();baseline_seal(r,a)
  slot=due.strftime('%Y%m%dT%H0000Z');dispatch=dict(attempt_id=seal['attempt_id'],approval_sha256=a.raw_hash,scheduler_id=scheduler['scheduler_id'],slot=slot,dispatch_id=str(uuid.uuid4()),dispatched_at=now().isoformat(),role='scheduled',mode='OPERATIONAL',sequence=seq,baseline_seal_sha256=sealhash)
  progress['inflight']=seq;save('progress.json',progress)
  with (r/'scheduler'/(slot+'.json')).open('x') as out:json.dump(dispatch,out,indent=2);out.flush();os.fsync(out.fileno())
  with (c/(str(seq)+'.stdout')).open('xb') as out,(c/(str(seq)+'.stderr')).open('xb') as err:
   p=subprocess.run(['board-clank-hourly','--root',str(r),'--approval','/approval/approval.json','once'],stdout=out,stderr=err,timeout=min(3300,(expiry-now()).total_seconds()))
  result=json.loads((c/(str(seq)+'.stdout')).read_bytes())
  if p.returncode!=0 or result.get('status')!='COMPLETE':raise ValueError('native slot failed; no retry')
  progress=dict(completed=seq,inflight=None);save('progress.json',progress)
 save('terminal.json',dict(status='168_SLOTS_TERMINAL_PENDING_PARENT_ACCEPTANCE',at=now().isoformat(),delivery=False))
except BaseException as exc:
 save('terminal.json',dict(status='STOPPED_FAIL_CLOSED',at=now().isoformat(),error_type=type(exc).__name__,reason=str(exc),delivery=False));raise
