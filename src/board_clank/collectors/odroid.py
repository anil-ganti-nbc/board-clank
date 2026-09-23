"""Hardkernel ODROID PRODUCT adapter.

Foundation 5A: fifth vendor, fifth live-capable source adapter. Default
path is offline fixtures. Network fetch is opt-in, manual, experimental,
and never required for tests.

First-party surface notes (observed 2026-09-23):
- ``https://www.hardkernel.com/shop/<slug>/`` is a WooCommerce catalogue;
  product identity lives in the ``h1`` product-title. Slugs encode RAM
  configurations (``odroid-m1-with-4gbyte-ram``) or even glue them
  (``odroid-c4with2gbyteram``), and one N2+ page's slug omits the plus and
  carries a WooCommerce duplicate suffix — the h1 is identity truth, never
  the slug.
- H-series (x86) pages carry a multi-model comparison table whose header
  row maps each ODROID model to its column with production dates. The
  board's own processor is read from its own column; other columns are
  cross-product furniture (the Banana Pi rule).
- Shop stock status ("Out of stock") is preserved as availability
  evidence. No discontinuation dates are invented.
- ``odroid.com`` / ``wiki.odroid.com`` / ``forum.odroid.com`` answer HTTP
  403 from this network; they are documentation/community planes and are
  refused regardless.
- H-series memory is user-fitted SO-DIMM (no soldered memory): RAM options
  stay UNKNOWN rather than inventing a matrix; the DIY store pages for the
  same board are configuration storefronts canonicalised onto the base
  board.
"""

from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from board_clank.collectors.base import CollectorAdapter, CollectorError
from board_clank.identity import UNKNOWN, VariantDimensions, slugify
from board_clank.models import CollectorRunRequest, NormalizedSpec, NoveltyEvidence, ObservationDraft
from board_clank.taxonomy import (
    Architecture,
    Availability,
    BoardType,
    EditorialContext,
    NoveltyStatus,
    RevisionKind,
    SourcePlane,
)

SOURCE_KEY = "hardkernel-odroid-product"
VENDOR_KEY = "hardkernel-odroid"
VENDOR_NAME = "Hardkernel"
COLLECTOR_KEY = "hardkernel-odroid-product"
OFFICIAL_HOSTS = frozenset({"www.hardkernel.com", "hardkernel.com"})
SHOP_URL = "https://www.hardkernel.com/shop/"
SHOP_PREFIX = "/shop/"

_REPO_CORPUS = Path(__file__).resolve().parents[3] / "fixtures" / "odroid_product"
_PACKAGED_CORPUS = Path(__file__).resolve().parents[1] / "fixture_data" / "odroid_product"
CORPUS_DIR = _REPO_CORPUS if (_REPO_CORPUS / "manifest.json").exists() else _PACKAGED_CORPUS

_ODROID_PREFIX_RE = re.compile(r"^ODROID[- ]?", re.I)
_CONFIG_WITH_RAM_RE = re.compile(r"\s+with\s+(\d+)\s*GByte\s+RAM$", re.I)
_IO_HEADER_RE = re.compile(r"\s*\+\s*(?:40Pin )?IO Header$", re.I)
_CONFIG_TRAILING_GB_RE = re.compile(r"\s+(\d+)\s*GB$", re.I)
_COLOR_WORDS_RE = re.compile(r"\s+(Clear White|Dim Gray|Black|Blue|Red|White|Gray)$", re.I)

_FAMILY_RE = re.compile(r"ODROID-([A-Z]+\d+)", re.I)
_SUBTYPE_WORDS_RE = re.compile(r"\s+(PLUS|ULTRA|LITE|PRO|MAX)$", re.I)

_SOC_TOKEN_RE = re.compile(r"\b(RK[0-9]{4}[A-Z0-9]*|S905X[35]M?|S922X|N[0-9]{2,3}|J4[0-9]{3}|N5105|N6005)\b")
_KNOWN_SOC_VENDORS = ("rockchip", "amlogic", "intel")
_SOC_VENDOR_BY_PREFIX = (("rk", "rockchip"), ("s9", "amlogic"), ("n", "intel"), ("j4", "intel"))
# Intel CPU names carry the token after brand words; bare N-words without
# Intel context are not admitted.
_INTEL_CONTEXT_RE = re.compile(r"Intel|Celeron|Pentium|Core|Processor|CPU", re.I)
_NON_SOC_TOKEN_RE = re.compile(r"^(?:RTL[0-9]{4}[A-Z]?|Mali|AP[0-9]{4}|NPU|RKNN)")

_RAM_TYPE_RE = re.compile(r"(LPDDR5|LPDDR4|DDR5|DDR4)\b", re.I)
_GIB_LIST_RE = re.compile(r"(?:\d+\s*GiB?\s*(?:or|/|,)\s*)+\d+\s*GiB?\b", re.I)
_GIB_SIZE_RE = re.compile(r"(\d+)\s*GiB?\b", re.I)
_EMMC_SOCKET_RE = re.compile(r"eMMC (module )?(socket|connector|Socket)", re.I)
_EMMC_ONBOARD_RE = re.compile(r"(?:on-?board|embedded|soldered)[^.]{0,20}?(\d+)\s*G[i]?[bB]?\s*eMMC|(\d+)\s*G[i]?[bB]?\s*eMMC", re.I)
_SATA_RE = re.compile(r"SATA", re.I)
_NAS_HINT_RE = re.compile(r"NAS|SATA", re.I)
_HANDHELD_RE = re.compile(r"GO ULTRA|Input Buttons|game console|Direction Pad", re.I)
_KIT_RE = re.compile(r"\bKIT\b|Transformation KIT|bundle", re.I)


class _PageParser(HTMLParser):
    """Capture title, meta description, h1, h2/h3, paragraphs, links, and
    table rows (label/value pairs and comparison tables)."""

    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.description = ""
        self.h1 = ""
        self.h2s: list[str] = []
        self.paragraphs: list[str] = []
        self.hrefs: list[str] = []
        self.tables: list[list[list[str]]] = []
        self.out_of_stock = False
        self._capture: str | None = None
        self._buf = ""
        self._cell_buf: list[str] = []
        self._row: list[str] | None = None
        self._table: list[list[str]] | None = None
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrd = dict(attrs)
        if tag == "a" and attrd.get("href"):
            self.hrefs.append(attrd["href"])
        if tag == "meta" and attrd.get("name", "").lower() == "description":
            self.description = attrd.get("content") or ""
        if tag in {"h1", "h2", "h3", "p"}:
            self._capture = tag
            self._buf = ""
        elif tag == "title":
            self._in_title = True
            self._buf = ""
        elif tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell_buf = []
            self._capture = "cell"

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._in_title:
            self.title = re.sub(r"\s+", " ", self._buf).strip()
            self._in_title = False
            self._buf = ""
        elif tag in {"h1", "h2", "h3", "p"} and self._capture == tag:
            text = re.sub(r"\s+", " ", self._buf).strip()
            if text:
                if tag == "h1" and not self.h1:
                    self.h1 = text
                elif tag == "h2":
                    self.h2s.append(text)
                else:
                    self.paragraphs.append(text)
            self._capture = None
            self._buf = ""
        elif tag in {"td", "th"} and self._capture == "cell":
            if self._row is not None:
                self._row.append(re.sub(r"\s+", " ", "".join(self._cell_buf)).strip())
            self._cell_buf = []
            self._capture = None
        elif tag == "tr" and self._row is not None:
            if any(c for c in self._row):
                self._table.append(self._row)  # type: ignore[union-attr]
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._buf += data
        elif self._capture == "cell":
            self._cell_buf.append(data)
        elif self._capture:
            self._buf += data


def _model_and_config(h1: str) -> tuple[str, str, str]:
    """Return (model, ram config, color/bundle token) from the h1 title."""
    text = re.sub(r"\s+", " ", h1).strip()
    ram_config = UNKNOWN
    bundle = UNKNOWN
    if _IO_HEADER_RE.search(text):
        bundle = "io-header"
        text = _IO_HEADER_RE.sub("", text)
    match = _CONFIG_WITH_RAM_RE.search(text)
    if match:
        ram_config = f"{match.group(1)}GB"
        text = _CONFIG_WITH_RAM_RE.sub("", text)
    else:
        match = _CONFIG_TRAILING_GB_RE.search(text)
        if match:
            ram_config = f"{match.group(1)}GB"
            text = _CONFIG_TRAILING_GB_RE.sub("", text)
    color = UNKNOWN
    match = _COLOR_WORDS_RE.search(text)
    if match:
        color = slugify(match.group(1))
        text = _COLOR_WORDS_RE.sub("", text)
    if bundle != UNKNOWN:
        color = bundle
    return text.strip(), ram_config, color


def _board_slug(model: str) -> str:
    return slugify(model.replace("+", " plus "))


def _family_slug(model: str) -> str:
    match = _FAMILY_RE.search(model)
    if match:
        return slugify(match.group(1))
    return slugify(model)


def _normalize_header_model(header: str) -> str:
    """Comparison-table headers: 'ODROID H4+ ('2024 Apr)' -> 'ODROID-H4+'."""
    text = header.split("(")[0].strip()
    return text.replace(" ", "-")


def _soc_candidates_from_value(value: str) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    for match in _SOC_TOKEN_RE.finditer(value):
        model = match.group(1).upper()
        if _NON_SOC_TOKEN_RE.match(model):
            continue
        window = value[max(0, match.start() - 40):match.end() + 20]
        if model.startswith(("N", "J4")) and not _INTEL_CONTEXT_RE.search(window):
            continue
        vendor = UNKNOWN
        for word in re.findall(r"[A-Za-z]+", value[max(0, match.start() - 40):match.start()])[::-1]:
            if word.lower() in _KNOWN_SOC_VENDORS:
                vendor = word.lower()
                break
        if vendor == UNKNOWN:
            for prefix, name in _SOC_VENDOR_BY_PREFIX:
                if model.lower().startswith(prefix):
                    vendor = name
                    break
        if (vendor, model) not in candidates:
            candidates.append((vendor, model))
    return candidates


def _extract_soc(tables: list[list[list[str]]], model: str) -> tuple[str, str, list[str], str]:
    """Application processor from the board's own spec rows.

    H-series comparison tables map each ODROID model to a column; the
    board's own column supplies its CPU, other columns are furniture.
    Returns (vendor, model, candidates, spec_revision_note)."""
    header_models: dict[str, int] = {}
    for table in tables:
        if not table:
            continue
        first = table[0]
        for idx, cell in enumerate(first):
            if "ODROID" in cell.upper() and idx:
                header_models.setdefault(_normalize_header_model(cell).upper(), idx)
    if header_models:
        target = model.upper().replace(" PLUS", "+").replace("-PLUS", "+")
        target = re.sub(r"\s+", "-", target)
        column = header_models.get(target)
        if column is not None:
            for table in tables:
                for row in table:
                    if len(row) > column and row and row[0].strip().lower().startswith(("cpu", "processor")):
                        value = row[column]
                        candidates = _soc_candidates_from_value(value)
                        if len(candidates) == 1:
                            vendor, m = candidates[0]
                            note = first_header_date = ""
                            for t2 in tables:
                                if t2 and t2[0] and column < len(t2[0]):
                                    date = re.search(r"\((.{4,12})\)", t2[0][column])
                                    if date:
                                        note = date.group(1)
                            return vendor, m, [m], note
                        if len(candidates) > 1:
                            return "CONFLICT", ",".join(m for _v, m in candidates), [m for _v, m in candidates], ""

    for table in tables:
        for row in table:
            if len(row) >= 2 and row[0].strip().lower() in {"processor", "cpu"}:
                candidates = _soc_candidates_from_value(" ".join(row[1:]))
                if len(candidates) > 1:
                    return "CONFLICT", ",".join(m for _v, m in candidates), [m for _v, m in candidates], ""
                if len(candidates) == 1:
                    vendor, m = candidates[0]
                    return vendor, m, [m], ""
    return UNKNOWN, UNKNOWN, [], ""


def _ram_evidence(text: str, ram_config: str) -> tuple[str, list[str]]:
    type_match = _RAM_TYPE_RE.search(text)
    options: list[str] = []
    for match in _GIB_LIST_RE.finditer(text):
        for amount in _GIB_SIZE_RE.findall(match.group(0)):
            label = f"{amount}GB"
            if float(amount) <= 64 and label not in options:
                options.append(label)
    if not options:
        single = re.search(r"(?:Memory|DDR4|DDR5|LPDDR\d)\D{0,20}(\d+)\s*GiB?\b", text, re.I)
        if not single:
            single = re.search(r"(\d+)\s*GiB?\b", text, re.I)
        if single:
            options = [f"{single.group(1)}GB"]
    if "No soldered memory" in text or "no soldered memory" in text:
        # H-series: memory is user-fitted SO-DIMM; the board has no RAM matrix.
        options = []
    if ram_config != UNKNOWN:
        if ram_config not in options:
            options = options + [ram_config]
        options = sorted(set(options), key=lambda x: float(x[:-2]))
    return (type_match.group(1).upper() if type_match else UNKNOWN), options


def _storage_options(text: str) -> list[str]:
    match = _EMMC_ONBOARD_RE.search(text)
    if match:
        amount = match.group(1) or match.group(2)
        return [f"{amount}GB"]
    if _EMMC_SOCKET_RE.search(text):
        return ["none", "module"]
    return []


def _architecture(text: str) -> Architecture:
    if re.search(r"Intel|Celeron|Pentium|Core.{0,4}i[3579]|N[0-9]{3}|DDR5 SO-DIMM|x86", text, re.I):
        return Architecture.X86
    if re.search(r"Cortex|RK[0-9]{4}|Amlogic|ARM", text, re.I):
        return Architecture.ARM
    return Architecture.UNKNOWN


def _editorial(text: str, soc_name: str) -> list[str]:
    ctx: list[str] = []
    if soc_name.startswith("RK3588"):
        ctx.append(EditorialContext.HIGH_END_ARM.value)
    if _NAS_HINT_RE.search(text):
        ctx.append(EditorialContext.NAS_ORIENTED.value)
    return ctx


_VOLATILE_HTML = (
    re.compile(r"<script[\s\S]*?</script>", re.I),
    re.compile(r"<style[\s\S]*?</style>", re.I),
    re.compile(r"<!--[\s\S]*?-->", re.I),
    re.compile(r"_wpnonce=[0-9a-fA-F]+"),
)


def semantic_html(html: str) -> str:
    """Strip per-request volatile artifacts (WooCommerce wpnonce links,
    scripts) plus transport comments, then collapse whitespace."""
    text = html
    for pattern in _VOLATILE_HTML:
        text = pattern.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def semantic_evidence_hash(html: str) -> str:
    return hashlib.sha256(semantic_html(html).encode("utf-8")).hexdigest()


def raw_body_hash(body: bytes | str) -> str:
    if isinstance(body, str):
        body = body.encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _is_product_page_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc not in OFFICIAL_HOSTS:
        return False
    parts = [seg for seg in parsed.path.split("/") if seg]
    return len(parts) == 2 and parts[0] == "shop" and parts[1] not in {"cart", "blog", "checkout"}


def _detail_leads(href_list: list[str], base_url: str) -> list[str]:
    leads: list[str] = []
    for href in href_list:
        abs_url = urljoin(base_url, href).split("#")[0].split("?")[0]
        if not abs_url.endswith("/"):
            abs_url += "/"
        if _is_product_page_url(abs_url) and abs_url not in leads:
            leads.append(abs_url)
    return sorted(leads)


def parse_product_html(html: str, *, page_url: str, observed_at: str, historical_known: bool = False) -> tuple[list[ObservationDraft], dict[str, Any]]:
    """Parse one official Hardkernel product-surface HTML document."""
    parser = _PageParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # noqa: BLE001
        raise CollectorError(f"html parse failed for {page_url}: {exc}") from exc

    diagnostics: dict[str, Any] = {"page_url": page_url, "heading": UNKNOWN, "lead_hrefs": [], "status": "ok"}
    parsed_url = urlparse(page_url)
    if parsed_url.netloc in OFFICIAL_HOSTS:
        parts = [seg for seg in parsed_url.path.split("/") if seg]
        if parts in (["shop"], []) or parsed_url.path.rstrip("/") in ("", "/shop"):
            diagnostics["lead_hrefs"] = _detail_leads(parser.hrefs, page_url)
            diagnostics["status"] = "lead-index"
            diagnostics["evidence_roles"] = ["DISCOVERY"]
            return [], diagnostics
        if not _is_product_page_url(page_url):
            diagnostics["status"] = "ignored-unknown-surface"
            return [], diagnostics

    if not parser.h1:
        diagnostics["status"] = "ignored-non-computer"
        diagnostics["scope"] = "NON_BOARD_CATALOGUE_ITEM"
        return [], diagnostics

    model, ram_config, color = _model_and_config(parser.h1)
    diagnostics["heading"] = model
    body_text = " ".join(parser.paragraphs + parser.h2s + [parser.description])
    table_text = " ".join(" ".join(row) for table in parser.tables for row in table)

    if _HANDHELD_RE.search(parser.h1) or _HANDHELD_RE.search(body_text):
        diagnostics["status"] = "ignored-non-computer"
        diagnostics["scope"] = "NON_BOARD_CATALOGUE_ITEM"
        diagnostics["reason"] = "handheld-consumer-device"
        return [], diagnostics
    if _KIT_RE.search(parser.h1):
        diagnostics["status"] = "ignored-non-computer"
        diagnostics["scope"] = "NON_BOARD_CATALOGUE_ITEM"
        diagnostics["reason"] = "chassis-or-power-bundle-kit"
        return [], diagnostics

    board_slug = _board_slug(model)
    family_slug = _family_slug(model)
    soc_vendor, soc_name, soc_candidates, spec_revision_note = _extract_soc(parser.tables, model)
    full_text = f"{body_text} {table_text}"
    conflict = soc_vendor == "CONFLICT"

    if conflict:
        diagnostics["status"] = "identity-conflict"
        diagnostics["soc_candidates"] = soc_candidates
        draft = ObservationDraft(
            source_key=SOURCE_KEY, plane=SourcePlane.PRODUCT, observed_at=observed_at,
            vendor_key=VENDOR_KEY, vendor_name=VENDOR_NAME, family_slug=family_slug,
            family_name=family_slug, board_slug=board_slug, marketing_name=model,
            spec=NormalizedSpec(), raw_fields={"soc_candidates": soc_candidates},
            native_fields={"heading": model, "page_url": page_url},
            novelty=NoveltyEvidence(first_seen_at=observed_at, first_seen_source=SOURCE_KEY,
                                    novelty_status=NoveltyStatus.UNKNOWN, novelty_basis="conflicting-soc-evidence",
                                    novelty_confidence="low"),
            page_url=page_url, historical_known=historical_known,
            identity_conflict=True, identity_conflict_reason="multiple application processors named for one board",
            evidence_insufficient=True,
        )
        return [draft], diagnostics

    if soc_name == UNKNOWN:
        diagnostics["status"] = "insufficient-evidence"
        draft = ObservationDraft(
            source_key=SOURCE_KEY, plane=SourcePlane.PRODUCT, observed_at=observed_at,
            vendor_key=VENDOR_KEY, vendor_name=VENDOR_NAME, family_slug=family_slug,
            family_name=family_slug, board_slug=board_slug, marketing_name=model,
            spec=NormalizedSpec(), raw_fields={"html_excerpt": html[:400]},
            native_fields={"heading": model, "page_url": page_url},
            novelty=NoveltyEvidence(first_seen_at=observed_at, first_seen_source=SOURCE_KEY,
                                    novelty_status=NoveltyStatus.UNKNOWN, novelty_basis="insufficient-first-party-specification",
                                    novelty_confidence="low"),
            page_url=page_url, historical_known=historical_known, evidence_insufficient=True,
        )
        return [draft], diagnostics

    ram_type, ram_opts = _ram_evidence(full_text, ram_config)
    storage_opts = _storage_options(full_text)
    if not ram_opts:
        ram_opts = [UNKNOWN]
    if not storage_opts:
        storage_opts = [UNKNOWN]
    ram_matrix = ",".join(ram_opts)
    storage_matrix = ",".join(storage_opts)
    arch = _architecture(full_text)
    board_type = BoardType.SBC
    if arch is Architecture.X86:
        board_type = BoardType.MINI_ITX_SBC if re.search(r"mini|ITX|H-series|SO-DIMM", full_text, re.I) else BoardType.SBC
    availability = Availability.OUT_OF_STOCK if parser.out_of_stock or "Out of stock" in html else Availability.UNKNOWN

    drafts: list[ObservationDraft] = []
    for ram in ram_opts:
        for storage in storage_opts:
            spec = NormalizedSpec(
                soc=soc_name,
                soc_key=f"{slugify(soc_vendor)}:{slugify(soc_name)}",
                cpu_arch=arch.value,
                ram_type=ram_type,
                ram_options=ram_matrix,
                onboard_emmc="yes" if any(s not in (UNKNOWN, "none", "module") for s in storage_opts) else ("optional" if "module" in storage_opts else UNKNOWN),
                emmc_options=storage_matrix,
                microsd="yes" if re.search(r"Micro ?SD|microSD", full_text, re.I) else UNKNOWN,
                sata="yes" if _SATA_RE.search(full_text) else UNKNOWN,
                ethernet="2.5g" if re.search(r"2\.5G", full_text) else ("gigabit" if re.search(r"10/100/1000|GbE", full_text, re.I) else UNKNOWN),
                usb="usb3" if re.search(r"USB ?3", full_text, re.I) else ("usb" if "USB" in full_text else UNKNOWN),
                pcb_revision=UNKNOWN,
            )
            drafts.append(
                ObservationDraft(
                    source_key=SOURCE_KEY, plane=SourcePlane.PRODUCT, observed_at=observed_at,
                    vendor_key=VENDOR_KEY, vendor_name=VENDOR_NAME, family_slug=family_slug,
                    family_name=family_slug, board_slug=board_slug, marketing_name=model,
                    board_type=board_type, revision_kind=RevisionKind.UNKNOWN, revision_token=UNKNOWN,
                    variant=VariantDimensions(ram=ram, storage=storage, bundle=color),
                    soc_vendor=soc_vendor, soc_marketing_name=soc_name, architecture=arch,
                    spec=spec,
                    raw_fields={
                        "ram_options": ram_opts, "storage_options": storage_opts,
                        "spec_table_revision_note": spec_revision_note,
                        "page_ram_config": ram_config, "page_color": color,
                    },
                    native_fields={"heading": model, "page_url": page_url},
                    availability=availability,
                    novelty=NoveltyEvidence(
                        first_seen_at=observed_at, first_seen_source=SOURCE_KEY,
                        novelty_status=NoveltyStatus.HISTORICAL if historical_known else NoveltyStatus.EXISTING_PRODUCT,
                        novelty_basis="official-product-catalogue",
                        novelty_confidence="high",
                    ),
                    editorial_context=_editorial(full_text, soc_name),
                    page_url=page_url, historical_known=historical_known,
                )
            )
    diagnostics["status"] = "resolved"
    diagnostics["observation_count"] = len(drafts)
    diagnostics["board_slug"] = board_slug
    return drafts, diagnostics


def _canonical_page_url(page_url: str) -> str:
    """Per-RAM storefront URLs canonicalise onto the base product URL.

    ``odroid-m1-with-4gbyte-ram`` -> ``odroid-m1``; the glued
    ``odroid-c4with2gbyteram`` -> ``odroid-c4``. The N2+ page's slug is
    normalised to the model's own slug (``odroid-n2-plus``)."""
    slug = urlparse(page_url).path.rstrip("/").rsplit("/", 1)[-1]
    stripped = re.sub(r"-io-header$", "", slug, flags=re.I)
    stripped = re.sub(r"-with-\d+gbyte-ram(-\d+)?$", "", stripped, flags=re.I)
    stripped = re.sub(r"-\d+gb$", "", stripped, flags=re.I)
    stripped = re.sub(r"with\d+gbyteram$", "", stripped, flags=re.I)
    if stripped == slug:
        return page_url
    return page_url.replace(slug, stripped)


def _canonicalize_page_references(page_drafts: list[tuple[str, list[ObservationDraft]]]) -> None:
    """Configuration storefronts anchor board-scope references onto the
    base product URL (Radxa storefront rule). The anchor is used even when
    the base page itself was not fetched in this run — otherwise two RAM
    storefronts of one board would alternate the board's canonical payload
    every collection. Board-scope spec is adopted from the base page only
    when the base was observed in the same run."""
    by_url: dict[str, tuple[str, list[ObservationDraft]]] = {}
    for url, drafts in page_drafts:
        by_url.setdefault(url.lower(), (url, drafts))
    for url, drafts in page_drafts:
        canonical = _canonical_page_url(url)
        if canonical == url:
            continue
        target = by_url.get(canonical.lower())
        base_spec = None
        base_heading = None
        if target is not None:
            base_url, base_drafts = target
            base_draft = base_drafts[0]
            base_spec = base_draft.spec.model_copy()
            base_heading = base_draft.native_fields.get("heading")
        for draft in drafts:
            references = list(draft.raw_fields.get("reference_urls") or [])
            if url not in references:
                references.append(url)
            draft.raw_fields["reference_urls"] = references
            draft.page_url = canonical
            draft.native_fields["page_url"] = canonical
            if base_heading:
                draft.native_fields["heading"] = base_heading
            if base_spec is not None:
                draft.spec = base_spec


def load_corpus_manifest(corpus_dir: Path | None = None) -> dict[str, Any]:
    root = corpus_dir or CORPUS_DIR
    path = root / "manifest.json"
    if not path.exists():
        raise CollectorError(f"odroid fixture corpus missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def collect_corpus(name: str, *, run_id: str, started_at: str, corpus_dir: Path | None = None) -> CollectorRunRequest:
    root = corpus_dir or CORPUS_DIR
    manifest = load_corpus_manifest(corpus_dir)
    corpora = manifest.get("corpora") or {}
    if name not in corpora:
        raise CollectorError(f"unknown odroid corpus: {name}")
    observations: list[ObservationDraft] = []
    diagnostics: dict[str, Any] = {
        "corpus": name, "documents": [], "candidate_references": 0, "resolved": 0,
        "insufficient": 0, "conflicts": 0, "parser_errors": [], "leads": [],
    }
    ok = True
    error: str | None = None
    page_drafts: list[tuple[str, list[ObservationDraft]]] = []
    for doc in corpora[name]["documents"]:
        path = root / doc["file"]
        page_url = doc["page_url"]
        observed_at = doc.get("observed_at") or started_at
        historical = bool(doc.get("historical_known"))
        try:
            html = path.read_text(encoding="utf-8")
            drafts, info = parse_product_html(html, page_url=page_url, observed_at=observed_at, historical_known=historical)
        except CollectorError as exc:
            ok = False
            error = str(exc)
            diagnostics["parser_errors"].append(str(exc))
            diagnostics["documents"].append({"id": doc["id"], "status": "parser-error", "page_url": page_url})
            continue
        diagnostics["documents"].append({"id": doc["id"], **info})
        diagnostics["leads"].extend(info.get("lead_hrefs") or [])
        if doc.get("role") != "lead":
            diagnostics["candidate_references"] += 1
        if info.get("status") in {"resolved", "resolved-identity"}:
            diagnostics["resolved"] += 1
            page_drafts.append((page_url, drafts))
            observations.extend(drafts)
        elif info.get("status") == "insufficient-evidence":
            diagnostics["insufficient"] += 1
            observations.extend(drafts)
        elif info.get("status") == "identity-conflict":
            diagnostics["conflicts"] += 1
            observations.extend(drafts)
    _canonicalize_page_references(page_drafts)
    if name == "malformed" and not observations:
        ok = False
        error = error or "odroid product parser failed: missing required product fields"
    return CollectorRunRequest(
        run_id=run_id, source_key=SOURCE_KEY, collector_key=COLLECTOR_KEY,
        started_at=started_at, observations=observations, ok=ok, error=error,
        fixture_scenario=f"odroid:{name}", diagnostics=diagnostics,
    )


def _assert_official_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise CollectorError(f"refusing non-https hardkernel url: {url}")
    if parsed.netloc not in OFFICIAL_HOSTS:
        raise CollectorError(f"refusing third-party url (odroid.com/wiki/forum are documentation planes): {url}")
    parts = [seg for seg in parsed.path.split("/") if seg]
    is_index = parts in (["shop"], []) or parsed.path.rstrip("/") in ("", "/shop")
    if not is_index and not _is_product_page_url(url):
        raise CollectorError(f"refusing non-product hardkernel url: {url}")
    return url


def fetch_official(url: str, *, timeout: int = 30) -> str:
    return fetch_official_meta(url, timeout=timeout)["text"]


def fetch_official_meta(url: str, *, timeout: int = 30) -> dict[str, Any]:
    _assert_official_url(url)
    request = Request(
        url,
        headers={"User-Agent": "board-clank/0.1.0 (+experimental-manual-hardkernel-odroid-product)"},
        method="GET",
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - host allowlisted above
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        text = raw.decode(charset, errors="replace")
        final = response.geturl()
        return {
            "requested_url": url,
            "final_url": final,
            "http_status": getattr(response, "status", None) or response.getcode(),
            "content_type": response.headers.get("Content-Type"),
            "byte_length": len(raw),
            "raw_body_hash": raw_body_hash(raw),
            "semantic_evidence_hash": semantic_evidence_hash(text),
            "redirected": final.rstrip("/") != url.rstrip("/"),
            "text": text,
        }


class OdroidProductAdapter(CollectorAdapter):
    source_key = SOURCE_KEY
    collector_key = COLLECTOR_KEY
    live_network = False
    supports_experimental_live = True

    def __init__(self, *, experimental_live: bool = False, corpus: str = "baseline") -> None:
        self.experimental_live = experimental_live
        self.corpus = corpus

    def collect(self, run_id: str, started_at: str) -> CollectorRunRequest:
        if self.experimental_live:
            return self._collect_live(run_id, started_at)
        return collect_corpus(self.corpus, run_id=run_id, started_at=started_at)

    def parse_fixture(self, payload: dict) -> list[ObservationDraft]:
        html = payload.get("html") or ""
        drafts, _info = parse_product_html(
            html,
            page_url=payload.get("page_url") or SHOP_URL,
            observed_at=payload.get("observed_at") or "1970-01-01T00:00:00+00:00",
            historical_known=bool(payload.get("historical_known")),
        )
        return drafts

    def _collect_live(self, run_id: str, started_at: str) -> CollectorRunRequest:
        """Live path: shop index -> product pages. hardkernel.com only;
        odroid.com / wiki / forum are never fetched (documentation planes)."""
        diagnostics: dict[str, Any] = {
            "mode": "experimental-live-odroid",
            "primary_surface": SHOP_URL,
            "documents": [], "fetches": [], "candidate_references": 0,
            "resolved": 0, "parser_errors": [], "leads": [], "rejected": [],
        }
        observations: list[ObservationDraft] = []

        def record_fetch(url: str) -> dict[str, Any]:
            try:
                meta = fetch_official_meta(url)
                rec = {k: v for k, v in meta.items() if k != "text"}
                rec["ok"] = True
                diagnostics["fetches"].append(rec)
                return meta
            except (CollectorError, HTTPError, URLError, OSError) as exc:
                diagnostics["fetches"].append({"requested_url": url, "ok": False, "error": str(exc)})
                raise CollectorError(f"fetch failed for {url}: {exc}") from exc

        try:
            meta = record_fetch(SHOP_URL)
            _drafts, info = parse_product_html(meta["text"], page_url=SHOP_URL, observed_at=started_at)
            info["raw_body_hash"] = meta["raw_body_hash"]
            info["semantic_evidence_hash"] = meta["semantic_evidence_hash"]
            diagnostics["documents"].append(info)
            in_scope = info.get("lead_hrefs") or []
            diagnostics["leads"] = in_scope
            diagnostics["candidate_references"] = len(in_scope)

            page_drafts: list[tuple[str, list[ObservationDraft]]] = []
            for url in in_scope:
                try:
                    page_meta = record_fetch(url)
                    drafts, page_info = parse_product_html(page_meta["text"], page_url=url, observed_at=started_at)
                except CollectorError as exc:
                    diagnostics["parser_errors"].append(str(exc))
                    diagnostics["documents"].append({"page_url": url, "status": "error"})
                    continue
                page_info["raw_body_hash"] = page_meta["raw_body_hash"]
                page_info["semantic_evidence_hash"] = page_meta["semantic_evidence_hash"]
                diagnostics["documents"].append(page_info)
                if page_info.get("status") == "resolved":
                    diagnostics["resolved"] += 1
                    page_drafts.append((url, drafts))
                    observations.extend(drafts)
                elif page_info.get("status") == "insufficient-evidence":
                    diagnostics["insufficient"] = diagnostics.get("insufficient", 0) + 1
                    observations.extend(drafts)
                elif page_info.get("status") == "identity-conflict":
                    diagnostics["conflicts"] = diagnostics.get("conflicts", 0) + 1
                    observations.extend(drafts)
            _canonicalize_page_references(page_drafts)

            return CollectorRunRequest(
                run_id=run_id, source_key=SOURCE_KEY, collector_key=COLLECTOR_KEY,
                started_at=started_at, observations=observations, ok=True,
                fixture_scenario=None, diagnostics=diagnostics,
            )
        except Exception as exc:  # noqa: BLE001
            return CollectorRunRequest(
                run_id=run_id, source_key=SOURCE_KEY, collector_key=COLLECTOR_KEY,
                started_at=started_at, observations=observations, ok=bool(observations),
                error=None if observations else f"experimental live fetch failed: {exc}",
                diagnostics=diagnostics,
            )


def _all_hrefs(html: str, base_url: str) -> list[str]:
    parser = _PageParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001
        return []
    seen: list[str] = []
    for href in parser.hrefs:
        abs_url = urljoin(base_url, href).split("#")[0]
        if abs_url not in seen:
            seen.append(abs_url)
    return seen
