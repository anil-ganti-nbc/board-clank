from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"


def test_no_discord_webhook_surface() -> None:
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "discord.com" not in text
        assert "webhook" not in text.lower()


def test_collectors_are_inert() -> None:
    from board_clank.collectors import InertVendorAdapter, RaspberryPiProductAdapter, get_adapter
    from board_clank.taxonomy import PHASE1_VENDORS

    for vendor in PHASE1_VENDORS:
        adapter = get_adapter(f"{vendor}-product")
        assert adapter.live_network is False
        if vendor == "raspberry-pi":
            assert isinstance(adapter, RaspberryPiProductAdapter)
            assert adapter.experimental_live is False
        else:
            assert isinstance(adapter, InertVendorAdapter)
