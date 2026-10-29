"""Owned Python network/attribution guard, including stripped-env children."""
import ipaddress,os,socket,subprocess,sys,inspect,functools
KEYS=('CLANKOPS_ACTOR','CLANKOPS_CLANK_ID','CLANKOPS_MISSION_ID','CLANKOPS_SESSION_ID')
assert all(os.environ.get(k) for k in KEYS),'CI attribution missing'
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
  if k.get('env') is not None:
   e=dict(k['env']);e.pop('PYTHONHOME',None)
   for field in (*KEYS,'BOARD_CI_GUARD','BOARD_REVIEW_FENCE_LOG'):e[field]=os.environ[field]
   e['PYTHONPATH']=os.path.dirname(__file__)+os.pathsep+e.get('PYTHONPATH','');k['env']=e
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
class Finder(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname in ('board_clank.collectors.odroid','board_clank.collectors.odroid_store'):
   spec=importlib.machinery.PathFinder.find_spec(fullname,path)
   spec.loader=FenceLoader(spec.loader);return spec
sys.meta_path.insert(0,Finder())
