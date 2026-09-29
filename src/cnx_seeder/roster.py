"""Read-only roster check. Does not write sources.yaml and does not sync a store."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from cnx_seeder.aliases import AliasRow
from cnx_seeder.normalize import strip_host
from cnx_seeder.paths import REPO_ROOT

PHASE1 = (
    "raspberry-pi",
    "orange-pi",
    "radxa",
    "banana-pi",
    "hardkernel-odroid",
    "pine64",
)
PHASE2 = (
    "friendlyelec",
    "milk-v",
    "beagleboard",
    "libre-computer",
    "khadas",
    "up-board",
    "seeed-studio",
    "firefly",
    "lattepanda",
)


@dataclass
class Roster:
    sha256: str
    vendors: dict[str, dict]
    active_hosts: dict[str, set[str]]


class RosterError(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def default_roster_path(repo_root: Path | None = None) -> Path:
    root = repo_root or REPO_ROOT
    return root / "config" / "sources.yaml"


def load_roster(path: Path) -> Roster:
    raw = path.read_bytes()
    payload = yaml.safe_load(raw.decode("utf-8")) or {}
    meta = payload.get("meta") or {}
    if meta.get("promotion_freeze") is not True:
        raise RosterError("roster_mismatch")
    sources = payload.get("sources") or []
    vendors: dict[str, dict] = {}
    for item in sources:
        vendors[str(item["vendor"])] = item
    expected = set(PHASE1) | set(PHASE2) | {"nvidia-jetson"}
    if set(vendors) != expected:
        raise RosterError("roster_mismatch")
    jetson = vendors["nvidia-jetson"]
    if not jetson.get("out_of_scope"):
        raise RosterError("roster_mismatch")
    for name in PHASE2:
        row = vendors[name]
        if not row.get("placeholder") or list(row.get("base_urls") or []):
            raise RosterError("roster_mismatch")
    hosts: dict[str, set[str]] = {}
    for name in PHASE1:
        found: set[str] = set()
        for url in vendors[name].get("base_urls") or []:
            host = urlsplit(str(url)).hostname or ""
            found.add(strip_host(host))
        hosts[name] = found
    return Roster(hashlib.sha256(raw).hexdigest(), vendors, hosts)


def assert_alias_coverage(roster: Roster, rows: list[AliasRow]) -> None:
    by_vendor = {row.vendor: row for row in rows}
    if set(by_vendor) != set(roster.vendors):
        raise RosterError("alias_table_incomplete")
    if by_vendor["nvidia-jetson"].role != "out_of_scope":
        raise RosterError("alias_table_incomplete")
    for vendor, hosts in roster.active_hosts.items():
        domains = by_vendor[vendor].domains
        for host in hosts:
            if host not in domains:
                raise RosterError("alias_table_incomplete")
