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
