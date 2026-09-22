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
