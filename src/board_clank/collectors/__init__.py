"""Collector adapters. Foundation 1 adds an experimental Raspberry Pi PRODUCT adapter.
Foundation 2A adds the Orange Pi PRODUCT adapter; Foundation 3A adds Radxa."""

from board_clank.collectors.base import CollectorAdapter, CollectorError
from board_clank.collectors.mock import FixtureCollector, InertVendorAdapter, get_adapter
from board_clank.collectors.orange_pi import OrangePiProductAdapter
from board_clank.collectors.radxa import RadxaProductAdapter
from board_clank.collectors.raspberry_pi import RaspberryPiProductAdapter

__all__ = [
    "CollectorAdapter",
    "CollectorError",
    "FixtureCollector",
    "InertVendorAdapter",
    "OrangePiProductAdapter",
    "RadxaProductAdapter",
    "RaspberryPiProductAdapter",
    "get_adapter",
]
