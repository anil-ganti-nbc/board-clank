"""Write immutable JSONL. Existing output is not rewritten."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from board_clank.research.baseline import BASELINE_VERSION, baseline_hash
from board_clank.research.envelope import CONTRACT_HASH, SCHEMA_VERSION, line_bytes, seal


def make_envelope(
    *,
    run_id: str,
    candidate_id: str,
    oem: str,
    domain: str,
    product_url: str,
    catalogue_url: str,
    discovered_at_utc: str = "2026-10-05T12:00:00Z",
    discovery_reason: str = "bounded synthetic research lead",
    discovery_source_class: str = "synthetic_fixture",
    provenance_hashes: dict[str, str] | None = None,
    notes: str | None = None,
    dedup_baseline_version: str | None = None,
    dedup_baseline_hash: str | None = None,
    sources_path: str | None = None,
) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "cnx_run_id": run_id,
        "discovered_at_utc": discovered_at_utc,
        "cnx_candidate_id": candidate_id,
        "canonical_oem_name": oem,
        "candidate_first_party_domain": domain,
        "candidate_product_urls": [product_url],
        "candidate_catalogue_url": catalogue_url,
        "discovery_reason": discovery_reason,
        "discovery_source_class": discovery_source_class,
        "dedup_baseline_version": dedup_baseline_version or BASELINE_VERSION,
        "dedup_baseline_hash": dedup_baseline_hash or baseline_hash(sources_path),
        "cnx_contract_version": SCHEMA_VERSION,
        "cnx_contract_hash": CONTRACT_HASH,
        "provenance_hashes": provenance_hashes or {
            "article": "sha256:" + "ab" * 32,
        },
        "discovery_status": "research_lead",
    }
    if notes is not None:
        envelope["notes"] = notes
    return envelope


def synthetic_envelope(run_id: str, *, sources_path: str | None = None) -> dict[str, Any]:
    return make_envelope(
        run_id=run_id,
        candidate_id="cand-northwind-1",
        oem="Northwind Boards",
        domain="northwind.example",
        product_url="https://northwind.example/products/sbc",
        catalogue_url="https://northwind.example/catalogue",
        notes="Synthetic stand-in. Not a CNX live discovery and not Board PRODUCT evidence.",
        sources_path=sources_path,
    )


def export_jsonl(path: str | Path, envelopes: list[dict[str, Any]], *, run_id: str) -> int:
    target = Path(path)
    if target.exists():
        raise FileExistsError(f"refusing to rewrite immutable JSONL: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as handle:
        for envelope in envelopes:
            if envelope.get("cnx_run_id") != run_id:
                raise ValueError("envelope run id does not match --run")
            handle.write(line_bytes(seal(envelope)))
    return len(envelopes)
