"""Synthetic native run_once boundary; no network, permits or live adapters."""
from datetime import datetime, timezone, timedelta

import pytest

from board_clank.production_ledger import Ledger, exclusive_lock
from board_clank.production_runtime import initialize, run_once
from test_production_runtime import (
    REV, approval_file as original_approval, load, synthetic_retained_collect,
)


@pytest.fixture
def approval_file(tmp_path, monkeypatch):
    monkeypatch.setattr('board_clank.pipeline.SOURCE_REVISION', REV)
    monkeypatch.setattr('board_clank.production_runtime.SOURCE_REVISION', REV)
    return original_approval.__wrapped__(tmp_path)


@pytest.mark.parametrize('release_time', [None, 0.5, 1, 2],
                         ids=['first-immediate-zero-wait', 'within-window',
                              'at-deadline', 'after-deadline'])
def test_native_claim_boundary(approval_file, tmp_path, release_time):
    admission = load(approval_file)
    root = tmp_path / 'runtime'
    initialize(root, admission)
    start = datetime.now(timezone.utc)
    current = [start]
    calls = []
    holder = exclusive_lock(root / 'runtime.lock') if release_time is not None else None
    held = [holder is not None]
    if holder:
        holder.__enter__()
    def sleep(_):
        assert holder is not None and held[0]
        current[0] = start + timedelta(seconds=release_time)
        holder.__exit__(None, None, None)
        held[0] = False
    def collect(*args):
        calls.append(args[2])
        return synthetic_retained_collect(*args)
    try:
        result = run_once(root, admission, now=start, collect=collect,
                          lock_deadline=start + timedelta(seconds=0 if holder is None else 1),
                          clock=lambda: current[0], sleep=sleep)
    finally:
        if held[0]:
            holder.__exit__(None, None, None)
    with Ledger(root / 'operations.sqlite').connect() as db:
        counts = {table: db.execute('select count(*) from ' + table).fetchone()[0]
                  for table in ['cycles', 'requests', 'source_permits']}
    refused = release_time is not None and release_time >= 1
    print({'release_time': release_time, 'status': result['status'],
           'collected_sources': len(calls), 'ledger_counts': counts})
    assert result['status'] == ('DEFERRED_LOCK' if refused else 'COMPLETE')
    assert len(calls) == (0 if refused else 8)
    assert counts == {'cycles': 0 if refused else 1, 'requests': 0, 'source_permits': 0}
    with exclusive_lock(root / 'runtime.lock'):
        pass
