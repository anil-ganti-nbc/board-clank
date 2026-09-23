"""Banana Pi PRODUCT adapter.

Foundation 4A: fourth vendor, fourth live-capable source adapter. Default
path is offline fixtures. Network fetch is opt-in, manual, experimental, and
never required for tests.

First-party surface notes (observed 2026-09-22):
- ``https://banana-pi.org/en/<category>/<number>.html`` — product pages
  with OPAQUE numbered URLs. Product identity lives in ``<title>`` (there
  is no h1). Titles follow "Banana Pi <BPI-model> with <SoC> ..." and the
  site's own suffix.
- Pages embed OTHER products' names and SoCs in footer/related furniture,
  so SoC extraction is title-anchored (plus the page's own meta
  description) and never scans full-body furniture.
- Some pages document multiple SoC options for one board (BPI-M2 Zero:
  H3 (option H2+/H5)) — identity conflict, fail closed, like every prior
  vendor.
- ``wiki.banana-pi.org`` / ``docs.banana-pi.org`` are documentation planes
  and are NOT fetched.
- HTTPS only, Cloudflare-fronted with per-request volatile markup; the
  semantic hash strips exactly those artifacts (same normalization family
  as the Radxa adapter).
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

SOURCE_KEY = "banana-pi-product"
VENDOR_KEY = "banana-pi"
VENDOR_NAME = "Banana Pi"
COLLECTOR_KEY = "banana-pi-product"
OFFICIAL_HOSTS = frozenset({"banana-pi.org", "www.banana-pi.org"})
EN_PREFIX = "/en/"
SBC_INDEX_URL = "https://banana-pi.org/en/banana-pi-sbcs/"
ROUTER_INDEX_URL = "https://banana-pi.org/en/bananapi-router/"
TITLE_SUFFIX_RE = re.compile(r"\s*-\s*Banana Pi open source hardware community.*$", re.I | re.S)

# Board-product categories; other /en/ categories are accessories, STEM
# microcontroller boards, services, news, or corporate pages.
_BOARD_CATEGORIES = {
    "banana-pi-sbcs": BoardType.SBC,
    "bananapi-router": BoardType.ROUTER_BOARD,
}

_MODEL_RE = re.compile(r"(BPI-[A-Za-z0-9+]+(?:-[A-Za-z0-9]+)*(?:\s+(?:Pro|Plus|Mini|Zero|Berry|Ultra|Max|LTS))*)")
_SUBTYPE_WORDS = ("Pro", "Plus", "Mini", "Zero", "Berry", "Ultra", "Max", "LTS")

_SOC_TOKEN_RE = re.compile(
    r"\b(RK[0-9]{4}[A-Za-z]?|H618|H3(?![0-9])|H2\+|H5(?![0-9])|A733|A64|A311D2?|S905X3|A40i|R40(?![0-9A-Z])|V40|"
    r"MT7981B|MT7986|MT7988A|K1(?![0-9A-Z])|K230D|SF21H8898|SP7350|VS680)",
    re.I,
)
_KNOWN_SOC_VENDORS = (
    "rockchip", "allwinner", "mediatek", "mtk", "spacemit", "canaan",
    "siflower", "sunplus", "senary", "synaptics", "amlogic",
)
_SOC_VENDOR_BY_PREFIX = (
    ("rk", "rockchip"), ("h2", "allwinner"), ("h3", "allwinner"), ("h5", "allwinner"),
    ("h618", "allwinner"), ("a7", "allwinner"), ("a64", "allwinner"), ("a3", "allwinner"),
    ("a40", "allwinner"), ("r40", "allwinner"), ("v40", "allwinner"),
    ("mt7", "mediatek"), ("k1", "spacemit"), ("k230", "canaan"),
    ("sf21", "siflower"), ("sp7", "sunplus"), ("vs", "synaptics"), ("s905", "amlogic"),
)
# Short/ambiguous tokens need an adjacent vendor word to be admitted at all.
_VENDOR_GATED_TOKENS = {"K1", "H3", "H5", "H2+", "R40", "V40", "SP7350", "VS680", "A64"}
# Tokens that are companion radios/PHYs whatever they resemble.
_WIFI_CONTEXT_RE = re.compile(r"WiFi|Wi-?Fi|chipset|dual-band|wireless module", re.I)
_SOC_CONTEXT_RE = re.compile(r"SoC|SOC|chip\b|processor", re.I)

_WIFI_LEVEL_RE = re.compile(r"Wi-?Fi\s*([567])", re.I)
_WIFI_GENERIC_RE = re.compile(r"WiFi|Wi-?Fi|802\.11", re.I)
_ACCESSORY_RE = re.compile(r"module|antenna|camera|case|cable|heatsink|power supply", re.I)
_MCUE_RE = re.compile(r"arduino|microcontroller|ESP32|Webduino", re.I)
_INDUSTRIAL_RE = re.compile(r"Industrial", re.I)


class _PageParser(HTMLParser):
    """Capture title, meta description, h2/h3 headings, paragraphs, links."""

    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.description = ""
        self.h2s: list[str] = []
        self.h3s: list[str] = []
        self.paragraphs: list[str] = []
        self.hrefs: list[str] = []
        self._capture: str | None = None
        self._buf = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrd = dict(attrs)
        if tag == "a" and attrd.get("href"):
            self.hrefs.append(attrd["href"])
        if tag == "meta" and attrd.get("name", "").lower() == "description":
            self.description = attrd.get("content") or ""
        if tag in {"h2", "h3", "p"}:
            self._capture = tag
            self._buf = ""
        elif tag == "title":
            self._in_title = True
            self._buf = ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._in_title:
            self.title = re.sub(r"\s+", " ", self._buf).strip()
            self._in_title = False
            self._buf = ""
        elif tag in {"h2", "h3", "p"} and self._capture == tag:
            text = re.sub(r"\s+", " ", self._buf).strip()
            if text:
                if tag == "h2":
                    self.h2s.append(text)
                elif tag == "h3":
                    self.h3s.append(text)
                else:
                    self.paragraphs.append(text)
            self._capture = None
            self._buf = ""

    def handle_data(self, data: str) -> None:
        if self._in_title or self._capture:
            self._buf += data


def _title_head(title: str) -> str:
    return TITLE_SUFFIX_RE.sub("", title).strip()


def _model_of(title_head: str) -> str:
    match = _MODEL_RE.search(title_head)
    return match.group(1).strip() if match else ""


def _board_slug(model: str) -> str:
    """Official plus markers stay distinct (BPI-M2+ != BPI-M2)."""
    return slugify(model.replace("+", " plus "))


def _family_slug(model: str) -> str:
    """Family from the model's generation token (first-party BPi line
    naming: M5 Pro/M5, M7/M7S, M4 Berry/M4 Zero, R4/R4 Pro share lines),
    mirroring the Radxa ROCK-series precedent. Subtype words and trailing
    subtype letters (S/X) after the generation digits are stripped."""
    words = model.split()
    base = words[0] if words else model  # BPI-xxxx or BPI-xxxx-sub
    while len(words) > 1 and words[1].rstrip("+") in [w.lower() for w in _SUBTYPE_WORDS]:
        base = words[0]
        break
    # strip trailing "-Zero"-style hyphenated subtypes: CanMV-K230D-Zero -> CanMV-K230D
    parts = base.split("-")
    while len(parts) > 2 and parts[-1].lower() in [w.lower() for w in _SUBTYPE_WORDS]:
        parts = parts[:-1]
    base = "-".join(parts)
    # strip trailing subtype letters directly after digits: M7S -> M7
    base = re.sub(r"(\d)[SX](?=$|[-+])", r"\1", base)
    return slugify(base)


def _soc_candidates(text: str) -> list[tuple[str, str]]:
    """Title-anchored (vendor, model) application-processor pairs.

    A token is rejected when wifi/chipset/module language sits right after
    it (MediaTek MT7976C dual-band WiFi 6 chipset) and admitted when SoC /
    chip language does (Rockchip RK3576 ... chip). Short ambiguous tokens
    need an adjacent vendor word."""
    candidates: list[tuple[str, str]] = []
    for match in _SOC_TOKEN_RE.finditer(text):
        model = match.group(1).upper()
        after = text[match.end():match.end() + 60]
        before = text[max(0, match.start() - 60):match.start()]
        if _WIFI_CONTEXT_RE.search(after) and not _SOC_CONTEXT_RE.search(after[:30]):
            continue
        if model in _VENDOR_GATED_TOKENS:
            window = f"{before} {after}"
            if not any(v in window.lower() for v in _KNOWN_SOC_VENDORS) and not re.search(
                r"option|chip|SoC", window, re.I
            ):
                continue
        vendor = UNKNOWN
        for word in re.findall(r"[A-Za-z]+", before)[::-1]:
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


def _extract_soc(identity_text: str) -> tuple[str, str, list[str]]:
    candidates = _soc_candidates(identity_text)
    if not candidates:
        return UNKNOWN, UNKNOWN, []
    if len(candidates) > 1:
        return "CONFLICT", ",".join(m for _v, m in candidates), [m for _v, m in candidates]
    vendor, model = candidates[0]
    return vendor, model, [model]


def _normalise_size(amount: str, unit: str) -> str:
    unit = "GB" if unit.upper() == "G" else ("MB" if unit.upper() == "M" else unit.upper())
    return f"{amount}{unit}"


# Lists look like "2GB/4GB/8GB", "8/16/32GB", "2/4/8/16G", "32/64/128GB":
# units may appear only on the last item.
_SIZE_LIST_RE = re.compile(
    r"(?:\d+(?:\.\d+)?\s*(?:GB|G|MB|M)?\s*(?:/|,)\s*)+\d+(?:\.\d+)?\s*(GB|G|MB|M)\b",
    re.I,
)
_SIZE_ITEM_RE = re.compile(r"\d+(?:\.\d+)?")
_UNIT_ANCHOR_RE = re.compile(r"^\s*(RAM|Memory|eMMC|Flash|Storage|LPDDR|DDR)", re.I)
_RAM_CONTEXT_RE = re.compile(r"RAM|Memory|LPDDR|DDR", re.I)
_STORAGE_CONTEXT_RE = re.compile(r"eMMC|Flash|NAND|Storage", re.I)
_RAM_TYPE_RE = re.compile(r"(LPDDR5X|LPDDR5|LPDDR4X|LPDDR4x|LPDDR4|LPDDR4/4x|DDR3L|DDR3|DDR2)\b", re.I)


def _list_matches(text: str, *, ram_side: bool) -> list[list[str]]:
    """Size lists classified by their own anchor, not a context window.

    A list belongs to RAM when RAM|Memory|LPDDR|DDR anchors it and to
    storage when eMMC|Flash|Storage|NAND does. The anchor may sit just
    before the list ("RAM: 2GB/4GB") or right after it ("2/4/8/16G eMMC",
    "8/16GB 32-bit LPDDR4x"), so adjacent RAM and eMMC lists cannot leak
    into each other."""
    found: list[list[str]] = []
    for match in _SIZE_LIST_RE.finditer(text):
        unit = match.group(1)
        before = text[max(0, match.start() - 25):match.start()]
        after = text[match.end():match.end() + 26]
        after_clean = re.sub(r"^\s*(?:\d+\s*-?\s*bit\s+|\(\s*max[^)]*\)\s*[:,]?\s*|\([^)]{1,20}\)\s*|\d+\s*bit\s+)", "", after)
        ram_anchor = bool(re.search(r"\b(RAM|Memory|LPDDR|DDR)\s*[:\-]?\s*$", before, re.I)) or bool(
            re.match(r"\s*(RAM|Memory|LPDDR|DDR)\b", after_clean, re.I)
        )
        storage_anchor = bool(re.search(r"\b(eMMC|Flash|Storage|NAND)\s*[:\-]?\s*$", before, re.I)) or bool(
            re.match(r"\s*(eMMC|Flash|Storage|NAND)\b", after_clean, re.I)
        )
        if ram_side and not ram_anchor:
            continue
        if not ram_side and not storage_anchor:
            continue
        if ram_anchor and storage_anchor and ram_side is False:
            continue
        norm_unit = "GB" if unit.upper() == "G" else ("MB" if unit.upper() == "M" else unit.upper())
        sizes = [f"{amt}{norm_unit}" for amt in _SIZE_ITEM_RE.findall(match.group(0))]
        found.append(sizes)
    return found


def _ram_evidence(text: str) -> tuple[str, list[str]]:
    type_match = _RAM_TYPE_RE.search(text)
    options: list[str] = []
    for sizes in _list_matches(text, ram_side=True):
        if any(label.endswith("GB") and float(label[:-2]) > 128 for label in sizes):
            continue
        for label in sizes:
            if label not in options:
                options.append(label)
    if not options:
        # Single values: "2G LPDDR4 RAM", "RAM: 4GB", "1GB LPDDR4".
        for pattern in (
            r"(\d+(?:\.\d+)?)\s*(GB|G|MB|M)\b(?=[^,;]{0,24}(?:LPDDR|DDR))",
            r"RAM\s*:\s*(\d+(?:\.\d+)?)\s*(GB|G|MB|M)\b",
            r"(\d+(?:\.\d+)?)\s*(GB|G|MB|M)\s*RAM\b",
        ):
            single = re.search(pattern, text, re.I)
            if single:
                options = [_normalise_size(single.group(1), single.group(2))]
                break
    return (type_match.group(1).upper() if type_match else UNKNOWN), options


def _storage_options(text: str) -> list[str]:
    options: list[str] = []
    for sizes in _list_matches(text, ram_side=False):
        for label in sizes:
            if label.endswith("GB") and float(label[:-2]) > 512:
                continue
            if label not in options:
                options.append(label)
    if options:
        return options
    single = re.search(r"(\d+(?:\.\d+)?)\s*(GB|G|MB|M)\s*eMMC", text, re.I)
    if single:
        return [_normalise_size(single.group(1), single.group(2))]
    single = re.search(r"(\d+(?:\.\d+)?)\s*(GB|G|MB|M)\s*NAND", text, re.I)
    if single:
        return [f"{_normalise_size(single.group(1), single.group(2))}-NAND"]
    if re.search(r"eMMC", text, re.I):
        return ["module"]
    return []


def _wireless_options(text: str) -> list[str]:
    level = _WIFI_LEVEL_RE.search(text)
    if level:
        return [f"wifi{level.group(1)}"]
    if _WIFI_GENERIC_RE.search(text):
        return ["wifi"]
    return [UNKNOWN]


def _architecture(text: str) -> Architecture:
    if re.search(r"RISC-V|RISC V|SpacemiT|K230D|SF21H8898", text, re.I):
        return Architecture.RISCV
    if re.search(r"Cortex|RK[0-9]{4}|Allwinner|MT7988|H618|ARM", text, re.I):
        return Architecture.ARM
    return Architecture.UNKNOWN


def _editorial(text: str, board_type: BoardType, soc_name: str) -> list[str]:
    ctx: list[str] = []
    if soc_name.startswith("RK3588") or soc_name in {"RK3576", "A733", "MT7988A"}:
        ctx.append(EditorialContext.HIGH_END_ARM.value)
    if _INDUSTRIAL_RE.search(text):
        ctx.append(EditorialContext.INDUSTRIAL.value)
    if board_type is BoardType.ROUTER_BOARD:
        ctx.append(EditorialContext.ROUTER_ORIENTED.value)
    return ctx


_VOLATILE_HTML = (
    re.compile(r"<script[\s\S]*?</script>", re.I),
    re.compile(r"<style[\s\S]*?</style>", re.I),
    re.compile(r"<!--[\s\S]*?-->", re.I),
    re.compile(r"/cdn-cgi/l/email-protection#[0-9a-fA-F]*"),
    re.compile(r'data-cfemail="[0-9a-fA-F]*"'),
)


def semantic_html(html: str) -> str:
    """Strip exactly the per-request volatile artifacts Banana Pi pages carry
    (Cloudflare challenge scripts, email-protection links) plus transport
    comments, then collapse whitespace."""
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


def _category_of(page_url: str) -> str:
    parts = [seg for seg in urlparse(page_url).path.split("/") if seg]
    # parts == ["en", category, "number.html"]
    if len(parts) >= 3 and parts[0] == "en":
        return parts[1]
    if len(parts) == 2 and parts[0] == "en":
        return parts[1]
    return ""


def _is_product_page_url(page_url: str) -> bool:
    parsed = urlparse(page_url)
    if parsed.netloc not in OFFICIAL_HOSTS:
        return False
    parts = [seg for seg in parsed.path.split("/") if seg]
    return len(parts) >= 3 and parts[0] == "en" and parts[-1].endswith(".html")


def _is_board_category(category: str) -> bool:
    return category in _BOARD_CATEGORIES


def _detail_leads(href_list: list[str], base_url: str) -> list[str]:
    leads: list[str] = []
    for href in href_list:
        abs_url = urljoin(base_url, href).split("#")[0]
        if not _is_product_page_url(abs_url):
            continue
        if _is_board_category(_category_of(abs_url)) and abs_url not in leads:
            leads.append(abs_url)
    return sorted(leads)


def parse_product_html(html: str, *, page_url: str, observed_at: str, historical_known: bool = False) -> tuple[list[ObservationDraft], dict[str, Any]]:
    """Parse one official Banana Pi product-surface HTML document."""
    parser = _PageParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # noqa: BLE001
        raise CollectorError(f"html parse failed for {page_url}: {exc}") from exc

    diagnostics: dict[str, Any] = {"page_url": page_url, "heading": UNKNOWN, "lead_hrefs": [], "status": "ok"}
    parsed_url = urlparse(page_url)
    if parsed_url.netloc in OFFICIAL_HOSTS:
        category = _category_of(page_url)
        parts = [seg for seg in parsed_url.path.split("/") if seg]
        is_index = parts[:2] == ["en", category] and len(parts) == 2 and category in (
            set(_BOARD_CATEGORIES) | {"banana-pi-ai-iot", "banana-pi-steam", "bananapi-news"}
        )
        if is_index or parsed_url.path.rstrip("/") in ("", "/en"):
            diagnostics["lead_hrefs"] = _detail_leads(parser.hrefs, page_url)
            diagnostics["status"] = "lead-index"
            diagnostics["evidence_roles"] = ["DISCOVERY"]
            return [], diagnostics
        if not _is_product_page_url(page_url):
            diagnostics["status"] = "ignored-unknown-surface"
            return [], diagnostics

    title_head = _title_head(parser.title)
    model = _model_of(title_head)
    diagnostics["heading"] = model or title_head or UNKNOWN
    category = _category_of(page_url)
    if not model:
        diagnostics["status"] = "ignored-non-computer"
        diagnostics["scope"] = "NON_BOARD_CATALOGUE_ITEM"
        return [], diagnostics
    if _ACCESSORY_RE.search(title_head):
        diagnostics["status"] = "ignored-non-computer"
        diagnostics["scope"] = "NON_BOARD_CATALOGUE_ITEM"
        diagnostics["reason"] = "accessory-or-module"
        return [], diagnostics
    if _MCUE_RE.search(title_head) or category == "banana-pi-steam":
        diagnostics["status"] = "ignored-non-computer"
        diagnostics["scope"] = "NON_BOARD_CATALOGUE_ITEM"
        diagnostics["reason"] = "microcontroller-or-education-board"
        return [], diagnostics
    if not _is_board_category(category):
        diagnostics["status"] = "ignored-non-computer"
        diagnostics["scope"] = "NON_BOARD_CATALOGUE_ITEM"
        diagnostics["reason"] = "non-board-category"
        return [], diagnostics

    # Identity text is title-anchored: the page's own title plus its own
    # meta description. Body furniture names other products' SoCs.
    identity_text = f"{title_head}. {parser.description}"
    board_slug = _board_slug(model)
    family_slug = _family_slug(model)
    board_type = _BOARD_CATEGORIES[category]
    if _INDUSTRIAL_RE.search(title_head):
        board_type = BoardType.INDUSTRIAL_SBC
    soc_vendor, soc_name, soc_candidates = _extract_soc(identity_text)
    body_text = " ".join(parser.h3s + parser.paragraphs)
    conflict = soc_vendor == "CONFLICT"

    if conflict:
        diagnostics["status"] = "identity-conflict"
        diagnostics["soc_candidates"] = soc_candidates
        draft = ObservationDraft(
            source_key=SOURCE_KEY,
            plane=SourcePlane.PRODUCT,
            observed_at=observed_at,
            vendor_key=VENDOR_KEY,
            vendor_name=VENDOR_NAME,
            family_slug=family_slug,
            family_name=family_slug,
            board_slug=board_slug,
            marketing_name=model,
            board_type=board_type,
            spec=NormalizedSpec(),
            raw_fields={"soc_candidates": soc_candidates, "category": category},
            native_fields={"heading": model, "page_url": page_url},
            novelty=NoveltyEvidence(
                first_seen_at=observed_at, first_seen_source=SOURCE_KEY,
                novelty_status=NoveltyStatus.UNKNOWN, novelty_basis="conflicting-soc-evidence",
                novelty_confidence="low",
            ),
            page_url=page_url,
            historical_known=historical_known,
            identity_conflict=True,
            identity_conflict_reason="multiple application processors named for one board",
            evidence_insufficient=True,
        )
        return [draft], diagnostics

    if soc_name == UNKNOWN:
        diagnostics["status"] = "insufficient-evidence"
        draft = ObservationDraft(
            source_key=SOURCE_KEY,
            plane=SourcePlane.PRODUCT,
            observed_at=observed_at,
            vendor_key=VENDOR_KEY,
            vendor_name=VENDOR_NAME,
            family_slug=family_slug,
            family_name=family_slug,
            board_slug=board_slug,
            marketing_name=model,
            board_type=board_type,
            spec=NormalizedSpec(),
            raw_fields={"category": category, "html_excerpt": html[:400]},
            native_fields={"heading": model, "page_url": page_url},
            novelty=NoveltyEvidence(
                first_seen_at=observed_at, first_seen_source=SOURCE_KEY,
                novelty_status=NoveltyStatus.UNKNOWN, novelty_basis="insufficient-first-party-specification",
                novelty_confidence="low",
            ),
            page_url=page_url,
            historical_known=historical_known,
            evidence_insufficient=True,
        )
        return [draft], diagnostics

    ram_type, ram_opts = _ram_evidence(f"{identity_text} {body_text}")
    storage_opts = _storage_options(f"{identity_text} {body_text}")
    wireless_opts = _wireless_options(f"{identity_text} {body_text}")
    if not ram_opts:
        ram_opts = [UNKNOWN]
    if not storage_opts:
        storage_opts = [UNKNOWN]
    ram_matrix = ",".join(ram_opts)
    storage_matrix = ",".join(storage_opts)
    arch = _architecture(identity_text)
    drafts: list[ObservationDraft] = []
    for ram in ram_opts:
        for storage in storage_opts:
            for wireless in wireless_opts:
                spec = NormalizedSpec(
                    soc=soc_name,
                    soc_key=f"{slugify(soc_vendor)}:{slugify(soc_name)}",
                    cpu_arch=arch.value,
                    ram_type=ram_type,
                    ram_options=ram_matrix,
                    onboard_emmc="yes" if any("eMMC" in s or s.endswith("GB") or s.endswith("G") for s in storage_opts if s != UNKNOWN) else UNKNOWN,
                    emmc_options=storage_matrix,
                    microsd="yes" if re.search(r"Micro ?SD|TF card|SD card", f"{identity_text} {body_text}", re.I) else UNKNOWN,
                    ethernet="2.5g" if "2.5G" in body_text or "2.5G" in identity_text else ("gigabit" if re.search(r"GbE|Gigabit", f"{identity_text} {body_text}", re.I) else ("100m" if "100M Ethernet" in body_text else UNKNOWN)),
                    wifi=_WIFI_LEVEL_RE.search(f"{identity_text} {body_text}").group(0).replace(" ", "").lower() if _WIFI_LEVEL_RE.search(f"{identity_text} {body_text}") else ("wifi" if _WIFI_GENERIC_RE.search(f"{identity_text} {body_text}") else UNKNOWN),
                    bluetooth="present" if re.search(r"BT[0-9]|Bluetooth", f"{identity_text} {body_text}", re.I) else UNKNOWN,
                    hdmi_out="hdmi" if re.search(r"HDMI", f"{identity_text} {body_text}", re.I) else UNKNOWN,
                    usb="usb3" if re.search(r"USB ?3", f"{identity_text} {body_text}", re.I) else ("usb" if "USB" in body_text else UNKNOWN),
                    gpio_header="40-pin" if re.search(r"40[- ]Pin|40-pin", f"{identity_text} {body_text}", re.I) else UNKNOWN,
                    pcb_revision=UNKNOWN,
                )
                drafts.append(
                    ObservationDraft(
                        source_key=SOURCE_KEY,
                        plane=SourcePlane.PRODUCT,
                        observed_at=observed_at,
                        vendor_key=VENDOR_KEY,
                        vendor_name=VENDOR_NAME,
                        family_slug=family_slug,
                        family_name=family_slug,
                        board_slug=board_slug,
                        marketing_name=model,
                        board_type=board_type,
                        revision_kind=RevisionKind.UNKNOWN,
                        revision_token=UNKNOWN,
                        variant=VariantDimensions(ram=ram, storage=storage, wireless=wireless),
                        soc_vendor=soc_vendor,
                        soc_marketing_name=soc_name,
                        architecture=arch,
                        spec=spec,
                        raw_fields={
                            "category": category,
                            "ram_options": ram_opts,
                            "storage_options": storage_opts,
                            "title_head": title_head,
                        },
                        native_fields={"heading": model, "page_url": page_url},
                        availability=Availability.UNKNOWN,
                        novelty=NoveltyEvidence(
                            first_seen_at=observed_at, first_seen_source=SOURCE_KEY,
                            novelty_status=NoveltyStatus.HISTORICAL if historical_known else NoveltyStatus.EXISTING_PRODUCT,
                            novelty_basis="official-product-catalogue",
                            novelty_confidence="high",
                        ),
                        editorial_context=_editorial(identity_text, board_type, soc_name),
                        page_url=page_url,
                        historical_known=historical_known,
                    )
                )
    diagnostics["status"] = "resolved"
    diagnostics["observation_count"] = len(drafts)
    diagnostics["board_slug"] = board_slug
    return drafts, diagnostics


def load_corpus_manifest(corpus_dir: Path | None = None) -> dict[str, Any]:
    root = corpus_dir or CORPUS_DIR
    path = root / "manifest.json"
    if not path.exists():
        raise CollectorError(f"banana pi fixture corpus missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


_REPO_CORPUS = Path(__file__).resolve().parents[3] / "fixtures" / "banana_pi_product"
_PACKAGED_CORPUS = Path(__file__).resolve().parents[1] / "fixture_data" / "banana_pi_product"
CORPUS_DIR = _REPO_CORPUS if (_REPO_CORPUS / "manifest.json").exists() else _PACKAGED_CORPUS


def collect_corpus(name: str, *, run_id: str, started_at: str, corpus_dir: Path | None = None) -> CollectorRunRequest:
    root = corpus_dir or CORPUS_DIR
    manifest = load_corpus_manifest(corpus_dir)
    corpora = manifest.get("corpora") or {}
    if name not in corpora:
        raise CollectorError(f"unknown banana pi corpus: {name}")
    observations: list[ObservationDraft] = []
    diagnostics: dict[str, Any] = {
        "corpus": name, "documents": [], "candidate_references": 0, "resolved": 0,
        "insufficient": 0, "conflicts": 0, "parser_errors": [], "leads": [],
    }
    ok = True
    error: str | None = None
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
            observations.extend(drafts)
        elif info.get("status") == "insufficient-evidence":
            diagnostics["insufficient"] += 1
            observations.extend(drafts)
        elif info.get("status") == "identity-conflict":
            diagnostics["conflicts"] += 1
            observations.extend(drafts)
    if name == "malformed" and not observations:
        ok = False
        error = error or "banana-pi product parser failed: missing required product fields"
    return CollectorRunRequest(
        run_id=run_id, source_key=SOURCE_KEY, collector_key=COLLECTOR_KEY,
        started_at=started_at, observations=observations, ok=ok, error=error,
        fixture_scenario=f"bpi:{name}", diagnostics=diagnostics,
    )


def _assert_official_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise CollectorError(f"refusing non-https banana pi url: {url}")
    if parsed.netloc not in OFFICIAL_HOSTS:
        raise CollectorError(f"refusing third-party or docs url: {url}")
    parts = [seg for seg in parsed.path.split("/") if seg]
    is_index = (
        len(parts) == 2
        and parts[0] == "en"
        and parts[1] in _BOARD_CATEGORIES
    ) or parsed.path.rstrip("/") in ("", "/en")
    if not is_index and not _is_product_page_url(url):
        raise CollectorError(f"refusing non-product banana pi url: {url}")
    if not is_index and not _is_board_category(_category_of(url)):
        raise CollectorError(f"refusing non-board catalogue category: {url}")
    return url


def fetch_official(url: str, *, timeout: int = 30) -> str:
    return fetch_official_meta(url, timeout=timeout)["text"]


def fetch_official_meta(url: str, *, timeout: int = 30) -> dict[str, Any]:
    _assert_official_url(url)
    request = Request(
        url,
        headers={"User-Agent": "board-clank/0.1.0 (+experimental-manual-banana-pi-product)"},
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


class BananaPiProductAdapter(CollectorAdapter):
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
            page_url=payload.get("page_url") or SBC_INDEX_URL,
            observed_at=payload.get("observed_at") or "1970-01-01T00:00:00+00:00",
            historical_known=bool(payload.get("historical_known")),
        )
        return drafts

    def _collect_live(self, run_id: str, started_at: str) -> CollectorRunRequest:
        """Live path: SBC + router category indexes -> board product pages.

        banana-pi.org only; wiki/docs/forums are never fetched. Opaque
        numbered URLs mean identity comes from each page's own title."""
        diagnostics: dict[str, Any] = {
            "mode": "experimental-live-bpi",
            "primary_surface": SBC_INDEX_URL,
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
            leads: list[str] = []
            for index_url in (SBC_INDEX_URL, ROUTER_INDEX_URL):
                meta = record_fetch(index_url)
                _drafts, info = parse_product_html(meta["text"], page_url=index_url, observed_at=started_at)
                info["raw_body_hash"] = meta["raw_body_hash"]
                info["semantic_evidence_hash"] = meta["semantic_evidence_hash"]
                diagnostics["documents"].append(info)
                leads.extend(info.get("lead_hrefs") or [])
                for href in _all_hrefs(meta["text"], index_url):
                    if href in (info.get("lead_hrefs") or []):
                        continue
                    parsed = urlparse(href)
                    if parsed.netloc in OFFICIAL_HOSTS and parsed.path.startswith(EN_PREFIX):
                        diagnostics["rejected"].append({"url": href, "reason": "non-board-category-or-anchor"})
            leads = sorted(set(leads))
            diagnostics["leads"] = leads
            diagnostics["candidate_references"] = len(leads)

            for url in leads:
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
                    observations.extend(drafts)
                elif page_info.get("status") == "identity-conflict":
                    diagnostics["conflicts"] = diagnostics.get("conflicts", 0) + 1
                    observations.extend(drafts)
                elif page_info.get("status") == "insufficient-evidence":
                    diagnostics["insufficient"] = diagnostics.get("insufficient", 0) + 1
                    observations.extend(drafts)

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
