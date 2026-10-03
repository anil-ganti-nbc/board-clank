"""Closed classification labels. Alias hits are decided before this module."""

from __future__ import annotations

SOC_NAMES = frozenset(
    {
        ("rockchip",),
        ("allwinner",),
        ("amlogic",),
        ("broadcom",),
        ("mediatek",),
        ("qualcomm",),
        ("intel",),
        ("amd",),
        ("nxp",),
    }
)
SOC_DOMAINS = frozenset(
    {
        "rock-chips.com",
        "allwinnertech.com",
        "amlogic.com",
        "mediatek.com",
        "intel.com",
        "amd.com",
        "nxp.com",
    }
)
DENYLIST: dict[str, tuple[str, str]] = {
    "amazon.com": ("reseller", "reseller"),
    "amazon.co.uk": ("reseller", "reseller"),
    "aliexpress.com": ("reseller", "reseller"),
    "alibaba.com": ("reseller", "reseller"),
    "ebay.com": ("reseller", "reseller"),
    "banggood.com": ("reseller", "reseller"),
    "walmart.com": ("reseller", "reseller"),
    "digikey.com": ("distributor", "distributor"),
    "mouser.com": ("distributor", "distributor"),
    "arrow.com": ("distributor", "distributor"),
    "lcsc.com": ("distributor", "distributor"),
    "avnet.com": ("distributor", "distributor"),
    "cnx-software.com": ("media", "media_or_marketplace"),
    "wikipedia.org": ("media", "media_or_marketplace"),
    "medium.com": ("media", "media_or_marketplace"),
    "youtube.com": ("media", "media_or_marketplace"),
    "reddit.com": ("media", "media_or_marketplace"),
    "twitter.com": ("media", "media_or_marketplace"),
    "x.com": ("media", "media_or_marketplace"),
    "facebook.com": ("media", "media_or_marketplace"),
    "linkedin.com": ("media", "media_or_marketplace"),
    "github.io": ("unresolved", "platform_host"),
    "gitlab.io": ("unresolved", "platform_host"),
    "wordpress.com": ("unresolved", "platform_host"),
    "blogspot.com": ("unresolved", "platform_host"),
    "wixsite.com": ("unresolved", "platform_host"),
    "myshopify.com": ("unresolved", "platform_host"),
}
PRODUCT_TOKENS = frozenset({"pro", "plus", "max", "ultra", "zero", "mini", "lite"})
REASON_CODES = frozenset(
    {
        "qualified",
        "known_active_source",
        "known_placeholder",
        "out_of_scope_jetson",
        "soc_vendor",
        "distributor",
        "reseller",
        "storefront_only",
        "single_product_name",
        "media_or_marketplace",
        "platform_host",
        "robots_disallow",
        "robots_unavailable",
        "http_blocked",
        "fetch_failed",
        "primary_domain_unresolved",
        "ambiguous_primary",
        "vendor_name_unresolved",
        "board_surface_unresolved",
        "board_maker_unresolved",
        "brand_domain_mismatch",
        "instruction_bearing_rejected",
        "malformed_page",
        "roster_mismatch",
        "alias_table_incomplete",
    }
)
ALIAS_CLASS = {
    "out_of_scope": ("out_of_scope", "out_of_scope_jetson"),
    "active": ("known_active", "known_active_source"),
    "placeholder": ("known_placeholder", "known_placeholder"),
}


def is_product_only(tokens: tuple[str, ...]) -> bool:
    if not tokens:
        return True
    return all(any(ch.isdigit() for ch in token) or token in PRODUCT_TOKENS for token in tokens)
