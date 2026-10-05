"""Operator actions. Every mutation calls the research bridge and then re-reads."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from board_clank.research import SCHEMA_VERSION
from board_clank.research.bridge import _public_lead, import_jsonl, qualify_lead, reject_lead
from board_clank.research.paths import same_database
from board_clank.research.store import ResearchStore, ResearchStoreError
from board_clank.sources import load_sources
from board_clank.ui.standards import (
    PROTOTYPE_BASE_SHA,
    PROTOTYPE_BASE_TREE,
    STANDARDS_UI_COMMIT,
    STANDARDS_UI_TAG,
)

DECIDED_STATUSES = frozenset({"QUALIFIED", "REJECTED", "QUARANTINED"})
_SUCCESS_STATUSES = frozenset({"qualified", "rejected", "imported", "replayed"})


class SurfaceError(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class UiIdentity:
    app_sha: str
    app_tree: str
    bind_host: str = ""
    bind_port: int = 0
    standards_tag: str = STANDARDS_UI_TAG
    standards_commit: str = STANDARDS_UI_COMMIT
    prototype_base_sha: str = PROTOTYPE_BASE_SHA
    prototype_base_tree: str = PROTOTYPE_BASE_TREE


def file_fingerprint(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {"path": str(path), "exists": False, "size_bytes": None, "sha256": None}
    data = path.read_bytes()
    return {
        "path": str(path),
        "exists": True,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def present_lead(row: dict[str, Any]) -> dict[str, Any]:
    lead = _public_lead(row)
    envelope = json.loads(row["envelope_json"])
    lead["discovered_at_utc"] = envelope.get("discovered_at_utc")
    lead["discovery_reason"] = envelope.get("discovery_reason")
    lead["discovery_source_class"] = envelope.get("discovery_source_class")
    lead["notes"] = envelope.get("notes")
    return lead


def _evidence_parts(evidence: Any) -> tuple[list[Any], Any]:
    if isinstance(evidence, list):
        return evidence, None
    if isinstance(evidence, dict):
        fetches = evidence.get("fetches")
        return (fetches if isinstance(fetches, list) else []), evidence.get("disagreement")
    return [], None


def activity_stages(lead: dict[str, Any]) -> list[dict[str, str]]:
    """Presentation of stored qualification fields. No stage is invented."""
    stages = [
        {"name": "research status", "outcome": str(lead.get("status") or "UNKNOWN")},
        {"name": "qualification state", "outcome": str(lead.get("qualification_state") or "UNKNOWN")},
    ]
    if lead.get("reason"):
        stages.append({"name": "recorded reason", "outcome": str(lead["reason"])})
    fetches, disagreement = _evidence_parts(lead.get("evidence"))
    if not fetches:
        stages.append({"name": "fetch", "outcome": "no fetch stage recorded"})
    for index, item in enumerate(fetches, start=1):
        if not isinstance(item, dict):
            stages.append({"name": f"fetch {index}", "outcome": "unreadable fetch record"})
            continue
        stages.append({
            "name": f"fetch {index} requested URL",
            "outcome": str(item.get("requested_url") or "UNKNOWN"),
        })
        stages.append({
            "name": f"fetch {index} final URL",
            "outcome": str(item.get("final_url") or "UNKNOWN"),
        })
        stages.append({
            "name": f"fetch {index} HTTP status",
            "outcome": str(item.get("status") if item.get("status") is not None else "UNKNOWN"),
        })
        stages.append({
            "name": f"fetch {index} body sha256",
            "outcome": str(item.get("body_sha256") or "UNKNOWN"),
        })
    if disagreement:
        stages.append({"name": "disagreement", "outcome": json.dumps(disagreement, sort_keys=True)})
    return stages


class ResearchSurface:
    def __init__(self, canonical_db: str | Path, research_db: str | Path, identity: UiIdentity) -> None:
        self.canonical_db = Path(canonical_db)
        self.research_db = Path(research_db)
        self.identity = identity
        self._lock = threading.Lock()
        if same_database(self.research_db, self.canonical_db):
            raise SurfaceError("research_db_must_not_be_canonical_db")

    def health(self) -> dict[str, Any]:
        return {
            "ready": True,
            "host": self.identity.bind_host,
            "port": self.identity.bind_port,
            "collection": False,
            "qualification": False,
            "cnx_export": False,
            "source_fetch": False,
            "scheduler": False,
        }

    def _leads(self) -> list[dict[str, Any]]:
        with ResearchStore(self.research_db) as store:
            rows = [store.lead(item["lead_id"]) for item in store.list_leads()]
        return [present_lead(row) for row in rows if row is not None]

    def _sources(self) -> list[dict[str, Any]]:
        rows = []
        for source in load_sources():
            plane = source.plane.value if hasattr(source.plane, "value") else str(source.plane)
            rows.append({
                "source_key": source.source_key,
                "vendor": source.vendor,
                "enabled": bool(source.enabled),
                "promotion_state": source.promotion_state,
                "plane": plane,
            })
        return rows

    def overview(self) -> dict[str, Any]:
        leads = self._leads()
        counts: dict[str, int] = {}
        for lead in leads:
            counts[lead["status"]] = counts.get(lead["status"], 0) + 1
        sources = self._sources()
        return {
            "identity": self.identity,
            "schema_version": SCHEMA_VERSION,
            "canonical": file_fingerprint(self.canonical_db),
            "research": file_fingerprint(self.research_db),
            "counts": counts,
            "lead_total": len(leads),
            "sources": sources,
            "sources_enabled": sum(1 for row in sources if row["enabled"]),
            "runtime_health": "UNKNOWN",
            "source_operational_health": "UNKNOWN",
        }

    def leads_by_queue(self, queue: str) -> list[dict[str, Any]]:
        leads = self._leads()
        if queue == "archive":
            return [lead for lead in leads if lead["status"] in DECIDED_STATUSES]
        return [lead for lead in leads if lead["status"] not in DECIDED_STATUSES]

    def lead(self, lead_id: str) -> dict[str, Any] | None:
        with ResearchStore(self.research_db) as store:
            row = store.lead(lead_id)
        if row is None:
            return None
        return present_lead(row)

    def activity(self) -> list[dict[str, Any]]:
        rows = []
        for lead in self._leads():
            rows.append({"lead": lead, "stages": activity_stages(lead)})
        return rows

    def import_candidates(self, jsonl_path: str) -> dict[str, Any]:
        target = Path(jsonl_path)
        if not jsonl_path.strip() or not target.is_file():
            return self._outcome(False, False, "import", "jsonl path is not a file", None, None)
        try:
            with self._lock:
                with ResearchStore(self.research_db) as store:
                    report = import_jsonl(store, target)
        except (OSError, ResearchStoreError) as exc:
            return self._outcome(False, False, "import", str(exc), None, None)
        success = report["exit_code"] == 0
        wrote = success or any(item.get("status") in {"quarantined", "rejected", "imported", "replayed"} for item in report["results"])
        reason = None if success else "import_not_fully_accepted"
        return self._outcome(success, wrote, "import", reason, None, report)

    def qualify(self, lead_id: str) -> dict[str, Any]:
        try:
            with self._lock:
                with ResearchStore(self.research_db) as store:
                    result = qualify_lead(store, lead_id)
                    stored = self._stored(store, result.get("lead"))
        except (OSError, ResearchStoreError) as exc:
            return self._outcome(False, False, "qualify", str(exc), None, None)
        return self._from_bridge(result, stored, action="qualify")

    def reject(self, lead_id: str, reason: str) -> dict[str, Any]:
        try:
            with self._lock:
                with ResearchStore(self.research_db) as store:
                    result = reject_lead(store, lead_id, reason)
                    stored = self._stored(store, result.get("lead"))
        except (OSError, ResearchStoreError) as exc:
            return self._outcome(False, False, "reject", str(exc), None, None)
        return self._from_bridge(result, stored, action="reject")

    def _stored(self, store: ResearchStore, lead: dict[str, Any] | None) -> dict[str, Any] | None:
        if not lead or not lead.get("lead_id"):
            return None
        row = store.lead(str(lead["lead_id"]))
        return present_lead(row) if row else None

    def _from_bridge(self, result: dict[str, Any], stored: dict[str, Any] | None, *, action: str) -> dict[str, Any]:
        returned = result.get("lead")
        match = bool(
            stored is not None
            and isinstance(returned, dict)
            and stored.get("status") == returned.get("status")
            and stored.get("lead_id") == returned.get("lead_id")
        )
        status = str(result.get("status") or "")
        success = bool(match and result.get("exit_code") == 0 and status in _SUCCESS_STATUSES)
        committed = bool(match and status in {"qualified", "quarantined", "rejected", "imported", "replayed"})
        return self._outcome(success, committed, action, result.get("reason"), stored, result)

    def _outcome(
        self,
        success: bool,
        committed: bool,
        action: str,
        reason: str | None,
        lead: dict[str, Any] | None,
        raw: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if success:
            message = f"{action} succeeded and committed"
        elif committed:
            message = f"{action} committed without success"
        else:
            message = f"{action} not committed"
        return {
            "success": success,
            "committed": committed,
            "action": action,
            "reason": reason,
            "message": message,
            "lead": lead,
            "raw": raw,
        }
