"""Operational DB path copy and seeder state-dir guard.

The rules match src/board_clank/paths.py at 613c3a13. This module does not
import that package.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def operational_db_path(repo_root: Path | None = None) -> Path:
    root = repo_root if repo_root is not None else REPO_ROOT
    raw = os.environ.get("BOARD_CLANK_DB")
    if raw:
        return Path(raw)
    data = os.environ.get("BOARD_CLANK_DATA_DIR")
    if data:
        return Path(data) / "board_clank.db"
    container = Path("/app/data")
    if container.exists():
        return container / "board_clank.db"
    return root / "data" / "board_clank.db"


def default_state_dir(repo_root: Path | None = None) -> Path:
    root = repo_root if repo_root is not None else REPO_ROOT
    raw = os.environ.get("CNX_SEEDER_STATE_DIR")
    if raw:
        return Path(raw)
    return root / "var" / "cnx-seeder"


class PathGuardError(RuntimeError):
    pass


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve(strict=False).relative_to(parent.resolve(strict=False))
    except ValueError:
        return False
    return True


def assert_state_dir_allowed(state_dir: Path, repo_root: Path | None = None) -> Path:
    root = repo_root if repo_root is not None else REPO_ROOT
    resolved = state_dir.resolve(strict=False)
    queue = (resolved / "queue.sqlite").resolve(strict=False)
    operational = operational_db_path(root).resolve(strict=False)
    if resolved == operational or queue == operational:
        raise PathGuardError(f"state dir collides with operational db: {operational}")
    forbidden_parents = [root / "data", Path("/app/data")]
    data_env = os.environ.get("BOARD_CLANK_DATA_DIR")
    if data_env:
        forbidden_parents.append(Path(data_env))
    for parent in forbidden_parents:
        if _inside(resolved, parent) or _inside(queue, parent):
            raise PathGuardError(f"state dir is inside operational data: {parent}")
    parts = list(resolved.parts) + ["queue.sqlite"]
    if "board_clank.db" in parts or resolved.name == "board_clank.db":
        raise PathGuardError("refusing board_clank.db")
    roster_names = {root / "config" / "sources.yaml", root / "src" / "board_clank" / "sources.yaml"}
    if resolved in {p.resolve(strict=False) for p in roster_names}:
        raise PathGuardError("refusing roster file as state dir")
    return resolved
