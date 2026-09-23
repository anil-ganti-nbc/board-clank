"""Inert Phase-1 adapters and a fixture collector. No live network."""

from __future__ import annotations

from board_clank.fixtures import load_scenario, scenario_to_request
from board_clank.models import CollectorRunRequest
from board_clank.taxonomy import PHASE1_VENDORS


class InertVendorAdapter:
    live_network = False

    def __init__(self, vendor: str, source_key: str) -> None:
        self.vendor = vendor
        self.source_key = source_key
        self.collector_key = f"{vendor}-inert"

    def collect(self, run_id: str, started_at: str) -> CollectorRunRequest:
        return CollectorRunRequest(
            run_id=run_id,
            source_key=self.source_key,
            collector_key=self.collector_key,
            started_at=started_at,
            observations=[],
            ok=True,
        )


class FixtureCollector:
    live_network = False
    collector_key = "fixture"

    def __init__(self, scenario: str) -> None:
        self.scenario = scenario
        self.source_key = "fixture"

    def collect_runs(self) -> list[CollectorRunRequest]:
        payload = load_scenario(self.scenario)
        return scenario_to_request(payload)


ADAPTERS = {
    vendor: InertVendorAdapter(vendor, f"{vendor}-product")
    for vendor in PHASE1_VENDORS
    if vendor not in PHASE1_VENDORS
}


def get_adapter(source_key: str, **kwargs):
    if source_key in {"raspberry-pi-product", "raspberry-pi"}:
        from board_clank.collectors.raspberry_pi import RaspberryPiProductAdapter

        return RaspberryPiProductAdapter(
            experimental_live=bool(kwargs.get("experimental_live")),
            corpus=str(kwargs.get("corpus") or "baseline"),
        )
    if source_key in {"orange-pi-product", "orange-pi"}:
        from board_clank.collectors.orange_pi import OrangePiProductAdapter

        return OrangePiProductAdapter(
            experimental_live=bool(kwargs.get("experimental_live")),
            corpus=str(kwargs.get("corpus") or "baseline"),
        )
    if source_key in {"radxa-product", "radxa"}:
        from board_clank.collectors.radxa import RadxaProductAdapter

        return RadxaProductAdapter(
            experimental_live=bool(kwargs.get("experimental_live")),
            corpus=str(kwargs.get("corpus") or "baseline"),
        )
    if source_key in {"banana-pi-product", "banana-pi"}:
        from board_clank.collectors.banana_pi import BananaPiProductAdapter

        return BananaPiProductAdapter(
            experimental_live=bool(kwargs.get("experimental_live")),
            corpus=str(kwargs.get("corpus") or "baseline"),
        )
    if source_key in {"hardkernel-odroid-product", "hardkernel-odroid", "odroid-product"}:
        from board_clank.collectors.odroid import OdroidProductAdapter

        return OdroidProductAdapter(
            experimental_live=bool(kwargs.get("experimental_live")),
            corpus=str(kwargs.get("corpus") or "baseline"),
        )
    if source_key in {"pine64-product", "pine64"}:
        from board_clank.collectors.pine64 import Pine64ProductAdapter

        return Pine64ProductAdapter(
            experimental_live=bool(kwargs.get("experimental_live")),
            corpus=str(kwargs.get("corpus") or "baseline"),
        )
    vendor = source_key.replace("-product", "")
    if vendor not in ADAPTERS:
        raise KeyError(f"no foundation-0 adapter for {source_key}")
    return ADAPTERS[vendor]
