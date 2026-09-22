"""Offline fixture loader. No network."""

from __future__ import annotations

import json
from pathlib import Path

from board_clank.identity import UNKNOWN, VariantDimensions
from board_clank.models import (
    CollectorRunRequest,
    NormalizedSpec,
    NoveltyEvidence,
    ObservationDraft,
    PriceObservation,
)
from board_clank.taxonomy import (
    Architecture,
    Availability,
    BoardType,
    NoveltyStatus,
    RevisionKind,
    SourcePlane,
)

_REPO_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "scenarios"
_PACKAGED_FIXTURES = Path(__file__).resolve().parent / "fixture_data"
FIXTURE_DIR = _REPO_FIXTURES if _REPO_FIXTURES.exists() else _PACKAGED_FIXTURES


def load_scenario(letter: str) -> dict:
    path = FIXTURE_DIR / f"{letter.upper()}.json"
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _draft(raw: dict) -> ObservationDraft:
    variant_raw = raw.get("variant") or {}
    spec_raw = raw.get("spec") or {}
    price_raw = raw.get("price")
    novelty_raw = raw.get("novelty") or {}
    return ObservationDraft(
        source_key=raw["source_key"],
        plane=SourcePlane(raw.get("plane", "PRODUCT")),
        observed_at=raw["observed_at"],
        vendor_key=raw["vendor_key"],
        vendor_name=raw.get("vendor_name", raw["vendor_key"]),
        family_slug=raw["family_slug"],
        family_name=raw.get("family_name", raw["family_slug"]),
        board_slug=raw["board_slug"],
        marketing_name=raw.get("marketing_name", raw["board_slug"]),
        board_type=BoardType(raw.get("board_type", "SBC")),
        revision_kind=RevisionKind(raw.get("revision_kind", "UNKNOWN")),
        revision_token=raw.get("revision_token", UNKNOWN),
        variant=VariantDimensions(
            ram=variant_raw.get("ram", UNKNOWN),
            storage=variant_raw.get("storage", UNKNOWN),
            wireless=variant_raw.get("wireless", UNKNOWN),
            region=variant_raw.get("region", UNKNOWN),
            bundle=variant_raw.get("bundle", UNKNOWN),
            sku=variant_raw.get("sku", UNKNOWN),
        ),
        soc_vendor=raw.get("soc_vendor", UNKNOWN),
        soc_marketing_name=raw.get("soc_marketing_name", UNKNOWN),
        architecture=Architecture(raw.get("architecture", "UNKNOWN")),
        cpu_configuration=raw.get("cpu_configuration", UNKNOWN),
        gpu=raw.get("gpu", UNKNOWN),
        npu=raw.get("npu", UNKNOWN),
        npu_tops=raw.get("npu_tops", UNKNOWN),
        process_node=raw.get("process_node", UNKNOWN),
        spec=NormalizedSpec(**spec_raw),
        raw_fields=raw.get("raw_fields") or {},
        native_fields=raw.get("native_fields") or {},
        price=PriceObservation(**price_raw) if price_raw else None,
        availability=Availability(raw.get("availability", "UNKNOWN")),
        novelty=NoveltyEvidence(
            first_seen_at=novelty_raw.get("first_seen_at", UNKNOWN),
            first_seen_source=novelty_raw.get("first_seen_source", UNKNOWN),
            official_announcement_at=novelty_raw.get("official_announcement_at", UNKNOWN),
            official_sale_at=novelty_raw.get("official_sale_at", UNKNOWN),
            official_shipping_at=novelty_raw.get("official_shipping_at", UNKNOWN),
            docs_date=novelty_raw.get("docs_date", UNKNOWN),
            store_date=novelty_raw.get("store_date", UNKNOWN),
            novelty_status=NoveltyStatus(novelty_raw.get("novelty_status", "UNKNOWN")),
            novelty_basis=novelty_raw.get("novelty_basis", UNKNOWN),
            novelty_confidence=novelty_raw.get("novelty_confidence", UNKNOWN),
        ),
        editorial_context=list(raw.get("editorial_context") or []),
        supported_os=list(raw.get("supported_os") or []),
        page_url=raw.get("page_url", UNKNOWN),
        historical_known=bool(raw.get("historical_known", False)),
        identity_conflict=bool(raw.get("identity_conflict", False)),
        identity_conflict_reason=raw.get("identity_conflict_reason", UNKNOWN),
        evidence_insufficient=bool(raw.get("evidence_insufficient", False)),
    )


def scenario_to_request(payload: dict) -> list[CollectorRunRequest]:
    runs = []
    for item in payload["runs"]:
        runs.append(
            CollectorRunRequest(
                run_id=item["run_id"],
                source_key=item.get("source_key", payload.get("source_key", "fixture")),
                collector_key=item.get("collector_key", "fixture"),
                started_at=item["started_at"],
                observations=[_draft(obs) for obs in item.get("observations", [])],
                ok=item.get("ok", True),
                error=item.get("error"),
                fixture_scenario=payload.get("scenario"),
            )
        )
    return runs
