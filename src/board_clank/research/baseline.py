"""Board-owned dedup baseline. CNX must name this exact roster snapshot."""

from __future__ import annotations

import hashlib
import json

from board_clank.sources import load_sources
from board_clank.taxonomy import SourceAuthority, SourcePlane

BASELINE_VERSION = "board-admitted-sources-v1"


def _domain(url: str) -> str | None:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host or None


def roster_snapshot(path: str | None = None) -> dict[str, list[str]]:
    admitted: list[str] = []
    placeholders: list[str] = []
    out_of_scope: list[str] = []
    domains: list[str] = []
    for row in load_sources(path):
        if row.out_of_scope:
            out_of_scope.append(row.vendor)
        elif row.placeholder:
            placeholders.append(row.vendor)
        elif row.plane is SourcePlane.PRODUCT and row.authority is SourceAuthority.FIRST_PARTY_CANONICAL:
            admitted.append(row.vendor)
        for base in row.base_urls:
            domain = _domain(base)
            if domain:
                domains.append(domain)
    return {
        "admitted_vendors": sorted(set(admitted)),
        "placeholders": sorted(set(placeholders)),
        "out_of_scope": sorted(set(out_of_scope)),
        "known_domains": sorted(set(domains)),
    }


def baseline_hash(path: str | None = None) -> str:
    payload = roster_snapshot(path)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def baseline_matches(version: str, digest: str, path: str | None = None) -> bool:
    return version == BASELINE_VERSION and digest == baseline_hash(path)
