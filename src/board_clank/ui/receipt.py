"""Disposable runtime receipt. It is operational state, not authority."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def pid_is_alive(pid: int) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        kernel.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def read_receipt(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def archive_if_stale(path: Path) -> None:
    """Mark a dead receipt stale. A live PID is not deleted and does not block startup."""
    existing = read_receipt(path)
    if existing is None or not path.exists():
        return
    pid = existing.get("pid")
    if isinstance(pid, int) and pid_is_alive(pid):
        return
    existing["stale"] = True
    existing["stale_marked_at_utc"] = utc_now()
    stale = path.with_name(path.name + ".stale")
    try:
        stale.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        path.unlink()
    except OSError:
        return


def write_receipt(path: Path, *, host: str, port: int, app_sha: str) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    archive_if_stale(path)
    payload = {
        "pid": os.getpid(),
        "host": host,
        "port": port,
        "started_at_utc": utc_now(),
        "app_sha": app_sha,
        "stale": False,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def clear_receipt(path: Path) -> None:
    existing = read_receipt(path)
    if existing is None:
        return
    if existing.get("pid") != os.getpid():
        return
    try:
        path.unlink()
    except OSError:
        return
