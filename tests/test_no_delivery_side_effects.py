from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"


def test_default_manifest_has_no_delivery_authority() -> None:
    # Explicit opt-in delivery now exists. Foundation/default invocations still
    # grant no notification authority; behavioral opt-in tests cover the sender.
    from board_clank.manifest import build_manifest
    assert build_manifest()['notification_authority'] == 'NONE'


def test_collectors_are_inert() -> None:
    from board_clank.collectors import (
        BananaPiProductAdapter,
        InertVendorAdapter,
        OdroidProductAdapter,
        OrangePiProductAdapter,
        Pine64ProductAdapter,
        RadxaProductAdapter,
        RaspberryPiProductAdapter,
        get_adapter,
    )
    from board_clank.taxonomy import PHASE1_VENDORS

    for vendor in PHASE1_VENDORS:
        adapter = get_adapter(f"{vendor}-product")
        assert adapter.live_network is False
        if vendor == "raspberry-pi":
            assert isinstance(adapter, RaspberryPiProductAdapter)
            assert adapter.experimental_live is False
        elif vendor == "orange-pi":
            assert isinstance(adapter, OrangePiProductAdapter)
            assert adapter.experimental_live is False
        elif vendor == "radxa":
            assert isinstance(adapter, RadxaProductAdapter)
            assert adapter.experimental_live is False
        elif vendor == "banana-pi":
            assert isinstance(adapter, BananaPiProductAdapter)
            assert adapter.experimental_live is False
        elif vendor == "hardkernel-odroid":
            assert isinstance(adapter, OdroidProductAdapter)
            assert adapter.experimental_live is False
        elif vendor == "pine64":
            assert isinstance(adapter, Pine64ProductAdapter)
            assert adapter.experimental_live is False
        else:
            raise AssertionError(f"unexpected Phase-1 vendor {vendor} resolved to inert")
