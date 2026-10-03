"""Manual, experimental FriendlyELEC PRODUCT evidence; never wiki/download ingestion.

See docs/FOUNDATION_7A_RESEARCH.txt. Purchase rows are paired configurations;
accessory options are never expanded into a Cartesian board matrix.
"""
from __future__ import annotations

import hashlib
import json
import re
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from board_clank.collectors.base import CollectorAdapter, CollectorError
from board_clank.identity import UNKNOWN, VariantDimensions, slugify
from board_clank.models import CollectorRunRequest, NormalizedSpec, NoveltyEvidence, ObservationDraft
from board_clank.taxonomy import Architecture, Availability, BoardType, NoveltyStatus, SourcePlane

SOURCE_KEY = 'friendlyelec-product'
BASE = 'https://www.friendlyelec.com/'
CORPUS_DIR = Path(__file__).resolve().parents[1] / 'fixture_data/friendlyelec_product'
INDEXES = [BASE + 'index.php?route=product/category&path=' + c for c in ('69', '60')]
SOC = re.compile(r'\b(RK\d{4}[A-Z0-9]*|H[23568]|A64|S5P\d+|Exynos\d+|S905[A-Z0-9]*)\b', re.I)


def _soc_vendor(soc):
    if soc.startswith('RK'):
        return 'rockchip'
    if soc in {'H2', 'H3', 'H5', 'H6', 'H8', 'A64'}:
        return 'allwinner'
    if soc.startswith(('S5P', 'EXYNOS')):
        return 'samsung'
    return 'amlogic' if soc.startswith('S905') else UNKNOWN


def text(html: str) -> str:
    return re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]+>', ' ', html))).strip()


def official_url(url: str) -> str:
    p = urlparse(url)
    if p.scheme != 'https' or p.netloc != 'www.friendlyelec.com' or p.fragment:
        raise CollectorError('refusing non-catalogue FriendlyELEC URL')
    q = parse_qs(p.query)
    if p.path not in ('/', '/index.php') or any(len(v) != 1 for v in q.values()):
        raise CollectorError('invalid catalogue route')
    if p.path == '/' and not q:
        return BASE
    route = q.get('route', [''])[0]
    if route == 'product/product' and q.get('product_id', [''])[0].isdigit():
        return BASE + 'index.php?' + urlencode({'route': route, 'product_id': q['product_id'][0]})
    if route == 'product/category' and q.get('path', [''])[0] in ('60', '69'):
        page = q.get('page', ['1'])[0]
        if page.isdigit() and 1 <= int(page) <= 10:
            return BASE + 'index.php?' + urlencode({'route': route, 'path': q['path'][0], 'page': page})
    raise CollectorError('unsupported FriendlyELEC surface')


class _Redirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        official_url(newurl)  # validate BEFORE following, not after fetching
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str) -> dict:
    url = official_url(url)
    with build_opener(_Redirect()).open(Request(url, headers={
        'User-Agent': 'BoardClank/0.1 (experimental-manual-friendlyelec-product)'
    }), timeout=30) as response:
        body = response.read(4_000_001)
        if len(body) > 4_000_000:
            raise CollectorError('FriendlyELEC response exceeds size limit')
        final = official_url(response.geturl())
        return dict(requested_url=url, final_url=final, status=response.status,
                    redirected=url != final, raw_body_hash=hashlib.sha256(body).hexdigest(),
                    text=body.decode('utf-8', 'replace'))


def links(html: str, url: str) -> list[str]:
    found = set()
    for href in re.findall(r'href=["\']([^"\']+)["\']', html, re.I):
        try:
            candidate = official_url(urljoin(url, unescape(href)))
        except CollectorError:
            continue
        if candidate != BASE:
            found.add(candidate)
    return sorted(found)


def parse_product_html(html: str, *, page_url: str, observed_at: str, historical_known=False):
    url = official_url(page_url)
    info = {'page_url': url, 'status': 'rejected', 'lead_hrefs': []}
    if 'product_id' not in parse_qs(urlparse(url).query):
        info.update(status='lead-index', lead_hrefs=links(html, url))
        return [], info
    headings = re.findall(r'<h1\b[^>]*>(.*?)</h1>', html, re.S | re.I)
    names = {text(h) for h in headings}
    if len(names) != 1:
        info['status'] = 'insufficient-page'
        return [], info
    name = names.pop()
    info['heading'] = name
    if re.search(r'\b(case|heatsink|heat sink|camera|display|dock|kit|carrier|shield|power|flash|hat|LCD)\b', name, re.I):
        return [], info
    # Whole heading gate, not a board name mentioned inside an accessory title.
    if not re.fullmatch(r'(?:NanoPi|NanoPC)[ -][A-Za-z0-9-]+(?: (?:Plus|Core|Core-LTS|Air-LTS))?|CM\d+(?: Plus)?|SOM-[A-Za-z0-9-]+', name):
        return [], info
    rows = [text(r) for r in re.findall(r'<tr\b[^>]*>(.*?)</tr>', html, re.S | re.I)]
    cpu = [r for r in rows if re.match(r'^(CPU|SoC)\b', r, re.I)]
    candidates = sorted({m.upper() for r in cpu for m in SOC.findall(r)})
    cpu_evidence = list(cpu)
    # Product Code is context-labelled processor/model evidence, not arbitrary prose.
    code = re.search(r'Product Code\s*:\s*(.*?)</li>', html, re.S | re.I)
    if not candidates and code:
        cpu_evidence.append('Product Code: ' + text(code[1]))
        candidates = sorted({m.upper() for m in SOC.findall(text(code[1]))})
    soc = candidates[0] if len(candidates) == 1 else UNKNOWN
    vendor = _soc_vendor(soc)
    cpu_evidence = sorted(set(cpu_evidence))
    soc_candidates = sorted(f'{_soc_vendor(candidate)}:{slugify(candidate)}' for candidate in candidates)
    ramrows = ' '.join(r for r in rows if re.match(r'^(Memory|RAM)\b', r, re.I))
    storage = ' '.join(r for r in rows if re.match(r'^Storage\b', r, re.I))
    ramtype = re.findall(r'\b(?:LP)?DDR[345]X?\b', ramrows, re.I)
    labels = [text(r) for r in re.findall(r'<label\s*>(.*?)</label>', html, re.S | re.I)]
    pairs = set()
    for label in labels:
        ram = re.search(r'\b(\d+)\s*GB\s+RAM\b', label, re.I)
        if not ram:
            continue  # independent accessory controls do not describe board memory
        emmc = re.search(r'\b(\d+)\s*GB\s+eMMC\b', label, re.I)
        cap = emmc[1] + 'GB eMMC' if emmc else ('none' if re.search(r'no eMMC', label, re.I) else UNKNOWN)
        pairs.add((ram[1] + 'GB', cap))
    if not pairs:
        capacities = sorted(set(re.findall(r'\b(\d+)\s*GB\b', ramrows, re.I)))
        # Do not invent combinations from independent spec capacity lists.
        capacity = capacities[0] + 'GB' if len(capacities) == 1 else UNKNOWN
        emmc = re.findall(r'\b(\d+)\s*GB\s+eMMC\b', storage, re.I)
        pairs.add((capacity, emmc[0]+'GB eMMC' if len(set(emmc)) == 1 else UNKNOWN))
    wireless_rows = ' '.join(r for r in rows if re.match(r'^(Connectivity|Wi-?Fi|Wireless|Bluetooth)\b', r, re.I))
    built_in_wifi = bool(re.search(r'(?:Wi-?Fi|Wireless).*?802\.11|On.Board Wi-Fi', wireless_rows, re.I))
    wireless = 'built-in' if built_in_wifi else ('optional' if any(re.search(r'Wi-?Fi Module', x, re.I) for x in labels) else UNKNOWN)
    bt = re.search(r'Bluetooth\s*:?\s*([0-9]+\.[0-9]+)', wireless_rows, re.I)
    listed_emmc = set(re.findall(r'\b(\d+)\s*GB', storage, re.I)) if re.search('eMMC',storage,re.I) else set()
    selected_emmc = {re.match(r'\d+',cap)[0] for _,cap in pairs if re.match(r'\d+',cap)}
    warnings = ['selector-spec-storage-disagreement'] if listed_emmc and selected_emmc-listed_emmc else []
    info.update(evidence_warnings=warnings, spec_storage=storage, paired_options=sorted(pairs),
                wireless_evidence=wireless_rows, cpu_evidence=cpu_evidence, soc_candidates=soc_candidates,
                evidence_roles=['PRODUCT_IDENTITY','LABELLED_SPEC','PAIRED_PURCHASE_OPTIONS'])
    family = 'compute-modules' if name.startswith(('CM', 'SOM-')) or 'Core' in name else ('nanopc' if name.startswith('NanoPC') else 'nanopi')
    typ = BoardType.COMPUTE_MODULE if family == 'compute-modules' else BoardType.SBC
    drafts = []
    for ram, emmc in sorted(pairs):
        drafts.append(ObservationDraft(
            source_key=SOURCE_KEY, plane=SourcePlane.PRODUCT, observed_at=observed_at,
            vendor_key='friendlyelec', vendor_name='FriendlyELEC', family_slug=family,
            family_name=family, board_slug=slugify(name), marketing_name=name, board_type=typ,
            variant=VariantDimensions(ram=ram, storage=emmc, wireless='wifi' if built_in_wifi else UNKNOWN), soc_vendor=vendor,
            soc_marketing_name=soc, architecture=Architecture.UNKNOWN,
            spec=NormalizedSpec(soc=soc, soc_key=f'{vendor}:{slugify(soc)}' if soc != UNKNOWN else UNKNOWN,
                ram_type='/'.join(sorted(set(x.upper() for x in ramtype))) or UNKNOWN,
                ram_options=','.join(sorted({x[0] for x in pairs})),
                emmc_options=','.join(sorted({x[1] for x in pairs})), wifi=wireless,
                bluetooth=bt[1] if bt else UNKNOWN,
                microsd='yes' if re.search('MicroSD', storage, re.I) else UNKNOWN),
            native_fields={'heading': name, 'page_url': url},
            raw_fields={'paired_options': sorted(pairs), 'cpu_evidence': cpu_evidence, 'soc_candidates': soc_candidates},
            page_url=url, historical_known=historical_known,
            novelty=NoveltyEvidence(first_seen_at=observed_at, first_seen_source=SOURCE_KEY,
                novelty_status=NoveltyStatus.EXISTING_PRODUCT, novelty_basis='first-party-catalogue-not-launch'),
            availability=Availability.UNKNOWN, evidence_insufficient=soc == UNKNOWN,
            identity_conflict=len(candidates)>1, identity_conflict_reason='multiple labelled application SoCs' if len(candidates)>1 else UNKNOWN,
        ))
    info.update(status='identity-conflict' if len(candidates)>1 else ('insufficient-evidence' if soc==UNKNOWN else 'resolved'),
                semantic_evidence_hash=hashlib.sha256(json.dumps([d.canonical_payload() for d in drafts],sort_keys=True,default=str).encode()).hexdigest())
    return drafts, info


class FriendlyElecProductAdapter(CollectorAdapter):
    source_key = collector_key = SOURCE_KEY
    supports_experimental_live = True
    live_network = False

    def __init__(self, *, experimental_live=False, corpus='baseline'):
        self.experimental_live, self.corpus = experimental_live, corpus

    def collect(self, run_id, started_at):
        observations, documents, fetches, errors = [], [], [], []
        queue = list(INDEXES) if self.experimental_live else []
        seen = set()
        if not self.experimental_live:
            manifest = json.loads((CORPUS_DIR/'manifest.json').read_text())
            entries = manifest['corpora'][self.corpus]['documents']
            queue = [e['page_url'] for e in entries]
            files = {official_url(e['page_url']): CORPUS_DIR/e['file'] for e in entries}
        while queue:
            url = official_url(queue.pop(0))
            if url in seen:
                continue
            seen.add(url)
            if len(seen)>150:
                errors.append('bounded discovery limit exceeded')
                break
            try:
                if self.experimental_live:
                    meta = fetch(url)
                    html = meta.pop('text')
                    fetches.append(dict(meta, ok=True))
                else:
                    html = files[url].read_text(encoding='utf-8')
                drafts, info = parse_product_html(html, page_url=url, observed_at=started_at)
                if info['status']=='insufficient-page':
                    errors.append({'url':url,'error':'missing or ambiguous product heading'})
                if info['status']=='lead-index' and not info['lead_hrefs']:
                    errors.append({'url':url,'error':'empty catalogue discovery'})
                observations.extend(drafts)
                documents.append(info)
                if self.experimental_live and info['status']=='lead-index':
                    queue.extend(u for u in info['lead_hrefs'] if u not in seen)
            except (OSError, ValueError, CollectorError) as exc:
                errors.append({'url':url,'error':str(exc)})
        return CollectorRunRequest(run_id=run_id,source_key=SOURCE_KEY,collector_key=SOURCE_KEY,
            # Atomic source admission: a partial fetch/parser run must not close
            # conditions merely because a missing page could not report them.
            started_at=started_at,observations=observations,ok=bool(observations) and not errors,
            error='incomplete first-party collection' if errors else (None if observations else 'no usable first-party observations'),
            diagnostics={'documents':documents,'fetches':fetches,'parser_errors':errors,'leads':sorted(seen)})
