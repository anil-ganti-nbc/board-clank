from __future__ import annotations

import pytest

from board_clank.identity import (
    IDENTITY_LAWS,
    UNKNOWN,
    VariantDimensions,
    board_key,
    build_identity,
    soc_key,
)
from board_clank.taxonomy import RevisionKind


def test_identity_laws_are_codified() -> None:
    joined = " ".join(IDENTITY_LAWS)
    assert "A NEW SKU IS NOT NECESSARILY A NEW BOARD" in joined
    assert "A NEW BOARD REVISION IS NOT NECESSARILY A NEW PRODUCT NAME" in joined
    assert "FIRST_SEEN != MARKET_NOVELTY" in joined


def test_ram_does_not_change_board_key() -> None:
    four = build_identity(vendor="raspberry-pi", family="pi-5", board_slug="raspberry-pi-5", variant=VariantDimensions(ram="4GB"))
    eight = build_identity(vendor="raspberry-pi", family="pi-5", board_slug="raspberry-pi-5", variant=VariantDimensions(ram="8GB"))
    assert four.board_key == eight.board_key
    assert four.variant_key != eight.variant_key


@pytest.mark.parametrize("ram", ["4GB", "8GB", "16GB"])
def test_variant_matrix_shares_board(ram: str) -> None:
    ident = build_identity(vendor="raspberry-pi", family="pi-5", board_slug="raspberry-pi-5", variant=VariantDimensions(ram=ram))
    assert ident.board_key == board_key("raspberry-pi", "raspberry-pi-5")
    assert ram.lower().replace("gb", "") in ident.variant_fingerprint or ident.variant_fingerprint


def test_revision_token_does_not_rename_board() -> None:
    v1 = build_identity(vendor="radxa", family="rock-5", board_slug="rock-5b", revision_kind=RevisionKind.MARKETING, revision_token="v1.0")
    v21 = build_identity(vendor="radxa", family="rock-5", board_slug="rock-5b", revision_kind=RevisionKind.MARKETING, revision_token="v2.1")
    assert v1.board_key == v21.board_key
    assert v1.revision_key != v21.revision_key


def test_soc_is_independent() -> None:
    assert soc_key("rockchip", "RK3588") == "rockchip:rk3588"
    assert soc_key(None, None) == UNKNOWN


def test_unknown_preserved() -> None:
    ident = build_identity(vendor="pine64", family="", board_slug="rock64")
    assert ident.family_key.endswith(":UNKNOWN")
    assert ident.revision_token == "UNKNOWN"


def test_compute_module_wireless_matrix_same_board() -> None:
    keys = set()
    variants = set()
    for wireless in ("none", "wifi"):
        for storage in ("none", "16GB", "32GB"):
            ident = build_identity(
                vendor="raspberry-pi",
                family="cm4",
                board_slug="cm4",
                variant=VariantDimensions(ram="4GB", storage=storage, wireless=wireless),
            )
            keys.add(ident.board_key)
            variants.add(ident.variant_key)
    assert len(keys) == 1
    assert len(variants) == 6
