"""Khadas PRODUCT admission from current family links and server-rendered Wix data.

Research: docs/FOUNDATION_8A_RESEARCH.txt. No docs/download/forum ingestion.
Atomic collection; explicit productItems, never option Cartesian products.
"""
from __future__ import annotations

import hashlib
import json
import re
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from board_clank.collectors.base import CollectorAdapter, CollectorError
from board_clank.identity import UNKNOWN, VariantDimensions, slugify
from board_clank.models import CollectorRunRequest, NormalizedSpec, NoveltyEvidence, ObservationDraft
from board_clank.taxonomy import Architecture, Availability, BoardType, NoveltyStatus, RevisionKind, SourcePlane

SOURCE_KEY = 'khadas-product'
BASE = 'https://www.khadas.com'
CORPUS_DIR = Path(__file__).resolve().parents[1] / 'fixture_data/khadas_product'
INDEXES = [BASE+'/family', BASE+'/vim', BASE+'/edge']
MODEL = re.compile(r'(VIM\d+[A-Z]?|Edge(?:\d+|-V|-\d+L)?)', re.I)


def text(value):
    return re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]*>', ' ', value))).strip()


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.links, self.meta, self.warmups, self.anchors = [], {}, [], []
        self.anchor, self.anchor_text = None, []
        self.script, self.buffer = False, []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'a' and a.get('href'):
            self.links.append(a['href'])
            self.anchor, self.anchor_text = a['href'], []
        if tag == 'meta':
            self.meta[a.get('name', a.get('property', ''))] = a.get('content', '')
        if tag == 'script' and a.get('id') == 'wix-warmup-data':
            self.script, self.buffer = True, []

    def handle_data(self, data):
        if self.anchor is not None:
            self.anchor_text.append(data)
        if self.script:
            self.buffer.append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.anchor is not None:
            self.anchors.append((self.anchor, text(' '.join(self.anchor_text))))
            self.anchor = None
        if tag == 'script' and self.script:
            self.warmups.append(json.loads(''.join(self.buffer)))
            self.script = False


def official_url(url):
    p = urlparse(url)
    if p.scheme != 'https' or p.netloc != 'www.khadas.com' or p.query or p.fragment:
        raise CollectorError('Khadas PRODUCT URL refused')
    path = p.path.rstrip('/')
    if path in ('/family', '/vim', '/edge') or re.fullmatch(r'/(?:vim\d+[a-z]?|edge\d+|edge-v|edge-\d+l)', path):
        return BASE+path
    if re.fullmatch(r'/product-page/[a-z0-9-]+', path):
        return BASE+path
    raise CollectorError('Khadas surface outside PRODUCT scope')


class _Redirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        official_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url):
    url = official_url(url)
    with build_opener(_Redirect()).open(Request(url, headers={'User-Agent': 'BoardClank/0.1 (manual experimental Khadas PRODUCT)'}), timeout=30) as r:
        body = r.read(6_000_001)
        if len(body)>6_000_000:
            raise CollectorError('Khadas page size limit')
        final = official_url(r.url)
        return {'text': body.decode('utf-8'), 'requested_url': url, 'final_url': final,
                'status': r.status, 'redirected': url != final,
                'raw_body_hash': hashlib.sha256(body).hexdigest()}


def links(html, page_url):
    result = set()
    for href in Page(html).links:
        try:
            result.add(official_url(urljoin(page_url, href)))
        except CollectorError:
            pass
    return sorted(result)


def marketing_evidence(html, url):
    """Current marketing heading, never a navigation mention, owns scope."""
    names = {text(s) for s in re.findall(r'<h[123]\b[^>]*>(.*?)</h[123]>', html, re.S | re.I) if MODEL.fullmatch(text(s))}
    if len(names) != 1:
        raise CollectorError('missing or ambiguous Khadas marketing identity')
    name = names.pop()
    return {'name': name, 'url': official_url(url), 'description': Page(html).meta.get('description', '')}


def purchase_links(html, market):
    """Observed Buy Now / exact model cards, not arbitrary accessory navigation."""
    selected = set()
    for href, label in Page(html).anchors:
        if label.casefold() not in ('buy now', market['name'].casefold()):
            continue
        try:
            url = official_url(urljoin(market['url'],href))
        except CollectorError:
            continue
        if '/product-page/' in url:
            selected.add(url)
    if not selected:
        raise CollectorError('missing current product purchase link')
    return sorted(selected)


def _products(value):
    if isinstance(value, dict):
        if 'productItems' in value and 'urlPart' in value:
            yield value
        for v in value.values():
            yield from _products(v)
    elif isinstance(value, list):
        for v in value:
            yield from _products(v)


def product_data(html, url):
    products = [p for root in Page(html).warmups for p in _products(root)
                if url == BASE+'/product-page/'+p['urlPart']]
    if len(products) != 1:
        raise CollectorError('missing or ambiguous server-rendered product object')
    headings = {text(h) for h in re.findall(r'<h1\b[^>]*>(.*?)</h1>', html, re.S | re.I)}
    if headings != {products[0]['name']}:
        raise CollectorError('product heading/object mismatch')
    return products[0]


def silicon(description):
    # Processor-vendor labelled evidence, not free matching of companion chips.
    found = set()
    for match in re.finditer(r'\b(Amlogic|Rockchip|Rockhip)\s+((?:S\d|A\d|RK\d{4})[A-Z0-9]*)\b', description, re.I):
        before, after = description[max(0,match.start()-40):match.start()], description[match.end():match.end()+65]
        if re.search(r'\b(?:PMIC|PHY|codec|microcontroller|Wi-Fi|Bluetooth)\b', after[:22], re.I):
            continue
        if re.search(r'\b(?:SoC|CPU|processor|SBC)\b',before,re.I) or re.search(r'\b(?:SoC|CPU|Cortex|core)\b',after,re.I):
            found.add((match[1].lower().replace('rockhip','rockchip'),match[2].upper()))
    return sorted(found)


def _configuration_blocks(product):
    content = ' '.join(text(x['description']) for x in product.get('additionalInfo', [])
                       if re.search(r'model|^VIM|^Edge', x.get('title', ''), re.I))
    matches = list(re.finditer(r'\b(Basic|Pro|Max)\s*:', content, re.I))
    if not matches:
        return {'default': content}
    return {m[1].lower(): content[m.end():matches[i+1].start() if i+1<len(matches) else len(content)] for i,m in enumerate(matches)}


def parse_product_html(html, *, page_url, observed_at, marketing=None):
    url = official_url(page_url)
    product = product_data(html, url)
    name = product['name']
    info = {'page_url': url, 'heading': name, 'status': 'rejected-non-sbc'}
    if not MODEL.fullmatch(name):
        return [], info
    if not marketing or marketing['name'].casefold() != name.casefold():
        raise CollectorError('product lacks matching current family/marketing evidence')
    description = text(product['description'])
    candidates = silicon(description)
    if not candidates:
        candidates = silicon(marketing['description'])
    vendor, soc = candidates[0] if len(candidates)==1 else (UNKNOWN, UNKNOWN)
    blocks = _configuration_blocks(product)
    selections = {}
    for option in product['options']:
        for selection in option['selections']:
            if selection['id'] in selections:
                raise CollectorError('duplicate option selection ID')
            selections[selection['id']] = (option['title'], selection['value'])
    # v1.4 PCB status was corroborated by the linked first-party transition guide.
    revision = '1.4' if name=='VIM2' and re.search(r'Latest Changes\s*\(v1\.4\)', description) else UNKNOWN
    stock = {'in_stock': Availability.IN_STOCK, 'out_of_stock': Availability.OUT_OF_STOCK}
    projection = {'name': name, 'description': description,
                  'additional_info': [(x['title'], text(x['description'])) for x in product['additionalInfo']],
                  'options': sorted(selections.values()), 'currency': product.get('currency', UNKNOWN),
                  'stock': product.get('inventory', {}).get('status', UNKNOWN), 'items': []}
    drafts = []
    for item in product['productItems']:
        try:
            chosen = [selections[i] for i in item['optionsSelections']]
        except KeyError as exc:
            raise CollectorError('unbound product item selection') from exc
        label = ' / '.join(value for _,value in chosen)
        configs = re.findall(r'\b(Basic|Pro|Max)\b', label, re.I)
        config = configs[0].lower() if len(configs)==1 else 'default'
        block = blocks.get(config, '')
        ram = re.findall(r'\b(\d+)\s*GB\s+(?:LP)?DDR\dX?', block, re.I)
        emmc = re.findall(r'\b(\d+)\s*GB\s+eMMC\b', block, re.I)
        wifi = re.findall(r'\bAP\d+[A-Z]*\b', block)
        ramtype = re.findall(r'\b(?:LP)?DDR\dX?\b', block, re.I)
        # Package/SKU distinctions belong to VARIANT, not board-native fields.
        bundle = next((v for _,v in chosen if re.search(r'Kit|ARM PC|with NPU', v, re.I)), UNKNOWN)
        dimensions = VariantDimensions(ram=ram[0]+'GB' if len(set(ram))==1 else UNKNOWN,
            storage=emmc[0]+'GB eMMC' if len(set(emmc))==1 else UNKNOWN,
            wireless=wifi[0] if len(set(wifi))==1 else UNKNOWN,
            bundle=bundle, sku=item.get('sku') or UNKNOWN)
        evidence = {'selections': chosen, 'sku': item.get('sku'), 'price': item.get('price'),
                    'stock': item.get('inventory', {}).get('status', UNKNOWN), 'visible': item.get('isVisible')}
        projection['items'].append(evidence)
        if not item.get('isVisible', False):
            continue
        drafts.append(ObservationDraft(source_key=SOURCE_KEY, plane=SourcePlane.PRODUCT,
            observed_at=observed_at, vendor_key='khadas', vendor_name='Khadas',
            family_slug='vim' if name.upper().startswith('VIM') else 'edge',
            family_name='VIM' if name.upper().startswith('VIM') else 'Edge',
            board_slug=slugify(name), marketing_name=name, board_type=BoardType.SBC,
            revision_kind=RevisionKind.PCB if revision!=UNKNOWN else RevisionKind.UNKNOWN,
            revision_token=revision, variant=dimensions, soc_vendor=vendor, soc_marketing_name=soc,
            architecture=Architecture.ARM if soc!=UNKNOWN else Architecture.UNKNOWN,
            spec=NormalizedSpec(soc=soc, soc_key=f'{vendor}:{slugify(soc)}' if soc!=UNKNOWN else UNKNOWN,
                ram_type='/'.join(sorted(set(ramtype))) or UNKNOWN, pcb_revision=revision),
            native_fields={'heading':name,'product_url':url,'marketing_url':marketing['url']},
            raw_fields=evidence, page_url=url,
            availability=stock.get(projection['stock'], Availability.UNKNOWN),
            novelty=NoveltyEvidence(first_seen_at=observed_at,first_seen_source=SOURCE_KEY,
                novelty_status=NoveltyStatus.EXISTING_PRODUCT,novelty_basis='current-catalogue-not-launch'),
            evidence_insufficient=soc==UNKNOWN, identity_conflict=len(candidates)>1,
            identity_conflict_reason='conflicting labelled application SoCs' if len(candidates)>1 else UNKNOWN))
    if not drafts:
        raise CollectorError('no visible product items')
    info.update(status='conflict' if len(candidates)>1 else ('insufficient' if soc==UNKNOWN else 'resolved'),
                semantic_evidence=projection,
                semantic_evidence_hash=hashlib.sha256(json.dumps(projection,sort_keys=True).encode()).hexdigest())
    return drafts, info


class KhadasProductAdapter(CollectorAdapter):
    source_key = collector_key = SOURCE_KEY
    supports_experimental_live = True
    live_network = False

    def __init__(self, *, experimental_live=False, corpus='baseline'):
        self.experimental_live, self.corpus = experimental_live, corpus

    def collect(self, run_id, started_at):
        observations, documents, fetches, errors = [], [], [], []
        markets, stores, seen, excluded = {}, {}, set(), set()
        def read(url):
            seen.add(url)
            try:
                result = fetch(url)
            except (OSError, ValueError, CollectorError) as exc:
                fetches.append({'requested_url':url,'ok':False,'error':str(exc)})
                raise
            html = result.pop('text')
            fetches.append(dict(result,ok=True))
            return html
        try:
            if self.experimental_live:
                market_urls = set()
                for index in INDEXES:
                    leads = links(read(index),index)
                    market_urls.update(u for u in leads if '/product-page/' not in u and u not in INDEXES)
                if not market_urls or len(market_urls)>40:
                    raise CollectorError('empty or excessive current marketing discovery')
                for url in sorted(market_urls):
                    html = read(url)
                    market = marketing_evidence(html,url)
                    markets[market['name'].casefold()] = market
                    purchases = purchase_links(html,market)
                    excluded.update(u for u in links(html,url) if '/product-page/' in u and u not in purchases)
                    for link in purchases:
                        stores.setdefault(link,None)
                if not stores or len(stores)>80:
                    raise CollectorError('empty or excessive store discovery')
                for url in stores:
                    stores[url] = read(url)
            else:
                manifest = json.loads((CORPUS_DIR/'manifest.json').read_text())
                for entry in manifest['marketing']:
                    market = marketing_evidence((CORPUS_DIR/entry['file']).read_text(), entry['page_url'])
                    markets[market['name'].casefold()] = market
                for entry in manifest['corpora'][self.corpus]:
                    stores[entry['page_url']] = (CORPUS_DIR/entry['file']).read_text(encoding='utf-8')
            for url,html in stores.items():
                name = product_data(html,url)['name'].casefold()
                drafts, info = parse_product_html(html,page_url=url,observed_at=started_at,marketing=markets.get(name))
                observations.extend(drafts)
                documents.append(info)
        except (OSError, ValueError, KeyError, TypeError, CollectorError) as exc:
            errors.append({'error':str(exc)})
        return CollectorRunRequest(run_id=run_id,source_key=SOURCE_KEY,collector_key=SOURCE_KEY,
            started_at=started_at,observations=observations,ok=bool(observations) and not errors,
            error='incomplete Khadas collection' if errors else (None if observations else 'no PRODUCT observations'),
            diagnostics={'documents':documents,'fetches':fetches,'errors':errors,'discovered_urls':sorted(seen),
                         'excluded_non_purchase_links':sorted(excluded-set(stores)), 'marketing':markets})
