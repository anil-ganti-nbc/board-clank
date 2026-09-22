"""Source registry. Foundation 0: Phase-1 vendors are REGISTERED / EXPERIMENTAL only."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from board_clank.models import SourceRecord
from board_clank.taxonomy import (
    PHASE1_VENDORS,
    PHASE2_PLACEHOLDERS,
    PromotionState,
    SourceAuthority,
    SourcePlane,
)

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
PACKAGED_SOURCES = Path(__file__).resolve().parent / "sources.yaml"
DEFAULT_SOURCES_PATH = CONFIG_DIR / "sources.yaml" if (Path(__file__).resolve().parents[2] / "config" / "sources.yaml").exists() else PACKAGED_SOURCES


class SourceRegistryError(RuntimeError):
    pass


def _parse_record(raw: dict[str, Any]) -> SourceRecord:
    return SourceRecord(
        source_key=raw["source_key"],
        vendor=raw["vendor"],
        plane=SourcePlane(raw["plane"]),
        authority=SourceAuthority(raw["authority"]),
        base_urls=list(raw.get("base_urls") or []),
        enabled=bool(raw.get("enabled", False)),
        promotion_state=str(raw.get("promotion_state", PromotionState.EXPERIMENTAL.value)),
        registered_state=str(raw.get("registered_state", "REGISTERED")),
        notes=str(raw.get("notes") or ""),
        expected_identity_surface=str(raw.get("expected_identity_surface") or "UNKNOWN"),
        expected_variant_surface=str(raw.get("expected_variant_surface") or "UNKNOWN"),
        placeholder=bool(raw.get("placeholder", False)),
        out_of_scope=bool(raw.get("out_of_scope", False)),
    )


@lru_cache(maxsize=4)
def load_sources(path: str | None = None) -> list[SourceRecord]:
    target = Path(path) if path else DEFAULT_SOURCES_PATH
    if not target.exists():
        raise SourceRegistryError(f"source registry missing: {target}")
    payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    records = [_parse_record(item) for item in payload.get("sources", [])]
    return records


def phase1_sources(path: str | None = None) -> list[SourceRecord]:
    return [row for row in load_sources(path) if row.vendor in PHASE1_VENDORS and not row.placeholder]


def promoted_sources(path: str | None = None) -> list[SourceRecord]:
    return [row for row in load_sources(path) if row.promotion_state == PromotionState.PROMOTED.value]


def assert_foundation_0_roster(path: str | None = None) -> None:
    records = load_sources(path)
    phase1 = {row.vendor for row in records if not row.placeholder and not row.out_of_scope}
    missing = set(PHASE1_VENDORS) - phase1
    if missing:
        raise SourceRegistryError(f"phase-1 vendors missing from roster: {sorted(missing)}")
    if promoted_sources(path):
        raise SourceRegistryError("Foundation 0 forbids promoted sources")
    live = [row for row in records if row.enabled and not row.placeholder]
    if live:
        raise SourceRegistryError("Foundation 0 forbids enabled live sources")
    placeholders = {row.vendor for row in records if row.placeholder}
    missing_phase2 = set(PHASE2_PLACEHOLDERS) - placeholders
    if missing_phase2:
        raise SourceRegistryError(f"phase-2 placeholders missing: {sorted(missing_phase2)}")


def sync_sources_to_store(store: Any, path: str | None = None) -> int:
    import json

    count = 0
    for row in load_sources(path):
        store.execute(
            """
            INSERT INTO sources(
                source_key, vendor, plane, authority, base_urls_json, enabled,
                promotion_state, registered_state, notes, expected_identity_surface,
                expected_variant_surface, placeholder, out_of_scope
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_key) DO UPDATE SET
                vendor=excluded.vendor,
                plane=excluded.plane,
                authority=excluded.authority,
                base_urls_json=excluded.base_urls_json,
                enabled=excluded.enabled,
                promotion_state=excluded.promotion_state,
                registered_state=excluded.registered_state,
                notes=excluded.notes,
                expected_identity_surface=excluded.expected_identity_surface,
                expected_variant_surface=excluded.expected_variant_surface,
                placeholder=excluded.placeholder,
                out_of_scope=excluded.out_of_scope
            """,
            (
                row.source_key,
                row.vendor,
                row.plane.value,
                row.authority.value,
                json.dumps(row.base_urls),
                1 if row.enabled else 0,
                row.promotion_state,
                row.registered_state,
                row.notes,
                row.expected_identity_surface,
                row.expected_variant_surface,
                1 if row.placeholder else 0,
                1 if row.out_of_scope else 0,
            ),
        )
        count += 1
    store.commit()
    return count
