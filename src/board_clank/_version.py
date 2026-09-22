"""Release and schema identity. Git revision is injected at image build time."""

from __future__ import annotations

import os

CLANK_ID = "board-clank"
PACKAGE_VERSION = "0.1.0"
EXPECTED_SCHEMA_VERSION = 2
RELEASE_CHANNEL = os.environ.get("BOARD_CLANK_RELEASE_CHANNEL", "foundation-0")
SOURCE_REVISION = os.environ.get("BOARD_CLANK_SOURCE_REVISION", "unknown")
IDENTITY_LAW = (
    "A NEW SKU IS NOT NECESSARILY A NEW BOARD. "
    "A NEW BOARD REVISION IS NOT NECESSARILY A NEW PRODUCT NAME."
)
FIRST_SEEN_LAW = "FIRST_SEEN != MARKET_NOVELTY."
