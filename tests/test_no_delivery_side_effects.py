from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"


def test_no_discord_webhook_surface() -> None:
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "discord.com" not in text
        assert "webhook" not in text.lower()


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
