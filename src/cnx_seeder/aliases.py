"""Seeder-owned alias table. Whole-token equality only."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from cnx_seeder.bounds import ALIAS_TABLE_VERSION
from cnx_seeder.normalize import normalize_tokens, registrable_domain

TABLE_PATH = Path(__file__).resolve().parent / "data" / "known_vendors_v1.yaml"


@dataclass(frozen=True)
class AliasRow:
    vendor: str
    role: str
    names: tuple[tuple[str, ...], ...]
    domains: frozenset[str]


def load_alias_table(path: Path | None = None) -> list[AliasRow]:
    target = path or TABLE_PATH
    payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    if payload.get("version") != ALIAS_TABLE_VERSION:
        raise RuntimeError("alias table version mismatch")
    rows: list[AliasRow] = []
    for item in payload.get("vendors") or []:
        names = tuple(normalize_tokens(name) for name in item.get("names") or [])
        domains = frozenset(registrable_domain(host) for host in item.get("domains") or [])
        rows.append(
            AliasRow(
                vendor=str(item["vendor"]),
                role=str(item["role"]),
                names=names,
                domains=domains,
            )
        )
    return rows


def match_alias(rows: list[AliasRow], subject: tuple[str, ...], domain: str | None) -> AliasRow | None:
    """Return the first row whose name tuple equals the subject or whose domain equals."""
    order = ("out_of_scope", "active", "placeholder")
    by_role = {role: [row for row in rows if row.role == role] for role in order}
    for role in order:
        for row in by_role[role]:
            if subject and subject in row.names:
                return row
            if domain and domain in row.domains:
                return row
    return None
