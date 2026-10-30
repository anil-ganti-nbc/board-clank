"""Metadata-only precollection fence proof. Never invoke a retained parser."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys


def metadata():
    import sitecustomize as guard
    import board_clank.collectors.raspberry_pi as rp
    import board_clank.collectors.odroid as od
    assert os.environ.get('BOARD_SEAM_GUARD_ENTERED') == '1'
    assert rp.parse_product_html is guard.refused
    assert od.OdroidProductAdapter.collect is guard.refused
    assert sum(isinstance(f, guard.Finder) for f in sys.meta_path) == 1
    assert isinstance(subprocess.Popen, type) and issubclass(subprocess.Popen, guard._Popen)
    for action in (lambda: socket.getaddrinfo('review.invalid', 443),
                   lambda: socket.socket().connect(('192.0.2.1', 443))):
        try:
            action()
        except PermissionError:
            pass
        else:
            raise AssertionError('network guard absent')
    # Identity established first; invoke only the owned replacement, never a
    # variable that could still reference the original parser on a bad build.
    log = Path(os.environ['BOARD_REVIEW_FENCE_LOG'])
    sentinel = log.with_name(log.name + '.sentinel-' + str(os.getpid()))
    assert not sentinel.exists()
    os.environ['BOARD_REVIEW_FENCE_LOG'] = str(sentinel)
    try:
        try:
            guard.refused()
        except AssertionError as exc:
            assert str(exc) == 'mothballed original function body prohibited'
        else:
            raise AssertionError('replacement failed to refuse')
        assert sentinel.read_text() == 'mothball fence refused\n'
    finally:
        os.environ['BOARD_REVIEW_FENCE_LOG'] = str(log)
        if sentinel.exists():
            sentinel.unlink()
    return {'entered': '1', 'parser_name': rp.parse_product_html.__name__,
            'rpi_identity': True, 'odroid_identity': True, 'single_finder': True,
            'network_denied': True, 'owned_sentinel': True}


def preflight():
    result = {'parent': metadata()}
    code = 'import json; from seven_preflight import metadata; print(json.dumps(metadata()))'
    # Windows needs SystemRoot to initialize Winsock; no Python/guard/actor
    # fields are supplied by this stripped caller.
    stripped = {k: os.environ[k] for k in ('SYSTEMROOT',) if k in os.environ}
    for name, env in (('ordinary_child', None), ('stripped_child', stripped)):
        child = subprocess.run([sys.executable, '-B', '-c', code], env=env,
                               capture_output=True, text=True)
        assert child.returncode == 0, (name, child.returncode, child.stdout, child.stderr)
        result[name] = json.loads(child.stdout)
    for flags in (['-I'], ['-S'], ['-E'], ['-IS'], ['-X', 'utf8', '-I']):
        try:
            subprocess.Popen([sys.executable, *flags, '-c', 'raise AssertionError("must not start")'])
        except PermissionError:
            pass
        else:
            raise AssertionError('startup bypass was not refused before spawn')
    result['unsupported_isolation_refused_before_spawn'] = True
    return result
