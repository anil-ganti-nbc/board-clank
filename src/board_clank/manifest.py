"""Board Clank manifest — machine-validatable identity for fleet onboarding.

Shaped after the canonical requirements (Unified Clank Architecture v0.1 §4
manifest MUSTs; Observer Adapter Surface Contract v0.2 required core; Fleet
Laws 4/5 authority declarations). Every field is asserted by tests; unknown
facts stay literal UNKNOWN. Capability states use the canonical vocabulary:
active / supported_unconfigured / supported_undeployed / unsupported_by_policy
/ unsupported / unknown_or_unverified.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from board_clank._version import (
    CLANK_ID,
    EXPECTED_SCHEMA_VERSION,
    PACKAGE_VERSION,
    RELEASE_CHANNEL,
    SOURCE_REVISION,
)

MANIFEST_VERSION = 1
ADAPTER_CONTRACT_VERSION = "0.2"  # Observer Adapter Surface Contract v0.2
BACKUP_FORMAT_VERSION_LABEL = 1

CAPABILITY_STATES = frozenset(
    {
        "active",
        "supported_unconfigured",
        "supported_undeployed",
        "unsupported_by_policy",
        "unsupported",
        "unknown_or_unverified",
    }
)

MANIFEST_PATH = Path(__file__).resolve().parents[2] / "manifest.json"
PACKAGED_MANIFEST_PATH = Path(__file__).resolve().parent / "manifest.json"


def build_manifest() -> dict[str, Any]:
    """Authoritative manifest content, derived from runtime truth."""
    return {
        "manifest_version": MANIFEST_VERSION,
        "clank_id": CLANK_ID,
        "display_name": "Board Clank (SBC hardware intelligence)",
        "maturity": "EXPERIMENTAL",
        "release_channel": RELEASE_CHANNEL,
        "versions": {
            "package": PACKAGE_VERSION,
            "schema": EXPECTED_SCHEMA_VERSION,
            "code_revision": SOURCE_REVISION,
            "adapter_contract": ADAPTER_CONTRACT_VERSION,
        },
        "ownership": {
            "domain": "SBC board/vendor inventory and novelty (first-party PRODUCT plane)",
            "operator": "anil-ganti-nbc",
        },
        "architecture": {"python": ">=3.11", "storage": "sqlite"},
        "capabilities": [
            "discovery",
            "identity",
            "spec_extraction",
            "variant_handling",
            "replay",
            "backup",
            "restore",
            "observer_surface",
        ],
        "capability_states": {
            "collection": {
                "state": "supported_unconfigured",
                "evidence": "six real source adapters exist; every source enabled=false",
            },
            "health": {
                "state": "active",
                "evidence": "read-only health surface over persistent state",
            },
            "events": {
                "state": "active",
                "evidence": "event/outbox plane with baseline silence and diagnostic conditions",
            },
            "delivery": {
                "state": "unsupported_by_policy",
                "evidence": "notification rows are generated outbox-only; no send path exists; promotion_freeze=true",
            },
            "scheduler": {
                "state": "unsupported_by_policy",
                "evidence": "no scheduler authority declared or implemented",
            },
            "backup_restore": {
                "state": "active",
                "evidence": "operator-triggered SQLite online backup with SHA-256 verified isolated restore",
            },
            "observer_surface": {
                "state": "active",
                "evidence": "read-only identity/capabilities/status/health/last_run/capability_states",
            },
            "replay": {
                "state": "active",
                "evidence": "processed_run_receipts idempotency proven across six vendors",
            },
            "deployment": {
                "state": "unknown_or_unverified",
                "evidence": "no deployment evidence exists; deployed HEAD is a separate observer fact",
            },
        },
        "sources": [
            "raspberry-pi-product",
            "orange-pi-product",
            "radxa-product",
            "banana-pi-product",
            "hardkernel-odroid-product",
            "pine64-product",
        ],
        "scheduler_authority": "NONE",
        "notification_authority": "NONE",
        "persistence": {
            "engine": "sqlite",
            "schema_version": EXPECTED_SCHEMA_VERSION,
            "default_path_semantics": "operator-provided --db path; no writes outside the declared database file",
        },
        "observer_surface": {
            "contract": "Observer Adapter Surface Contract v0.2 (required core)",
            "methods": [
                "identity",
                "capabilities",
                "status",
                "health",
                "last_run",
                "capability_states",
            ],
            "optional_extensions": [
                "schema_revision",
                "source_summary",
                "diagnostic_summary",
                "execution_evidence",
            ],
            "read_only": True,
        },
        "backup_restore": {
            "operator_triggered": True,
            "format": f"sqlite online-backup image + sidecar metadata (format v{BACKUP_FORMAT_VERSION_LABEL})",
            "integrity": "PRAGMA integrity_check + SHA-256 verified",
        },
    }




REQUIRED_FIELDS = (
    "manifest_version",
    "clank_id",
    "display_name",
    "maturity",
    "versions",
    "ownership",
    "capabilities",
    "capability_states",
    "sources",
    "scheduler_authority",
    "notification_authority",
    "persistence",
    "observer_surface",
    "backup_restore",
)

REQUIRED_VERSION_FIELDS = ("package", "schema", "code_revision", "adapter_contract")


class ManifestError(RuntimeError):
    pass


def validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Machine-validation. Raises ManifestError on any violation; returns a
    report on success."""
    missing = [field for field in REQUIRED_FIELDS if field not in manifest]
    if missing:
        raise ManifestError(f"manifest missing required fields: {missing}")
    missing_versions = [field for field in REQUIRED_VERSION_FIELDS if field not in manifest["versions"]]
    if missing_versions:
        raise ManifestError(f"manifest versions missing required fields: {missing_versions}")
    if manifest["clank_id"] != CLANK_ID:
        raise ManifestError(f"clank_id mismatch: {manifest['clank_id']}")
    if manifest["versions"]["schema"] != EXPECTED_SCHEMA_VERSION:
        raise ManifestError(
            f"manifest schema version {manifest['versions']['schema']} != runtime {EXPECTED_SCHEMA_VERSION}"
        )
    for state_entry in manifest["capability_states"].values():
        state = state_entry.get("state")
        if state not in CAPABILITY_STATES:
            raise ManifestError(f"capability state outside canonical vocabulary: {state}")
        if not state_entry.get("evidence"):
            raise ManifestError("capability state without evidence reference")
    if manifest["scheduler_authority"] != "NONE":
        raise ManifestError("Board Clank must declare scheduler_authority NONE (Fleet Law 5, Phase 1)")
    if manifest["notification_authority"] != "NONE":
        raise ManifestError("Board Clank must declare notification_authority NONE (Fleet Law 5, Phase 1)")
    if not manifest["observer_surface"].get("read_only"):
        raise ManifestError("observer surface must declare read_only=true")
    for source in manifest["sources"]:
        if not isinstance(source, str) or not source.endswith("-product"):
            raise ManifestError(f"malformed source key: {source}")
    return {
        "valid": True,
        "clank_id": manifest["clank_id"],
        "manifest_version": manifest["manifest_version"],
        "schema_version": manifest["versions"]["schema"],
        "capability_count": len(manifest["capabilities"]),
        "source_count": len(manifest["sources"]),
    }


def load_manifest(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path else (MANIFEST_PATH if MANIFEST_PATH.exists() else PACKAGED_MANIFEST_PATH)
    return json.loads(target.read_text(encoding="utf-8"))
