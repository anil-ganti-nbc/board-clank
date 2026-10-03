"""Full git SHA gate. No subprocess."""

from __future__ import annotations

import os
import re
from pathlib import Path

SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class RevisionError(RuntimeError):
    pass


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _resolve_git_dir(repo_root: Path) -> Path | None:
    git = repo_root / ".git"
    if git.is_dir():
        return git
    if not git.is_file():
        return None
    line = _read_text(git).strip()
    if not line.startswith("gitdir:"):
        return None
    raw = line.split(":", 1)[1].strip()
    return Path(raw) if Path(raw).is_absolute() else (repo_root / raw)


def _common_git_dir(git_dir: Path) -> Path:
    marker = git_dir / "commondir"
    if not marker.is_file():
        return git_dir
    raw = _read_text(marker).strip()
    path = Path(raw) if Path(raw).is_absolute() else (git_dir / raw)
    return path.resolve()


def _sha_from_gitdir(git_dir: Path) -> str | None:
    head_path = git_dir / "HEAD"
    if not head_path.is_file():
        return None
    head = _read_text(head_path).strip()
    if SHA_RE.fullmatch(head):
        return head
    if not head.startswith("ref:"):
        return None
    ref = head.split(":", 1)[1].strip()
    parts = Path(ref).parts
    if ref.startswith("/") or ".." in parts or Path(ref).is_absolute():
        return None
    search = [git_dir, _common_git_dir(git_dir)]
    for root in search:
        ref_file = root.joinpath(*parts)
        if ref_file.is_file():
            value = _read_text(ref_file).strip()
            return value if SHA_RE.fullmatch(value) else None
    packed = _common_git_dir(git_dir) / "packed-refs"
    if not packed.is_file():
        packed = git_dir / "packed-refs"
    if not packed.is_file():
        return None
    for line in _read_text(packed).splitlines():
        if not line or line.startswith("#") or line.startswith("^"):
            continue
        sha, _, name = line.partition(" ")
        if name.strip() == ref and SHA_RE.fullmatch(sha.strip()):
            return sha.strip()
    return None


def read_head_sha(repo_root: Path) -> str | None:
    git_dir = _resolve_git_dir(repo_root)
    if git_dir is None:
        return None
    return _sha_from_gitdir(git_dir)


def resolve_revision(
    flag: str | None,
    *,
    repo_root: Path,
    live: bool,
) -> str:
    value = flag if flag is not None else os.environ.get("CNX_SEEDER_CODE_REVISION")
    env = os.environ.get("CNX_SEEDER_CODE_REVISION")
    if flag is not None and env and flag != env:
        raise RevisionError("code revision flag and environment disagree")
    if value is None or not SHA_RE.fullmatch(value):
        raise RevisionError("code revision must be a full 40-hex git SHA")
    if live:
        head = read_head_sha(repo_root)
        if head is not None and head != value:
            raise RevisionError("code revision does not match checked out SHA")
    return value
