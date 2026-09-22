"""Domain contracts. Raw/native fields are preserved beside normalized fields."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from board_clank.identity import UNKNOWN, VariantDimensions, soc_key
from board_clank.taxonomy import (
    PORT_FIELDS,
    Architecture,
    Availability,
    BoardType,
    EntityKind,
    EventType,
    NoveltyStatus,
    RevisionKind,
    SourceAuthority,
    SourcePlane,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


class NormalizedSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    soc: str = UNKNOWN
    soc_key: str = UNKNOWN
    cpu_arch: str = Architecture.UNKNOWN.value
    cpu_cores: str = UNKNOWN
    cpu_config: str = UNKNOWN
    gpu: str = UNKNOWN
    npu: str = UNKNOWN
    npu_tops: str = UNKNOWN
    ram_type: str = UNKNOWN
    ram_options: str = UNKNOWN
    onboard_emmc: str = UNKNOWN
    emmc_options: str = UNKNOWN
    microsd: str = UNKNOWN
    m2_m_key: str = UNKNOWN
    m2_e_key: str = UNKNOWN
    pcie_lanes: str = UNKNOWN
    sata: str = UNKNOWN
    ethernet: str = UNKNOWN
    wifi: str = UNKNOWN
    bluetooth: str = UNKNOWN
    hdmi_out: str = UNKNOWN
    hdmi_in: str = UNKNOWN
    displayport: str = UNKNOWN
    mipi_csi: str = UNKNOWN
    mipi_dsi: str = UNKNOWN
    usb: str = UNKNOWN
    gpio_header: str = UNKNOWN
    power_input: str = UNKNOWN
    dimensions: str = UNKNOWN
    supported_os: str = UNKNOWN
    price: str = UNKNOWN
    currency: str = UNKNOWN
    availability: str = Availability.UNKNOWN.value
    pcb_revision: str = UNKNOWN
    marketing_revision: str = UNKNOWN

    def ports_signature(self) -> str:
        ports = {field: getattr(self, field) for field in PORT_FIELDS}
        return content_hash(ports)[:20]


class PriceObservation(BaseModel):
    amount: str = UNKNOWN
    currency: str = UNKNOWN
    region: str = UNKNOWN
    variant_key: str = UNKNOWN
    source_key: str = UNKNOWN
    observed_at: str = UNKNOWN


class NoveltyEvidence(BaseModel):
    first_seen_at: str = UNKNOWN
    first_seen_source: str = UNKNOWN
    official_announcement_at: str = UNKNOWN
    official_sale_at: str = UNKNOWN
    official_shipping_at: str = UNKNOWN
    docs_date: str = UNKNOWN
    store_date: str = UNKNOWN
    novelty_status: NoveltyStatus = NoveltyStatus.UNKNOWN
    novelty_basis: str = UNKNOWN
    novelty_confidence: str = UNKNOWN


class ObservationDraft(BaseModel):
    """Collector-facing observation. Adapters must not invent identity."""

    source_key: str
    plane: SourcePlane
    observed_at: str
    vendor_key: str
    vendor_name: str
    family_slug: str
    family_name: str
    board_slug: str
    marketing_name: str
    board_type: BoardType = BoardType.UNKNOWN
    revision_kind: RevisionKind = RevisionKind.UNKNOWN
    revision_token: str = UNKNOWN
    variant: VariantDimensions = Field(default_factory=VariantDimensions)
    soc_vendor: str = UNKNOWN
    soc_marketing_name: str = UNKNOWN
    architecture: Architecture = Architecture.UNKNOWN
    cpu_configuration: str = UNKNOWN
    gpu: str = UNKNOWN
    npu: str = UNKNOWN
    npu_tops: str = UNKNOWN
    process_node: str = UNKNOWN
    spec: NormalizedSpec = Field(default_factory=NormalizedSpec)
    raw_fields: dict[str, Any] = Field(default_factory=dict)
    native_fields: dict[str, Any] = Field(default_factory=dict)
    price: PriceObservation | None = None
    availability: Availability = Availability.UNKNOWN
    novelty: NoveltyEvidence = Field(default_factory=NoveltyEvidence)
    editorial_context: list[str] = Field(default_factory=list)
    supported_os: list[str] = Field(default_factory=list)
    page_url: str = UNKNOWN
    historical_known: bool = False
    identity_conflict: bool = False
    identity_conflict_reason: str = UNKNOWN
    evidence_insufficient: bool = False

    def resolved_soc_key(self) -> str:
        if self.spec.soc_key and self.spec.soc_key != UNKNOWN:
            return self.spec.soc_key
        return soc_key(self.soc_vendor, self.soc_marketing_name)

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "vendor_key": self.vendor_key,
            "family_slug": self.family_slug,
            "board_slug": self.board_slug,
            "marketing_name": self.marketing_name,
            "board_type": str(self.board_type),
            "revision_kind": str(self.revision_kind),
            "revision_token": self.revision_token,
            "variant": self.variant.as_dict(),
            "soc_key": self.resolved_soc_key(),
            "soc_vendor": self.soc_vendor,
            "soc_marketing_name": self.soc_marketing_name,
            "architecture": str(self.architecture),
            "spec": self.spec.model_dump(),
            "availability": str(self.availability),
            "price": self.price.model_dump() if self.price else None,
            "supported_os": sorted(self.supported_os),
            "editorial_context": sorted(self.editorial_context),
            "native_fields": self.native_fields,
            "page_url": self.page_url,
        }

    def payload_hash(self) -> str:
        return content_hash(self.canonical_payload())


class CollectorRunRequest(BaseModel):
    run_id: str
    source_key: str
    collector_key: str
    started_at: str
    observations: list[ObservationDraft] = Field(default_factory=list)
    ok: bool = True
    error: str | None = None
    fixture_scenario: str | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class EventRecord(BaseModel):
    event_key: str
    event_type: EventType
    entity_kind: EntityKind
    entity_key: str
    board_key: str
    revision_key: str
    variant_key: str
    source_key: str
    from_hash: str
    to_hash: str
    baseline_silent: bool
    payload: dict[str, Any] = Field(default_factory=dict)


class NotificationRecord(BaseModel):
    event_key: str
    disposition: str
    channel: str = "outbox"
    payload: dict[str, Any] = Field(default_factory=dict)


class SourceRecord(BaseModel):
    source_key: str
    vendor: str
    plane: SourcePlane
    authority: SourceAuthority
    base_urls: list[str] = Field(default_factory=list)
    enabled: bool = False
    promotion_state: str = "EXPERIMENTAL"
    registered_state: str = "REGISTERED"
    notes: str = ""
    expected_identity_surface: str = UNKNOWN
    expected_variant_surface: str = UNKNOWN
    placeholder: bool = False
    out_of_scope: bool = False
