"""Real disposable OS locks; stdlib-only deadline and ownership regressions."""
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from board_clank.production_ledger import LockDeferred, bounded_runtime_lock, exclusive_lock


class RuntimeLockDeadlineTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='board-deadline-')
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'runtime.lock'

    def test_first_immediate_acquisition_at_deadline_stays_useful(self):
        with bounded_runtime_lock(self.path, 0, clock=lambda: 0,
                                  sleep=lambda _: self.fail('slept'), recheck=lambda: None):
            pass
        with exclusive_lock(self.path):
            pass

    def test_zero_wait_contention_refuses_without_sleep(self):
        with exclusive_lock(self.path), self.assertRaises(LockDeferred):
            with bounded_runtime_lock(self.path, 0, clock=lambda: 0,
                                      sleep=lambda _: self.fail('slept'), recheck=lambda: None):
                self.fail('entered')

    def test_release_after_wait_deadline_refuses_and_keeps_lock_available(self):
        self.release_after_wait(2, False)

    def test_release_exactly_at_wait_deadline_refuses(self):
        self.release_after_wait(1, False)

    def test_release_within_wait_deadline_is_useful(self):
        self.release_after_wait(0.5, True)

    def release_after_wait(self, release_time, expected_entry):
        now = [0]
        entered = []
        holder = exclusive_lock(self.path)
        holder.__enter__()
        held = [True]
        def sleep(_):
            now[0] = release_time
            holder.__exit__(None, None, None)
            held[0] = False
        def attempt():
            with bounded_runtime_lock(self.path, 1, clock=lambda: now[0],
                                      sleep=sleep, recheck=lambda: None):
                entered.append(now[0])
        try:
            if expected_entry:
                attempt()
            else:
                with self.assertRaises(LockDeferred):
                    attempt()
        finally:
            if held[0]:
                holder.__exit__(None, None, None)
        self.assertEqual(entered, [release_time] if expected_entry else [])
        with exclusive_lock(self.path):
            pass

    def test_retry_acquisition_crossing_deadline_releases_before_refusal(self):
        self.cross_acquisition_boundary(cancel=False)

    def test_cancellation_after_retry_acquisition_releases_before_refusal(self):
        self.cross_acquisition_boundary(cancel=True)

    def cross_acquisition_boundary(self, *, cancel):
        now = [0]
        acquired = []
        released = []
        holder = exclusive_lock(self.path)
        holder.__enter__()
        held = [True]
        @contextmanager
        def observed_lock(path):
            # Wrap the actual syscall, not a fabricated successful acquisition.
            with exclusive_lock(path):
                acquired.append(True)
                now[0] = 0.5 if cancel else 1
                try:
                    yield
                finally:
                    released.append(True)
        def sleep(_):
            now[0] = 0.25
            holder.__exit__(None, None, None)
            held[0] = False
        def recheck():
            if cancel and acquired:
                raise ValueError('cancelled at acquired retry boundary')
        try:
            with patch('board_clank.production_ledger.exclusive_lock', observed_lock):
                with self.assertRaisesRegex(ValueError, 'cancelled') if cancel else self.assertRaises(LockDeferred):
                    with bounded_runtime_lock(self.path, 1, clock=lambda: now[0],
                                              sleep=sleep, recheck=recheck):
                        self.fail('protected body entered')
        finally:
            if held[0]:
                holder.__exit__(None, None, None)
        self.assertEqual(acquired, [True])
        self.assertEqual(released, [True])
        with exclusive_lock(self.path):
            pass
