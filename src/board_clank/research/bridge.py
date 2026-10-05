"""Import, replay, qualify, and reject CNX research envelopes."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from board_clank.research.baseline import BASELINE_VERSION, baseline_matches
from board_clank.research.domain import domain_refusal, normalize_domain, normalize_oem, url_on_domain
from board_clank.research.envelope import EnvelopeError, verify_record
from board_clank.research.fetch import FetchEvidence, FetchRejected, fetch_first_party
from board_clank.research.policy import roster_conflict
from board_clank.research.store import ResearchStore

Fetch = Callable[[str, str], FetchEvidence]
OEM_MARK = "board-research-oem:"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def lead_id_for(candidate_id: str) -> str:
    return "lead_" + hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[:24]


def _disposition_id(raw: bytes) -> str:
    return "disp_" + hashlib.sha256(raw).hexdigest()[:24]


def _public_lead(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "lead_id": row["lead_id"],
        "cnx_candidate_id": row["cnx_candidate_id"],
        "cnx_run_id": row["cnx_run_id"],
        "canonical_oem_name": row["canonical_oem_name"],
        "claimed_domain": row["claimed_domain"],
        "candidate_urls": json.loads(row["candidate_urls_json"]),
        "catalogue_url": row["catalogue_url"],
        "envelope_hash": row["envelope_hash"],
        "provenance": json.loads(row["provenance_json"]),
        "imported_at": row["imported_at"],
        "status": row["status"],
        "qualification_state": row["qualification_state"],
        "reason": row["reason"],
        "evidence": json.loads(row["evidence_json"]),
    }


def _result(status: str, reason: str | None, lead: dict[str, Any] | None, code: int) -> dict[str, Any]:
    return {"status": status, "reason": reason, "lead": lead, "exit_code": code}


def _policy_reason(envelope: dict[str, Any], sources_path: str | None) -> str | None:
    if not baseline_matches(envelope["dedup_baseline_version"], envelope["dedup_baseline_hash"], sources_path):
        if envelope["dedup_baseline_version"] != BASELINE_VERSION:
            return "unknown_baseline"
        return "stale_baseline"
    domain = normalize_domain(envelope["candidate_first_party_domain"])
    refusal = domain_refusal(domain)
    if refusal:
        return refusal
    urls = [envelope["candidate_catalogue_url"], *envelope["candidate_product_urls"]]
    if any(not url_on_domain(url, domain) for url in urls):
        return "third_party_only"
    return roster_conflict(envelope["canonical_oem_name"], domain, sources_path)


def import_record(store: ResearchStore, raw: bytes, record: Any, *, sources_path: str | None = None) -> dict[str, Any]:
    try:
        envelope, digest = verify_record(record)
    except EnvelopeError as exc:
        disposition = _disposition_id(raw)
        existing = store.disposition(disposition)
        if existing:
            return _result("replayed_quarantine", existing["reason"], None, 2)
        store.insert_disposition({
            "disposition_id": disposition,
            "created_at": _now(),
            "status": "QUARANTINED",
            "reason": exc.reason,
            "envelope_hash": record.get("envelope_hash") if isinstance(record, dict) else None,
            "cnx_candidate_id": record.get("envelope", {}).get("cnx_candidate_id") if isinstance(record, dict) and isinstance(record.get("envelope"), dict) else None,
            "cnx_run_id": record.get("envelope", {}).get("cnx_run_id") if isinstance(record, dict) and isinstance(record.get("envelope"), dict) else None,
            "detail": {"reason": exc.reason},
        })
        return _result("quarantined", exc.reason, None, 2)
    except json.JSONDecodeError:
        return _quarantine_raw(store, raw, "malformed_json")

    prior = store.lead_by_hash(digest)
    if prior:
        return _result("replayed", None, _public_lead(prior), 0)
    same_candidate = store.lead_by_candidate(envelope["cnx_candidate_id"])
    if same_candidate:
        _remember(store, raw, "QUARANTINED", "cross_run_duplicate", digest, envelope)
        return _result("quarantined", "cross_run_duplicate", _public_lead(same_candidate), 2)
    reason = _policy_reason(envelope, sources_path)
    if reason:
        status = "REJECTED" if reason.endswith("_duplicate") else "QUARANTINED"
        _remember(store, raw, status, reason, digest, envelope)
        return _result(status.lower(), reason, None, 2)
    created = _now()
    row = {
        "lead_id": lead_id_for(envelope["cnx_candidate_id"]),
        "cnx_candidate_id": envelope["cnx_candidate_id"],
        "cnx_run_id": envelope["cnx_run_id"],
        "canonical_oem_name": envelope["canonical_oem_name"],
        "claimed_domain": normalize_domain(envelope["candidate_first_party_domain"]),
        "candidate_urls_json": json.dumps(envelope["candidate_product_urls"], sort_keys=False),
        "catalogue_url": envelope["candidate_catalogue_url"],
        "envelope_hash": digest,
        "provenance_json": json.dumps({
            "provenance_hashes": envelope["provenance_hashes"],
            "cnx_contract_version": envelope["cnx_contract_version"],
            "cnx_contract_hash": envelope["cnx_contract_hash"],
            "dedup_baseline_version": envelope["dedup_baseline_version"],
            "dedup_baseline_hash": envelope["dedup_baseline_hash"],
            "discovery_source_class": envelope["discovery_source_class"],
            "discovery_reason": envelope["discovery_reason"],
        }, sort_keys=True),
        "imported_at": created,
        "status": "IMPORTED",
        "qualification_state": "unreviewed",
        "reason": None,
        "evidence_json": "[]",
        "envelope_json": json.dumps(envelope, sort_keys=True),
    }
    store.insert_lead(row)
    return _result("imported", None, _public_lead(store.lead(row["lead_id"]) or row), 0)


def _quarantine_raw(store: ResearchStore, raw: bytes, reason: str) -> dict[str, Any]:
    disposition = _disposition_id(raw)
    if store.disposition(disposition):
        return _result("replayed_quarantine", reason, None, 2)
    store.insert_disposition({
        "disposition_id": disposition,
        "created_at": _now(),
        "status": "QUARANTINED",
        "reason": reason,
        "detail": {"reason": reason},
    })
    return _result("quarantined", reason, None, 2)


def _remember(store: ResearchStore, raw: bytes, status: str, reason: str, digest: str, envelope: dict[str, Any]) -> None:
    store.insert_disposition({
        "disposition_id": _disposition_id(raw),
        "created_at": _now(),
        "status": status,
        "reason": reason,
        "envelope_hash": digest,
        "cnx_candidate_id": envelope.get("cnx_candidate_id"),
        "cnx_run_id": envelope.get("cnx_run_id"),
        "detail": {"reason": reason, "oem": envelope.get("canonical_oem_name"), "domain": envelope.get("candidate_first_party_domain")},
    })


def import_jsonl(store: ResearchStore, path: str | Path, *, sources_path: str | None = None) -> dict[str, Any]:
    lines = Path(path).read_bytes().splitlines()
    results = []
    for raw in lines:
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            results.append(_quarantine_raw(store, raw, "malformed_json"))
            continue
        results.append(import_record(store, raw, record, sources_path=sources_path))
    code = 0 if results and all(item["exit_code"] == 0 for item in results) else 2
    if not results:
        code = 2
    return {"exit_code": code, "results": results, "counts": store.counts()}


def qualify_lead(store: ResearchStore, lead_id: str, *, fetch: Fetch | None = None) -> dict[str, Any]:
    fetch = fetch or fetch_first_party
    row = store.lead(lead_id)
    if row is None:
        return _result("missing", "unknown_lead", None, 2)
    if row["status"] in {"REJECTED", "QUARANTINED"}:
        return _result(row["status"].lower(), row["reason"], _public_lead(row), 2)
    store.update_lead(lead_id, status="QUALIFYING")
    envelope = json.loads(row["envelope_json"])
    domain = row["claimed_domain"]
    urls = [row["catalogue_url"], *json.loads(row["candidate_urls_json"])]
    evidence: list[dict[str, Any]] = []
    disagreement = None
    try:
        for url in urls:
            item = fetch(url, domain)
            text = item.body_text
            marker = next((line.split(":", 1)[1].strip() for line in text.splitlines() if line.lower().startswith(OEM_MARK)), None)
            evidence.append({**item.as_dict(), "board_oem_marker": marker})
            if marker is not None and normalize_oem(marker) != normalize_oem(envelope["canonical_oem_name"]):
                disagreement = {"cnx_oem": envelope["canonical_oem_name"], "board_oem": marker, "url": item.final_url}
                break
    except FetchRejected as exc:
        store.update_lead(
            lead_id,
            status="QUARANTINED",
            qualification_state="unreviewed",
            reason=exc.reason,
            evidence_json=json.dumps(evidence, sort_keys=True),
        )
        return _result("quarantined", exc.reason, _public_lead(store.lead(lead_id) or row), 2)
    if disagreement:
        store.update_lead(
            lead_id,
            status="QUARANTINED",
            qualification_state="disagreement",
            reason="board_evidence_disagrees",
            evidence_json=json.dumps({"fetches": evidence, "disagreement": disagreement}, sort_keys=True),
        )
        fresh = _public_lead(store.lead(lead_id) or row)
        return _result("quarantined", "board_evidence_disagrees", fresh, 2)
    store.update_lead(
        lead_id,
        status="QUALIFIED",
        qualification_state="first_party_observed",
        reason=None,
        evidence_json=json.dumps(evidence, sort_keys=True),
    )
    return _result("qualified", None, _public_lead(store.lead(lead_id) or row), 0)


def reject_lead(store: ResearchStore, lead_id: str, reason: str) -> dict[str, Any]:
    if not isinstance(reason, str) or not reason.strip():
        return _result("rejected", "missing_reason", None, 2)
    row = store.lead(lead_id)
    if row is None:
        return _result("missing", "unknown_lead", None, 2)
    store.update_lead(lead_id, status="REJECTED", reason=reason.strip())
    return _result("rejected", reason.strip(), _public_lead(store.lead(lead_id) or row), 0)
