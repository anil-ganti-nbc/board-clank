"""Collector adapters. Foundation 0 ships inert/mock adapters only."""

from board_clank.collectors.base import CollectorAdapter, CollectorError
from board_clank.collectors.mock import FixtureCollector, InertVendorAdapter, get_adapter

__all__ = [
    "CollectorAdapter",
    "CollectorError",
    "FixtureCollector",
    "InertVendorAdapter",
    "get_adapter",
]
