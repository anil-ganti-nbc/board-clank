"""Frozen cnx-board-candidate-v1 envelope. The content hash excludes itself."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from board_clank.research import SCHEMA_VERSION

REQUIRED_FIELDS = (
    "schema_version",
    "cnx_run_id",
    "discovered_at_utc",
    "cnx_candidate_id",
    "canonical_oem_name",
    "candidate_first_party_domain",
    "candidate_product_urls",
    "candidate_catalogue_url",
    "discovery_reason",
    "discovery_source_class",
    "dedup_baseline_version",
    "dedup_baseline_hash",
    "cnx_contract_version",
    "cnx_contract_hash",
    "provenance_hashes",
    "discovery_status",
)
OPTIONAL_FIELDS = ("notes",)
ALLOWED_FIELDS = frozenset(REQUIRED_FIELDS + OPTIONAL_FIELDS)
DISCOVERY_STATUSES = frozenset({"research_lead"})
DISCOVERY_SOURCE_CLASSES = frozenset({"cnx_article", "synthetic_fixture"})
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,200}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_SHA = re.compile(r"^sha256:[0-9a-f]{64}$")
_PROVENANCE_KEY = re.compile(r"^[a-z0-9_]{1,64}$")

CONTRACT_TEXT = "\n".join((SCHEMA_VERSION, *REQUIRED_FIELDS, "notes")) + "\n"
CONTRACT_HASH = "sha256:" + hashlib.sha256(CONTRACT_TEXT.encode("utf-8")).hexdigest()


class EnvelopeError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def canonical_bytes(envelope: dict[str, Any]) -> bytes:
    """Sorted-key JSON of the envelope only. Insertion order cannot change the hash."""
    return json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def envelope_hash(envelope: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(envelope)).hexdigest()


def seal(envelope: dict[str, Any]) -> dict[str, Any]:
    """JSONL record. The hash is a sibling, so it is not part of the hashed bytes."""
    return {"envelope_hash": envelope_hash(envelope), "envelope": envelope}


def line_bytes(record: dict[str, Any]) -> bytes:
    return (json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(ord(ch) < 32 for ch in value):
        raise EnvelopeError(f"malformed_{field}")
    return value.strip()


def validate_envelope(envelope: Any) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        raise EnvelopeError("malformed_envelope")
    unknown = set(envelope) - ALLOWED_FIELDS
    if unknown:
        raise EnvelopeError("unknown_field")
    missing = [field for field in REQUIRED_FIELDS if field not in envelope]
    if missing:
        if "cnx_candidate_id" in missing:
            raise EnvelopeError("missing_candidate_id")
        if "candidate_first_party_domain" in missing:
            raise EnvelopeError("missing_domain")
        raise EnvelopeError("missing_field:" + ",".join(missing))
    if envelope["schema_version"] != SCHEMA_VERSION or envelope["cnx_contract_version"] != SCHEMA_VERSION:
        raise EnvelopeError("schema_version")
    if envelope["cnx_contract_hash"] != CONTRACT_HASH:
        raise EnvelopeError("contract_hash")
    if envelope["discovery_status"] not in DISCOVERY_STATUSES:
        raise EnvelopeError("discovery_status")
    if envelope["discovery_source_class"] not in DISCOVERY_SOURCE_CLASSES:
        raise EnvelopeError("discovery_source_class")
    for field in ("cnx_run_id", "cnx_candidate_id"):
        if not isinstance(envelope[field], str) or _ID.fullmatch(envelope[field]) is None:
            raise EnvelopeError("missing_candidate_id" if field == "cnx_candidate_id" else "malformed_run_id")
    if not isinstance(envelope["discovered_at_utc"], str) or _UTC.fullmatch(envelope["discovered_at_utc"]) is None:
        raise EnvelopeError("malformed_discovered_at")
    oem = _text(envelope["canonical_oem_name"], "oem")
    if len(oem) > 200:
        raise EnvelopeError("malformed_oem")
    domain = _text(envelope["candidate_first_party_domain"], "domain")
    urls = envelope["candidate_product_urls"]
    if not isinstance(urls, list) or not urls or any(not isinstance(item, str) or not item.strip() for item in urls):
        raise EnvelopeError("malformed_product_urls")
    catalogue = _text(envelope["candidate_catalogue_url"], "catalogue_url")
    _text(envelope["discovery_reason"], "discovery_reason")
    if not isinstance(envelope["dedup_baseline_version"], str) or not envelope["dedup_baseline_version"].strip():
        raise EnvelopeError("stale_baseline")
    if not isinstance(envelope["dedup_baseline_hash"], str) or _SHA.fullmatch(envelope["dedup_baseline_hash"]) is None:
        raise EnvelopeError("stale_baseline")
    provenance = envelope["provenance_hashes"]
    if not isinstance(provenance, dict) or not provenance:
        raise EnvelopeError("malformed_provenance")
    for key, value in provenance.items():
        if not isinstance(key, str) or _PROVENANCE_KEY.fullmatch(key) is None:
            raise EnvelopeError("malformed_provenance")
        if not isinstance(value, str) or _SHA.fullmatch(value) is None:
            raise EnvelopeError("malformed_provenance")
    if "notes" in envelope and envelope["notes"] is not None and not isinstance(envelope["notes"], str):
        raise EnvelopeError("malformed_notes")
    cleaned = {field: envelope[field] for field in REQUIRED_FIELDS}
    cleaned["candidate_first_party_domain"] = domain
    cleaned["canonical_oem_name"] = oem
    cleaned["candidate_product_urls"] = [item.strip() for item in urls]
    cleaned["candidate_catalogue_url"] = catalogue
    if "notes" in envelope and envelope["notes"] is not None:
        cleaned["notes"] = envelope["notes"]
    return cleaned


def verify_record(record: Any) -> tuple[dict[str, Any], str]:
    if not isinstance(record, dict) or set(record) != {"envelope", "envelope_hash"}:
        raise EnvelopeError("malformed_record")
    envelope = validate_envelope(record["envelope"])
    expected = envelope_hash(envelope)
    declared = record["envelope_hash"]
    if not isinstance(declared, str) or declared != expected:
        raise EnvelopeError("invalid_envelope_hash")
    return envelope, expected
