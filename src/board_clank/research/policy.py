"""Roster firewall. A research lead cannot restate an admitted or placeholder vendor."""

from __future__ import annotations

from board_clank.research.baseline import roster_snapshot
from board_clank.research.domain import normalize_domain, normalize_oem, url_on_domain
from board_clank.sources import load_sources
from board_clank.taxonomy import SourceAuthority, SourcePlane


def _class_of(row) -> str | None:
    if row.out_of_scope:
        return "out_of_scope"
    if row.placeholder:
        return "placeholder"
    if row.plane is SourcePlane.PRODUCT and row.authority is SourceAuthority.FIRST_PARTY_CANONICAL:
        return "admitted"
    if row.authority is SourceAuthority.FIRST_PARTY_SUPPORTING:
        return "supporting"
    return None


def domain_owner(domain: str, path: str | None = None) -> str | None:
    claimed = normalize_domain(domain)
    for row in load_sources(path):
        kind = _class_of(row)
        if kind is None:
            continue
        for base in row.base_urls:
            if url_on_domain(base, claimed):
                return kind
    return None


def roster_conflict(oem: str, domain: str, path: str | None = None) -> str | None:
    snapshot = roster_snapshot(path)
    name = normalize_oem(oem)
    if name in snapshot["admitted_vendors"]:
        return "admitted_vendor_duplicate"
    if name in snapshot["placeholders"]:
        return "placeholder_duplicate"
    if name in snapshot["out_of_scope"]:
        return "out_of_scope_duplicate"
    owner = domain_owner(domain, path)
    if owner == "admitted":
        return "admitted_vendor_duplicate"
    if owner == "placeholder":
        return "placeholder_duplicate"
    if owner == "out_of_scope":
        return "out_of_scope_duplicate"
    if owner == "supporting":
        return "admitted_vendor_duplicate"
    return None
