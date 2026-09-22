"""Hierarchical identity. SKU ≠ board. Revision ≠ product name. Merges are conservative."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from board_clank._version import FIRST_SEEN_LAW, IDENTITY_LAW
from board_clank.taxonomy import RevisionKind

UNKNOWN = "UNKNOWN"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str | None) -> str:
    if value is None:
        return UNKNOWN
    text = str(value).strip().lower()
    if not text or text.upper() == UNKNOWN:
        return UNKNOWN
    slugged = _SLUG_RE.sub("-", text).strip("-")
    return slugged or UNKNOWN


def preserve_unknown(value: str | None) -> str:
    if value is None:
        return UNKNOWN
    text = str(value).strip()
    if not text:
        return UNKNOWN
    return text


@dataclass(frozen=True)
class VariantDimensions:
    ram: str = UNKNOWN
    storage: str = UNKNOWN
    wireless: str = UNKNOWN
    region: str = UNKNOWN
    bundle: str = UNKNOWN
    sku: str = UNKNOWN

    def fingerprint(self) -> str:
        payload = {
            "ram": slugify(self.ram),
            "storage": slugify(self.storage),
            "wireless": slugify(self.wireless),
            "region": slugify(self.region),
            "bundle": slugify(self.bundle),
            "sku": slugify(self.sku),
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
        return digest

    def as_dict(self) -> dict[str, str]:
        return {
            "ram": preserve_unknown(self.ram),
            "storage": preserve_unknown(self.storage),
            "wireless": preserve_unknown(self.wireless),
            "region": preserve_unknown(self.region),
            "bundle": preserve_unknown(self.bundle),
            "sku": preserve_unknown(self.sku),
        }


@dataclass(frozen=True)
class BoardIdentity:
    vendor_key: str
    family_key: str
    board_key: str
    revision_key: str
    variant_key: str
    revision_kind: RevisionKind
    revision_token: str
    variant_fingerprint: str

    def as_dict(self) -> dict[str, str]:
        return {
            "vendor_key": self.vendor_key,
            "family_key": self.family_key,
            "board_key": self.board_key,
            "revision_key": self.revision_key,
            "variant_key": self.variant_key,
            "revision_kind": str(self.revision_kind),
            "revision_token": self.revision_token,
            "variant_fingerprint": self.variant_fingerprint,
        }


def vendor_key(vendor: str) -> str:
    return slugify(vendor)


def family_key(vendor: str, family: str) -> str:
    return f"{vendor_key(vendor)}:{slugify(family)}"


def board_key(vendor: str, board_slug: str) -> str:
    """Board identity never includes RAM, storage, wireless, region, bundle or SKU."""
    return f"{vendor_key(vendor)}:{slugify(board_slug)}"


def revision_key(
    board: str,
    kind: RevisionKind | str,
    token: str | None,
) -> str:
    kind_value = RevisionKind(str(kind)) if not isinstance(kind, RevisionKind) else kind
    token_slug = slugify(token)
    return f"{board}:{kind_value.value}:{token_slug}"


def variant_key(revision: str, dims: VariantDimensions) -> str:
    return f"{revision}:{dims.fingerprint()}"


def soc_key(soc_vendor: str | None, marketing_name: str | None) -> str:
    vendor = slugify(soc_vendor)
    name = slugify(marketing_name)
    if vendor == UNKNOWN and name == UNKNOWN:
        return UNKNOWN
    return f"{vendor}:{name}"


def build_identity(
    *,
    vendor: str,
    family: str,
    board_slug: str,
    revision_kind: RevisionKind | str = RevisionKind.UNKNOWN,
    revision_token: str | None = None,
    variant: VariantDimensions | None = None,
) -> BoardIdentity:
    dims = variant or VariantDimensions()
    kind = RevisionKind(str(revision_kind)) if not isinstance(revision_kind, RevisionKind) else revision_kind
    token = preserve_unknown(revision_token)
    vk = vendor_key(vendor)
    fk = family_key(vendor, family)
    bk = board_key(vendor, board_slug)
    rk = revision_key(bk, kind, token)
    var_key = variant_key(rk, dims)
    return BoardIdentity(
        vendor_key=vk,
        family_key=fk,
        board_key=bk,
        revision_key=rk,
        variant_key=var_key,
        revision_kind=kind,
        revision_token=slugify(token),
        variant_fingerprint=dims.fingerprint(),
    )


def silent_revision_token(ports_signature: str, soc: str, dimensions: str) -> str:
    """Deterministic token for a silent hardware change under the same marketing name."""
    blob = json.dumps(
        {
            "ports": preserve_unknown(ports_signature),
            "soc": preserve_unknown(soc),
            "dimensions": preserve_unknown(dimensions),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


IDENTITY_LAWS = (IDENTITY_LAW, FIRST_SEEN_LAW)
