"""Release and schema identity. Git revision is injected at image build time."""

from __future__ import annotations

import os

CLANK_ID = "board-clank"
PACKAGE_VERSION = "0.1.0"
EXPECTED_SCHEMA_VERSION = 3
RELEASE_CHANNEL = os.environ.get("BOARD_CLANK_RELEASE_CHANNEL", "foundation-0")
# Fleet Law 6 provenance: injected at build/deploy time (env), never shelled
# out from Git at runtime — a deployed artefact may not contain .git.
# Unknown stays literal UNKNOWN; it is never fabricated.
SOURCE_REVISION = os.environ.get("BOARD_CLANK_SOURCE_REVISION", "UNKNOWN") or "UNKNOWN"
IDENTITY_LAW = (
    "A NEW SKU IS NOT NECESSARILY A NEW BOARD. "
    "A NEW BOARD REVISION IS NOT NECESSARILY A NEW PRODUCT NAME."
)
FIRST_SEEN_LAW = "FIRST_SEEN != MARKET_NOVELTY."
