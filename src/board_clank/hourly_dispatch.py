"""Repaired hourly native dispatch: returncode before stdout, bounded lock deferral.

Historical ops/reviewed-sidecars/hourly_controller.py is preserved unmodified.
This module is the reviewable scheduling helper; it does not deploy or clear inflight.
"""
from __future__ import annotations

from board_clank.native_slot_outcome import interpret_native_output


def dispatch_native_slot(*, invoke, due, grace, expiry, clock, sleep, stop, poll=15.0):
    """Run one due slot. Retry only DEFERRED_LOCK inside due+grace. No catch-up."""
    while True:
        stop()
        now = clock()
        if now >= expiry:
            raise ValueError('absolute expiry')
        if now > due + grace:
            raise ValueError('missed due; no catchup')
        code, stdout, stderr = invoke()
        outcome = interpret_native_output(code, stdout, stderr)
        if outcome.kind == 'PARSED' and outcome.result.get('status') == 'DEFERRED_LOCK':
            remaining = (due + grace) - clock()
            seconds = remaining.total_seconds() if hasattr(remaining, 'total_seconds') else float(remaining)
            if seconds <= 0:
                raise ValueError('missed due; no catchup')
            sleep(min(poll, seconds))
            continue
        if outcome.kind == 'PARSED' and outcome.result.get('status') == 'COMPLETE':
            return outcome.result
        typed = (outcome.typed or {}).get('error_type') or outcome.kind
        raise ValueError(f'native slot failed; typed {typed}; no retry')
