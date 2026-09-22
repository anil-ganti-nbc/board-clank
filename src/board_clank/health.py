"""Read-only health inspection. Never migrates."""

from __future__ import annotations

from pathlib import Path

from board_clank._version import (
    CLANK_ID,
    EXPECTED_SCHEMA_VERSION,
    PACKAGE_VERSION,
    RELEASE_CHANNEL,
    SOURCE_REVISION,
)
from board_clank.compatibility import inspect_path
from board_clank.paths import default_db_path
from board_clank.sources import load_sources, promoted_sources
from board_clank.taxonomy import CompatibilityState


def health_payload(db_path: str | Path | None = None) -> dict:
    path = Path(db_path) if db_path else default_db_path()
    report = inspect_path(path)
    sources = load_sources()
    promoted = promoted_sources()
    status = "ok"
    reasons: list[str] = []
    if report.state in {
        CompatibilityState.CORRUPT,
        CompatibilityState.UNKNOWN,
        CompatibilityState.PARTIAL,
        CompatibilityState.INCOMPATIBLE_NEWER,
    }:
        status = "degraded"
        reasons.append(f"persistent_state: {report.state.value} ({report.reason})")
    else:
        reasons.append(f"persistent_state: {report.state.value} ({report.reason})")
    if promoted:
        status = "degraded"
        reasons.append("promoted sources present in foundation-0 roster")
    return {
        "clank_id": CLANK_ID,
        "version": PACKAGE_VERSION,
        "release_channel": RELEASE_CHANNEL,
        "source_revision": SOURCE_REVISION,
        "schema_version_expected": EXPECTED_SCHEMA_VERSION,
        "status": status,
        "mutating": False,
        "discord_contact_possible": False,
        "live_network_required": False,
        "promoted_source_count": len(promoted),
        "registered_source_count": len(sources),
        "database": str(path),
        "compatibility": report.as_dict(),
        "status_reasons": reasons,
    }
