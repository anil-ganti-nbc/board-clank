"""Transactional observation admission. Canonical payload is separate from chronology."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace

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
    diagnostics: dict = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
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
        if self.diagnostics:
            payload["diagnostics"] = self.diagnostics
        return payload


class Pipeline:
    def __init__(self, store: Store) -> None:
        self.store = store

    def accept_run(self, request: CollectorRunRequest) -> RunResult:
        existing = self.store.one(
            "SELECT run_id FROM processed_run_receipts WHERE run_id = ?",
            (request.run_id,),
        )
        if existing:
            return RunResult(
                run_id=request.run_id,
                status="replayed",
                replayed=True,
                diagnostics=dict(request.diagnostics or {}),
            )

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
            return RunResult(
                run_id=request.run_id,
                status="failed",
                error=request.error,
                diagnostics=dict(request.diagnostics or {}),
            )

        baseline = self._is_baseline(request.source_key)
        event_keys: list[str] = []
        occurrences = 0
        unresolved: list[tuple[ObservationDraft, "_UnresolvedIdentity"]] = []
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
                occ, keys = self._admit_observation(request, draft, baseline=baseline, unresolved_out=unresolved)
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
            # Diagnostics are admitted as a per-run batch: one candidate may be
            # evidenced ambiguous by several pages at once, and the condition's
            # state is the aggregate of that run's evidence.
            event_keys.extend(self._admit_diagnostic_batch(request, unresolved, baseline=baseline))
            resolved_keys = self._reconcile_diagnostic_conditions(request, baseline=baseline)
            event_keys.extend(resolved_keys)
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
            diagnostics=dict(request.diagnostics or {}),
        )

    def _is_baseline(self, source_key: str) -> bool:
        row = self.store.one("SELECT source_key FROM source_baselines WHERE source_key = ?", (source_key,))
        return row is None

    def _admit_observation(
        self,
        request: CollectorRunRequest,
        draft: ObservationDraft,
        *,
        baseline: bool,
        unresolved_out: list | None = None,
    ) -> tuple[int, list[str]]:
        if draft.evidence_insufficient:
            if unresolved_out is not None:
                unresolved_out.append((draft, _UnresolvedIdentity(draft)))
                return 0, []
            return self._admit_unresolved(request, draft, baseline=baseline)
        identity = self._resolve_identity(draft)
        self._upsert_graph(draft, identity, request)
        events: list[EventRecord] = []

        for entity_key, kind in (
            (identity.board_key, EntityKind.BOARD),
            (identity.revision_key, EntityKind.REVISION),
            (identity.variant_key, EntityKind.VARIANT),
        ):
            payload = draft.canonical_payload(kind)
            payload_hash = draft.payload_hash(kind)
            events.extend(
                self._sync_entity(
                    request,
                    draft,
                    entity_key,
                    kind,
                    payload,
                    payload_hash,
                    identity,
                    baseline,
                )
            )

        self._record_novelty(draft, identity)
        self._record_classifications(draft, identity)
        self._record_software(draft, identity, request)
        if draft.price:
            self.store.execute(
                """
                INSERT INTO price_observations(variant_key, source_key, amount, currency, region, observed_at, run_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identity.variant_key,
                    request.source_key,
                    draft.price.amount,
                    draft.price.currency,
                    draft.price.region,
                    draft.price.observed_at,
                    request.run_id,
                ),
            )

        if draft.identity_conflict:
            events.append(
                self._make_event(
                    EventType.IDENTITY_ANOMALY,
                    EntityKind.BOARD,
                    identity.board_key,
                    request,
                    identity,
                    UNKNOWN,
                    payload_hash,
                    baseline,
                    {"reason": draft.identity_conflict_reason},
                )
            )

        persisted: list[str] = []
        for event in events:
            persisted.append(self._persist_event(event, request.run_id))
        return 1, [key for key in persisted if key]

    def _resolve_identity(self, draft: ObservationDraft):
        spec = draft.spec
        spec.soc_key = draft.resolved_soc_key()
        spec.soc = draft.soc_marketing_name or spec.soc
        spec.cpu_arch = draft.architecture.value
        spec.cpu_config = draft.cpu_configuration or spec.cpu_config
        spec.gpu = draft.gpu or spec.gpu
        spec.npu = draft.npu or spec.npu
        spec.npu_tops = draft.npu_tops or spec.npu_tops
        spec.availability = draft.availability.value
        ports = spec.ports_signature()
        kind = draft.revision_kind
        token = draft.revision_token
        if kind is RevisionKind.UNKNOWN and token == UNKNOWN:
            existing = self.store.one(
                "SELECT revision_key, revision_kind, revision_token, soc_key, ports_signature FROM board_revisions WHERE board_key = ?",
                (f"{draft.vendor_key}:{draft.board_slug}",),
            )
            # Conservative split: identity-critical change under same name becomes a silent revision.
            board = f"{draft.vendor_key}:{draft.board_slug}"
            current_rows = self.store.all(
                "SELECT revision_key, soc_key, ports_signature FROM board_revisions WHERE board_key = ?",
                (board,),
            )
            matching = [
                row
                for row in current_rows
                if row["soc_key"] == spec.soc_key and row["ports_signature"] == ports
            ]
            if matching:
                # Reuse existing revision identity rather than inventing another UNKNOWN token.
                from board_clank.identity import BoardIdentity, variant_key as make_variant_key

                row = matching[0]
                kind_token = row["revision_key"].split(":")
                # revision_key = vendor:board:KIND:token
                kind = RevisionKind(kind_token[-2]) if len(kind_token) >= 2 else RevisionKind.UNKNOWN
                token = kind_token[-1]
                # The resolved identity owns the revision echo from here on;
                # a page that stopped naming the revision must not make the
                # stored revision payload look like it changed.
                draft.revision_kind = kind
                draft.revision_token = token
                draft.spec.pcb_revision = token
                identity = BoardIdentity(
                    vendor_key=draft.vendor_key,
                    family_key=f"{draft.vendor_key}:{draft.family_slug}",
                    board_key=board,
                    revision_key=row["revision_key"],
                    variant_key=make_variant_key(row["revision_key"], draft.variant),
                    revision_kind=kind,
                    revision_token=token,
                    variant_fingerprint=draft.variant.fingerprint(),
                )
                return identity
            if current_rows:
                kind = RevisionKind.SILENT
                token = silent_revision_token(ports, spec.soc_key, spec.dimensions)
        return build_identity(
            vendor=draft.vendor_key,
            family=draft.family_slug,
            board_slug=draft.board_slug,
            revision_kind=kind,
            revision_token=token,
            variant=draft.variant,
        )

    def _upsert_graph(self, draft: ObservationDraft, identity, request: CollectorRunRequest) -> None:
        now = draft.observed_at
        self.store.execute(
            "INSERT OR IGNORE INTO vendors(vendor_key, display_name, created_at) VALUES (?, ?, ?)",
            (identity.vendor_key, draft.vendor_name or identity.vendor_key, now),
        )
        self.store.execute(
            """
            INSERT OR IGNORE INTO board_families(family_key, vendor_key, family_slug, display_name, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (identity.family_key, identity.vendor_key, draft.family_slug, draft.family_name, now),
        )
        self.store.execute(
            """
            INSERT OR IGNORE INTO socs(
                soc_key, vendor, marketing_name, architecture, cpu_configuration,
                gpu, npu, npu_tops, process_node_if_known, source_provenance, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                draft.resolved_soc_key(),
                draft.soc_vendor,
                draft.soc_marketing_name,
                draft.architecture.value,
                draft.cpu_configuration,
                draft.gpu,
                draft.npu,
                draft.npu_tops,
                draft.process_node,
                request.source_key,
                now,
            ),
        )
        self.store.execute(
            """
            INSERT OR IGNORE INTO boards(
                board_key, vendor_key, family_key, board_slug, marketing_name, board_type,
                created_at, first_seen_at, first_seen_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                identity.board_key,
                identity.vendor_key,
                identity.family_key,
                draft.board_slug,
                draft.marketing_name,
                draft.board_type.value,
                now,
                now,
                request.source_key,
            ),
        )
        self.store.execute(
            """
            INSERT OR IGNORE INTO board_revisions(
                revision_key, board_key, revision_kind, revision_token, soc_key, ports_signature, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                identity.revision_key,
                identity.board_key,
                identity.revision_kind.value,
                identity.revision_token,
                draft.resolved_soc_key(),
                draft.spec.ports_signature(),
                now,
            ),
        )
        dims = draft.variant
        self.store.execute(
            """
            INSERT OR IGNORE INTO board_variants(
                variant_key, board_key, revision_key, variant_fingerprint,
                ram, storage, wireless, region, bundle, sku, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                identity.variant_key,
                identity.board_key,
                identity.revision_key,
                identity.variant_fingerprint,
                dims.ram,
                dims.storage,
                dims.wireless,
                dims.region,
                dims.bundle,
                dims.sku,
                now,
            ),
        )

    def _sync_entity(
        self,
        request: CollectorRunRequest,
        draft: ObservationDraft,
        entity_key: str,
        kind: EntityKind,
        payload: dict,
        payload_hash: str,
        identity,
        baseline: bool,
    ) -> list[EventRecord]:
        events: list[EventRecord] = []
        existing = self.store.one(
            """
            SELECT observation_id, content_hash FROM canonical_observations
            WHERE entity_kind = ? AND entity_key = ? AND content_hash = ?
            """,
            (kind.value, entity_key, payload_hash),
        )
        if existing is None:
            cur = self.store.execute(
                """
                INSERT INTO canonical_observations(
                    entity_kind, entity_key, board_key, revision_key, variant_key,
                    content_hash, payload_json, first_accepted_at, first_source_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kind.value,
                    entity_key,
                    identity.board_key,
                    identity.revision_key,
                    identity.variant_key,
                    payload_hash,
                    canonical_json(payload),
                    draft.observed_at,
                    request.source_key,
                ),
            )
            observation_id = cur.lastrowid
        else:
            observation_id = existing["observation_id"]

        self.store.execute(
            """
            INSERT INTO observation_occurrences(
                observation_id, run_id, source_key, plane, entity_kind, entity_key, observed_at, content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                observation_id,
                request.run_id,
                request.source_key,
                draft.plane.value,
                kind.value,
                entity_key,
                draft.observed_at,
                payload_hash,
            ),
        )

        current = self.store.one(
            "SELECT observation_id, content_hash FROM current_entity_observations WHERE entity_kind = ? AND entity_key = ?",
            (kind.value, entity_key),
        )
        if current is None:
            self.store.execute(
                """
                INSERT INTO current_entity_observations(
                    entity_kind, entity_key, observation_id, content_hash, updated_at, updated_run_id
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (kind.value, entity_key, observation_id, payload_hash, draft.observed_at, request.run_id),
            )
            events.extend(self._birth_events(kind, draft, identity, request, payload_hash, baseline))
        elif current["content_hash"] == payload_hash:
            # Sighting only. Current state already points at this payload.
            return events
        else:
            previous_hash = current["content_hash"]
            previous_payload = self._payload_for_hash(kind, entity_key, previous_hash)
            self.store.execute(
                """
                UPDATE current_entity_observations
                SET observation_id = ?, content_hash = ?, updated_at = ?, updated_run_id = ?
                WHERE entity_kind = ? AND entity_key = ?
                """,
                (observation_id, payload_hash, draft.observed_at, request.run_id, kind.value, entity_key),
            )
            events.extend(
                self._transition_events(
                    kind,
                    draft,
                    identity,
                    request,
                    previous_hash,
                    payload_hash,
                    previous_payload,
                    payload,
                    baseline,
                )
            )
        return events

    def _payload_for_hash(self, kind: EntityKind, entity_key: str, content_hash_value: str) -> dict:
        row = self.store.one(
            """
            SELECT payload_json FROM canonical_observations
            WHERE entity_kind = ? AND entity_key = ? AND content_hash = ?
            """,
            (kind.value, entity_key, content_hash_value),
        )
        if not row:
            return {}
        return json.loads(row["payload_json"])

    def _birth_events(
        self,
        kind: EntityKind,
        draft: ObservationDraft,
        identity,
        request: CollectorRunRequest,
        payload_hash: str,
        baseline: bool,
    ) -> list[EventRecord]:
        events: list[EventRecord] = []
        if kind is EntityKind.BOARD:
            events.append(
                self._make_event(
                    EventType.FIRST_SEEN_BY_CLANK,
                    kind,
                    identity.board_key,
                    request,
                    identity,
                    UNKNOWN,
                    payload_hash,
                    baseline,
                    {"plane": draft.plane.value, "page_url": draft.page_url},
                )
            )
            if baseline:
                events.append(
                    self._make_event(
                        EventType.BASELINE_ENTITY,
                        kind,
                        identity.board_key,
                        request,
                        identity,
                        UNKNOWN,
                        payload_hash,
                        True,
                        {"plane": draft.plane.value},
                    )
                )
            if draft.historical_known:
                events.append(
                    self._make_event(
                        EventType.HISTORICAL_DISCOVERY,
                        kind,
                        identity.board_key,
                        request,
                        identity,
                        UNKNOWN,
                        payload_hash,
                        baseline,
                        {"plane": draft.plane.value},
                    )
                )
                # First-seen now does not become NEW_BOARD when historical evidence exists.
                return events
            events.append(
                self._make_event(
                    EventType.NEW_BOARD,
                    kind,
                    identity.board_key,
                    request,
                    identity,
                    UNKNOWN,
                    payload_hash,
                    baseline,
                    {
                        "plane": draft.plane.value,
                        "audit": "baseline-inventory" if baseline else "live-admission",
                    },
                )
            )
        elif kind is EntityKind.REVISION and identity.revision_kind in {RevisionKind.MARKETING, RevisionKind.PCB, RevisionKind.SILENT}:
            if identity.revision_token != UNKNOWN:
                events.append(
                    self._make_event(
                        EventType.BOARD_REVISION,
                        kind,
                        identity.revision_key,
                        request,
                        identity,
                        UNKNOWN,
                        payload_hash,
                        baseline,
                        {"revision_kind": identity.revision_kind.value, "revision_token": identity.revision_token},
                    )
                )
        elif kind is EntityKind.VARIANT:
            events.append(
                self._make_event(
                    EventType.NEW_VARIANT,
                    kind,
                    identity.variant_key,
                    request,
                    identity,
                    UNKNOWN,
                    payload_hash,
                    baseline,
                    {**draft.variant.as_dict(), "audit": "baseline-inventory" if baseline else "live-admission"},
                )
            )
            if draft.variant.ram != UNKNOWN:
                events.append(
                    self._make_event(
                        EventType.RAM_VARIANT_ADDED,
                        kind,
                        identity.variant_key,
                        request,
                        identity,
                        UNKNOWN,
                        payload_hash,
                        baseline,
                        {"ram": draft.variant.ram},
                    )
                )
            if draft.variant.storage != UNKNOWN:
                events.append(
                    self._make_event(
                        EventType.STORAGE_VARIANT_ADDED,
                        kind,
                        identity.variant_key,
                        request,
                        identity,
                        UNKNOWN,
                        payload_hash,
                        baseline,
                        {"storage": draft.variant.storage},
                    )
                )
            if draft.variant.region != UNKNOWN:
                events.append(
                    self._make_event(
                        EventType.REGION_ADDED,
                        kind,
                        identity.variant_key,
                        request,
                        identity,
                        UNKNOWN,
                        payload_hash,
                        baseline,
                        {"region": draft.variant.region},
                    )
                )
        return events

    def _transition_events(
        self,
        kind: EntityKind,
        draft: ObservationDraft,
        identity,
        request: CollectorRunRequest,
        from_hash: str,
        to_hash: str,
        previous: dict,
        current: dict,
        baseline: bool,
    ) -> list[EventRecord]:
        events: list[EventRecord] = []
        if kind is EntityKind.BOARD:
            if previous.get("page_url") != current.get("page_url"):
                events.append(
                    self._make_event(
                        EventType.NEW_REFERENCE,
                        kind,
                        identity.board_key,
                        request,
                        identity,
                        from_hash,
                        to_hash,
                        baseline,
                        {"from": previous.get("page_url"), "to": current.get("page_url")},
                    )
                )
            prev_soc = (previous.get("soc_key") or UNKNOWN)
            cur_soc = (current.get("soc_key") or UNKNOWN)
            if prev_soc != cur_soc:
                events.append(
                    self._make_event(
                        EventType.SOC_CHANGED,
                        kind,
                        identity.board_key,
                        request,
                        identity,
                        from_hash,
                        to_hash,
                        baseline,
                        {"from": prev_soc, "to": cur_soc},
                    )
                )
            prev_ports = (previous.get("spec") or {}).get("ethernet", UNKNOWN)
            # Compare ports via signature fields
            if self._ports_changed(previous, current):
                events.append(
                    self._make_event(
                        EventType.PORTS_CHANGED,
                        kind,
                        identity.board_key,
                        request,
                        identity,
                        from_hash,
                        to_hash,
                        baseline,
                        {"field": "ports"},
                    )
                )
            prev_avail = previous.get("availability")
            cur_avail = current.get("availability")
            if prev_avail != cur_avail:
                event_type = EventType.EOL if cur_avail in {"EOL", "DISCONTINUED"} else EventType.AVAILABILITY_CHANGED
                events.append(
                    self._make_event(
                        event_type,
                        kind,
                        identity.board_key,
                        request,
                        identity,
                        from_hash,
                        to_hash,
                        baseline,
                        {"from": prev_avail, "to": cur_avail},
                    )
                )
            prev_os = set(previous.get("supported_os") or [])
            cur_os = set(current.get("supported_os") or [])
            if cur_os - prev_os:
                events.append(
                    self._make_event(
                        EventType.OS_SUPPORT_ADDED,
                        kind,
                        identity.board_key,
                        request,
                        identity,
                        from_hash,
                        to_hash,
                        baseline,
                        {"added": sorted(cur_os - prev_os)},
                    )
                )
            if prev_os - cur_os:
                events.append(
                    self._make_event(
                        EventType.OS_SUPPORT_REMOVED,
                        kind,
                        identity.board_key,
                        request,
                        identity,
                        from_hash,
                        to_hash,
                        baseline,
                        {"removed": sorted(prev_os - cur_os)},
                    )
                )
            prev_ctx = set(previous.get("editorial_context") or [])
            cur_ctx = set(current.get("editorial_context") or [])
            if prev_ctx != cur_ctx:
                events.append(
                    self._make_event(
                        EventType.CLASSIFICATION_CHANGED,
                        kind,
                        identity.board_key,
                        request,
                        identity,
                        from_hash,
                        to_hash,
                        baseline,
                        {"from": sorted(prev_ctx), "to": sorted(cur_ctx)},
                    )
                )
            if previous.get("price") != current.get("price"):
                events.append(
                    self._make_event(
                        EventType.PRICE_CHANGED,
                        kind,
                        identity.board_key,
                        request,
                        identity,
                        from_hash,
                        to_hash,
                        baseline,
                        {"from": previous.get("price"), "to": current.get("price")},
                    )
                )
            if not events:
                events.append(
                    self._make_event(
                        EventType.FIELD_CHANGED,
                        kind,
                        identity.board_key,
                        request,
                        identity,
                        from_hash,
                        to_hash,
                        baseline,
                        {"transition": f"{from_hash[:8]}->{to_hash[:8]}"},
                    )
                )
        return events

    def _ports_changed(self, previous: dict, current: dict) -> bool:
        from board_clank.taxonomy import PORT_FIELDS

        prev_spec = previous.get("spec") or {}
        cur_spec = current.get("spec") or {}
        return any(prev_spec.get(field) != cur_spec.get(field) for field in PORT_FIELDS)

    def _make_event(
        self,
        event_type: EventType,
        kind: EntityKind,
        entity_key: str,
        request: CollectorRunRequest,
        identity,
        from_hash: str,
        to_hash: str,
        baseline: bool,
        payload: dict,
    ) -> EventRecord:
        # Durable identity includes the run so A→B later A→B is a new event.
        event_key = content_hash(
            {
                "event_type": event_type.value,
                "entity_key": entity_key,
                "from_hash": from_hash,
                "to_hash": to_hash,
                "run_id": request.run_id,
            }
        )
        return EventRecord(
            event_key=event_key,
            event_type=event_type,
            entity_kind=kind,
            entity_key=entity_key,
            board_key=identity.board_key,
            revision_key=identity.revision_key,
            variant_key=identity.variant_key,
            source_key=request.source_key,
            from_hash=from_hash,
            to_hash=to_hash,
            baseline_silent=baseline,
            payload=payload,
        )

    def _persist_event(self, event: EventRecord, run_id: str) -> str:
        existing = self.store.one("SELECT event_key FROM events WHERE event_key = ?", (event.event_key,))
        if existing:
            return event.event_key
        self.store.execute(
            """
            INSERT INTO events(
                event_key, event_type, entity_kind, entity_key, board_key, revision_key, variant_key,
                source_key, run_id, from_hash, to_hash, baseline_silent, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_key,
                event.event_type.value,
                event.entity_kind.value,
                event.entity_key,
                event.board_key,
                event.revision_key,
                event.variant_key,
                event.source_key,
                run_id,
                event.from_hash,
                event.to_hash,
                1 if event.baseline_silent else 0,
                canonical_json(event.payload),
                _now(),
            ),
        )
        disposition = disposition_for(event.event_type, baseline_silent=event.baseline_silent)
        self.store.execute(
            """
            INSERT INTO notifications(event_key, disposition, channel, payload_json, created_at, delivered_at)
            VALUES (?, ?, ?, ?, ?, NULL)
            """,
            (
                event.event_key,
                disposition.value,
                "outbox",
                canonical_json({"event_type": event.event_type.value, "disposition": disposition.value}),
                _now(),
            ),
        )
        return event.event_key

    def _count_notifications(self, event_keys: list[str]) -> int:
        if not event_keys:
            return 0
        row = self.store.one(
            f"SELECT COUNT(*) AS n FROM notifications WHERE event_key IN ({','.join('?' * len(event_keys))})",
            tuple(event_keys),
        )
        return int(row["n"]) if row else 0

    def _record_novelty(self, draft: ObservationDraft, identity) -> None:
        novelty = draft.novelty
        status = novelty.novelty_status
        if status is NoveltyStatus.UNKNOWN and draft.historical_known:
            status = NoveltyStatus.HISTORICAL
        self.store.execute(
            """
            INSERT OR IGNORE INTO novelty_evidence(
                entity_kind, entity_key, first_seen_at, first_seen_source,
                official_announcement_at, official_sale_at, official_shipping_at,
                docs_date, store_date, novelty_status, novelty_basis, novelty_confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                EntityKind.BOARD.value,
                identity.board_key,
                novelty.first_seen_at if novelty.first_seen_at != UNKNOWN else draft.observed_at,
                novelty.first_seen_source if novelty.first_seen_source != UNKNOWN else draft.source_key,
                novelty.official_announcement_at,
                novelty.official_sale_at,
                novelty.official_shipping_at,
                novelty.docs_date,
                novelty.store_date,
                status.value,
                novelty.novelty_basis,
                novelty.novelty_confidence,
            ),
        )

    def _record_classifications(self, draft: ObservationDraft, identity) -> None:
        for context in draft.editorial_context:
            self.store.execute(
                """
                INSERT OR IGNORE INTO board_classifications(board_key, context, source_key, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (identity.board_key, context, draft.source_key, draft.observed_at),
            )

    # ------------------------------------------------------ diagnostic conditions

    def _diagnostic_condition_key(
        self,
        request: CollectorRunRequest,
        draft: ObservationDraft,
        identity: _UnresolvedIdentity,
        diagnostic_type: EventType,
    ) -> str:
        """Durable identity of a diagnostic condition: semantic facts only.

        Source, plane, candidate entity and diagnostic class. Never run id,
        timestamps, raw bytes, or session noise; reason and evidence hashes
        are state, not identity, so their changes are transitions.
        """
        return content_hash(
            {
                "source_key": request.source_key,
                "plane": draft.plane.value,
                "entity_key": identity.board_key,
                "diagnostic_type": diagnostic_type.value,
            }
        )

    def _diagnostic_state(
        self,
        draft: ObservationDraft,
        identity: _UnresolvedIdentity,
        diagnostic_type: EventType,
        reason: str,
    ) -> tuple[str, dict]:
        """Semantic state of a condition: reason, candidates, names, reference.

        Raw HTML excerpts and other volatile transport artifacts are excluded
        on purpose: a raw-only change with identical semantic content must not
        look like a state transition.
        """
        state = {
            "entity_key": identity.board_key,
            "diagnostic_type": diagnostic_type.value,
            "reason": reason,
            "soc_candidates": sorted(
                str(item) for item in (draft.raw_fields.get("soc_candidates") or [])
            ),
            "marketing_name": draft.marketing_name,
            "page_url": draft.page_url,
        }
        return content_hash(state), state

    def _upsert_condition_row(
        self,
        *,
        condition_key: str,
        source_key: str,
        plane: str,
        diagnostic_type: str,
        entity_key: str,
        reason: str,
        state_hash: str,
        payload_json: str,
        observed_at: str,
        run_id: str,
    ) -> dict:
        row = self.store.one(
            "SELECT status, state_hash, resolved_at FROM diagnostic_conditions WHERE condition_key = ?",
            (condition_key,),
        )
        if row is None:
            self.store.execute(
                """
                INSERT INTO diagnostic_conditions(
                    condition_key, source_key, plane, diagnostic_type, entity_key, reason,
                    state_hash, payload_json, status, first_observed_at, first_run_id,
                    last_observed_at, last_run_id, open_occurrences, total_occurrences,
                    transition_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, ?, 1, 1, 0)
                """,
                (condition_key, source_key, plane, diagnostic_type, entity_key, reason,
                 state_hash, payload_json, observed_at, run_id, observed_at, run_id),
            )
            return {"transition": "opened", "state_hash": state_hash, "from_state_hash": UNKNOWN, "resolved_at": None}
        from_state_hash = row["state_hash"]
        bump = ", transition_count = transition_count + 1" if from_state_hash != state_hash or row["status"] == "RESOLVED" else ""
        if row["status"] == "RESOLVED":
            transition = "reappeared"
            self.store.execute(
                f"""
                UPDATE diagnostic_conditions
                SET status = 'OPEN', reason = ?, state_hash = ?, payload_json = ?,
                    last_observed_at = ?, last_run_id = ?, resolved_at = NULL, resolved_run_id = NULL,
                    open_occurrences = open_occurrences + 1, total_occurrences = total_occurrences + 1{bump}
                WHERE condition_key = ?
                """,
                (reason, state_hash, payload_json, observed_at, run_id, condition_key),
            )
            return {"transition": transition, "state_hash": state_hash, "from_state_hash": from_state_hash, "resolved_at": row["resolved_at"]}
        if from_state_hash != state_hash:
            self.store.execute(
                f"""
                UPDATE diagnostic_conditions
                SET reason = ?, state_hash = ?, payload_json = ?, last_observed_at = ?, last_run_id = ?,
                    open_occurrences = open_occurrences + 1, total_occurrences = total_occurrences + 1{bump}
                WHERE condition_key = ?
                """,
                (reason, state_hash, payload_json, observed_at, run_id, condition_key),
            )
            return {"transition": "evidence-changed", "state_hash": state_hash, "from_state_hash": from_state_hash, "resolved_at": None}
        self.store.execute(
            """
            UPDATE diagnostic_conditions
            SET last_observed_at = ?, last_run_id = ?,
                open_occurrences = open_occurrences + 1, total_occurrences = total_occurrences + 1
            WHERE condition_key = ?
            """,
            (observed_at, run_id, condition_key),
        )
        return {"transition": None, "state_hash": state_hash, "from_state_hash": from_state_hash, "resolved_at": None}

    def _admit_diagnostic_batch(
        self,
        request: CollectorRunRequest,
        unresolved: list[tuple[ObservationDraft, "_UnresolvedIdentity"]],
        *,
        baseline: bool,
    ) -> list[str]:
        """Admit one run's unresolved/anomalous observations as durable state.

        Foundation 2B law: persistent uncertainty is state, not perpetual
        novelty. A condition's durable identity is (source, plane, candidate
        entity, diagnostic class); its state is the aggregate of every page
        that evidenced it in this run. Unchanged aggregate state means an
        existing condition: sightings are recorded, nothing is emitted.
        Transitions — opened, evidence-changed, reappeared — are the only
        intelligence events.
        """
        groups: dict[tuple[str, str], list[tuple[ObservationDraft, "_UnresolvedIdentity", str]]] = {}
        for draft, identity in unresolved:
            reason = draft.identity_conflict_reason if draft.identity_conflict else "insufficient-evidence"
            types = [EventType.NOVELTY_UNRESOLVED]
            if draft.identity_conflict:
                types.append(EventType.IDENTITY_ANOMALY)
            for diagnostic_type in types:
                key = self._diagnostic_condition_key(request, draft, identity, diagnostic_type)
                groups.setdefault((diagnostic_type.value, key), []).append((draft, identity, reason))

        persisted: list[str] = []
        observed_at = unresolved[0][0].observed_at if unresolved else _now()
        for (type_value, condition_key), members in sorted(groups.items()):
            diagnostic_type = EventType(type_value)
            identity = members[0][1]
            page_states = [
                self._diagnostic_state(draft, ident, diagnostic_type, reason)
                for draft, ident, reason in members
            ]
            aggregate = {
                "entity_key": identity.board_key,
                "diagnostic_type": type_value,
                "pages": sorted((state for _h, state in page_states), key=canonical_json),
            }
            aggregate_hash = content_hash(aggregate)
            reasons = sorted({reason for _d, _i, reason in members})
            reason_label = "; ".join(reasons)
            outcome = self._upsert_condition_row(
                condition_key=condition_key,
                source_key=request.source_key,
                plane=members[0][0].plane.value,
                diagnostic_type=type_value,
                entity_key=identity.board_key,
                reason=reason_label,
                state_hash=aggregate_hash,
                payload_json=canonical_json(aggregate),
                observed_at=observed_at,
                run_id=request.run_id,
            )
            event_key = None
            if outcome["transition"] is not None:
                payload = {
                    "reason": reason_label,
                    "condition_key": condition_key,
                    "transition": outcome["transition"],
                    "pages": len(page_states),
                    "page_urls": sorted({draft.page_url for draft, _i, _r in members}),
                }
                if outcome["transition"] == "evidence-changed":
                    payload["from_state_hash"] = outcome["from_state_hash"]
                    payload["to_state_hash"] = outcome["state_hash"]
                elif outcome["transition"] == "reappeared":
                    payload["previously_resolved_at"] = outcome["resolved_at"]
                    if outcome["from_state_hash"] != outcome["state_hash"]:
                        payload["from_state_hash"] = outcome["from_state_hash"]
                event = self._make_event(
                    diagnostic_type,
                    EntityKind.BOARD,
                    identity.board_key,
                    request,
                    identity,
                    outcome["from_state_hash"],
                    outcome["state_hash"],
                    baseline,
                    payload,
                )
                event_key = self._persist_event(event, request.run_id)
                if event_key:
                    persisted.append(event_key)
            for (draft, _ident, _reason), (_page_hash, _page_state) in zip(members, page_states):
                self._record_diagnostic_sighting(request, draft, condition_key, outcome["state_hash"], event_key)
        return [key for key in persisted if key]

    def _record_diagnostic_sighting(
        self,
        request: CollectorRunRequest,
        draft: ObservationDraft,
        condition_key: str,
        state_hash: str,
        event_key: str | None,
    ) -> None:
        """Operational, per-run record that this run encountered the condition.

        The health/diagnostics plane: present for every run and every
        evidencing page, whether or not the intelligence plane emitted an
        event for the condition.
        """
        self.store.execute(
            """
            INSERT INTO diagnostic_sightings(condition_key, run_id, source_key, observed_at, state_hash, emitted_event_key)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (condition_key, request.run_id, request.source_key, draft.observed_at, state_hash, event_key),
        )

    def _reconcile_diagnostic_conditions(self, request: CollectorRunRequest, *, baseline: bool) -> list[str]:
        """Close still-open conditions of this source that the run did not see.

        A condition the source no longer reports is resolved: closure is
        observable once (DIAGNOSTIC_RESOLVED) instead of the condition
        lingering or re-opening as fresh intelligence later. A later
        material reappearance is a new occurrence and re-opens it.
        """
        rows = self.store.all(
            """
            SELECT condition_key, entity_key, diagnostic_type, state_hash, last_observed_at
            FROM diagnostic_conditions
            WHERE source_key = ? AND status = 'OPEN' AND COALESCE(last_run_id, '') != ?
            """,
            (request.source_key, request.run_id),
        )
        persisted: list[str] = []
        for row in rows:
            self.store.execute(
                """
                UPDATE diagnostic_conditions
                SET status = 'RESOLVED', resolved_at = ?, resolved_run_id = ?
                WHERE condition_key = ?
                """,
                (_now(), request.run_id, row["condition_key"]),
            )
            closed = SimpleNamespace(
                board_key=row["entity_key"], revision_key=UNKNOWN, variant_key=UNKNOWN
            )
            event = self._make_event(
                EventType.DIAGNOSTIC_RESOLVED,
                EntityKind.BOARD,
                row["entity_key"],
                request,
                closed,
                row["state_hash"],
                UNKNOWN,
                baseline,
                {
                    "condition_key": row["condition_key"],
                    "diagnostic_type": row["diagnostic_type"],
                    "entity_key": row["entity_key"],
                    "last_observed_at": row["last_observed_at"],
                    "transition": "resolved",
                },
            )
            key = self._persist_event(event, request.run_id)
            if key:
                persisted.append(key)
        return persisted

    def _record_software(self, draft: ObservationDraft, identity, request: CollectorRunRequest) -> None:
        for os_name in draft.supported_os:
            self.store.execute(
                """
                INSERT OR IGNORE INTO software_support(board_key, os_name, source_key, observed_at)
                VALUES (?, ?, ?, ?)
                """,
                (identity.board_key, os_name, request.source_key, draft.observed_at),
            )


def source_authority_may_override_identity(authority: SourceAuthority) -> bool:
    return authority not in WEAK_OVERRIDE_AUTHORITY


class _UnresolvedIdentity:
    board_key = UNKNOWN
    revision_key = UNKNOWN
    variant_key = UNKNOWN


    def __init__(self, draft: ObservationDraft) -> None:
        slug = draft.board_slug if draft.board_slug and draft.board_slug != UNKNOWN else UNKNOWN
        vendor = draft.vendor_key or UNKNOWN
        self.board_key = f"{vendor}:{slug}" if slug != UNKNOWN else UNKNOWN
        self.revision_key = UNKNOWN
        self.variant_key = UNKNOWN


# Bound as a method via assignment below to keep Pipeline methods together.
def _admit_unresolved(self, request: CollectorRunRequest, draft: ObservationDraft, *, baseline: bool) -> tuple[int, list[str]]:
    """Single-draft fallback; the run-level batch path is the normal route."""
    keys = self._admit_diagnostic_batch(
        request, [(draft, _UnresolvedIdentity(draft))], baseline=baseline
    )
    return 0, keys


Pipeline._admit_unresolved = _admit_unresolved
