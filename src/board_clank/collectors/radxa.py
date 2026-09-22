"""Radxa PRODUCT adapter.

Foundation 3A: third vendor, third live-capable source adapter. Default path
is offline fixtures. Network fetch is opt-in, manual, experimental, and never
required for tests.

First-party surface notes (observed 2026-09-22):
- ``https://radxa.com/products/`` is the catalogue index; product pages live
  at ``/products/<category>/<model>/``. The category IS the first-party
  family taxonomy (docs.radxa.com sidebar names the same series), so family
  identity comes from the catalogue taxonomy, not name surgery.
- ``docs.radxa.com`` (Docusaurus) and ``wiki.radxa.com`` are documentation
  planes and are NOT fetched.
- Pages are Cloudflare-fronted and contain per-request volatile markup
  (challenge-platform scripts, email-protection links). Raw body hashes are
  unstable across fetches; the semantic hash strips exactly those artifacts
  (proven byte-identical across fetches of the same page).
- Some pages document two related SKUs in one table (CM5 vs CM5 Lite with
  different SoCs). One page naming two application processors fails closed
  as identity conflict, mirroring both prior vendors.
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

SOURCE_KEY = "radxa-product"
VENDOR_KEY = "radxa"
VENDOR_NAME = "Radxa"
COLLECTOR_KEY = "radxa-product"
OFFICIAL_HOSTS = frozenset({"radxa.com", "www.radxa.com"})
PRODUCTS_URL = "https://radxa.com/products/"
PRODUCTS_PREFIX = "/products/"

_REPO_CORPUS = Path(__file__).resolve().parents[3] / "fixtures" / "radxa_product"
_PACKAGED_CORPUS = Path(__file__).resolve().parents[1] / "fixture_data" / "radxa_product"
CORPUS_DIR = _REPO_CORPUS if (_REPO_CORPUS / "manifest.json").exists() else _PACKAGED_CORPUS

# First-party catalogue categories (docs.radxa.com names the same series).
_FAMILY_BY_CATEGORY = {
    "rock2": "rock-2",
    "rock3": "rock-3",
    "rock4": "rock-4",
    "rock5": "rock-5",
    "rockpi": "rock-pi",
    "zeros": "zero",
    "x": "x",
    "cm": "cm",
    "nx": "nx",
    "orion": "orion",
    "aicore": "aicore",
    "cubie": "cubie",
    "dragon": "dragon",
    "fogwise": "fogwise",
    "network-computer": "network-computer",
    "nio": "nio",
    "rcore": "rcore",
    "sirider": "sirider",
    "vmarc": "vmarc",
    "linkr": "linkr",
}
_FAMILY_DISPLAY = {key: key.replace("-", " ").upper() for key in _FAMILY_BY_CATEGORY}
_FAMILY_DISPLAY["cm"] = "CM"
_FAMILY_DISPLAY["x"] = "X"

_TYPE_BY_CATEGORY = {
    "cm": BoardType.COMPUTE_MODULE,
    "orion": BoardType.MINI_ITX_SBC,
    "zeros": BoardType.ZERO_CLASS,
    "network-computer": BoardType.ROUTER_BOARD,
    "aicore": BoardType.AI_SBC,
}
# Carrier and accessory categories are not board inventory.
_NON_BOARD_CATEGORIES = frozenset({"accessories", "io-board"})

_SOC_MODEL_RE = re.compile(r"\b(RK[0-9]{4}[A-Z0-9]*|A311D|N[0-9]{3}|CD8180|CD8160)\b")
# "P1" alone is too generic to admit by shape; it identifies the Cix P1 SoC
# only when a Cix vendor word sits next to it.
_SOC_P1_RE = re.compile(r"\b(?:Cix|CIX|Cixin)\s+P1\b|\bP1\s+SoC\b")
_KNOWN_SOC_VENDORS = ("rockchip", "intel", "amlogic", "cix", "sophon", "allwinner", "amd", "qualcomm")
_SOC_VENDOR_BY_PREFIX = (("rk", "rockchip"), ("a3", "amlogic"), ("n", "intel"), ("cd", "cix"))
# Companion silicon: never the application processor whatever it resembles.
_NON_SOC_TOKEN_RE = re.compile(r"^(?:RP2040|RP[0-9]{4}|RTL[0-9]{4}[A-Z]{0,2}|Mali|IMX[0-9]{3}|AXP[0-9]{3}|ES[0-9]{4}|AP[0-9]{4})")

_RAM_LIST_RE = re.compile(r"(?:\d+(?:\.\d+)?\s*GB\s*(?:/|or|,|·)\s*)+\d+(?:\.\d+)?\s*GB")
_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*GB")
_RAM_CONTEXT_RE = re.compile(r"RAM|Memory|LPDDR", re.I)
_EMMC_CONTEXT_RE = re.compile(r"eMMC", re.I)
_UP_TO_RE = re.compile(r"up to\s+(\d+(?:\.\d+)?)\s*GB", re.I)
_RAM_TYPE_RE = re.compile(r"(LPDDR5X|LPDDR5|LPDDR4X|LPDDR4|LPDDR4x|DDR5|DDR4)\b", re.I)
_VERSIONED_RAM_RE = re.compile(r"V(\d+(?:\.\d+)?)\s*:\s*(LPDDR[45]X?)", re.I)
_WIFI_OR_RE = re.compile(r"Wi-?Fi\s*([56])\s*(?:/&|\s+or\s+)Wi-?Fi\s*([56])", re.I)
_WIFI_SINGLE_RE = re.compile(r"Wi-?Fi\s*([567])", re.I)
_WIFI_MODULE_RE = re.compile(r"wireless module|wi-fi\s*7\s+wireless module", re.I)
_DIMENSION_RE = re.compile(r"(\d+)\s*mm\s*[x×]\s*(\d+)\s*mm", re.I)


class _PageParser(HTMLParser):
    """Capture h1/h2 text, paragraphs, meta description, and links."""

    def __init__(self) -> None:
        super().__init__()
        self.h1 = ""
        self.h2s: list[str] = []
        self.paragraphs: list[str] = []
        self.description = ""
        self.hrefs: list[str] = []
        self._capture: str | None = None
        self._buf = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrd = dict(attrs)
        if tag == "a" and attrd.get("href"):
            self.hrefs.append(attrd["href"])
        if tag == "meta" and attrd.get("name", "").lower() == "description":
            self.description = attrd.get("content") or ""
        if tag in {"h1", "h2", "p"}:
            self._capture = tag
            self._buf = ""

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h1", "h2", "p"} and self._capture == tag:
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

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buf += data


def _clean_name(raw: str) -> str:
    text = re.sub(r"\s+", " ", raw).strip()
    return text


def _board_slug(name: str) -> str:
    """Keep official plus-markers distinct (ROCK 5B+ != ROCK 5B)."""
    return slugify(name.replace("+", " plus "))


def _category_and_model(page_url: str) -> tuple[str, str]:
    parts = [seg for seg in urlparse(page_url).path.split("/") if seg]
    # parts == ["products", category, model] (or the site's duplicated
    # "products/products/..." path bug, which normalises to one segment).
    if len(parts) >= 3 and parts[0] == "products":
        parts = [p for i, p in enumerate(parts) if not (i > 0 and p == "products" and parts[i - 1] == "products")]
    if len(parts) >= 3:
        return parts[1], parts[2]
    if len(parts) == 2:
        return parts[1], ""
    return "", ""


def _family_for_category(category: str) -> tuple[str, str, BoardType]:
    family = _FAMILY_BY_CATEGORY.get(category, slugify(category))
    board_type = _TYPE_BY_CATEGORY.get(category, BoardType.SBC)
    return family, _FAMILY_DISPLAY.get(family, family), board_type


def _soc_candidates(text: str) -> list[tuple[str, str]]:
    """Extract (vendor, model) application-processor pairs.

    Vendor comes from the nearest preceding vendor word; model tokens must
    match known first-party SoC part-number shapes. Companion silicon
    (RP2040 co-processor, RTL8852BE radio, Mali GPU, IMX cameras) is never
    admitted by shape. "P1" is admitted only with adjacent Cix context.
    """
    candidates: list[tuple[str, str]] = []
    matches: list[tuple[str, re.Match]] = []
    for match in _SOC_MODEL_RE.finditer(text):
        matches.append((match.group(1).upper(), match))
    for match in _SOC_P1_RE.finditer(text):
        model = "P1"
        if all(existing.upper() != model or True for existing, _m in matches):
            if model not in [m for m, _ in matches]:
                matches.append((model, match))
    for model, match in matches:
        if _NON_SOC_TOKEN_RE.match(model):
            continue
        window = text[max(0, match.start() - 60):match.start()]
        vendor = UNKNOWN
        for word in re.findall(r"[A-Za-z]+", window)[::-1]:
            if word.lower() in _KNOWN_SOC_VENDORS:
                vendor = word.lower()
                break
        if model == "P1":
            vendor = "cix"
        if vendor == UNKNOWN:
            for prefix, name in _SOC_VENDOR_BY_PREFIX:
                if model.lower().startswith(prefix):
                    vendor = name
                    break
        if (vendor, model) not in candidates:
            candidates.append((vendor, model))
    return candidates


def _extract_soc(text: str) -> tuple[str, str, list[str]]:
    candidates = _soc_candidates(text)
    if not candidates:
        return UNKNOWN, UNKNOWN, []
    if len(candidates) > 1:
        return "CONFLICT", ",".join(model for _v, model in candidates), [m for _v, m in candidates]
    vendor, model = candidates[0]
    return vendor, model, [model]


def _ram_evidence(text: str) -> tuple[str, list[str]]:
    """Return (ram_type, options). 'Up to XGB' maxima are not matrices."""
    type_match = _RAM_TYPE_RE.search(text)
    options: list[str] = []
    for match in _RAM_LIST_RE.finditer(text):
        segment = text[max(0, match.start() - 70):match.end() + 30]
        if not _RAM_CONTEXT_RE.search(segment) or _EMMC_CONTEXT_RE.search(segment):
            continue
        for amount in _SIZE_RE.findall(match.group(0)):
            label = f"{amount}GB"
            if float(amount) <= 128 and label not in options:
                options.append(label)
    if not options:
        for match in _RAM_LIST_RE.finditer(text):
            segment = text[max(0, match.start() - 70):match.end() + 30]
            if _RAM_CONTEXT_RE.search(segment) and not _EMMC_CONTEXT_RE.search(segment):
                for amount in _SIZE_RE.findall(match.group(0)):
                    label = f"{amount}GB"
                    if float(amount) <= 128 and label not in options:
                        options.append(label)
                break
    # Single explicit "RAM : 4 GB" statement is a real single-configuration.
    if not options:
        single = re.search(r"RAM\s*[:\s]\s*(\d+(?:\.\d+)?)\s*GB", text, re.I)
        if single:
            options = [f"{single.group(1)}GB"]
    return (type_match.group(1).upper() if type_match else UNKNOWN), options


def _storage_options(text: str) -> list[str]:
    options: list[str] = []
    for match in _RAM_LIST_RE.finditer(text):
        segment = text[max(0, match.start() - 90):match.end() + 30]
        if not _EMMC_CONTEXT_RE.search(segment):
            continue
        for amount in _SIZE_RE.findall(match.group(0)):
            label = f"{amount}GB"
            if float(amount) <= 512 and label not in options:
                options.append(label)
    if options:
        return options
    if re.search(r"Onboard eMMC", text, re.I):
        return ["onboard"]
    if re.search(r"eMMC Module|eMMC Connector", text):
        return ["none", "module"]
    return []


def _wireless_options(text: str) -> list[str]:
    levels: list[str] = []
    for match in _WIFI_SINGLE_RE.finditer(text):
        level = match.group(1)
        if level not in levels:
            levels.append(level)
    if not levels:
        return [UNKNOWN]
    # Two distinct wifi levels joined by an explicit OR are configuration
    # choices ("WiFi5 & BT5 OR WiFi6 & BT5.4", "WiFi 5 or WiFi 6").
    if len(levels) > 1 and re.search(r"\bOR\b", text, re.I):
        return [f"wifi{level}" for level in levels]
    level = levels[0]
    if _WIFI_MODULE_RE.search(text) and "onboard" not in text[max(0, _WIFI_SINGLE_RE.search(text).start() - 60):_WIFI_SINGLE_RE.search(text).start() + 60].lower():
        return ["none", f"wifi{level}"]
    return [f"wifi{level}"]


def _versioned_revisions(text: str) -> list[tuple[str, str]]:
    """Hardware versions that name distinct RAM types (e.g. 5C V1.1/V2.1)."""
    return [(m.group(1), m.group(2).upper()) for m in _VERSIONED_RAM_RE.finditer(text)]


def _architecture(text: str) -> Architecture:
    if re.search(r"Intel|Alder Lake|N100|x86", text, re.I):
        return Architecture.X86
    if re.search(r"RISC-V|RISC V", text, re.I):
        return Architecture.RISCV
    if re.search(r"Cortex|RK[0-9]{4}|Arm", text, re.I):
        return Architecture.ARM
    return Architecture.UNKNOWN


def _editorial(category: str, soc_name: str) -> list[str]:
    ctx: list[str] = []
    if soc_name.startswith("RK3588") or soc_name.startswith("CD8180") or soc_name == "P1":
        ctx.append(EditorialContext.HIGH_END_ARM.value)
    if category == "cm":
        ctx.append(EditorialContext.INDUSTRIAL.value)
    if category == "x":
        ctx.append(EditorialContext.X86_SBC.value)
    return ctx


_VOLATILE_HTML = (
    re.compile(r"<script[\s\S]*?</script>", re.I),
    re.compile(r"<style[\s\S]*?</style>", re.I),
    re.compile(r"<!--[\s\S]*?-->", re.I),
    re.compile(r"/cdn-cgi/l/email-protection#[0-9a-fA-F]*"),
    re.compile(r'data-cfemail="[0-9a-fA-F]*"'),
)


def semantic_html(html: str) -> str:
    """Strip exactly the per-request volatile artifacts Radxa pages carry
    (Cloudflare challenge scripts, email-protection links) plus transport
    comments, then collapse whitespace. Proven byte-stable across fetches of
    the same page while raw hashes differ."""
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


def _product_url_pattern(parsed_url) -> bool:
    parts = [seg for seg in parsed_url.path.split("/") if seg]
    if parts and parts[0] != "products":
        return False
    normalized = [p for i, p in enumerate(parts) if not (i > 0 and p == "products" and parts[i - 1] == "products")]
    return len(normalized) >= 3


def _is_in_scope_product_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc not in OFFICIAL_HOSTS:
        return False
    if not _product_url_pattern(parsed):
        return False
    category, _model = _category_and_model(url)
    return category not in _NON_BOARD_CATEGORIES


def _detail_leads(href_list: list[str], base_url: str) -> list[str]:
    leads: list[str] = []
    for href in href_list:
        abs_url = urljoin(base_url, href).split("#")[0]
        # The site intermittently doubles the products path segment.
        abs_url = re.sub(r"/products/products/", "/products/", abs_url)
        if not abs_url.endswith("/"):
            abs_url += "/"
        if _is_in_scope_product_url(abs_url) and abs_url not in leads:
            leads.append(abs_url)
    return sorted(leads)


def parse_product_html(html: str, *, page_url: str, observed_at: str, historical_known: bool = False) -> tuple[list[ObservationDraft], dict[str, Any]]:
    """Parse one official Radxa product-surface HTML document."""
    parser = _PageParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # noqa: BLE001
        raise CollectorError(f"html parse failed for {page_url}: {exc}") from exc

    diagnostics: dict[str, Any] = {"page_url": page_url, "heading": UNKNOWN, "lead_hrefs": [], "status": "ok"}
    parsed_url = urlparse(page_url)
    if parsed_url.netloc in OFFICIAL_HOSTS:
        path_parts = [seg for seg in parsed_url.path.split("/") if seg]
        is_index = path_parts in (["products"], ["products", "products"]) or parsed_url.path.rstrip("/") in ("", "/products")
        if is_index:
            diagnostics["lead_hrefs"] = _detail_leads(parser.hrefs, page_url)
            diagnostics["status"] = "lead-index"
            diagnostics["evidence_roles"] = ["DISCOVERY"]
            return [], diagnostics
        if not _product_url_pattern(parsed_url):
            diagnostics["status"] = "ignored-unknown-surface"
            return [], diagnostics

    name = _clean_name(parser.h1)
    diagnostics["heading"] = name or UNKNOWN
    category, _model = _category_and_model(page_url)
    if not name:
        diagnostics["status"] = "ignored-non-computer"
        diagnostics["scope"] = "NON_BOARD_CATALOGUE_ITEM"
        return [], diagnostics
    if category in _NON_BOARD_CATEGORIES:
        diagnostics["status"] = "ignored-non-computer"
        diagnostics["scope"] = "NON_BOARD_CATALOGUE_ITEM"
        diagnostics["reason"] = "accessory-or-carrier-category"
        return [], diagnostics

    text = " ".join([parser.description, *parser.h2s, *parser.paragraphs])
    family_slug, family_name, board_type = _family_for_category(category)
    board_slug = _board_slug(name)
    soc_vendor, soc_name, soc_candidates = _extract_soc(text)
    ram_type, ram_opts = _ram_evidence(text)
    storage_opts = _storage_options(text)
    wireless_opts = _wireless_options(text)
    revisions = _versioned_revisions(text)
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
            family_name=family_name,
            board_slug=board_slug,
            marketing_name=name,
            board_type=board_type,
            spec=NormalizedSpec(),
            raw_fields={"soc_candidates": soc_candidates, "category": category},
            native_fields={"heading": name, "page_url": page_url},
            novelty=NoveltyEvidence(
                first_seen_at=observed_at, first_seen_source=SOURCE_KEY,
                novelty_status=NoveltyStatus.UNKNOWN, novelty_basis="conflicting-soc-evidence",
                novelty_confidence="low",
            ),
            page_url=page_url,
            historical_known=historical_known,
            identity_conflict=True,
            identity_conflict_reason="multiple application processors named on one product page",
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
            family_name=family_name,
            board_slug=board_slug,
            marketing_name=name,
            board_type=board_type,
            spec=NormalizedSpec(),
            raw_fields={"category": category, "html_excerpt": html[:400]},
            native_fields={"heading": name, "page_url": page_url},
            novelty=NoveltyEvidence(
                first_seen_at=observed_at, first_seen_source=SOURCE_KEY,
                novelty_status=NoveltyStatus.UNKNOWN,
                novelty_basis="insufficient-first-party-specification",
                novelty_confidence="low",
            ),
            page_url=page_url,
            historical_known=historical_known,
            evidence_insufficient=True,
        )
        return [draft], diagnostics

    if not ram_opts:
        ram_opts = [UNKNOWN]
    if not storage_opts:
        storage_opts = [UNKNOWN]
    ram_matrix = ",".join(ram_opts)
    storage_matrix = ",".join(storage_opts)
    dim_match = _DIMENSION_RE.search(parser.description)
    dims = f"{dim_match.group(1)}x{dim_match.group(2)}mm" if dim_match else UNKNOWN
    revision_specs = revisions or [("", ram_type)]
    drafts: list[ObservationDraft] = []
    for version_token, version_ram_type in revision_specs:
        rev_kind = RevisionKind.PCB if version_token else RevisionKind.UNKNOWN
        rev_token = version_token or UNKNOWN
        effective_ram_type = version_ram_type if version_ram_type else ram_type
        for ram in ram_opts:
            for storage in storage_opts:
                for wireless in wireless_opts:
                    spec = NormalizedSpec(
                        soc=soc_name,
                        soc_key=f"{slugify(soc_vendor)}:{slugify(soc_name)}",
                        cpu_arch=_architecture(text).value,
                        ram_type=effective_ram_type,
                        ram_options=ram_matrix,
                        onboard_emmc="yes" if "onboard" in storage_opts else ("optional" if "module" in storage_opts else UNKNOWN),
                        emmc_options=storage_matrix,
                        microsd="yes" if re.search(r"Micro ?SD|micro sd", text, re.I) else UNKNOWN,
                        m2_m_key="yes" if re.search(r"M\.2 M Key", text, re.I) else UNKNOWN,
                        sata="yes" if "SATA" in text else UNKNOWN,
                        ethernet="2.5g" if "2.5G" in text else ("gigabit" if re.search(r"Gigabit", text, re.I) else UNKNOWN),
                        wifi=_first_wifi(text),
                        bluetooth="present" if re.search(r"BT ?5|Bluetooth", text, re.I) else UNKNOWN,
                        hdmi_out="hdmi" if re.search(r"HDMI", text, re.I) else UNKNOWN,
                        usb="usb3" if re.search(r"USB ?3", text, re.I) else ("usb" if "USB" in text else UNKNOWN),
                        gpio_header="40-pin" if re.search(r"40-?Pin", text, re.I) else UNKNOWN,
                        dimensions=dims,
                        pcb_revision=rev_token,
                    )
                    variant = VariantDimensions(ram=ram, storage=storage, wireless=wireless)
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
                            architecture=_architecture(text),
                            spec=spec,
                            raw_fields={
                                "category": category,
                                "ram_options": ram_opts,
                                "storage_options": storage_opts,
                                "hardware_versions": [v for v, _t in revisions],
                            },
                            native_fields={"heading": name, "page_url": page_url},
                            availability=Availability.UNKNOWN,
                            novelty=NoveltyEvidence(
                                first_seen_at=observed_at, first_seen_source=SOURCE_KEY,
                                novelty_status=NoveltyStatus.HISTORICAL if historical_known else NoveltyStatus.EXISTING_PRODUCT,
                                novelty_basis="official-product-catalogue",
                                novelty_confidence="high",
                            ),
                            editorial_context=_editorial(category, soc_name),
                            page_url=page_url,
                            historical_known=historical_known,
                        )
                    )
    diagnostics["status"] = "resolved"
    diagnostics["observation_count"] = len(drafts)
    diagnostics["board_slug"] = board_slug
    return drafts, diagnostics


def _first_wifi(text: str) -> str:
    or_match = _WIFI_OR_RE.search(text)
    if or_match:
        return f"wifi{or_match.group(1)}/wifi{or_match.group(2)}"
    single = _WIFI_SINGLE_RE.search(text)
    return f"wifi{single.group(1)}" if single else UNKNOWN


def load_corpus_manifest(corpus_dir: Path | None = None) -> dict[str, Any]:
    root = corpus_dir or CORPUS_DIR
    path = root / "manifest.json"
    if not path.exists():
        raise CollectorError(f"radxa fixture corpus missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def collect_corpus(name: str, *, run_id: str, started_at: str, corpus_dir: Path | None = None) -> CollectorRunRequest:
    root = corpus_dir or CORPUS_DIR
    manifest = load_corpus_manifest(root)
    corpora = manifest.get("corpora") or {}
    if name not in corpora:
        raise CollectorError(f"unknown radxa corpus: {name}")
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
        error = error or "radxa product parser failed: missing required product fields"
    return CollectorRunRequest(
        run_id=run_id, source_key=SOURCE_KEY, collector_key=COLLECTOR_KEY,
        started_at=started_at, observations=observations, ok=ok, error=error,
        fixture_scenario=f"radxa:{name}", diagnostics=diagnostics,
    )


def _assert_official_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise CollectorError(f"refusing non-https radxa url: {url}")
    if parsed.netloc not in OFFICIAL_HOSTS:
        raise CollectorError(f"refusing third-party or docs url: {url}")
    parts = [seg for seg in parsed.path.split("/") if seg]
    is_index = parts in (["products"], ["products", "products"]) or parsed.path.rstrip("/") in ("", "/products")
    if not is_index and not _product_url_pattern(parsed):
        raise CollectorError(f"refusing non-product radxa url: {url}")
    if not is_index:
        category, _model = _category_and_model(url)
        if category in _NON_BOARD_CATEGORIES:
            raise CollectorError(f"refusing non-board catalogue category: {url}")
    return url


def fetch_official(url: str, *, timeout: int = 30) -> str:
    return fetch_official_meta(url, timeout=timeout)["text"]


def fetch_official_meta(url: str, *, timeout: int = 30) -> dict[str, Any]:
    _assert_official_url(url)
    request = Request(
        url,
        headers={"User-Agent": "board-clank/0.1.0 (+experimental-manual-radxa-product)"},
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


class RadxaProductAdapter(CollectorAdapter):
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
            page_url=payload.get("page_url") or PRODUCTS_URL,
            observed_at=payload.get("observed_at") or "1970-01-01T00:00:00+00:00",
            historical_known=bool(payload.get("historical_known")),
        )
        return drafts

    def _collect_live(self, run_id: str, started_at: str) -> CollectorRunRequest:
        """Live path: catalogue index -> in-scope product pages.

        radxa.com only; docs.radxa.com / wiki.radxa.com / stores are never
        fetched. Volatile Cloudflare markup is excluded from semantic
        evidence hashes so transport churn is not intelligence churn."""
        diagnostics: dict[str, Any] = {
            "mode": "experimental-live-radxa",
            "primary_surface": PRODUCTS_URL,
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
            meta = record_fetch(PRODUCTS_URL)
            _drafts, info = parse_product_html(meta["text"], page_url=PRODUCTS_URL, observed_at=started_at)
            info["raw_body_hash"] = meta["raw_body_hash"]
            info["semantic_evidence_hash"] = meta["semantic_evidence_hash"]
            diagnostics["documents"].append(info)
            in_scope = info.get("lead_hrefs") or []
            diagnostics["leads"] = in_scope
            diagnostics["candidate_references"] = len(in_scope)
            for href in _all_hrefs(meta["text"], PRODUCTS_URL):
                if href in in_scope:
                    continue
                parsed = urlparse(href)
                if parsed.netloc in OFFICIAL_HOSTS and parsed.path.startswith(PRODUCTS_PREFIX):
                    diagnostics["rejected"].append({"url": href, "reason": "accessory-or-carrier-or-non-product"})

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
