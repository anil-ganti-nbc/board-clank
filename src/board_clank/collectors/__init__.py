"""Collector adapters. Foundation 1 adds an experimental Raspberry Pi PRODUCT adapter.
Foundation 2A adds Orange Pi, Foundation 3A adds Radxa, Foundation 4A adds Banana Pi,
Foundation 5A adds Hardkernel ODROID, Foundation 6A adds Pine64."""

from board_clank.collectors.banana_pi import BananaPiProductAdapter
from board_clank.collectors.base import CollectorAdapter, CollectorError
from board_clank.collectors.mock import FixtureCollector, InertVendorAdapter, get_adapter
from board_clank.collectors.odroid import OdroidProductAdapter
from board_clank.collectors.orange_pi import OrangePiProductAdapter
from board_clank.collectors.radxa import RadxaProductAdapter
from board_clank.collectors.pine64 import Pine64ProductAdapter
from board_clank.collectors.raspberry_pi import RaspberryPiProductAdapter

__all__ = [
    "BananaPiProductAdapter",
    "CollectorAdapter",
    "CollectorError",
    "FixtureCollector",
    "InertVendorAdapter",
    "OdroidProductAdapter",
    "OrangePiProductAdapter",
    "RadxaProductAdapter",
    "Pine64ProductAdapter",
    "RaspberryPiProductAdapter",
    "get_adapter",
]
