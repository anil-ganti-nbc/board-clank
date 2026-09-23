"""Pine64 PRODUCT adapter.

Foundation 6A: sixth and FINAL vendor of the expansion programme. Default
path is offline fixtures. Network fetch is opt-in, manual, experimental,
and never required for tests.

First-party surface notes (observed 2026-09-23):
- ``https://pine64.org/devices/`` is the DISCOVERY surface AND the category
  authority: device boxes pair a display name with a slug under a section
  heading (Single Board Computers, Laptops, Phones and Tablets, Wearables,
  Clusters and Compute Modules, IP Cameras, Soldering Irons, Makerspace,
  Power Supplies, IoT, Smart home).
- Device pages are thin static pages; identity is the page heading, specs
  are prose (``powered by a Rockchip RK3566 ...``) and/or a labelled
  ``Features and Specifications`` list. Some pages (SOQuartz) carry only an
  identity sentence — those resolve identity-only.
- CATEGORY SCOPE: only Single Board Computers + compute modules are board
  scope. Pine64's phones, laptops, tablets, smartwatches, earbuds, solder
  irons, power supplies, IoT devices and cameras are rejected explicitly —
  the PinePhone page even names the A64 SoC, so scope gating happens on the
  device category, never on SoC presence.
- ``store.pine64.org`` (TLS principal mismatch) / ``pine64.com``
  (commerce-only) / ``linux.pine64.org`` (blog, TLS failure) /
  ``wiki.pine64.org`` (documentation) are NOT ingested.
- Family comes from the first-party series names (Quartz, ROCK, PINE A64,
  STAR, SO-modules), not string chopping.
- The A64 family spans board generations under one marketing name: the
  base ``pine-a64`` page documents both PINE A64 and PINE A64+ (plus is a
  board option, not identity); PINE A64-LTS is a distinct board (Allwinner
  R18); SOPINE is a compute module in its own right.
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

SOURCE_KEY = "pine64-product"
VENDOR_KEY = "pine64"
VENDOR_NAME = "Pine64"
COLLECTOR_KEY = "pine64-product"
OFFICIAL_HOSTS = frozenset({"pine64.org", "www.pine64.org"})
DEVICES_URL = "https://pine64.org/devices/"
DEVICES_PREFIX = "/devices/"

_REPO_CORPUS = Path(__file__).resolve().parents[3] / "fixtures" / "pine64_product"
_PACKAGED_CORPUS = Path(__file__).resolve().parents[1] / "fixture_data" / "pine64_product"
CORPUS_DIR = _REPO_CORPUS if (_REPO_CORPUS / "manifest.json").exists() else _PACKAGED_CORPUS

# First-party category gates. Board scope = SBCs + compute modules;
# everything else Pine64 makes is rejected.
_BOARD_CATEGORIES = frozenset(
    {
        "single-board-computers",
        "clusters-and-compute-modules",
    }
)
_CATEGORY_ANCHOR_RE = re.compile(r"id=([a-z0-9-]+)", re.I)

_SOC_TOKEN_RE = re.compile(
    r"\b(RK[0-9]{4}[A-Z0-9]*|A64\b|R18\b|JH-7110|BL808|BL706|S905X3|H64\b)\b",
)
_KNOWN_SOC_VENDORS = ("rockchip", "allwinner", "starfive", "bouffalo", "amlogic", "nordic")
_SOC_VENDOR_BY_PREFIX = (("rk", "rockchip"), ("jh", "starfive"), ("bl", "bouffalo"), ("s9", "amlogic"))
# Vendor-gated short tokens (A64/R18 need Allwinner; H64 is a board name).
_VENDOR_GATED_TOKENS = {"A64", "R18", "H64"}
_CPU_CONTEXT_RE = re.compile(r"SoC|CPU|Processor|powered by|features? the|quad-core", re.I)
_RADIO_CONTEXT_RE = re.compile(r"Wi-?Fi|Bluetooth|wireless|radio", re.I)
_GENEALOGY_CONTEXT_RE = re.compile(r"used in (?:our|the) popular|same .* SoC", re.I)

_RAM_LIST_RE = re.compile(r"(?:\d\s*GB\s*(?:,|or|/)\s*)+\d\s*GB|\d\s*GB\s*(?:,\s*)?\d\s*GB", re.I)
_GB_RE = re.compile(r"(\d+(?:\.\d+)?)\s*GB", re.I)
_RAM_CTX_RE = re.compile(r"(?:\d\s*GB\s*(?:,|or|/)\s*)+\d\s*GB[^.]{0,30}RAM|RAM[^.]{0,20}\(up to \d+GB\)|(\dGB|2GB|3GB|4GB|8GB)\s+(?:LP)?DDR", re.I)
_RAM_TYPE_RE = re.compile(r"(LPDDR5|LPDDR4|LPDDR3|DDR4|DDR3)\b", re.I)
_EMMC_OPT_RE = re.compile(r"optional eMMC module \(up to (\d+)\s*GB\)", re.I)
_EMMC_SOCKET_RE = re.compile(r"eMMC module socket", re.I)
_WIFI_BUILTIN_RE = re.compile(r"[Bb]uilt-in\s+(?:802\.11[\w/]*\s*)?WiFi|[Ii]ntegrated\s+Wi-?Fi|dual band Wi-?Fi")
_WIFI_OPTIONAL_RE = re.compile(r"[Oo]ptional\s+(?:\d*G\s*)?(?:802\.11[\w/]*\s*)?WiFi|WiFi.*expansion module|Optional WiFi")


def _strip_entities(text: str) -> str:
    return text.replace("&rsquo;", "'").replace("&ndash;", "-").replace("&rsquor;", "'").replace("&nbsp;", " ")


class _PageParser(HTMLParser):
    """Capture headings, paragraphs, list items, links. On index pages the
    h2 stream interleaves category headings and device box names (a box is
    an h2 whose preceding <a href=/devices/<slug>/> opened inside the box
    div); ``boxes`` / ``categories`` separate the two streams."""

    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.h2s: list[str] = []
        self.paragraphs: list[str] = []
        self.list_items: list[str] = []
        self.hrefs: list[str] = []
        self.boxes: list[tuple[str, str]] = []  # (name, slug) from index pages
        self.categories: list[str] = []  # section headings on index pages
        self._capture: str | None = None
        self._buf = ""
        self._in_title = False
        self._pending_box_href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrd = dict(attrs)
        if tag == "a" and attrd.get("href"):
            self.hrefs.append(attrd["href"])
            if attrd["href"].startswith(DEVICES_PREFIX):
                self._pending_box_href = attrd["href"]
        if tag == "title":
            self._in_title = True
            self._buf = ""
        elif tag in {"h2", "p", "li"}:
            self._capture = tag
            self._buf = ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._in_title:
            self.title = re.sub(r"\s+", " ", self._buf).strip()
            self._in_title = False
            self._buf = ""
        elif tag == "a" and not self._capture:
            # An anchor that closed without enclosing an h2 was navigation;
            # drop any stale pending box href so it cannot poison pairing.
            self._pending_box_href = None
        if tag in {"h2", "p", "li"} and self._capture == tag:
            text = re.sub(r"\s+", " ", _strip_entities(self._buf)).strip()
            if text:
                if tag == "h2":
                    if self._pending_box_href is not None:
                        slug = self._pending_box_href.rstrip("/").rsplit("/", 1)[-1]
                        self.boxes.append((text, slug))
                        self._pending_box_href = None
                    else:
                        self.h2s.append(text)
                        self.categories.append(text)
                elif tag == "li":
                    self.list_items.append(text)
                else:
                    self.paragraphs.append(text)
            self._capture = None
            self._buf = ""

    def handle_data(self, data: str) -> None:
        if self._in_title or self._capture:
            self._buf += data


def _index_events(parser: _PageParser, html: str) -> list[tuple[str, Any]]:
    """Replay the index's h2 stream as ('category', name) / ('box', (name, slug))
    events in document order, so scope gating follows the page's own order.
    A box h2 is recognised by matching the parser's captured box names."""
    box_names = {name for name, _slug in parser.boxes}
    events: list[tuple[str, Any]] = []
    for m in re.finditer(r"<h2[^>]*>([\s\S]*?)</h2>", html):
        text = re.sub(r"\s+", " ", _strip_entities(re.sub(r"<[^>]+>", " ", m.group(1)))).strip()
        if text in box_names:
            box = next(b for b in parser.boxes if b[0] == text)
            events.append(("box", box))
        else:
            events.append(("category", text))
    return events


def _board_slug(name: str) -> str:
    """Keep official suffixes distinct (Quartz64 Model A/B, A64-LTS)."""
    return slugify(name)


def _family_slug(name: str) -> str:
    """First-party series names, from the vendor's own catalogue groupings.
    SO* compute modules (SOPINE / SOQuartz / SOEDGE) are their own product
    line under "Clusters and Compute Modules" and are checked first."""
    lowered = name.lower()
    if re.match(r"^so[a-z]", lowered):
        match = re.match(r"(so[a-z]+)", slugify(name))
        return match.group(1) if match else slugify(name)
    if "quartz" in lowered:
        return "quartz"
    if "rock" in lowered:
        return "rock"
    if "star" in lowered:
        return "star"
    if re.search(r"\ba64\b|pine a64", lowered):
        return "pine-a64"
    return slugify(name)


def _board_type_from_category(category: str) -> BoardType:
    if category == "clusters-and-compute-modules":
        return BoardType.COMPUTE_MODULE
    return BoardType.SBC


def _soc_candidates(text: str) -> list[tuple[str, str]]:
    """(vendor, model) pairs from SoC/CPU context. Radio-only contexts and
    genealogical mentions (SoC 'used in our popular PINE A64') never mint a
    candidate for the page at hand."""
    candidates: list[tuple[str, str]] = []
    for match in _SOC_TOKEN_RE.finditer(text):
        model = match.group(1).upper()
        window = text[max(0, match.start() - 70):match.end() + 30]
        if model in _VENDOR_GATED_TOKENS:
            if not any(v in window.lower() for v in _KNOWN_SOC_VENDORS):
                continue
        if _RADIO_CONTEXT_RE.search(window) and not _CPU_CONTEXT_RE.search(window):
            continue
        vendor = UNKNOWN
        for word in re.findall(r"[A-Za-z]+", window)[::-1]:
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


def _extract_soc(text: str) -> tuple[str, str, list[str]]:
    candidates = _soc_candidates(text)
    if not candidates:
        return UNKNOWN, UNKNOWN, []
    if len(candidates) > 1:
        # Same-family mentions (A64 genealogy) are collapsed; genuinely
        # different SoCs conflict.
        models = [m for _v, m in candidates]
        if set(models) <= {"A64", "R18"}:
            vendor = "allwinner"
            model = "R18" if "R18" in models else "A64"
            return vendor, model, [model]
        return "CONFLICT", ",".join(models), models
    vendor, model = candidates[0]
    return vendor, model, [model]


def _ram_evidence(text: str) -> tuple[str, list[str]]:
    type_match = _RAM_TYPE_RE.search(text)
    options: list[str] = []
    for match in _RAM_LIST_RE.finditer(text):
        segment = text[max(0, match.start() - 40):match.end() + 60]
        if not re.search(r"RAM|LPDDR|DDR", segment, re.I):
            continue
        for amount in _GB_RE.findall(match.group(0)):
            label = f"{int(float(amount))}GB"
            if float(amount) <= 64 and label not in options:
                options.append(label)
    if not options:
        single = re.search(r"(\d(?:\.\d+)?)\s*GB\s+(?:LP)?DDR\d?", text, re.I)
        if not single:
            single = re.search(r"(\d)G\s+LPDDR", text, re.I)
        if not single:
            single = re.search(r"(?:LP)?DDR\d?\s+RAM\s*\((\d)GB\)", text, re.I)
        if single:
            options = [f"{int(float(single.group(1)))}GB"]
        else:
            up_to = re.search(r"RAM\s*\(up to (\d)GB\)", text, re.I)
            if up_to:
                # "up to N GB" states a matrix: 1..N GB are the options.
                options = [f"{n}GB" for n in range(1, int(up_to.group(1)) + 1) if n in (1, 2, 3, 4, 6, 8, 16)]
    return (type_match.group(1).upper() if type_match else UNKNOWN), options


def _storage_options(text: str) -> list[str]:
    match = _EMMC_OPT_RE.search(text)
    if match:
        return ["none", f"{match.group(1)}GB"]
    if _EMMC_SOCKET_RE.search(text):
        return ["none", "module"]
    return []


def _wireless_options(text: str) -> list[str]:
    if _WIFI_BUILTIN_RE.search(text):
        return ["wifi"]
    if _WIFI_OPTIONAL_RE.search(text):
        return ["none", "wifi"]
    return [UNKNOWN]


def _architecture(text: str) -> Architecture:
    if re.search(r"RISC-V|RISC V|SiFive|U74", text, re.I):
        return Architecture.RISCV
    if re.search(r"Cortex|Rockchip|Allwinner|ARM", text, re.I):
        return Architecture.ARM
    return Architecture.UNKNOWN


def _editorial(board_type: BoardType, soc_name: str) -> list[str]:
    ctx: list[str] = []
    if soc_name.startswith("RK3588") or soc_name.startswith("JH-7110"):
        ctx.append(EditorialContext.HIGH_END_ARM.value)
    if board_type is BoardType.COMPUTE_MODULE:
        ctx.append(EditorialContext.INDUSTRIAL.value)
    return ctx


_VOLATILE_HTML = (
    re.compile(r"<script[\s\S]*?</script>", re.I),
    re.compile(r"<style[\s\S]*?</style>", re.I),
    re.compile(r"<!--[\s\S]*?-->", re.I),
)


def semantic_html(html: str) -> str:
    """The pine64.org pages are static; only transport scripts/comments are
    stripped before hashing."""
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


def _classify_category(heading: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")


def _is_product_page_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc not in OFFICIAL_HOSTS:
        return False
    parts = [seg for seg in parsed.path.split("/") if seg]
    return len(parts) == 2 and parts[0] == "devices" and parts[1] not in {"", "index.html"}


def _detail_leads(parser: _PageParser, base_url: str, html: str) -> list[str]:
    """Leads only from board-scope categories, gated by the index's own
    category headings in document order."""
    leads: list[str] = []
    current_category = ""
    for event_kind, payload in _index_events(parser, html):
        if event_kind == "category":
            current_category = payload
        else:
            _name, slug = payload
            if _classify_category(current_category) in _BOARD_CATEGORIES:
                abs_url = urljoin(base_url, f"{DEVICES_PREFIX}{slug}/").split("#")[0]
                if abs_url not in leads:
                    leads.append(abs_url)
    return leads


def parse_product_html(html: str, *, page_url: str, observed_at: str, historical_known: bool = False) -> tuple[list[ObservationDraft], dict[str, Any]]:
    """Parse one official Pine64 product-surface HTML document."""
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
        if parts in (["devices"], []) or parsed_url.path.rstrip("/") in ("", "/devices"):
            leads = _detail_leads(parser, page_url, html)
            diagnostics["lead_hrefs"] = leads
            diagnostics["status"] = "lead-index"
            diagnostics["evidence_roles"] = ["DISCOVERY", "SCOPE"]
            diagnostics["rejected_categories"] = sorted(
                {_classify_category(c) for c in parser.categories if _classify_category(c) not in _BOARD_CATEGORIES}
            )
            return [], diagnostics
        if not _is_product_page_url(page_url):
            diagnostics["status"] = "ignored-unknown-surface"
            return [], diagnostics

    title_name = re.sub(r"\s*-\s*PINE64\s*$", "", parser.title, flags=re.I).strip() if parser.title else ""
    # The A64 catalogue entry's title is "PINE A64 and PINE A64+": the plus
    # variant is the page's own documented option, and the index names this
    # entry "PINE A64 (+)". One catalogue entry, one board identity.
    collapsed = re.match(r"^(.*?)\s+and\s+\1\s*\+\s*$", title_name)
    if collapsed:
        title_name = collapsed.group(1).strip()
    name = title_name or (parser.h2s[0] if parser.h2s else "")
    diagnostics["heading"] = name or UNKNOWN
    if not name:
        diagnostics["status"] = "ignored-non-computer"
        diagnostics["scope"] = "NON_BOARD_CATALOGUE_ITEM"
        return [], diagnostics

    # Scope gate: Pine64 makes many non-SBC things. Only names that the
    # index files under SBC/compute categories are boards. Device pages do
    # not carry their own category, so gate on the known non-board name
    # space of the current catalogue (pine* consumer names, tools, IoT).
    lowered = name.lower()
    non_board_patterns = (
        r"^pinephone", r"^pinetab", r"^pinebook", r"^pinetime", r"^pinebuds",
        r"^pinecil", r"^pinecone", r"^pinedio", r"^pinepower", r"^pinenut",
        r"^pinevoice", r"^pinecam", r"^pinecube", r"^alpha-one",
    )
    if re.match(non_board_patterns[0], lowered) or any(re.match(p, lowered) for p in non_board_patterns):
        diagnostics["status"] = "ignored-non-computer"
        diagnostics["scope"] = "NON_BOARD_CATALOGUE_ITEM"
        diagnostics["reason"] = "pine64-consumer-or-tool-product"
        return [], diagnostics

    board_slug = _board_slug(name)
    family_slug = _family_slug(name)
    body_text = " ".join(parser.paragraphs + parser.list_items)
    soc_vendor, soc_name, soc_candidates = _extract_soc(body_text)
    conflict = soc_vendor == "CONFLICT"

    if conflict:
        diagnostics["status"] = "identity-conflict"
        diagnostics["soc_candidates"] = soc_candidates
        draft = ObservationDraft(
            source_key=SOURCE_KEY, plane=SourcePlane.PRODUCT, observed_at=observed_at,
            vendor_key=VENDOR_KEY, vendor_name=VENDOR_NAME, family_slug=family_slug,
            family_name=family_slug, board_slug=board_slug, marketing_name=name,
            spec=NormalizedSpec(), raw_fields={"soc_candidates": soc_candidates},
            native_fields={"heading": name, "page_url": page_url},
            novelty=NoveltyEvidence(first_seen_at=observed_at, first_seen_source=SOURCE_KEY,
                                    novelty_status=NoveltyStatus.UNKNOWN, novelty_basis="conflicting-soc-evidence",
                                    novelty_confidence="low"),
            page_url=page_url, historical_known=historical_known,
            identity_conflict=True, identity_conflict_reason="multiple application processors named for one board",
            evidence_insufficient=True,
        )
        return [draft], diagnostics

    if soc_name == UNKNOWN:
        # Thin identity-only page (SOQuartz pattern): names a family in the
        # SoC slot? No — never invent. Fail closed as insufficient but keep
        # the identity-only marker.
        diagnostics["status"] = "insufficient-evidence"
        diagnostics["identity_only"] = True
        draft = ObservationDraft(
            source_key=SOURCE_KEY, plane=SourcePlane.PRODUCT, observed_at=observed_at,
            vendor_key=VENDOR_KEY, vendor_name=VENDOR_NAME, family_slug=family_slug,
            family_name=family_slug, board_slug=board_slug, marketing_name=name,
            spec=NormalizedSpec(), raw_fields={"html_excerpt": html[:400]},
            native_fields={"heading": name, "page_url": page_url},
            novelty=NoveltyEvidence(first_seen_at=observed_at, first_seen_source=SOURCE_KEY,
                                    novelty_status=NoveltyStatus.UNKNOWN, novelty_basis="insufficient-first-party-specification",
                                    novelty_confidence="low"),
            page_url=page_url, historical_known=historical_known, evidence_insufficient=True,
        )
        return [draft], diagnostics

    ram_type, ram_opts = _ram_evidence(body_text)
    storage_opts = _storage_options(body_text)
    wireless_opts = _wireless_options(body_text)
    if not ram_opts:
        ram_opts = [UNKNOWN]
    if not storage_opts:
        storage_opts = [UNKNOWN]
    ram_matrix = ",".join(ram_opts)
    storage_matrix = ",".join(storage_opts)
    arch = _architecture(body_text)
    # Compute modules come from the index category; the page itself is
    # category-less, so modules (SO*) keep the module type via family rule.
    board_type = BoardType.COMPUTE_MODULE if family_slug in {"sopine", "soquartz", "soedge"} else BoardType.SBC
    if family_slug == "quartz" and "-zero" in board_slug:
        pass  # Zero-class remains within quartz family as a board
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
                    onboard_emmc="optional" if "module" in storage_opts else UNKNOWN,
                    emmc_options=storage_matrix,
                    microsd="yes" if re.search(r"micro ?SD", body_text, re.I) else UNKNOWN,
                    ethernet="gigabit" if re.search(r"Gigabit Ethernet", body_text, re.I) else UNKNOWN,
                    wifi="wifi" if any(w != "none" for w in wireless_opts) else UNKNOWN,
                    bluetooth="present" if re.search(r"Bluetooth", body_text, re.I) else UNKNOWN,
                    usb="usb3" if re.search(r"USB ?3", body_text, re.I) else UNKNOWN,
                    gpio_header="40-pin" if re.search(r"40 ?pin", body_text, re.I) else UNKNOWN,
                    pcie_lanes="x4" if "PCIe x4" in body_text else ("x1" if "PCIe x1" in body_text else UNKNOWN),
                    pcb_revision=UNKNOWN,
                )
                drafts.append(
                    ObservationDraft(
                        source_key=SOURCE_KEY, plane=SourcePlane.PRODUCT, observed_at=observed_at,
                        vendor_key=VENDOR_KEY, vendor_name=VENDOR_NAME, family_slug=family_slug,
                        family_name=family_slug, board_slug=board_slug, marketing_name=name,
                        board_type=board_type, revision_kind=RevisionKind.UNKNOWN, revision_token=UNKNOWN,
                        variant=VariantDimensions(ram=ram, storage=storage, wireless=wireless),
                        soc_vendor=soc_vendor, soc_marketing_name=soc_name, architecture=arch,
                        spec=spec,
                        raw_fields={"ram_options": ram_opts, "storage_options": storage_opts},
                        native_fields={"heading": name, "page_url": page_url},
                        availability=Availability.UNKNOWN,
                        novelty=NoveltyEvidence(
                            first_seen_at=observed_at, first_seen_source=SOURCE_KEY,
                            novelty_status=NoveltyStatus.HISTORICAL if historical_known else NoveltyStatus.EXISTING_PRODUCT,
                            novelty_basis="official-product-catalogue",
                            novelty_confidence="high",
                        ),
                        editorial_context=_editorial(board_type, soc_name),
                        page_url=page_url, historical_known=historical_known,
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
        raise CollectorError(f"pine64 fixture corpus missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def collect_corpus(name: str, *, run_id: str, started_at: str, corpus_dir: Path | None = None) -> CollectorRunRequest:
    root = corpus_dir or CORPUS_DIR
    manifest = load_corpus_manifest(corpus_dir)
    corpora = manifest.get("corpora") or {}
    if name not in corpora:
        raise CollectorError(f"unknown pine64 corpus: {name}")
    observations: list[ObservationDraft] = []
    diagnostics: dict[str, Any] = {
        "corpus": name, "documents": [], "candidate_references": 0, "resolved": 0,
        "insufficient": 0, "conflicts": 0, "parser_errors": [], "leads": [], "rejected": [],
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
        error = error or "pine64 product parser failed: missing required product fields"
    return CollectorRunRequest(
        run_id=run_id, source_key=SOURCE_KEY, collector_key=COLLECTOR_KEY,
        started_at=started_at, observations=observations, ok=ok, error=error,
        fixture_scenario=f"pine64:{name}", diagnostics=diagnostics,
    )


def _assert_official_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise CollectorError(f"refusing non-https pine64 url: {url}")
    if parsed.netloc not in OFFICIAL_HOSTS:
        raise CollectorError(
            "refusing non-pine64.org url (store.pine64.org / pine64.com / wiki / linux blog are not ingested): " + url
        )
    parts = [seg for seg in parsed.path.split("/") if seg]
    is_index = parts in (["devices"], []) or parsed.path.rstrip("/") in ("", "/devices")
    if not is_index and not _is_product_page_url(url):
        raise CollectorError(f"refusing non-product pine64 url: {url}")
    return url


def fetch_official(url: str, *, timeout: int = 30) -> str:
    return fetch_official_meta(url, timeout=timeout)["text"]


def fetch_official_meta(url: str, *, timeout: int = 30) -> dict[str, Any]:
    _assert_official_url(url)
    request = Request(
        url,
        headers={"User-Agent": "board-clank/0.1.0 (+experimental-manual-pine64-product)"},
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


class Pine64ProductAdapter(CollectorAdapter):
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
            page_url=payload.get("page_url") or DEVICES_URL,
            observed_at=payload.get("observed_at") or "1970-01-01T00:00:00+00:00",
            historical_known=bool(payload.get("historical_known")),
        )
        return drafts

    def _collect_live(self, run_id: str, started_at: str) -> CollectorRunRequest:
        """Live path: devices index (scope-gated) -> SBC/compute-module pages.

        pine64.org only; store/commerce, wiki, blog and mirrors are never
        fetched."""
        diagnostics: dict[str, Any] = {
            "mode": "experimental-live-pine64",
            "primary_surface": DEVICES_URL,
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
            meta = record_fetch(DEVICES_URL)
            _drafts, info = parse_product_html(meta["text"], page_url=DEVICES_URL, observed_at=started_at)
            info["raw_body_hash"] = meta["raw_body_hash"]
            info["semantic_evidence_hash"] = meta["semantic_evidence_hash"]
            diagnostics["documents"].append(info)
            diagnostics["rejected"].extend(
                {"category": c, "reason": "non-board-category"} for c in info.get("rejected_categories") or []
            )
            in_scope = info.get("lead_hrefs") or []
            diagnostics["leads"] = in_scope
            diagnostics["candidate_references"] = len(in_scope)

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
                elif page_info.get("status") == "insufficient-evidence":
                    diagnostics["insufficient"] = diagnostics.get("insufficient", 0) + 1
                    observations.extend(drafts)
                elif page_info.get("status") == "identity-conflict":
                    diagnostics["conflicts"] = diagnostics.get("conflicts", 0) + 1
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
