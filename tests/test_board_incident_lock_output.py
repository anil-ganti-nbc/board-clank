"""Offline regressions for Board slot-25 lock contention and empty-stdout masking.

Synthetic replicas only. No live publisher, Discord, deploy or inflight rewrite.
"""
from __future__ import annotations

import json
import socket
import threading
from datetime import datetime, timedelta, timezone

import pytest

from board_clank.production_ledger import Ledger, exclusive_lock, is_lock_contention
from board_clank.production_runtime import initialize, run_once
from board_clank.native_slot_outcome import interpret_native_output
from board_clank.hourly_dispatch import dispatch_native_slot
from test_production_runtime import (
    load, REV, synthetic_retained_collect, approval_file as _production_approval_file,
)


@pytest.fixture
def approval_file(tmp_path):
    return _production_approval_file.__wrapped__(tmp_path)


@pytest.fixture(autouse=True)
def _offline_lock_tests(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('test attempted live network')
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr('board_clank.pipeline.SOURCE_REVISION', REV)
    monkeypatch.setattr('board_clank.production_runtime.SOURCE_REVISION', REV)


def _collect(root, admission, source, slot, directory):
    return synthetic_retained_collect(root, admission, source, slot, directory)


def _cycles(root):
    with Ledger(root / 'operations.sqlite').connect() as db:
        return list(db.execute('SELECT slot,status FROM cycles ORDER BY slot'))


def _permits(root):
    with Ledger(root / 'operations.sqlite').connect() as db:
        return list(db.execute('SELECT slot,source FROM source_permits'))


def test_nested_os_lock_is_genuine_contention_not_arbitrary_oserror(tmp_path):
    held = tmp_path / 'runtime.lock'
    with exclusive_lock(held):
        with pytest.raises(OSError) as raised:
            with exclusive_lock(held):
                pytest.fail('overlap admitted')
    assert is_lock_contention(raised.value)
    assert not is_lock_contention(OSError(5, 'Input/output error'))
    assert not is_lock_contention(FileNotFoundError('missing'))
    assert not is_lock_contention(PermissionError(13, 'Access is denied'))
    import errno as errno_mod
    assert not is_lock_contention(BlockingIOError(errno_mod.EINVAL, 'invalid'))
    assert is_lock_contention(BlockingIOError(errno_mod.EAGAIN, 'locked'))


def test_preclaim_contention_is_deferred_without_cycle_or_permit(approval_file, tmp_path):
    admission = load(approval_file)
    root = tmp_path / 'runtime'
    initialize(root, admission)
    frozen = datetime.now(timezone.utc)
    with exclusive_lock(root / 'runtime.lock'):
        result = run_once(
            root, admission,
            collect=lambda *a: pytest.fail('acquisition under contention'),
            now=frozen, lock_deadline=frozen, clock=lambda: frozen, sleep=lambda n: pytest.fail('waited'),
        )
    assert result == {'status': 'DEFERRED_LOCK', 'slot': frozen.strftime('%Y%m%dT%H0000Z'), 'collection_invoked': False}
    assert _cycles(root) == []
    assert _permits(root) == []


def test_cli_contention_keeps_typed_busy_on_stdout_not_empty_refused(approval_file, tmp_path, capsys):
    from board_clank import production_runtime as runtime
    admission = load(approval_file)
    root = tmp_path / 'runtime'
    initialize(root, admission)
    frozen = datetime.now(timezone.utc)
    with exclusive_lock(root / 'runtime.lock'):
        code = runtime.main(['--root', str(root), '--approval', str(approval_file), 'once'])
    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert payload['status'] == 'DEFERRED_LOCK'
    assert payload['collection_invoked'] is False
    assert captured.err == ''
    assert _cycles(root) == []


def test_wait_then_useful_complete_after_holder_releases(approval_file, tmp_path):
    admission = load(approval_file)
    root = tmp_path / 'runtime'
    initialize(root, admission)

    def hold():
        with exclusive_lock(root / 'runtime.lock'):
            threading.Event().wait(0.15)

    holder = threading.Thread(target=hold)
    holder.start()
    threading.Event().wait(0.05)
    try:
        result = run_once(
            root, admission, collect=_collect,
            lock_deadline=datetime.now(timezone.utc) + timedelta(seconds=2),
        )
    finally:
        holder.join(2)
    assert result['status'] == 'COMPLETE', result
    assert result.get('collection_invoked') is not False
    assert len(_cycles(root)) == 1


def test_postclaim_contention_does_not_duplicate_reservation(approval_file, tmp_path):
    admission = load(approval_file)
    root = tmp_path / 'runtime'
    initialize(root, admission)
    started = threading.Event()
    finish = threading.Event()

    def slow_collect(*args):
        started.set()
        assert finish.wait(2)
        return _collect(*args)

    def first():
        run_once(root, admission, collect=slow_collect)

    worker = threading.Thread(target=first)
    worker.start()
    assert started.wait(5)
    frozen = datetime.now(timezone.utc)
    second = run_once(
        root, admission,
        collect=lambda *a: pytest.fail('duplicate acquisition'),
        now=frozen, lock_deadline=frozen, clock=lambda: frozen, sleep=lambda n: None,
    )
    finish.set()
    worker.join(30)
    assert second['status'] == 'DEFERRED_LOCK'
    rows = _cycles(root)
    assert len(rows) == 1
    assert rows[0]['status'] == 'COMPLETE'


def test_directory_lock_path_is_not_treated_as_busy(approval_file, tmp_path):
    admission = load(approval_file)
    root = tmp_path / 'runtime'
    initialize(root, admission)
    lock = root / 'runtime.lock'
    lock.unlink()
    lock.mkdir()
    frozen = datetime.now(timezone.utc)
    with pytest.raises(OSError) as raised:
        run_once(
            root, admission,
            collect=lambda *a: pytest.fail('acquisition after filesystem error'),
            now=frozen, lock_deadline=frozen, clock=lambda: frozen, sleep=lambda n: None,
        )
    assert not is_lock_contention(raised.value)
    assert _cycles(root) == []


def test_emergency_stop_during_wait_does_not_claim(approval_file, tmp_path):
    admission = load(approval_file)
    root = tmp_path / 'runtime'
    initialize(root, admission)
    frozen = datetime.now(timezone.utc)
    ticks = {'n': 0}

    def clock():
        return frozen

    def sleep(_n):
        pytest.fail('should not wait after stop')

    (root / 'PAUSED').write_text('stop')
    with exclusive_lock(root / 'runtime.lock'):
        with pytest.raises(ValueError, match='paused|human'):
            run_once(
                root, admission,
                collect=lambda *a: pytest.fail('acquisition under stop'),
                now=frozen, lock_deadline=frozen + timedelta(seconds=30), clock=clock, sleep=sleep,
            )
    assert (root / 'PAUSED').read_text() == 'stop'
    assert _cycles(root) == []
    assert ticks['n'] == 0


def test_already_claimed_still_refuses_duplicate_after_success(approval_file, tmp_path):
    admission = load(approval_file)
    root = tmp_path / 'runtime'
    initialize(root, admission)
    first = run_once(root, admission, collect=_collect)
    assert first['status'] == 'COMPLETE', first
    again = run_once(root, admission, collect=lambda *a: pytest.fail('duplicate acquisition'))
    assert again['status'] == 'ALREADY_CLAIMED'
    assert len(_cycles(root)) == 1


def test_historical_empty_stdout_no_longer_masks_typed_refusal():
    stderr = json.dumps({
        'status': 'REFUSED',
        'error_type': 'BlockingIOError',
        'collection_or_delivery_claimed': 'UNKNOWN',
        'evidence': 'inspect retained cycle and source receipts; failure can follow acquisition',
    }).encode()
    with pytest.raises(json.JSONDecodeError):
        json.loads(b'')
    outcome = interpret_native_output(2, b'', stderr)
    assert outcome.kind == 'REFUSED'
    assert outcome.typed['error_type'] == 'BlockingIOError'
    assert outcome.result is None


@pytest.mark.parametrize('stdout,kind', [
    (b'', 'EMPTY_STDOUT'),
    (b'{not json', 'MALFORMED_STDOUT'),
    (b'[]', 'MALFORMED_STDOUT'),
])
def test_nonzero_or_malformed_stdout_stays_observable(stdout, kind):
    stderr = b'{"status":"REFUSED","error_type":"ValueError"}'
    if stdout == b'[]':
        outcome = interpret_native_output(0, stdout, b'')
        assert outcome.kind == kind
        return
    outcome = interpret_native_output(2, stdout, stderr)
    assert outcome.kind in {kind, 'REFUSED'}
    if outcome.kind == 'REFUSED':
        assert outcome.typed['error_type'] == 'ValueError'


def test_complete_stdout_is_parsed_only_after_zero_exit():
    body = json.dumps({'status': 'COMPLETE', 'collection_invoked': True}).encode()
    ok = interpret_native_output(0, body, b'')
    assert ok.kind == 'PARSED' and ok.result['status'] == 'COMPLETE'
    masked = interpret_native_output(2, body, json.dumps({'status': 'REFUSED', 'error_type': 'ValueError'}).encode())
    assert masked.kind == 'REFUSED'
    assert masked.typed['error_type'] == 'ValueError'


def test_dispatch_retries_deferred_lock_then_completes_without_second_claim_token():
    calls = []
    complete = json.dumps({'status': 'COMPLETE', 'slot': 's', 'collection_invoked': True}).encode()
    deferred = json.dumps({'status': 'DEFERRED_LOCK', 'slot': 's', 'collection_invoked': False}).encode()

    def invoke():
        calls.append(1)
        if len(calls) == 1:
            return 0, deferred, b''
        return 0, complete, b''

    clock = {'t': 0.0}

    def now():
        return clock['t']

    def sleep(n):
        clock['t'] += n

    result = dispatch_native_slot(
        invoke=invoke, due=0.0, grace=120.0, expiry=1000.0,
        clock=now, sleep=sleep, stop=lambda: None,
    )
    assert result['status'] == 'COMPLETE'
    assert calls == [1, 1]


def test_dispatch_does_not_catch_up_after_grace_and_preserves_typed_refusal():
    def invoke():
        pytest.fail('catch-up native invoke')

    with pytest.raises(ValueError, match='no catchup'):
        dispatch_native_slot(
            invoke=invoke, due=0.0, grace=120.0, expiry=1000.0,
            clock=lambda: 121.0, sleep=lambda n: pytest.fail('slept'), stop=lambda: None,
        )


def test_dispatch_fail_closed_on_empty_stdout_keeps_stderr_type():
    stderr = json.dumps({'status': 'REFUSED', 'error_type': 'BlockingIOError'}).encode()

    def invoke():
        return 2, b'', stderr

    with pytest.raises(ValueError, match='BlockingIOError') as raised:
        dispatch_native_slot(
            invoke=invoke, due=0.0, grace=120.0, expiry=1000.0,
            clock=lambda: 1.0, sleep=lambda n: None, stop=lambda: None,
        )
    assert 'JSONDecodeError' not in str(raised.value)


def test_dispatch_stop_cancels_before_retry():
    calls = []

    def invoke():
        calls.append(1)
        return 0, json.dumps({'status': 'DEFERRED_LOCK', 'collection_invoked': False}).encode(), b''

    def stop():
        raise ValueError('runtime paused or human review required')

    with pytest.raises(ValueError, match='paused'):
        dispatch_native_slot(
            invoke=invoke, due=0.0, grace=120.0, expiry=1000.0,
            clock=lambda: 1.0, sleep=lambda n: None, stop=stop,
        )
    assert calls == []
