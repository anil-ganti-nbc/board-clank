"""Collector adapters. Foundation 1 adds an experimental Raspberry Pi PRODUCT adapter."""

from board_clank.collectors.base import CollectorAdapter, CollectorError
from board_clank.collectors.mock import FixtureCollector, InertVendorAdapter, get_adapter
from board_clank.collectors.raspberry_pi import RaspberryPiProductAdapter

__all__ = [
    "CollectorAdapter",
    "CollectorError",
    "FixtureCollector",
    "InertVendorAdapter",
    "RaspberryPiProductAdapter",
    "get_adapter",
]
