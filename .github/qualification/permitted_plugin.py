import json, os, pathlib, socket, subprocess, sys
import pytest
HERE=pathlib.Path(__file__).parent
N=json.loads((HERE/'selection.json').read_text())
def pytest_sessionstart(session):
 assert os.environ.get('BOARD_SEAM_GUARD_ENTERED')=='1'
 for fn,args in [(socket.getaddrinfo,('example.com',443)),(socket.socket().connect,('203.0.113.1',443))]:
  try:fn(*args) if fn==socket.getaddrinfo else fn(args)
  except PermissionError:pass
  else:raise AssertionError('network guard absent')
 child="import os,socket; assert os.environ.get('BOARD_SEAM_GUARD_ENTERED')=='1';\ntry:socket.getaddrinfo('example.com',443)\nexcept PermissionError:pass\nelse:raise AssertionError('child DNS guard absent')\ntry:socket.socket().connect(('203.0.113.1',443))\nexcept PermissionError:pass\nelse:raise AssertionError('child connect guard absent')"
 p=subprocess.run([sys.executable,'-B','-c',child],env={'PATH':os.environ.get('PATH',''),'SYSTEMROOT':os.environ.get('SYSTEMROOT','')},capture_output=True)
 assert p.returncode==0,'child guard absent'
def pytest_collection_modifyitems(config,items):
 ids=[i.nodeid for i in items]
 assert len(ids)==len(set(ids))==818 and set(ids)==set(N['collected']),'collection differs from authenticated 818 identities'
 by={i.nodeid:i for i in items}; excluded=[i for i in items if i.nodeid not in N['allowed']]
 assert len(excluded)==87 and {i.nodeid for i in excluded}==set(N['NOT_RUN'])
 assert len(N['allowed'])==731 and len(set(N['allowed']))==731
 config.hook.pytest_deselected(items=excluded);items[:]=[by[n] for n in N['allowed']]
 print('Explicit selection: 818 collected; 731 permitted; 87 NOT_RUN')
def pytest_runtest_teardown(item,nextitem):
 if pathlib.Path(os.environ['BOARD_REVIEW_FENCE_LOG']).exists():pytest.exit('mothball fence attempted',returncode=4)
