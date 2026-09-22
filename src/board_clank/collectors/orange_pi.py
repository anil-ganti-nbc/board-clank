"""Orange Pi PRODUCT adapter.

Foundation 2A: second vendor, second live-capable source adapter. Default
path is offline fixtures. Network fetch is opt-in, manual, experimental, and
never required for tests. The product index is a lead surface; product
detail pages carry identity/spec tables.

First-party surface notes (observed 2026-09-22):
- The official English catalogue is HTTP-only (TLS is not served); the
  allowlist therefore admits http for this host specifically.
- ``www.orangepi.org`` is canonical. ``www.orangepi.cn`` is a regional
  mirror with duplicated identities and is NOT fetched.
- Detail pages expose explicit parameter tables: an SoC/Master Chip row,
  companion silicon in labelled PMU / Wi-Fi / Ethernet / audio rows, RAM
  matrices, and pin-definition headings that name hardware revisions.
- Some boards are split across storefront pages per configuration
  (``Orange-Pi-5-32GB.html``) or per bundle (``-With-Metal-Case``). Those
  pages are variant evidence for the same board, never new boards.
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

SOURCE_KEY = "orange-pi-product"
VENDOR_KEY = "orange-pi"
VENDOR_NAME = "Orange Pi"
COLLECTOR_KEY = "orange-pi-product"
OFFICIAL_HOSTS = frozenset({"www.orangepi.org", "orangepi.org"})
HARDWARE_PATH = "/html/hardWare/computerAndMicrocontrollers"
DETAILS_PREFIX = f"{HARDWARE_PATH}/details/"
INDEX_URL = f"http://www.orangepi.org{HARDWARE_PATH}/index.html"

_REPO_CORPUS = Path(__file__).resolve().parents[3] / "fixtures" / "orange_pi_product"
_PACKAGED_CORPUS = Path(__file__).resolve().parents[1] / "fixture_data" / "orange_pi_product"
CORPUS_DIR = _REPO_CORPUS if (_REPO_CORPUS / "manifest.json").exists() else _PACKAGED_CORPUS

# Storefront filenames that are per-configuration or per-bundle pages of the
# board named by their base filename. Evidence-only suffixes, never identity.
_STOREFRONT_SUFFIX_RE = re.compile(r"(?:-32gb|-with-metal-case)$", re.I)

_NAME_RE = re.compile(r"^orange\s*pi\b", re.I)
_KEYBOARD_COMPUTER_RE = re.compile(r"\b800\b")
_ACCESSORY_HINTS = (
    "camera",
    "cooling fan",
    "fan",
    "heat sink",
    "heatsink",
    "expansion board",
    "base board",
    "tablet board",
    "shell",
    "power supply",
    "cable",
    "monitor",
    "touch screen",
    "antenna",
    "sensor",
    "converter",
    "mouse",
    "keyboard",
    "jig",
    "rtc",
    "emmc module",
)
_MODULE_HINTS = ("wi-fi", "wifi", "bt5", "bluetooth")
_OS_ROW_KEYS = ("supported os", "os support", "os")
_PMU_ROW_KEYS = ("pmu", "power management", "pmic")
_WIFI_ROW_KEYS = ("wi-fi", "wifi", "wireless")

# Companion silicon families seen on first-party pages. These tokens never
# identify the application processor, whatever row they appear in.
_NON_SOC_MODEL_RE = re.compile(
    r"^(?:RK80[0-9](?:-[0-9])?|AP[0-9]{4}|20U[0-9]{4}|YT[0-9]{4}[A-Z]?|RTL[0-9]{4,5}"
    r"|ES[0-9]{4}|AXP[0-9]{3}[A-Z]?|Mali[- ]|BCM43[0-9]{3}|CYW[0-9]+)",
    re.I,
)
_CPU_TOKEN_EXCLUDE = re.compile(
    r"^(?:cortex|arm|quad|octa|dual|hexa|single|big|little|core|processor|mali|lpddr|ddr|"
    r"android|ubuntu|debian|openwrt|ghz|mhz|up|to|and|x|with|a|the)",
    re.I,
)
_KNOWN_SOC_VENDORS = (
    "rockchip",
    "allwinner",
    "cixin",
    "cix",
    "amlogic",
    "mediatek",
    "samsung",
    "ascend",
    "broadcom",
    "ky",
)
_MODEL_TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*[0-9][A-Za-z0-9-]*$")
_RAM_OPTION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(GB|MB)\b", re.I)
_RAM_TYPE_RE = re.compile(r"(LPDDR5X|LPDDR5|LPDDR4X|LPDDR4|LPDDR3|LPDDR2|DDR4|DDR3)\b", re.I)
_REV_HEADING_RE = re.compile(r"\bv\s?(\d+(?:\.\d+)?)\s+pin definition", re.I)
_PIN_RE_HEADING_RE = re.compile(r"pin definition", re.I)

_FULLWIDTH = {"（": "(", "）": ")", "：": ":", "、": ",", "，": ",", "；": ";", "　": " "}


def _ascii(text: str) -> str:
    for src, dst in _FULLWIDTH.items():
        text = text.replace(src, dst)
    return text


class _PageParser(HTMLParser):
    """Capture h3 headings, paragraphs, links, and specification table rows."""

    def __init__(self) -> None:
        super().__init__()
        self.h3s: list[str] = []
        self.paragraphs: list[str] = []
        self.hrefs: list[str] = []
        self.tables: list[list[list[str]]] = []
        self._cell_buf: list[str] = []
        self._row: list[str] | None = None
        self._table: list[list[str]] | None = None
        self._capture: str | None = None
        self._buf = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)
        if tag in {"h3", "p"}:
            self._capture = tag
            self._buf = ""
        elif tag == "table":
            self._table = []
        elif tag in {"tr"} and self._table is not None:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell_buf = []
            self._capture = "cell"

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h3", "p"} and self._capture == tag:
            text = re.sub(r"\s+", " ", _ascii(self._buf)).strip()
            if text:
                if tag == "h3":
                    self.h3s.append(text)
                else:
                    self.paragraphs.append(text)
            self._capture = None
            self._buf = ""
        elif tag in {"td", "th"} and self._capture == "cell":
            if self._row is not None:
                text = re.sub(r"\s+", " ", _ascii("".join(self._cell_buf))).strip()
                self._row.append(text)
            self._cell_buf = []
            self._capture = None
        elif tag == "tr" and self._row is not None:
            if any(cell for cell in self._row):
                self._table.append(self._row)  # type: ignore[union-attr]
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None

    def handle_data(self, data: str) -> None:
        if self._capture == "cell":
            self._cell_buf.append(data)
        elif self._capture in {"h3", "p"}:
            self._buf += data

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br" and self._capture == "cell":
            self._cell_buf.append(" ")


def _spec_rows(tables: list[list[list[str]]]) -> list[tuple[str, str]]:
    """Flatten table rows into (label, value) pairs.

    Grouped template rows carry a rowspan section header (``SOC``) followed by
    a label cell (``Master Chip``); those become ``soc|master chip`` keys.
    """
    rows: list[tuple[str, str]] = []
    for table in tables:
        for cells in table:
            if not cells:
                continue
            if len(cells) >= 3 and cells[0].strip().upper() == "SOC":
                key = f"soc|{cells[1].strip().lower()}"
                value = " ".join(c for c in cells[2:] if c)
            elif len(cells) >= 2:
                key = cells[0].strip().lower()
                value = " ".join(c for c in cells[1:] if c)
            else:
                continue
            if key and value:
                rows.append((key, value))
    return rows


def _row_value(rows: list[tuple[str, str]], *keys: str, contains: tuple[str, ...] = ()) -> str | None:
    for key, value in rows:
        if key in keys:
            return value
        if contains and any(token in key for token in contains):
            return value
    return None


def _product_name(h3s: list[str]) -> str:
    for heading in h3s:
        if heading.startswith("请"):
            continue
        if "pin definition" in heading.lower():
            continue
        if _NAME_RE.match(_ascii(heading)):
            return _ascii(heading)
    return ""


_BUNDLE_PAREN_RE = re.compile(r"\s*\(\s*with\s+([^)]+)\)\s*$", re.I)
_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")


def _normalize_name(raw: str) -> tuple[str, str]:
    """Return (clean name, bundle token). Strips storefront parentheticals.

    - "(With Metal Case)" is bundle evidence, not identity.
    - "(4GB/8GB/16GB)" / "(32GB)" are configuration storefronts, not identity.
    - "OrangePi" and "Zero3" spacing variants normalise onto one slug space.
    """
    text = _ascii(raw)
    text = re.sub(r"\s+", " ", text).strip()
    bundle = UNKNOWN
    match = _BUNDLE_PAREN_RE.search(text)
    if match:
        bundle = slugify(f"with {match.group(1)}")
        text = _BUNDLE_PAREN_RE.sub("", text)
    else:
        text = _PAREN_RE.sub("", text)
    text = re.sub(r"\bOrangePi\b", "Orange Pi", text)
    # "Zero3" glues a generation digit onto the Zero line; split it so the
    # slug matches the spaced form. R1/R2S/CM4-style codes must stay glued.
    text = re.sub(r"(?<=zero)(?=\d)", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    return text, bundle


def _board_slug(name: str) -> str:
    return slugify(name)


def _is_keyboard_computer(name: str) -> bool:
    """Orange Pi 800 is an integrated keyboard computer, not SBC inventory."""
    return bool(_KEYBOARD_COMPUTER_RE.search(name))


def _is_accessory_name(name: str) -> bool:
    lowered = name.lower()
    if any(hint in lowered for hint in _ACCESSORY_HINTS):
        return True
    if lowered.endswith("module") and any(hint in lowered for hint in _MODULE_HINTS):
        return True
    return False


def _is_board_name(name: str) -> bool:
    return bool(_NAME_RE.match(name))


def _family_and_type(name: str) -> tuple[str, str, BoardType]:
    """Durable family from the official marketing name.

    - Compute Modules share ``compute-module``.
    - Zero-class boards share ``orange-pi-zero`` across SoC generations.
    - Router boards (R1/R2/R6) share ``router``.
    - Numeric generations use ``orange-pi-{N}``: 5, 5 Plus, 5 Pro, 5 Max,
      5 Ultra, 5B all share ``orange-pi-5`` while staying distinct boards.
    - Everything else keeps a one-board family rather than inventing a series.
    """
    lowered = name.lower()
    if "compute module" in lowered or re.search(r"\bcm\s?\d", lowered):
        return "compute-module", "Compute Module", BoardType.COMPUTE_MODULE
    if re.search(r"\bzero\b", lowered):
        return "orange-pi-zero", "Orange Pi Zero", BoardType.ZERO_CLASS
    if re.search(r"\br1\b|\br2\b|\br2s\b|\br6\b", lowered):
        return "router", "Router", BoardType.ROUTER_BOARD
    if re.search(r"\brv\b|\brv2\b", lowered):
        return "rv", "RV", BoardType.SBC
    if "aipro" in lowered or "ai station" in lowered or re.search(r"\borange pi ai\b", lowered):
        return "ai", "AI", BoardType.AI_SBC
    gen = re.search(r"orange pi (\d+)", lowered)
    if gen:
        number = gen.group(1)
        return f"orange-pi-{number}", f"Orange Pi {number}", BoardType.SBC
    return slugify(name), name, BoardType.UNKNOWN


def _editorial(name: str, board_type: BoardType, soc_marketing_name: str) -> list[str]:
    ctx: list[str] = []
    if soc_marketing_name.startswith("RK3588") or soc_marketing_name.startswith("CD8180"):
        ctx.append(EditorialContext.HIGH_END_ARM.value)
    if board_type is BoardType.COMPUTE_MODULE:
        ctx.append(EditorialContext.INDUSTRIAL.value)
    return ctx


def _soc_candidates_from_value(value: str) -> list[tuple[str, str]]:
    """Extract (vendor, model) application-processor pairs from one cell."""
    text = _ascii(value)
    # Tokenize loosely, splitting glued "RockchipRK3566" style too.
    tokens: list[str] = []
    for raw in re.split(r"[\s,;(/]+", text):
        token = raw.strip("()·.").strip()
        if not token:
            continue
        tokens.append(token)
    found: list[tuple[str, str]] = []
    vendor = UNKNOWN
    for token in tokens:
        if token.lower() in _KNOWN_SOC_VENDORS:
            vendor = token.lower()
            continue
        # Glued vendor+model ("RockchipRK3566"): strip a leading known vendor.
        glued_vendor = next((v for v in _KNOWN_SOC_VENDORS if token.lower().startswith(v) and len(token) > len(v)), None)
        if glued_vendor:
            vendor = glued_vendor
            token = token[len(glued_vendor):]
        if not _MODEL_TOKEN_RE.match(token) or _NON_SOC_MODEL_RE.match(token):
            continue
        if _CPU_TOKEN_EXCLUDE.match(token):
            continue
        if (vendor, token.upper()) not in found:
            found.append((vendor, token.upper()))
    return found


def _extract_soc(rows: list[tuple[str, str]]) -> tuple[str, str, list[str]]:
    """Resolve the application processor from labelled table rows only.

    PMU / Wi-Fi / Ethernet / audio rows are never consulted, so companion
    silicon (RK806-1 PMIC, AP6256 radio, YT8531C PHY, ES8388 codec, AXP313A)
    cannot become the SoC even though they share vendor prefixes.
    """
    candidates: list[tuple[str, str]] = []
    soc_value = _row_value(rows, "soc", "soc|master chip", "soc|chip", "processor", "master chip")
    if soc_value:
        candidates = _soc_candidates_from_value(soc_value)
    if not candidates:
        cpu_value = _row_value(rows, "cpu")
        if cpu_value:
            candidates = _soc_candidates_from_value(cpu_value)
    if not candidates:
        return UNKNOWN, UNKNOWN, []
    if len(candidates) > 1:
        return "CONFLICT", ",".join(model for _vendor, model in candidates), [model for _v, model in candidates]
    vendor, model = candidates[0]
    if vendor == UNKNOWN:
        prefix_match = next((v for v in ("rockchip", "allwinner", "cix") if model.lower().startswith(v)), None)
        vendor = prefix_match or UNKNOWN
    return vendor, model, [model]


def _ram_evidence(rows: list[tuple[str, str]], paragraphs: list[str]) -> tuple[str, list[str]]:
    """Return (ram_type, options). RAM row wins; Memory row only when it
    declares DDR memory; prose only when no table row does."""
    ram_row = _row_value(rows, "ram")
    memory_row = _row_value(rows, "memory")
    blob = ""
    if ram_row:
        blob = ram_row
    elif memory_row and re.search(r"LPDDR|DDR[234]", memory_row, re.I):
        blob = memory_row
    else:
        prose = " ".join(p for p in paragraphs if re.search(r"LPDDR|DDR[234]|\bRAM\b", p, re.I))
        blob = prose
    if not blob:
        return UNKNOWN, []
    type_match = _RAM_TYPE_RE.search(blob)
    options: list[str] = []
    for amount, unit in _RAM_OPTION_RE.findall(blob):
        label = f"{amount}{unit.upper()}"
        if amount == "0":
            continue
        if unit.upper() == "GB" and float(amount) > 128:
            continue
        if label not in options:
            options.append(label)
    if "512MB" in blob.upper() and "512MB" not in options:
        options = ["512MB"] + [o for o in options if o != "512GB"]
    return (type_match.group(1).upper() if type_match else UNKNOWN), options


def _storage_options(rows: list[tuple[str, str]]) -> list[str]:
    memory_row = _row_value(rows, "memory") or ""
    storage_row = _row_value(rows, "on-board storage", "storage", "emmc") or ""
    blob = f"{memory_row} {storage_row}"
    if "emmc" not in blob.lower():
        return []
    options: list[str] = []
    socketed = bool(re.search(r"socket|module|optional|customizable|support", blob, re.I))
    for amount, unit in _RAM_OPTION_RE.findall(blob):
        if unit.upper() != "GB" or amount == "0":
            continue
        label = f"{amount}GB"
        if float(amount) > 512:
            continue
        if label not in options:
            options.append(label)
    if not options:
        return ["none", "module"] if socketed else []
    return (["none"] + options) if socketed else options


def _wireless_options(rows: list[tuple[str, str]]) -> list[str]:
    wifi_row = _row_value(rows, *(), contains=_WIFI_ROW_KEYS)
    if not wifi_row:
        return [UNKNOWN]
    lowered = wifi_row.lower()
    has_radio = "wi-fi" in lowered or "wifi" in lowered or "bluetooth" in lowered
    optional = bool(re.search(r"optional|expandable|supports?\s+.*module", lowered))
    if not has_radio:
        return [UNKNOWN]
    return ["none", "wifi"] if optional else ["wifi"]


def _revision_token(h3s: list[str]) -> tuple[RevisionKind, str]:
    for heading in h3s:
        if _PIN_RE_HEADING_RE.search(heading):
            match = _REV_HEADING_RE.search(heading)
            if match:
                return RevisionKind.PCB, match.group(1)
    return RevisionKind.UNKNOWN, UNKNOWN


def _os_names(rows: list[tuple[str, str]]) -> list[str]:
    value = _row_value(rows, *_OS_ROW_KEYS) or ""
    names: set[str] = set()
    for token in re.split(r"[,;/]+", value):
        token = token.strip().lower()
        if "orangepi os" in token or "orange pi os" in token:
            names.add("orange-pi-os")
        elif "ubuntu" in token:
            names.add("ubuntu")
        elif "debian" in token:
            names.add("debian")
        elif "android" in token:
            names.add("android")
        elif "openwrt" in token:
            names.add("openwrt")
        elif "manjaro" in token:
            names.add("manjaro")
    return sorted(names)


def _first_match(blob: str, patterns: list[tuple[str, str]]) -> str:
    lowered = blob.lower()
    for needle, value in patterns:
        if needle in lowered:
            return value
    return UNKNOWN


def _architecture(rows: list[tuple[str, str]]) -> Architecture:
    blob = " ".join(value for _key, value in rows).lower()
    if "risc-v" in blob or "riscv" in blob:
        return Architecture.RISCV
    if "cortex" in blob or "arm" in blob:
        return Architecture.ARM
    return Architecture.UNKNOWN


def _build_spec(
    rows: list[tuple[str, str]],
    paragraphs: list[str],
    *,
    soc_vendor: str,
    soc_name: str,
    ram_type: str,
    ram_matrix: str,
    storage_matrix: str,
) -> NormalizedSpec:
    blob = _ascii(" ".join(value for _key, value in rows) + " " + " ".join(paragraphs))
    if soc_name in {UNKNOWN, "CONFLICT"}:
        key = UNKNOWN
    else:
        key = f"{slugify(soc_vendor)}:{slugify(soc_name)}"
    cpu_value = _row_value(rows, "cpu") or ""
    gpu_match = re.search(r"(Mali[- ][A-Za-z0-9]{2,10})", blob, re.I)
    npu_row = _row_value(rows, "npu")
    npu_tops = UNKNOWN
    if npu_row:
        tops = re.search(r"([\d.]+)\s*TOPS", npu_row, re.I)
        npu_tops = tops.group(1) if tops else UNKNOWN
    ethernet_row = _row_value(rows, "ethernet", "network") or ""
    wifi_row = _row_value(rows, *(), contains=_WIFI_ROW_KEYS) or ""
    video_row = _row_value(rows, "video output", "video") or ""
    usb_row = _row_value(rows, "usb") or ""
    expansion_row = _row_value(rows, "expansion port", "expansion interface", "interface") or ""
    pcb_row = _row_value(rows, "pcb", "dimension") or ""
    dims = UNKNOWN
    dim_match = re.search(r"(\d+(?:\.\d+)?)\s*mm\s*[*x×]\s*(\d+(?:\.\d+)?)\s*mm", pcb_row, re.I)
    if dim_match:
        dims = f"{dim_match.group(1)}x{dim_match.group(2)}mm"
    return NormalizedSpec(
        soc=soc_name,
        soc_key=key,
        cpu_arch=_architecture(rows).value,
        cpu_configuration=_first_match(cpu_value, [("cortex-a76", "Cortex-A76 + Cortex-A55"), ("cortex-a55", "Cortex-A55"), ("cortex-a53", "Cortex-A53")]) if cpu_value else UNKNOWN,
        gpu=gpu_match.group(1) if gpu_match else UNKNOWN,
        npu="yes" if npu_row else UNKNOWN,
        npu_tops=npu_tops,
        ram_type=ram_type,
        ram_options=ram_matrix,
        onboard_emmc="optional" if re.search(r"emmc", blob, re.I) else UNKNOWN,
        emmc_options=storage_matrix if re.search(r"emmc", blob, re.I) else UNKNOWN,
        microsd="yes" if "microsd" in blob.lower() or "tf card" in blob.lower() or "tf slot" in blob.lower() else UNKNOWN,
        m2_m_key="yes" if "m.2 m-key" in blob.lower() or "m.2 m key" in blob.lower() else UNKNOWN,
        ethernet=_first_match(ethernet_row, [("2xpcie", "2x 2.5g"), ("2.5g", "2.5g"), ("10/100/1000", "gigabit"), ("1000m", "gigabit"), ("gigabit", "gigabit"), ("10/100", "100m"), ("10m/100m", "100m")]),
        wifi=_first_match(wifi_row, [("wi-fi 6e", "wifi6e"), ("wi-fi6", "wifi6"), ("wi-fi 6", "wifi6"), ("wifi6", "wifi6"), ("wi-fi 5", "wifi5"), ("wi-fi5", "wifi5"), ("wifi5", "wifi5"), ("wi-fi", "wifi"), ("wifi", "wifi")]),
        bluetooth=_first_match(wifi_row, [("bt 5.3", "5.3"), ("bt 5.0", "5.0"), ("bluetooth 5.0", "5.0"), ("bt", "present"), ("bluetooth", "present")]),
        hdmi_out=_first_match(video_row, [("micro hdmi", "micro-hdmi"), ("mini hdmi", "mini-hdmi"), ("hdmi2.1", "hdmi2.1"), ("hdmi 2.1", "hdmi2.1"), ("hdmi2.0", "hdmi2.0"), ("hdmi 2.0", "hdmi2.0"), ("hdmi", "hdmi")]),
        mipi_dsi="yes" if "dsi" in blob.lower() else UNKNOWN,
        mipi_csi="yes" if "csi" in blob.lower() or "camera" in blob.lower() else UNKNOWN,
        usb=_first_match(usb_row, [("usb3", "usb3"), ("usb 3", "usb3"), ("usb2", "usb2"), ("usb 2", "usb2"), ("usb", "usb")]),
        gpio_header=_first_match(expansion_row, [("40pin", "40-pin"), ("26pin", "26-pin"), ("13pin", "13-pin")]),
        pcie_lanes="x1" if "pcie" in blob.lower() else UNKNOWN,
        dimensions=dims,
        pcb_revision=UNKNOWN,
    )


_VOLATILE_HTML = (
    re.compile(r"<meta[^>]*csrf-token[^>]*>", re.I),
    re.compile(r'name="authenticity_token"[^>]*value="[^"]*"', re.I),
    re.compile(r'\bnonce="[^"]+"', re.I),
)


def semantic_html(html: str) -> str:
    """Drop transport-volatile tokens before hashing. The Orange Pi catalogue
    is a static Apache host; only nonce-style noise is stripped defensively."""
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


def _classify_path(parsed_url) -> str:
    path = parsed_url.path.rstrip("/").lower()
    hardware = HARDWARE_PATH.lower()
    if path in {"", "/"} or path == hardware or path in {f"{hardware}/index", f"{hardware}/index.html"}:
        return "lead-index"
    if path.startswith(f"{hardware}/details/"):
        return "product"
    return "unknown-surface"


def _is_in_scope_details_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc not in OFFICIAL_HOSTS:
        return False
    if not parsed.path.lower().startswith(DETAILS_PREFIX.lower()):
        return False
    filename = parsed.path.rsplit("/", 1)[-1].lower()
    if not filename.startswith(("orange-pi-", "orangepi-", "orange_pi_")):
        return False
    blocked = ("heat-sink", "cooling-fan", "-camera", "camera-", "expansion-board", "touch-screen", "monitor")
    return not any(token in filename for token in blocked)


def _detail_leads(href_list: list[str], base_url: str) -> list[str]:
    leads: list[str] = []
    for href in href_list:
        abs_url = urljoin(base_url, href).split("#")[0]
        if _is_in_scope_details_url(abs_url):
            leads.append(abs_url)
    return sorted(set(leads))


def parse_product_html(html: str, *, page_url: str, observed_at: str, historical_known: bool = False) -> tuple[list[ObservationDraft], dict[str, Any]]:
    """Parse one official Orange Pi product-surface HTML document.

    Returns drafts plus diagnostics. Never invents SoC, revision, or dates
    the document does not contain. Storefront configuration pages are
    normalized at the corpus level, not here.
    """
    parser = _PageParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # noqa: BLE001 - parser failure must be observable
        raise CollectorError(f"html parse failed for {page_url}: {exc}") from exc

    diagnostics: dict[str, Any] = {
        "page_url": page_url,
        "heading": UNKNOWN,
        "lead_hrefs": [],
        "status": "ok",
    }
    parsed_url = urlparse(page_url)
    if parsed_url.netloc in OFFICIAL_HOSTS:
        surface = _classify_path(parsed_url)
        if surface == "lead-index":
            leads = _detail_leads(parser.hrefs, page_url)
            diagnostics["lead_hrefs"] = leads
            diagnostics["status"] = "lead-index"
            diagnostics["evidence_roles"] = ["DISCOVERY"]
            return [], diagnostics
        if surface == "unknown-surface":
            diagnostics["status"] = "ignored-unknown-surface"
            return [], diagnostics

    raw_name = _product_name(parser.h3s)
    diagnostics["heading"] = raw_name or UNKNOWN
    if not raw_name:
        diagnostics["status"] = "ignored-non-computer"
        diagnostics["scope"] = "NON_BOARD_CATALOGUE_ITEM"
        return [], diagnostics
    name, bundle = _normalize_name(raw_name)

    if _is_keyboard_computer(name):
        diagnostics["status"] = "ignored-non-computer"
        diagnostics["scope"] = "NON_BOARD_CATALOGUE_ITEM"
        diagnostics["reason"] = "integrated-consumer-computer-out-of-sbc-scope"
        return [], diagnostics
    if _is_accessory_name(name):
        diagnostics["status"] = "ignored-non-computer"
        diagnostics["scope"] = "NON_BOARD_CATALOGUE_ITEM"
        diagnostics["reason"] = "accessory-or-carrier-item"
        return [], diagnostics
    if not _is_board_name(name):
        diagnostics["status"] = "ignored-non-computer"
        diagnostics["scope"] = "NON_BOARD_CATALOGUE_ITEM"
        return [], diagnostics

    rows = _spec_rows(parser.tables)
    board_slug = _board_slug(name)
    family_slug, family_name, board_type = _family_and_type(name)
    soc_vendor, soc_name, soc_candidates = _extract_soc(rows)
    ram_type, ram_opts = _ram_evidence(rows, parser.paragraphs)
    storage_opts = _storage_options(rows)
    wireless_opts = _wireless_options(rows)
    rev_kind, rev_token = _revision_token(parser.h3s)
    conflict = soc_vendor == "CONFLICT"
    has_spec_table = bool(rows)

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
            family_name=family_name,
            board_slug=board_slug,
            marketing_name=name,
            board_type=board_type,
            soc_vendor=UNKNOWN,
            soc_marketing_name=UNKNOWN,
            architecture=_architecture(rows),
            spec=NormalizedSpec(),
            raw_fields={"soc_candidates": soc_candidates, "spec_rows": rows},
            native_fields={"heading": name, "conflicting_socs": soc_name},
            novelty=NoveltyEvidence(
                first_seen_at=observed_at,
                first_seen_source=SOURCE_KEY,
                novelty_status=NoveltyStatus.UNKNOWN,
                novelty_basis="conflicting-soc-evidence",
                novelty_confidence="low",
            ),
            page_url=page_url,
            historical_known=historical_known,
            identity_conflict=True,
            identity_conflict_reason="multiple application processors named on one product page",
            evidence_insufficient=True,
        )
        return [draft], diagnostics

    if not has_spec_table or soc_name == UNKNOWN:
        identity_only = has_spec_table and _is_board_name(name)
        diagnostics["status"] = "resolved-identity" if identity_only else "insufficient-evidence"
        draft = ObservationDraft(
            source_key=SOURCE_KEY,
            plane=SourcePlane.PRODUCT,
            observed_at=observed_at,
            vendor_key=VENDOR_KEY,
            vendor_name=VENDOR_NAME,
            family_slug=family_slug,
            family_name=family_name,
            board_slug=board_slug,
            marketing_name=name,
            board_type=board_type,
            spec=NormalizedSpec(),
            raw_fields={"spec_rows": rows, "html_excerpt": html[:400]},
            native_fields={"heading": name, "page_url": page_url},
            novelty=NoveltyEvidence(
                first_seen_at=observed_at,
                first_seen_source=SOURCE_KEY,
                novelty_status=NoveltyStatus.UNKNOWN,
                novelty_basis="insufficient-first-party-specification",
                novelty_confidence="low" if not has_spec_table else "medium",
            ),
            page_url=page_url,
            historical_known=historical_known,
            evidence_insufficient=True,
        )
        if not has_spec_table:
            diagnostics["status"] = "insufficient-evidence"
        return [draft], diagnostics

    if not ram_opts:
        ram_opts = [UNKNOWN]
    if not storage_opts:
        storage_opts = [UNKNOWN]
    ram_matrix = ",".join(ram_opts)
    storage_matrix = ",".join(storage_opts)
    variants = [
        VariantDimensions(ram=ram, storage=storage, wireless=wireless, bundle=bundle)
        for ram in ram_opts
        for storage in storage_opts
        for wireless in wireless_opts
    ]
    drafts: list[ObservationDraft] = []
    for variant in variants:
        spec = _build_spec(
            rows,
            parser.paragraphs,
            soc_vendor=soc_vendor,
            soc_name=soc_name,
            ram_type=ram_type,
            ram_matrix=ram_matrix,
            storage_matrix=storage_matrix,
        )
        spec.pcb_revision = rev_token
        drafts.append(
            ObservationDraft(
                source_key=SOURCE_KEY,
                plane=SourcePlane.PRODUCT,
                observed_at=observed_at,
                vendor_key=VENDOR_KEY,
                vendor_name=VENDOR_NAME,
                family_slug=family_slug,
                family_name=family_name,
                board_slug=board_slug,
                marketing_name=name,
                board_type=board_type,
                revision_kind=rev_kind,
                revision_token=rev_token,
                variant=variant,
                soc_vendor=soc_vendor,
                soc_marketing_name=soc_name,
                architecture=_architecture(rows),
                cpu_configuration=spec.cpu_configuration,
                gpu=spec.gpu,
                npu=spec.npu,
                npu_tops=spec.npu_tops,
                spec=spec,
                raw_fields={"spec_rows": rows, "ram_options": ram_opts, "storage_options": storage_opts},
                native_fields={
                    "heading": name,
                    "page_url": page_url,
                },
                availability=Availability.UNKNOWN,
                novelty=NoveltyEvidence(
                    first_seen_at=observed_at,
                    first_seen_source=SOURCE_KEY,
                    novelty_status=NoveltyStatus.HISTORICAL if historical_known else NoveltyStatus.EXISTING_PRODUCT,
                    novelty_basis="official-product-catalogue",
                    novelty_confidence="high" if has_spec_table else "low",
                ),
                editorial_context=_editorial(name, board_type, soc_name),
                supported_os=_os_names(rows),
                page_url=page_url,
                historical_known=historical_known,
            )
        )
    diagnostics["status"] = "resolved"
    diagnostics["observation_count"] = len(drafts)
    diagnostics["board_slug"] = board_slug
    return drafts, diagnostics


def _canonical_page_url(url: str) -> str:
    """Map a per-configuration / per-bundle storefront URL onto the board's
    base product URL (e.g. ``Orange-Pi-5-32GB.html`` -> ``Orange-Pi-5.html``)."""
    parsed = urlparse(url)
    filename = parsed.path.rsplit("/", 1)[-1]
    stem = filename[:-5] if filename.lower().endswith(".html") else filename
    stripped = _STOREFRONT_SUFFIX_RE.sub("", stem)
    if stripped == stem:
        return url
    return url.replace(filename, stripped + ".html")


def _canonicalize_page_references(page_drafts: list[tuple[str, list[ObservationDraft]]]) -> None:
    """Storefront pages are variant evidence for the board's canonical page.

    When the base page was observed in the same run, board-scope references
    collapse onto it and the storefront draft adopts the canonical page's
    board-scope spec wholesale, so BOARD-level comparison sees one stable
    product identity. The storefront's own contribution stays where it
    belongs: VARIANT dimensions and raw reference evidence."""
    by_url: dict[str, tuple[str, list[ObservationDraft]]] = {}
    for url, drafts in page_drafts:
        by_url.setdefault(url.lower(), (url, drafts))
    for url, drafts in page_drafts:
        canonical = _canonical_page_url(url)
        target = by_url.get(canonical.lower())
        if target is None or canonical == url:
            continue
        base_url, base_drafts = target
        base_draft = base_drafts[0]
        base_spec = base_draft.spec.model_copy()
        base_supported_os = list(base_draft.supported_os)
        base_editorial = list(base_draft.editorial_context)
        for draft in drafts:
            references = list(draft.raw_fields.get("reference_urls") or [])
            if url not in references:
                references.append(url)
            draft.raw_fields["reference_urls"] = references
            draft.page_url = base_url
            draft.spec = base_spec
            draft.supported_os = base_supported_os
            draft.editorial_context = base_editorial
            draft.native_fields["page_url"] = base_draft.native_fields.get("page_url", base_url)
            draft.native_fields["heading"] = base_draft.native_fields.get("heading", draft.native_fields.get("heading"))


def load_corpus_manifest(corpus_dir: Path | None = None) -> dict[str, Any]:
    root = corpus_dir or CORPUS_DIR
    path = root / "manifest.json"
    if not path.exists():
        raise CollectorError(f"orange pi fixture corpus missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def collect_corpus(name: str, *, run_id: str, started_at: str, corpus_dir: Path | None = None) -> CollectorRunRequest:
    root = corpus_dir or CORPUS_DIR
    manifest = load_corpus_manifest(root)
    corpora = manifest.get("corpora") or {}
    if name not in corpora:
        raise CollectorError(f"unknown orange pi corpus: {name}")
    observations: list[ObservationDraft] = []
    diagnostics: dict[str, Any] = {
        "corpus": name,
        "documents": [],
        "candidate_references": 0,
        "resolved": 0,
        "insufficient": 0,
        "conflicts": 0,
        "parser_errors": [],
        "leads": [],
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
            drafts, info = parse_product_html(
                html,
                page_url=page_url,
                observed_at=observed_at,
                historical_known=historical,
            )
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
        error = error or "orange-pi product parser failed: missing required product fields"
    return CollectorRunRequest(
        run_id=run_id,
        source_key=SOURCE_KEY,
        collector_key=COLLECTOR_KEY,
        started_at=started_at,
        observations=observations,
        ok=ok,
        error=error,
        fixture_scenario=f"opi:{name}",
        diagnostics=diagnostics,
    )


def _assert_official_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise CollectorError(f"refusing non-http(s) orange pi url: {url}")
    # The official Orange Pi catalogue is served over plain HTTP only; the
    # host allowlist below is the security boundary, mirroring the HTTPS-only
    # rule of the Raspberry Pi adapter for that vendor's TLS-served site.
    if parsed.netloc not in OFFICIAL_HOSTS:
        raise CollectorError(f"refusing third-party or mirror url: {url}")
    surface = _classify_path(parsed)
    if surface not in {"lead-index", "product"}:
        raise CollectorError(f"refusing non-catalogue orange pi url: {url}")
    return url


def fetch_official(url: str, *, timeout: int = 25) -> str:
    return fetch_official_meta(url, timeout=timeout)["text"]


def fetch_official_meta(url: str, *, timeout: int = 25) -> dict[str, Any]:
    _assert_official_url(url)
    request = Request(
        url,
        headers={"User-Agent": "board-clank/0.1.0 (+experimental-manual-orange-pi-product)"},
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


class OrangePiProductAdapter(CollectorAdapter):
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
        page_url = payload.get("page_url") or INDEX_URL
        observed_at = payload.get("observed_at") or "1970-01-01T00:00:00+00:00"
        drafts, _info = parse_product_html(
            html,
            page_url=page_url,
            observed_at=observed_at,
            historical_known=bool(payload.get("historical_known")),
        )
        return drafts

    def _collect_live(self, run_id: str, started_at: str) -> CollectorRunRequest:
        """Live path: official English product index -> in-scope detail pages.

        Mirrors the vendor's catalogue split: ``orangepi.org`` only; the CN
        regional mirror, wiki, and commerce stores are never fetched."""
        diagnostics: dict[str, Any] = {
            "mode": "experimental-live-opi",
            "primary_surface": INDEX_URL,
            "documents": [],
            "fetches": [],
            "candidate_references": 0,
            "resolved": 0,
            "parser_errors": [],
            "leads": [],
            "rejected": [],
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
            meta = record_fetch(INDEX_URL)
            _drafts, info = parse_product_html(meta["text"], page_url=INDEX_URL, observed_at=started_at)
            info["raw_body_hash"] = meta["raw_body_hash"]
            info["semantic_evidence_hash"] = meta["semantic_evidence_hash"]
            diagnostics["documents"].append(info)
            in_scope = info.get("lead_hrefs") or []
            diagnostics["leads"] = in_scope
            diagnostics["candidate_references"] = len(in_scope)
            for href in parser_hrefs_all(meta["text"], INDEX_URL):
                if href in in_scope:
                    continue
                if urlparse(href).netloc in OFFICIAL_HOSTS and urlparse(href).path.lower().startswith(DETAILS_PREFIX):
                    diagnostics["rejected"].append({"url": href, "reason": "out-of-scope-or-accessory"})
                elif urlparse(href).netloc and urlparse(href).netloc not in OFFICIAL_HOSTS and "/details/" in href:
                    diagnostics["rejected"].append({"url": href, "reason": "mirror-or-third-party-host"})

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
                if page_info.get("status") in {"resolved", "resolved-identity"}:
                    diagnostics["resolved"] += 1
                    page_drafts.append((url, drafts))
                    observations.extend(drafts)
                elif page_info.get("status") == "identity-conflict":
                    diagnostics["conflicts"] = diagnostics.get("conflicts", 0) + 1
                    observations.extend(drafts)
                elif page_info.get("status") == "insufficient-evidence":
                    diagnostics["insufficient"] = diagnostics.get("insufficient", 0) + 1
                    observations.extend(drafts)
            _canonicalize_page_references(page_drafts)

            return CollectorRunRequest(
                run_id=run_id,
                source_key=SOURCE_KEY,
                collector_key=COLLECTOR_KEY,
                started_at=started_at,
                observations=observations,
                ok=True,
                fixture_scenario=None,
                diagnostics=diagnostics,
            )
        except Exception as exc:  # noqa: BLE001
            return CollectorRunRequest(
                run_id=run_id,
                source_key=SOURCE_KEY,
                collector_key=COLLECTOR_KEY,
                started_at=started_at,
                observations=observations,
                ok=bool(observations),
                error=None if observations else f"experimental live fetch failed: {exc}",
                diagnostics=diagnostics,
            )


def parser_hrefs_all(html: str, base_url: str) -> list[str]:
    parser = _PageParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - lead extraction is best effort
        return []
    seen: list[str] = []
    for href in parser.hrefs:
        abs_url = urljoin(base_url, href).split("#")[0]
        if abs_url not in seen:
            seen.append(abs_url)
    return seen
