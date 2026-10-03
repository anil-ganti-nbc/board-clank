"""Disabled Forlinx PRODUCT adapter. Scope comes from current SBC catalogue cards.

See docs/FOUNDATION_9A_RESEARCH.txt. Application silicon and memory pairings
must be explicit; multi-chip option lists remain unresolved, never combined.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
from html import unescape
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from board_clank.collectors.base import CollectorAdapter, CollectorError
from board_clank.identity import UNKNOWN, VariantDimensions, slugify
from board_clank.models import CollectorRunRequest, NormalizedSpec, NoveltyEvidence, ObservationDraft
from board_clank.taxonomy import Architecture, BoardType, NoveltyStatus, SourcePlane

SOURCE_KEY = 'forlinx-product'
BASE = 'https://www.forlinx.net'
INDEX = BASE + '/product-list-2.html'
CORPUS_DIR = Path(__file__).resolve().parents[1] / 'fixture_data/forlinx_product'
MODEL = re.compile(r'^(OK[A-Za-z0-9-]+)\s+(?:Mini\s+)?Single Board Computer(?:\s*\([^)]*\))?$', re.I)


def text(html: str) -> str:
    """Decode public Cloudflare presentation strings before semantic projection."""
    def decode(match):
        raw = bytes.fromhex(match[2])
        return ''.join(chr(c ^ raw[0]) for c in raw[1:])
    html = re.sub(r'<(span|a)\b[^>]*data-cfemail=[\"\']([0-9a-f]+)[\"\'][^>]*>.*?</\1>',
                  decode, html, flags=re.I | re.S)
    return re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]*>', ' ', html))).strip()


def official_url(url: str) -> str:
    p = urlparse(url)
    if p.scheme != 'https' or p.netloc != 'www.forlinx.net' or p.query or p.fragment:
        raise CollectorError('Forlinx PRODUCT host/protocol refused')
    if re.fullmatch(r'/product-list-2(?:-[1-9]\d*)?\.html', p.path):
        return BASE + p.path
    if re.fullmatch(r'/product/[a-z0-9._-]+-\d+\.html', p.path):
        return BASE + p.path
    raise CollectorError('Forlinx surface outside PRODUCT scope')


class _Redirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        official_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str) -> dict:
    url = official_url(url)
    attempts = []
    for attempt in range(2):
        try:
            with build_opener(_Redirect()).open(Request(url, headers={
                'User-Agent': 'BoardClank/0.1 (manual experimental Forlinx PRODUCT)'}), timeout=60) as r:
                body = r.read(4_000_001)
                if len(body) > 4_000_000:
                    raise CollectorError('Forlinx page size limit')
                final = official_url(r.url)
                return {'text': body.decode('utf-8'), 'raw_body': body,
                        'requested_url': url, 'final_url': final, 'status': r.status,
                        'redirected': final != url, 'bytes': len(body),
                        'raw_body_hash': hashlib.sha256(body).hexdigest(),
                        'attempt_errors': attempts}
        except (OSError, ValueError) as exc:
            attempts.append(str(exc))
            if attempt == 1:
                raise
    raise CollectorError('unreachable fetch state')


def catalogue(html: str, page_url: str) -> tuple[dict[str, str], list[str], list[dict]]:
    page_url = official_url(page_url)
    title = re.search(r'<title\b[^>]*>(.*?)</title>', html, re.I | re.S)
    if not title or not text(title[1]).startswith('Single Board Computer'):
        raise CollectorError('missing explicit SBC catalogue title')
    cards, excluded = {}, []
    for link, heading in re.findall(r'<a\b[^>]*href=[\"\']([^\"\']+)[\"\'][^>]*>\s*<h3\b[^>]*>(.*?)</h3>', html, re.I | re.S):
        url = official_url(urljoin(page_url, link))
        label = text(heading)
        match = MODEL.fullmatch(label)
        if not match or re.search(r'Jetson|NVIDIA|\bFET', label, re.I):
            excluded.append({'url': url, 'heading': label, 'reason': 'not-explicit-application-sbc'})
            continue
        if url in cards and cards[url] != match[1]:
            raise CollectorError('conflicting catalogue identity')
        cards[url] = match[1]
    # Only pagination controls, never broad category/sidebar navigation.
    pages = set()
    for block in re.findall(r'<ul\b[^>]*class=[\"\']page[\"\'][^>]*>(.*?)</ul>', html, re.I | re.S):
        for link in re.findall(r'href=[\"\']([^\"\']+)[\"\']', block):
            if re.fullmatch(r'/product-list-2-[1-9]\d*\.html', link):
                pages.add(official_url(urljoin(page_url, link)))
    if not cards:
        raise CollectorError('empty current SBC catalogue')
    return cards, sorted(pages), excluded


def hero(html: str) -> tuple[str, dict[str, str]]:
    blocks = re.findall(r'<div\b[^>]*class=[\"\']product-cp[\"\'][^>]*>(.*?)</div>', html, re.I | re.S)
    if len(blocks) != 1:
        raise CollectorError('missing or ambiguous product hero')
    headings = re.findall(r'<h3\b[^>]*>(.*?)</h3>', blocks[0], re.I | re.S)
    if len(headings) != 1:
        raise CollectorError('missing or ambiguous product heading')
    fields = {}
    for paragraph in re.findall(r'<p\b[^>]*>(.*?)</p>', blocks[0], re.I | re.S):
        value = text(paragraph)
        match = re.fullmatch(r'(CPU|Architecture|Frequency|RAM|ROM|System)\s*:\s*(.*)', value, re.I)
        if match:
            key = match[1].lower()
            if key in fields:
                raise CollectorError('duplicate labelled product field')
            fields[key] = match[2]
    if 'cpu' not in fields or 'architecture' not in fields:
        raise CollectorError('missing labelled CPU/architecture evidence')
    return text(headings[0]), fields


def silicon(cpu: str) -> tuple[str, str]:
    """Whole labelled CPU value; no free-text or companion-chip matching."""
    patterns = (
        ('rockchip', r'(?:Rockchip\s+)?((?:RK\d{4}|RV\d{4})[A-Z]*)'),
        ('allwinner', r'(?:Allwinner\s+)?((?:T\d{1,3}|A\d{2})[A-Z]*)'),
        ('texas-instruments', r'(?:(?:TI|Texas Instruments)\s+)?(AM\d{4}[A-Z0-9]*)'),
        ('renesas', r'(?:Renesas\s+)?(RZ/G2L)'),
        ('starfive', r'(?:StarFive\s+)?(JH7110)'),
        ('nuvoton', r'(?:Nuvoton\s+)?(MA35D1)'),
        ('samsung', r'(?:Samsung\s+)?(S5P\d{4})'),
        ('nxp', r'(?:NXP\s+)?(LS\d{4}A|i\.MX\s*\d+(?:ULL|UltraLite|DualLite|\s*Quad|M\s+Mini|x)?)'),
    )
    for vendor, pattern in patterns:
        match = re.fullmatch(pattern, cpu, re.I)
        if match:
            soc = match[1]
            if vendor == 'nxp' and soc.lower().startswith('i.mx'):
                soc = re.sub(r'\s+', '', soc)
                soc = soc.replace('UltraLite', 'UL').replace('DualLite', 'DL').replace('Quad', 'Q')
            else:
                soc = soc.upper()
            return vendor, soc
    return UNKNOWN, UNKNOWN


def memory_pair(fields: dict[str, str]) -> VariantDimensions:
    ram, rom = fields.get('ram', ''), fields.get('rom', '')
    # One unconditional quantity each is the only observed binding contract.
    amounts = re.findall(r'\b\d+\s*(?:MB|GB)\b', ram, re.I)
    emmc = re.fullmatch(r'(\d+)\s*GB\s+eMMC', rom, re.I)
    if len(amounts) == 1 and emmc and not re.search(r'optional|/|,|，|\+', ram, re.I):
        return VariantDimensions(ram=re.sub(r'\s+', '', amounts[0]).upper(), storage=emmc[1] + 'GB eMMC')
    return VariantDimensions()


def parse_product_html(html: str, *, page_url: str, observed_at: str, catalogue_model: str | None = None):
    url = official_url(page_url)
    heading, fields = hero(html)
    info = {'page_url': url, 'heading': heading, 'status': 'rejected-non-sbc'}
    match = MODEL.fullmatch(heading)
    if not match or re.search(r'Jetson|NVIDIA', heading + ' ' + fields['cpu'], re.I):
        return [], info
    name = match[1]
    if not catalogue_model or name != catalogue_model:
        raise CollectorError('product lacks matching current catalogue identity')
    architecture = fields['architecture']
    if re.search(r'Cortex-M', architecture, re.I) and not re.search(r'(?:Cortex|Cotex)-A|\bA(?:35|53|55|72|76)\b', architecture, re.I):
        info['status'] = 'rejected-mcu-only'
        return [], info
    vendor, soc = silicon(fields['cpu'])
    arch = Architecture.RISCV if vendor == 'starfive' else (Architecture.ARM if soc != UNKNOWN else Architecture.UNKNOWN)
    projection = {'model': name, 'fields': fields}
    ram_types = re.findall(r'\b(?:LP)?DDR\d(?:L|X)?\b', fields.get('ram', ''), re.I)
    draft = ObservationDraft(source_key=SOURCE_KEY, plane=SourcePlane.PRODUCT, observed_at=observed_at,
        vendor_key='forlinx', vendor_name='Forlinx Embedded', family_slug='single-board-computers',
        family_name='Single Board Computers', board_slug=slugify(name), marketing_name=name,
        board_type=BoardType.SBC, variant=memory_pair(fields), soc_vendor=vendor,
        soc_marketing_name=soc, architecture=arch,
        spec=NormalizedSpec(soc=soc, soc_key=f'{vendor}:{slugify(soc)}' if soc != UNKNOWN else UNKNOWN,
            cpu_arch=arch.value, cpu_config=architecture or UNKNOWN, ram_type='/'.join(sorted(set(ram_types))) or UNKNOWN,
            ram_options=fields.get('ram', UNKNOWN), emmc_options=fields.get('rom', UNKNOWN),
            supported_os=fields.get('system', UNKNOWN)),
        native_fields={'model': name, 'product_url': url, 'product_summary': fields},
        raw_fields=fields, page_url=url, evidence_insufficient=soc == UNKNOWN,
        novelty=NoveltyEvidence(first_seen_at=observed_at, first_seen_source=SOURCE_KEY,
            novelty_status=NoveltyStatus.EXISTING_PRODUCT, novelty_basis='current-catalogue-not-launch'))
    info.update(status='resolved' if soc != UNKNOWN else 'insufficient', semantic_evidence=projection,
        semantic_evidence_hash=hashlib.sha256(json.dumps(projection, sort_keys=True).encode()).hexdigest())
    return [draft], info


class ForlinxProductAdapter(CollectorAdapter):
    source_key = collector_key = SOURCE_KEY
    supports_experimental_live = True
    live_network = False

    def __init__(self, *, experimental_live=False, corpus='baseline'):
        self.experimental_live, self.corpus = experimental_live, corpus

    def collect(self, run_id, started_at):
        observations, documents, fetches, errors, excluded = [], [], [], [], []
        cards, products, seen = {}, {}, set()

        def read(url):
            try:
                result = fetch(url)
                html = result.pop('text')
                result.pop('raw_body', None)
                return url, html, dict(result, ok=True), None
            except (OSError, ValueError, CollectorError) as exc:
                return url, None, {'requested_url': url, 'ok': False, 'error': str(exc)}, str(exc)

        def batch(urls):
            with ThreadPoolExecutor(max_workers=4) as pool:
                rows = list(pool.map(read, sorted(urls)))
            bodies = {}
            for url, html, receipt, error in rows:
                seen.add(url)
                fetches.append(receipt)
                if error:
                    errors.append({'url': url, 'error': error})
                else:
                    if receipt.get('final_url', url) != url:
                        raise CollectorError('current catalogue route redirected; linkage requires requalification')
                    bodies[url] = html
            if errors:
                raise CollectorError('required Forlinx page fetch failed')
            return bodies

        try:
            if self.experimental_live:
                indexes = batch([INDEX])
                initial_cards, pages, rejected = catalogue(indexes[INDEX], INDEX)
                # page 1 is an explicit alias of the already-read index, not a second input.
                pages = [p for p in pages if p != BASE + '/product-list-2-1.html']
                if len(pages) > 15:
                    raise CollectorError('excessive SBC catalogue pagination')
                indexes.update(batch(pages))
                for url, html in indexes.items():
                    found, _, rejected = catalogue(html, url)
                    excluded.extend(rejected)
                    for link, name in found.items():
                        if link in cards and cards[link] != name:
                            raise CollectorError('conflicting cross-page model identity')
                        cards[link] = name
                if len(cards) > 200 or len(set(cards.values())) != len(cards):
                    raise CollectorError('excessive or duplicate ambiguous model routes')
                products = batch(cards)
            else:
                manifest = json.loads((CORPUS_DIR / 'manifest.json').read_text(encoding='utf-8'))
                for entry in manifest['catalogues']:
                    found, _, rejected = catalogue((CORPUS_DIR / entry['file']).read_text(encoding='utf-8'), entry['page_url'])
                    cards.update(found)
                    excluded.extend(rejected)
                products = {entry['page_url']: (CORPUS_DIR / entry['file']).read_text(encoding='utf-8')
                            for entry in manifest['corpora'][self.corpus]}
                if set(cards) != set(products):
                    raise CollectorError('fixture catalogue/product coverage mismatch')
            for url, html in sorted(products.items()):
                drafts, info = parse_product_html(html, page_url=url, observed_at=started_at, catalogue_model=cards[url])
                observations.extend(drafts)
                documents.append(info)
        except (OSError, ValueError, KeyError, TypeError, CollectorError) as exc:
            errors.append({'error': str(exc)})
        return CollectorRunRequest(run_id=run_id, source_key=SOURCE_KEY, collector_key=SOURCE_KEY,
            started_at=started_at, observations=observations, ok=bool(observations) and not errors,
            error='incomplete Forlinx collection' if errors else (None if observations else 'no PRODUCT observations'),
            diagnostics={'documents': documents, 'fetches': fetches, 'errors': errors,
                         'discovered_urls': sorted(seen), 'catalogue_models': cards, 'excluded_cards': excluded})
