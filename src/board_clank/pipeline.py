"""Transactional observation admission. Canonical payload is separate from chronology."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from board_clank.identity import (
    UNKNOWN,
    VariantDimensions,
    build_identity,
    silent_revision_token,
)
from board_clank.models import (
    CollectorRunRequest,
    EventRecord,
    ObservationDraft,
    canonical_json,
    content_hash,
)
from board_clank.policy import disposition_for
from board_clank.store import Store
from board_clank.taxonomy import (
    EntityKind,
    EventType,
    NoveltyStatus,
    RevisionKind,
    SourceAuthority,
    SourcePlane,
)

AUTHORITATIVE_PLANES = {SourcePlane.PRODUCT, SourcePlane.DOCUMENTATION, SourcePlane.ANNOUNCEMENT}
WEAK_OVERRIDE_AUTHORITY = {SourceAuthority.THIRD_PARTY_DISCOVERY, SourceAuthority.UNVERIFIED}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class RunResult:
    run_id: str
    status: str
    replayed: bool = False
    baseline: bool = False
    observations: int = 0
    occurrences: int = 0
    events: list[str] = field(default_factory=list)
    notifications: int = 0
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "replayed": self.replayed,
            "baseline": self.baseline,
            "observations": self.observations,
            "occurrences": self.occurrences,
            "events": self.events,
            "notifications": self.notifications,
            "error": self.error,
        }


class Pipeline:
    def __init__(self, store: Store) -> None:
        self.store = store

    def accept_run(self, request: CollectorRunRequest) -> RunResult:
        existing = self.store.one(
            "SELECT run_id FROM processed_run_receipts WHERE run_id = ?",
            (request.run_id,),
        )
        if existing:
            return RunResult(run_id=request.run_id, status="replayed", replayed=True)

        if not request.ok:
            self.store.execute(
                """
                INSERT INTO collector_runs(run_id, source_key, collector_key, started_at, finished_at, status, fixture_scenario, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request.run_id,
                    request.source_key,
                    request.collector_key,
                    request.started_at,
                    _now(),
                    "failed",
                    request.fixture_scenario,
                    request.error,
                ),
            )
            self.store.execute(
                "INSERT INTO run_errors(run_id, source_key, message, created_at) VALUES (?, ?, ?, ?)",
                (request.run_id, request.source_key, request.error or "collector failed", _now()),
            )
            self.store.commit()
            return RunResult(run_id=request.run_id, status="failed", error=request.error)

        baseline = self._is_baseline(request.source_key)
        event_keys: list[str] = []
        occurrences = 0
        try:
            self.store.begin()
            self.store.execute(
                """
                INSERT INTO collector_runs(run_id, source_key, collector_key, started_at, finished_at, status, fixture_scenario, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request.run_id,
                    request.source_key,
                    request.collector_key,
                    request.started_at,
                    None,
                    "accepted",
                    request.fixture_scenario,
                    None,
                ),
            )
            for draft in request.observations:
                occ, keys = self._admit_observation(request, draft, baseline=baseline)
                occurrences += occ
                event_keys.extend(keys)
            if baseline:
                self.store.execute(
                    """
                    INSERT INTO source_baselines(source_key, baseline_run_id, established_at, observation_count)
                    VALUES (?, ?, ?, ?)
                    """,
                    (request.source_key, request.run_id, _now(), len(request.observations)),
                )
            notification_count = self._count_notifications(event_keys)
            receipt_hash = content_hash(
                {
                    "run_id": request.run_id,
                    "source_key": request.source_key,
                    "observation_count": len(request.observations),
                    "event_keys": event_keys,
                }
            )
            self.store.execute(
                """
                INSERT INTO processed_run_receipts(run_id, source_key, receipt_hash, accepted_at, observation_count, event_count)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    request.run_id,
                    request.source_key,
                    receipt_hash,
                    _now(),
                    len(request.observations),
                    len(event_keys),
                ),
            )
            self.store.execute(
                "UPDATE collector_runs SET finished_at = ?, status = ? WHERE run_id = ?",
                (_now(), "accepted", request.run_id),
            )
            self.store.commit()
        except Exception:
            self.store.rollback()
            raise
        return RunResult(
            run_id=request.run_id,
            status="accepted",
            baseline=baseline,
            observations=len(request.observations),
            occurrences=occurrences,
            events=event_keys,
            notifications=notification_count,
        )
