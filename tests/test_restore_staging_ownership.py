"""Owned staging checks on distinct inputs; prohibited alias coverage NOT_RUN."""
from __future__ import annotations

import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

import board_clank.backup as backup_module
from board_clank.backup import create_backup, restore_backup, sha256_file, verify_backup
from board_clank.store import Store


def _ordinary_backup(tmp_path):
    source = tmp_path / "source.db"
    Store(source).close()
    return create_backup(source, tmp_path / "backup")


def _record_allocations(monkeypatch):
    native = backup_module.tempfile.mkstemp
    allocated = []
    def allocate(*args, **kwargs):
        assert kwargs["prefix"] == ".board-clank-restore-"
        descriptor, name = native(*args, **kwargs)
        allocated.append(Path(name))
        return descriptor, name
    monkeypatch.setattr(backup_module.tempfile, "mkstemp", allocate)
    return allocated


@pytest.mark.parametrize("activate", [False, True])
def test_distinct_inputs_use_exclusively_owned_staging(tmp_path, monkeypatch, activate):
    backup = _ordinary_backup(tmp_path)
    before = (backup.database_path.read_bytes(), backup.metadata_path.read_bytes())
    allocated = _record_allocations(monkeypatch)
    native_check = backup_module._require_distinct_restore_paths
    checks = []
    def check(paths):
        if not allocated:
            assert set(paths) == {"backup", "metadata", "target"}
        checks.append(tuple(paths))
        return native_check(paths)
    monkeypatch.setattr(backup_module, "_require_distinct_restore_paths", check)
    native_unlink = Path.unlink
    removed = []
    def unlink_owned(path, *args, **kwargs):
        assert path in allocated
        removed.append(path)
        return native_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", unlink_owned)
    target = tmp_path / "ordinary-target.db"
    report = restore_backup(backup.database_path, backup.metadata_path, target, activate=activate)
    assert len(allocated) == 1 and allocated[0].parent == target.parent
    assert checks[0] == ("backup", "metadata", "target")
    assert any("staging" in roles for roles in checks)
    restored = target if activate else Path(report["staging_path"])
    assert verify_backup(restored, backup.metadata_path)["verified"]
    assert report["activated"] is activate
    assert removed == (allocated if activate else [])
    assert (backup.database_path.read_bytes(), backup.metadata_path.read_bytes()) == before


def test_mock_copy_failure_cleans_only_owned_temporary(tmp_path, monkeypatch):
    backup = _ordinary_backup(tmp_path)
    before = (backup.database_path.read_bytes(), backup.metadata_path.read_bytes())
    allocated = _record_allocations(monkeypatch)
    native_fdopen = os.fdopen
    class WriteFailure:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def write(self, contents):
            raise OSError("mock owned copy failure")
    monkeypatch.setattr(os, "fdopen", lambda descriptor, mode: WriteFailure(native_fdopen(descriptor, mode)))
    target = tmp_path / "ordinary-target.db"
    with pytest.raises(OSError, match="mock owned copy failure"):
        restore_backup(backup.database_path, backup.metadata_path, target)
    assert len(allocated) == 1 and not allocated[0].exists() and not target.exists()
    assert (backup.database_path.read_bytes(), backup.metadata_path.read_bytes()) == before


@pytest.mark.parametrize("matches", [False, True])
def test_mock_cleanup_requires_owned_regular_file(monkeypatch, matches):
    path = Path("mock-owned-temporary.db")
    observed = SimpleNamespace(st_mode=stat.S_IFREG, st_dev=7, st_ino=31 if matches else 32)
    monkeypatch.setattr(Path, "lstat", lambda self: observed)
    removed = []
    monkeypatch.setattr(Path, "unlink", lambda self: removed.append(self))
    backup_module._discard_owned_staging(path, (7, 31))
    assert removed == ([path] if matches else [])


def test_ordinary_forced_activation_preserves_backup_pair(tmp_path):
    backup = _ordinary_backup(tmp_path)
    before = (backup.database_path.read_bytes(), backup.metadata_path.read_bytes())
    target = tmp_path / "ordinary-target.db"
    Store(target).close()
    report = restore_backup(backup.database_path, backup.metadata_path, target, activate=True, force=True)
    assert report["activated"] and sha256_file(target) == backup.sha256
    assert (backup.database_path.read_bytes(), backup.metadata_path.read_bytes()) == before
