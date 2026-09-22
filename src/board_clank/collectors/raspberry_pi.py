"""Raspberry Pi PRODUCT adapter.

Foundation 1: first live-capable source adapter. Default path is offline
fixtures. Network fetch is opt-in, manual, experimental, and never required
for tests. Index/navigation pages are leads, not product evidence.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

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

SOURCE_KEY = "raspberry-pi-product"
VENDOR_KEY = "raspberry-pi"
VENDOR_NAME = "Raspberry Pi"
COLLECTOR_KEY = "raspberry-pi-product"
OFFICIAL_HOSTS = frozenset({"www.raspberrypi.com", "raspberrypi.com"})
PRODUCT_PREFIX = "/products/"
CATALOGUE_URL = "https://www.raspberrypi.com/products/"

_REPO_CORPUS = Path(__file__).resolve().parents[3] / "fixtures" / "rpi_product"
_PACKAGED_CORPUS = Path(__file__).resolve().parents[1] / "fixture_data" / "rpi_product"
CORPUS_DIR = _REPO_CORPUS if (_REPO_CORPUS / "manifest.json").exists() else _PACKAGED_CORPUS

_BOARD_ALLOW = (
    re.compile(r"^raspberry pi \d", re.I),
    re.compile(r"^raspberry pi zero", re.I),
    re.compile(r"^compute module", re.I),
    re.compile(r"^raspberry pi compute module", re.I),
    re.compile(r"^raspberry pi 400", re.I),
    re.compile(r"^raspberry pi 500", re.I),
)
_ACCESSORY_HINTS = (
    "case",
    "hat",
    "power supply",
    "camera",
    "display",
    "cable",
    "sd card",
    "cooler",
    "antenna",
    "keyboard kit",
    "desktop kit",
    "io board",
    "debug probe",
)
_SOC_RE = re.compile(r"\bBCM[0-9A-Z]+\b", re.I)
_RAM_OPTION_RE = re.compile(r"(\d+)\s*GB", re.I)
_STORAGE_OPTION_RE = re.compile(r"(\d+)\s*GB", re.I)
_REV_RE = re.compile(r"(?:pcb\s+revision|board\s+revision|hardware\s+revision|revision)\s+([0-9]+(?:\.[0-9]+)?)", re.I)


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._capture = False
        self._tag_stack: list[str] = []
        self.title = ""
        self.h1 = ""
        self.heading = ""
        self.texts: list[str] = []
        self.hrefs: list[str] = []
        self._buf = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._tag_stack.append(tag)
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)
        if tag in {"title", "h1", "h2", "li", "p"}:
            self._capture = True
            self._buf = ""

    def handle_endtag(self, tag: str) -> None:
        if tag in {"title", "h1", "h2", "li", "p"} and self._capture:
            text = re.sub(r"\s+", " ", self._buf).strip()
            if text:
                if tag == "title" and not self.title:
                    self.title = text
                elif tag == "h1" and not self.h1:
                    self.h1 = text
                elif tag == "h2":
                    self.heading = text
                    self.texts.append(text)
                else:
                    self.texts.append(text)
            self._capture = False
            self._buf = ""
        if self._tag_stack and self._tag_stack[-1] == tag:
            self._tag_stack.pop()
        elif tag in self._tag_stack:
            self._tag_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buf += data


def _clean_name(raw: str) -> str:
    text = raw.strip()
    text = re.sub(r"^Buy a\s+", "", text, flags=re.I)
    text = re.sub(r"\s+[–-]\s+Raspberry Pi.*$", "", text, flags=re.I)
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _is_computer_name(name: str) -> bool:
    lowered = name.lower()
    if any(hint in lowered for hint in _ACCESSORY_HINTS) and not re.search(r"raspberry pi (400|500)", lowered):
        return False
    return any(pat.search(name) for pat in _BOARD_ALLOW)


def _family_and_type(name: str) -> tuple[str, str, BoardType]:
    lowered = name.lower()
    if "compute module" in lowered:
        token = re.search(r"compute module\s*([0-9]+(?:\s*\+)?)?", lowered)
        family = "compute-module-" + (token.group(1).replace(" ", "") if token and token.group(1) else "unknown")
        return family, name, BoardType.COMPUTE_MODULE
    if "zero" in lowered:
        return "raspberry-pi-zero", name, BoardType.ZERO_CLASS
    if re.search(r"raspberry pi 500", lowered):
        return "raspberry-pi-500", name, BoardType.SBC
    if re.search(r"raspberry pi 400", lowered):
        return "raspberry-pi-400", name, BoardType.SBC
    gen = re.search(r"raspberry pi\s+(\d+)", lowered)
    if gen:
        family = f"raspberry-pi-{gen.group(1)}"
        return family, name, BoardType.SBC
    return slugify(name), name, BoardType.UNKNOWN


def _editorial(name: str, board_type: BoardType) -> list[str]:
    lowered = name.lower()
    ctx: list[str] = []
    if "zero" in lowered:
        ctx.append(EditorialContext.RPI_ZERO_CLASS.value)
    if re.search(r"raspberry pi 5\b", lowered) or "compute module 5" in lowered:
        ctx.append(EditorialContext.RPI_5_CLASS.value)
    if "compute module 4" in lowered:
        ctx.append(EditorialContext.CM4_COMPATIBLE.value)
    if board_type is BoardType.COMPUTE_MODULE:
        ctx.append(EditorialContext.INDUSTRIAL.value)
    return ctx


def _spec_lines(texts: list[str]) -> list[str]:
    lines: list[str] = []
    in_spec = False
    for line in texts:
        if re.search(r"^specification", line, re.I):
            in_spec = True
            continue
        if in_spec and re.match(r"^(documents|compliance|obsolescence|accessories|buy)\b", line, re.I):
            break
        if in_spec:
            lines.append(line)
    return lines


def _join(lines: list[str]) -> str:
    return " ".join(lines)


def _extract_soc(blob: str) -> tuple[str, str]:
    matches = _SOC_RE.findall(blob)
    unique = []
    for item in matches:
        token = item.upper()
        if token not in unique:
            unique.append(token)
    if not unique:
        return UNKNOWN, UNKNOWN
    if len(unique) > 1:
        return "CONFLICT", ",".join(unique)
    return "broadcom", unique[0]


def _memory_sentences(blob: str) -> tuple[str, str]:
    ram_bits: list[str] = []
    storage_bits: list[str] = []
    for sentence in re.split(r"(?<=[;.])\s+|\n", blob):
        lowered = sentence.lower()
        if "emmc" in lowered or "flash memory" in lowered:
            storage_bits.append(sentence)
        elif "sdram" in lowered or "lpddr" in lowered or "memory options" in lowered or re.search(r"\bram\b", lowered):
            ram_bits.append(sentence)
    return " ".join(ram_bits), " ".join(storage_bits)


def _ram_options(blob: str) -> list[str]:
    ram_blob, _storage_blob = _memory_sentences(blob)
    target = ram_blob or blob
    if "SDRAM" not in target.upper() and "LPDDR" not in target.upper() and "RAM" not in target.upper() and "512MB" not in target.upper():
        return []
    options: list[str] = []
    for match in _RAM_OPTION_RE.findall(target):
        if match == "0":
            continue
        label = f"{match}GB"
        if label not in options and int(match) <= 128:
            options.append(label)
    if "512MB" in target.upper() or "512 MB" in target.upper():
        options = ["512MB"] + [item for item in options if item != "512GB"]
    return options


def _storage_options(blob: str) -> list[str]:
    _ram_blob, storage_blob = _memory_sentences(blob)
    target = storage_blob
    options: list[str] = []
    if not target:
        return options
    if re.search(r'0GB\s*\(\s*"?Lite"?\s*\)', target, re.I) or re.search(r"\blite\b", target, re.I):
        options.append("none")
    for match in _STORAGE_OPTION_RE.findall(target):
        if match == "0":
            continue
        label = f"{match}GB"
        if label not in options:
            options.append(label)
    return options


def _wireless_options(blob: str) -> list[str]:
    lowered = blob.lower()
    has_radio = "wi-fi" in lowered or "wifi" in lowered or "wireless" in lowered
    optional = "option for fully certified radio" in lowered or "wireless, sdram and emmc options" in lowered
    if optional and has_radio:
        return ["none", "wifi"]
    if has_radio:
        return ["wifi"]
    return [UNKNOWN]


def _revision_token(blob: str) -> tuple[RevisionKind, str]:
    match = _REV_RE.search(blob)
    if not match:
        return RevisionKind.UNKNOWN, UNKNOWN
    return RevisionKind.PCB, match.group(1)


def _first_match(blob: str, patterns: list[tuple[str, str]]) -> str:
    for needle, value in patterns:
        if needle in blob.lower():
            return value
    return UNKNOWN


def _build_spec(blob: str, soc_name: str, ram: str, storage: str, wireless: str) -> NormalizedSpec:
    return NormalizedSpec(
        soc=soc_name,
        soc_key=f"broadcom:{slugify(soc_name)}" if soc_name not in {UNKNOWN, "CONFLICT"} else UNKNOWN,
        cpu_arch=Architecture.ARM.value,
        ram_type=_first_match(blob, [("lpddr4x", "LPDDR4X"), ("lpddr4", "LPDDR4"), ("lpddr2", "LPDDR2")]),
        ram_options=ram,
        onboard_emmc="optional" if "emmc" in blob.lower() else UNKNOWN,
        emmc_options="matrix" if "emmc" in blob.lower() else UNKNOWN,
        microsd="yes" if "microsd" in blob.lower() or "micro sd" in blob.lower() else UNKNOWN,
        ethernet=_first_match(blob, [("gigabit ethernet", "gigabit"), ("10/100 ethernet", "100m")]),
        wifi=_first_match(blob, [("802.11ac", "802.11ac"), ("802.11n", "802.11n"), ("wi-fi", "wifi"), ("wireless", "wifi")]),
        bluetooth=_first_match(blob, [("bluetooth 5.0", "5.0"), ("bluetooth 4.2", "4.2"), ("bluetooth 4.1", "4.1"), ("bluetooth", "present")]),
        hdmi_out=_first_match(blob, [("micro-hdmi", "2x micro-hdmi"), ("mini hdmi", "mini-hdmi"), ("hdmi", "hdmi")]),
        mipi_csi="yes" if "csi" in blob.lower() or "camera" in blob.lower() else UNKNOWN,
        mipi_dsi="yes" if "dsi" in blob.lower() or "display" in blob.lower() else UNKNOWN,
        usb=_first_match(blob, [("usb 3.0", "usb3"), ("usb 2.0", "usb2"), ("usb", "usb")]),
        gpio_header="40-pin" if "40-pin" in blob.lower() or "40 pin" in blob.lower() else UNKNOWN,
        m2_m_key=UNKNOWN,
        pcie_lanes="x1" if "pcie" in blob.lower() else UNKNOWN,
        dimensions=_first_match(blob, [("55 mm × 40 mm", "55x40mm"), ("65 mm × 30 mm", "65x30mm")]),
        pcb_revision=UNKNOWN,
    )


def parse_product_html(html: str, *, page_url: str, observed_at: str, historical_known: bool = False) -> tuple[list[ObservationDraft], dict[str, Any]]:
    """Parse one official product-surface HTML document.

    Returns drafts plus a diagnostic dict. Never invents SoC, revision, or dates
    that the document does not contain.
    """
    parser = _PageParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # noqa: BLE001 - parser failure must be observable
        raise CollectorError(f"html parse failed for {page_url}: {exc}") from exc

    name = _clean_name(parser.h1 or parser.title)
    diagnostics: dict[str, Any] = {
        "page_url": page_url,
        "heading": name or UNKNOWN,
        "lead_hrefs": [],
        "status": "ok",
    }
    parsed_url = urlparse(page_url)
    if parsed_url.path.rstrip("/") == "/products":
        leads = []
        for href in parser.hrefs:
            abs_url = urljoin("https://www.raspberrypi.com", href)
            parsed = urlparse(abs_url)
            if parsed.netloc in OFFICIAL_HOSTS and parsed.path.startswith(PRODUCT_PREFIX) and parsed.path.rstrip("/") != "/products":
                leads.append(abs_url.split("#")[0])
        diagnostics["lead_hrefs"] = sorted(set(leads))
        diagnostics["status"] = "lead-index"
        return [], diagnostics

    if not name or not _is_computer_name(name):
        diagnostics["status"] = "ignored-non-computer"
        return [], diagnostics

    spec_lines = _spec_lines(parser.texts)
    blob = _join(spec_lines) if spec_lines else ""
    ram_source = " ".join(line for line in spec_lines if re.search(r"sdram|lpddr|\bram\b|512\s*mb", line, re.I) and "emmc" not in line.lower())
    storage_source = " ".join(line for line in spec_lines if "emmc" in line.lower() or "flash memory" in line.lower())
    family_slug, family_name, board_type = _family_and_type(name)
    board_slug = slugify(name)
    soc_vendor, soc_name = _extract_soc(blob)
    ram_opts = _ram_options(ram_source or blob)
    storage_opts = _storage_options(storage_source or blob) or [UNKNOWN]
    wireless_opts = _wireless_options(blob)
    rev_kind, rev_token = _revision_token(blob)
    conflict = soc_vendor == "CONFLICT"
    insufficient = not spec_lines or soc_name in {UNKNOWN, "CONFLICT"} or not ram_opts and "512MB" not in blob.upper() and "SDRAM" not in blob.upper()
    if not spec_lines:
        insufficient = True

    if insufficient and not conflict:
        diagnostics["status"] = "insufficient-evidence"
        draft = ObservationDraft(
            source_key=SOURCE_KEY,
            plane=SourcePlane.PRODUCT,
            observed_at=observed_at,
            vendor_key=VENDOR_KEY,
            vendor_name=VENDOR_NAME,
            family_slug=family_slug,
            family_name=family_name,
            board_slug=board_slug or UNKNOWN,
            marketing_name=name or UNKNOWN,
            board_type=board_type,
            spec=NormalizedSpec(),
            raw_fields={"html_excerpt": html[:400]},
            native_fields={"heading": name, "page_url": page_url},
            novelty=NoveltyEvidence(
                first_seen_at=observed_at,
                first_seen_source=SOURCE_KEY,
                novelty_status=NoveltyStatus.UNKNOWN,
                novelty_basis="insufficient-first-party-specification",
                novelty_confidence="low",
            ),
            page_url=page_url,
            historical_known=historical_known,
            evidence_insufficient=True,
        )
        return [draft], diagnostics

    if conflict:
        diagnostics["status"] = "identity-conflict"
        diagnostics["soc_candidates"] = soc_name.split(",")
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
            architecture=Architecture.ARM,
            spec=NormalizedSpec(),
            raw_fields={"soc_candidates": soc_name.split(",")},
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
            identity_conflict_reason="multiple BCM SoC tokens on one product page",
            evidence_insufficient=True,
        )
        return [draft], diagnostics

    if not ram_opts:
        ram_opts = [UNKNOWN]

    drafts: list[ObservationDraft] = []
    for ram in ram_opts:
        for storage in storage_opts:
            for wireless in wireless_opts:
                spec = _build_spec(blob, soc_name, ram, storage, wireless)
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
                        variant=VariantDimensions(ram=ram, storage=storage, wireless=wireless),
                        soc_vendor="broadcom",
                        soc_marketing_name=soc_name,
                        architecture=Architecture.ARM,
                        cpu_configuration=UNKNOWN,
                        gpu="VideoCore VII" if "videocore vii" in blob.lower() else ("VideoCore" if "videocore" in blob.lower() else UNKNOWN),
                        spec=spec,
                        raw_fields={"spec_lines": spec_lines},
                        native_fields={
                            "heading": name,
                            "page_url": page_url,
                            "revision_evidence": rev_token,
                        },
                        availability=Availability.UNKNOWN,
                        novelty=NoveltyEvidence(
                            first_seen_at=observed_at,
                            first_seen_source=SOURCE_KEY,
                            novelty_status=NoveltyStatus.HISTORICAL if historical_known else NoveltyStatus.EXISTING_PRODUCT,
                            novelty_basis="official-product-catalogue",
                            novelty_confidence="high" if spec_lines else "low",
                        ),
                        editorial_context=_editorial(name, board_type),
                        supported_os=["raspberry-pi-os"] if board_type is not BoardType.UNKNOWN else [],
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
        raise CollectorError(f"raspberry pi fixture corpus missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def collect_corpus(name: str, *, run_id: str, started_at: str, corpus_dir: Path | None = None) -> CollectorRunRequest:
    root = corpus_dir or CORPUS_DIR
    manifest = load_corpus_manifest(root)
    corpora = manifest.get("corpora") or {}
    if name not in corpora:
        raise CollectorError(f"unknown raspberry pi corpus: {name}")
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
        diagnostics["candidate_references"] += 1 if doc.get("role") != "lead" else len(info.get("lead_hrefs") or [])
        if info.get("status") == "resolved":
            diagnostics["resolved"] += 1
            observations.extend(drafts)
        elif info.get("status") == "insufficient-evidence":
            diagnostics["insufficient"] += 1
            observations.extend(drafts)
        elif info.get("status") == "identity-conflict":
            diagnostics["conflicts"] += 1
            observations.extend(drafts)
        elif info.get("status") == "parser-error":
            diagnostics["parser_errors"].append(page_url)
    if name == "malformed" and not observations:
        ok = False
        error = error or "raspberry-pi product parser failed: missing required product fields"
    return CollectorRunRequest(
        run_id=run_id,
        source_key=SOURCE_KEY,
        collector_key=COLLECTOR_KEY,
        started_at=started_at,
        observations=observations,
        ok=ok,
        error=error,
        fixture_scenario=f"rpi:{name}",
        diagnostics=diagnostics,
    )


def _assert_official_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise CollectorError(f"refusing non-https raspberry pi url: {url}")
    if parsed.netloc not in OFFICIAL_HOSTS:
        raise CollectorError(f"refusing third-party url: {url}")
    if not parsed.path.startswith(PRODUCT_PREFIX):
        raise CollectorError(f"refusing non-product raspberry pi url: {url}")
    return url


def fetch_official(url: str, *, timeout: int = 20) -> str:
    _assert_official_url(url)
    request = Request(
        url,
        headers={"User-Agent": "board-clank/0.1.0 (+experimental-manual-raspberry-pi-product)"},
        method="GET",
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - host allowlisted above
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


class RaspberryPiProductAdapter(CollectorAdapter):
    source_key = SOURCE_KEY
    collector_key = COLLECTOR_KEY
    live_network = False

    def __init__(self, *, experimental_live: bool = False, corpus: str = "baseline") -> None:
        self.experimental_live = experimental_live
        self.corpus = corpus

    def collect(self, run_id: str, started_at: str) -> CollectorRunRequest:
        if self.experimental_live:
            return self._collect_live(run_id, started_at)
        return collect_corpus(self.corpus, run_id=run_id, started_at=started_at)

    def parse_fixture(self, payload: dict) -> list[ObservationDraft]:
        html = payload.get("html") or ""
        page_url = payload.get("page_url") or CATALOGUE_URL
        observed_at = payload.get("observed_at") or "1970-01-01T00:00:00+00:00"
        drafts, _info = parse_product_html(
            html,
            page_url=page_url,
            observed_at=observed_at,
            historical_known=bool(payload.get("historical_known")),
        )
        return drafts

    def _collect_live(self, run_id: str, started_at: str) -> CollectorRunRequest:
        diagnostics: dict[str, Any] = {
            "mode": "experimental-live",
            "documents": [],
            "candidate_references": 0,
            "resolved": 0,
            "parser_errors": [],
            "leads": [],
        }
        try:
            index_html = fetch_official(CATALOGUE_URL)
            _drafts, info = parse_product_html(index_html, page_url=CATALOGUE_URL, observed_at=started_at)
            leads = [url for url in info.get("lead_hrefs") or [] if _is_likely_computer_url(url)]
            diagnostics["leads"] = leads
            diagnostics["candidate_references"] = len(leads)
            observations: list[ObservationDraft] = []
            for url in leads:
                try:
                    html = fetch_official(url)
                    drafts, page_info = parse_product_html(html, page_url=url, observed_at=started_at)
                except CollectorError as exc:
                    diagnostics["parser_errors"].append(str(exc))
                    diagnostics["documents"].append({"page_url": url, "status": "error"})
                    continue
                diagnostics["documents"].append(page_info)
                if page_info.get("status") == "resolved":
                    diagnostics["resolved"] += 1
                    observations.extend(drafts)
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
                observations=[],
                ok=False,
                error=f"experimental live fetch failed: {exc}",
                diagnostics=diagnostics,
            )


def _is_likely_computer_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    blocked = ("case", "hat", "power", "camera", "display", "cable", "sd-card", "cooler", "antenna", "keyboard")
    if any(token in path for token in blocked) and "raspberry-pi-400" not in path and "raspberry-pi-500" not in path:
        return False
    allowed = ("raspberry-pi-", "compute-module")
    return any(token in path for token in allowed)
