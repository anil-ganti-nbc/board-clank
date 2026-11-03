"""Owned Python network/attribution guard, including stripped-env children."""
import ipaddress,os,socket,subprocess,sys,inspect,functools
KEYS=('CLANKOPS_ACTOR','CLANKOPS_CLANK_ID','CLANKOPS_MISSION_ID','CLANKOPS_SESSION_ID')
if os.environ.get('GITHUB_ACTIONS')=='true':
 assert all(os.environ.get(k) for k in ('GITHUB_REPOSITORY','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_SHA','GITHUB_JOB')),'hosted run provenance missing'
 assert not any(os.environ.get(k) for k in KEYS),'hosted CI must not impersonate a local ClankOps Session'
else:
 assert all(os.environ.get(k) for k in KEYS),'local ClankOps attribution missing'
assert os.environ.get('BOARD_CI_GUARD')=='1','CI guard not enabled'
os.environ['BOARD_SEAM_GUARD_ENTERED']='1'
def allowed(h):
 if h=='localhost':return True
 try:return ipaddress.ip_address(h).is_loopback
 except ValueError:return False
for name in ('connect','connect_ex'):
 original=getattr(socket.socket,name)
 def guarded(self,address,_original=original):
  if isinstance(address,tuple) and not allowed(address[0]):raise PermissionError('offline external network denied')
  return _original(self,address)
 setattr(socket.socket,name,guarded)
_dns=socket.getaddrinfo
def dns(host,*a,**k):
 if not allowed(host):raise PermissionError('offline DNS denied')
 return _dns(host,*a,**k)
socket.getaddrinfo=dns
_Popen=subprocess.Popen
class Child(_Popen):
 def __init__(self,*a,**k):
  command=a[0] if a else k.get('args')
  # Only the direct Python form used by admitted runners is covered. Refuse
  # isolation/startup bypasses before spawning, not after an unguarded import.
  if k.get('shell') or not isinstance(command,(list,tuple)) or not command:
   raise PermissionError('qualification requires direct guarded Python argv')
  executable=k.get('executable') or command[0]
  if os.path.normcase(os.path.abspath(executable))!=os.path.normcase(os.path.abspath(sys.executable)):
   raise PermissionError('qualification child interpreter not admitted')
  options=iter(command[1:])
  for option in options:
   if option in ('-c','-m') or not str(option).startswith('-'):break
   if option in ('-B','-u'):continue
   if option=='-X' and next(options,None)=='utf8':continue
   raise PermissionError('qualification child startup option not supported')
  e=dict(os.environ if k.get('env') is None else k['env']);e.pop('PYTHONHOME',None)
  fields=(*KEYS,'BOARD_CI_GUARD','BOARD_REVIEW_FENCE_LOG','GITHUB_ACTIONS','GITHUB_REPOSITORY','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_SHA','GITHUB_JOB')
  for field in fields:
   if field in os.environ:e[field]=os.environ[field]
   else:e.pop(field,None)
  paths=[os.path.dirname(__file__),*os.environ.get('PYTHONPATH','').split(os.pathsep),*e.get('PYTHONPATH','').split(os.pathsep)]
  e['PYTHONPATH']=os.pathsep.join(dict.fromkeys(p for p in paths if p));k['env']=e
  super().__init__(*a,**k)
subprocess.Popen=Child
# Replace functions before imports reach any test. A raised profile callback
# disables profiling, so profiling is not a persistent refusal boundary.
import importlib.abc,importlib.machinery

def refused(*args,**kwargs):
 with open(os.environ['BOARD_REVIEW_FENCE_LOG'],'a',encoding='utf-8') as f:f.write('mothball fence refused\n')
 raise AssertionError('mothballed original function body prohibited')
class FenceLoader:
 def __init__(self,loader):self.loader=loader
 def create_module(self,spec):return self.loader.create_module(spec)
 def exec_module(self,module):
  self.loader.exec_module(module)
  for name,value in list(vars(module).items()):
   if inspect.isfunction(value) and value.__module__==module.__name__:setattr(module,name,refused)
   elif inspect.isclass(value) and value.__module__==module.__name__:
    for key,method in list(vars(value).items()):
     if not inspect.isfunction(method):continue
     if module.__name__.endswith('.odroid') and value.__name__=='OdroidProductAdapter' and key=='__init__':
      original=method
      def metadata(self,experimental_live=False,corpus='baseline',_original=original):
       if experimental_live is not False or corpus!='baseline':return refused()
       return _original(self,experimental_live=experimental_live,corpus=corpus)
      setattr(value,key,metadata)
     else:setattr(value,key,refused)
FENCED_MODULES=('board_clank.collectors.raspberry_pi','board_clank.collectors.odroid','board_clank.collectors.odroid_store')
assert not any(name in sys.modules for name in FENCED_MODULES),'mothball fence installed too late'
class Finder(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname in FENCED_MODULES:
   spec=importlib.machinery.PathFinder.find_spec(fullname,path)
   spec.loader=FenceLoader(spec.loader);return spec
sys.meta_path.insert(0,Finder())
