"""Public first-party WooCommerce PRODUCT records, scoped specs and explicit SKUs."""
import hashlib
import json
import re
from html import escape, unescape
from html.parser import HTMLParser
from urllib.parse import urlparse, urlencode, parse_qs
from urllib.request import Request, build_opener

from .base import CollectorError
from ._http import ValidatedRedirect, require_document_role
from . import odroid as o
from board_clank.identity import UNKNOWN, VariantDimensions
from board_clank.models import CollectorRunRequest
from board_clank.taxonomy import Availability

BASE='https://www.hardkernel.com/wp-json/wc/store/v1/'

class ScopedDescription(HTMLParser):
    """Remove empirically identified product cards, scripts and styles only."""
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.depth=0;self.skip=None;self.script=None;self.parts=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='div':
            self.depth+=1
            if self.skip is None and 'product-small' in a.get('class','').split():self.skip=self.depth
        if tag in ('script','style'):self.script=tag
        if self.skip is None and self.script is None:self.parts.append(self.get_starttag_text())
    def handle_endtag(self,tag):
        if self.skip is None and self.script is None:self.parts.append('</'+tag+'>')
        if tag=='div':
            if self.skip==self.depth:self.skip=None
            self.depth-=1
        if tag==self.script:self.script=None
    def handle_data(self,data):
        if self.skip is None and self.script is None:self.parts.append(data)
    def handle_entityref(self,name):
        self.handle_data('&'+name+';')
    def handle_charref(self,name):
        self.handle_data('&#'+name+';')

def validate_api_url(url):
    p=urlparse(url)
    if p.scheme!='https' or p.netloc!='www.hardkernel.com' or p.fragment or p.params:
        raise CollectorError('ODROID Store API host refused')
    if p.path not in ('/wp-json/wc/store/v1/products','/wp-json/wc/store/v1/products/categories'):
        raise CollectorError('ODROID Store API route refused')
    for key,values in parse_qs(p.query,keep_blank_values=True).items():
        if key=='slug' and len(values)==1 and re.fullmatch(r'[a-z0-9-]+(?:,[a-z0-9-]+)*',values[0]):
            continue
        if key=='catalog_visibility' and values==['any']:
            continue
        if key not in ('per_page','page','category','include') or len(values)!=1 or not re.fullmatch(r'[1-9]\d*(?:,[1-9]\d*)*',values[0]):
            raise CollectorError('ODROID Store API query refused')
    return url

def fetch_api(url):
    validate_api_url(url)
    def selected(final):
        validate_api_url(final)
        if final!=url:raise CollectorError('ODROID selected API route changed')
    with build_opener(ValidatedRedirect(selected)).open(Request(url,headers={'User-Agent':'BoardClank/0.1 (manual experimental public PRODUCT)'}),timeout=45) as r:
        selected(r.url)
        if 'application/json' not in r.headers.get('Content-Type',''):raise CollectorError('ODROID expected public product JSON')
        raw=r.read(8_000_001)
        if len(raw)>8_000_000:raise CollectorError('ODROID API response limit')
        data=json.loads(raw)
        if not isinstance(data,list):raise CollectorError('ODROID API collection shape')
        return {'data':data,'requested_url':url,'final_url':r.url,'status':r.status,
            'raw_body_hash':hashlib.sha256(raw).hexdigest(),'total':r.headers.get('X-WP-Total'),
            'pages':r.headers.get('X-WP-TotalPages')}

def parse_record(product,observed_at):
    supplier_name=unescape(product['name'])
    plug=re.search(r'\s*[–-]\s*(US|UK|KR|AU|EU)\s+plug$',supplier_name,re.I)
    name=supplier_name[:plug.start()].strip() if plug else supplier_name
    oled=bool(re.fullmatch(r'ODROID-HC4 with OLED',name,re.I))
    if oled:name='ODROID-HC4'
    url=product['permalink'];o._assert_official_url(url)
    if not o._is_product_page_url(url) or not re.match(r'^ODROID[- ]',name,re.I):
        raise CollectorError('ODROID selected record identity mismatch')
    if re.search(r'^ODROID[- ]GO\b',name,re.I) or o._KIT_RE.search(name):
        return [],{'page_url':url,'heading':name,'status':'ignored-non-computer','scope':'NON_BOARD_CATALOGUE_ITEM','reason':'explicit-handheld-or-package'}
    if product.get('type')!='simple':raise CollectorError('ODROID product configuration requires explicit qualification')
    if not product['description'].strip():raise CollectorError('ODROID required specification document is blank')
    cleaned=ScopedDescription();cleaned.feed(product['description'])
    html='<h1>'+escape(name)+'</h1>'+''.join(cleaned.parts)
    drafts,info=o.parse_product_html(html,page_url=url,observed_at=observed_at,scope_from_identity=True)
    if not drafts:raise CollectorError('ODROID selected board lacks identity evidence')
    # A supplier simple product is one explicit SKU, never a socket/addon matrix.
    parser=o._PageParser();parser.feed(html)
    model,ram,color=o._model_and_config(name)
    own_memory=' '.join(row[1] for table in parser.tables for row in table if len(row)==2 and row[0].strip().lower()=='memory')
    _,memory=o._ram_evidence(own_memory,ram)
    fitted=ram if ram!=UNKNOWN else (memory[0] if len(memory)==1 and not re.match(r'^ODROID-H\d',model,re.I) else UNKNOWN)
    own_storage=' '.join(row[1] for table in parser.tables for row in table if len(row)==2 and row[0].strip().lower()=='storage')
    soldered=re.search(r'(?:on-?board|embedded|soldered)[^.]{0,25}?(\d+)\s*G(?:iB|B|Byte)?\s*eMMC',own_storage,re.I)
    storage=soldered[1]+'GB' if soldered else UNKNOWN
    draft=drafts[0]
    bundle='OLED' if oled else ('IO Header' if re.search(r'\+\s*(?:40Pin\s+)?IO Header',name,re.I) else color)
    draft.variant=VariantDimensions(ram=fitted,storage=storage,bundle=bundle,
        region=plug[1].upper() if plug else UNKNOWN,sku=product.get('sku') or UNKNOWN)
    draft.spec.ram_options=fitted
    draft.spec.emmc_options=storage
    draft.spec.onboard_emmc='optional' if o._EMMC_SOCKET_RE.search(own_storage) else ('yes' if soldered else UNKNOWN)
    draft.raw_fields.update(supplier_product_id=product['id'],supplier_name=supplier_name,supplier_sku=product.get('sku'),
        supplier_prices=product.get('prices'),supplier_stock=product.get('is_in_stock'),
        supplier_attributes=product.get('attributes'),supplier_variations=product.get('variations'))
    draft.availability=Availability.IN_STOCK if product.get('is_in_stock') is True else (Availability.OUT_OF_STOCK if product.get('is_in_stock') is False else Availability.UNKNOWN)
    projection={k:product.get(k) for k in ('id','name','sku','type','attributes','variations','prices','is_in_stock','is_on_backorder')}
    projection['specification']=o.semantic_html(html)
    info.update(observation_count=1,semantic_evidence_hash=hashlib.sha256(json.dumps(projection,sort_keys=True).encode()).hexdigest())
    return [draft],info

def collect_api(run_id,started_at):
    observations=[];diagnostics={'mode':'experimental-live-public-store-api','fetches':[],'documents':[],'errors':[]}
    def read(url):
        try:
            row=fetch_api(url);diagnostics['fetches'].append({k:v for k,v in row.items() if k!='data'});return row
        except (OSError,ValueError,CollectorError) as e:
            diagnostics['fetches'].append({'requested_url':url,'ok':False,'error':str(e)});raise
    try:
        cats=read(BASE+'products/categories?per_page=100')['data']
        parent=next((c['id'] for c in cats if c['slug']=='odroid-board' and c['parent']==0),None)
        if not parent:raise CollectorError('ODROID board taxonomy absent')
        ids={parent};changed=True
        while changed:
            children={c['id'] for c in cats if c['parent'] in ids};changed=bool(children-ids);ids.update(children)
        products=[];seen=set();expected=None;total=None
        for page in range(1,101):
            query=urlencode({'category':','.join(map(str,sorted(ids))),'catalog_visibility':'any','per_page':10,'page':page})
            row=read(BASE+'products?'+query)
            pages=int(row['pages']);count=int(row['total'])
            if not 1<=pages<=100 or count>1000:raise CollectorError('ODROID catalogue bounds')
            if expected is None:expected,total=pages,count
            if (pages,count)!=(expected,total):raise CollectorError('ODROID catalogue pagination changed')
            for p in row['data']:
                if type(p['id']) is not int or p['id'] in seen:raise CollectorError('ODROID duplicate product record')
                if not any(c['id'] in ids for c in p['categories']):raise CollectorError('ODROID product category mismatch')
                seen.add(p['id']);products.append(p)
            if page==pages:break
        if len(products)!=total:raise CollectorError('ODROID catalogue incomplete')
        diagnostics['supplier_product_count']=total
        # The supplier collection omits some still-linked published shop pages.
        # Supplement only through current first-party shop discovery, never a
        # hard-coded model list or a resurrected historical fixture.
        shop=o.fetch_official_meta(o.SHOP_URL)
        diagnostics['fetches'].append({k:v for k,v in shop.items() if k!='text'})
        _,leads=o.parse_product_html(shop['text'],page_url=shop['final_url'],observed_at=started_at)
        require_document_role([],leads,'index')
        current_urls={p['permalink'].rstrip('/') for p in products}
        missing_slugs=sorted({urlparse(u).path.rstrip('/').split('/')[-1] for u in leads['lead_hrefs'] if u.rstrip('/') not in current_urls})
        if missing_slugs:
            row=read(BASE+'products?'+urlencode({'slug':','.join(missing_slugs),'per_page':100,'page':1}))
            diagnostics['unlisted_current_shop_records']=len(row['data'])
            returned={p['slug'] for p in row['data']}
            if not returned<=set(missing_slugs):raise CollectorError('ODROID supplemental route mismatch')
            for p in row['data']:
                if p['id'] in seen:raise CollectorError('ODROID supplemental duplicate identity')
                if not any(c['id'] in ids for c in p['categories']):continue
                seen.add(p['id']);products.append(p)
            diagnostics['unpublished_shop_slugs']=sorted(set(missing_slugs)-returned)
        groups_by_id={p['id']:p for p in products if p.get('type')=='grouped'}
        product_by_id={p['id']:p for p in products}
        linked_ids={i for p in groups_by_id.values() for i in p.get('grouped_products',[])}
        missing=linked_ids-set(product_by_id)
        if missing:
            if any(type(i) is not int or i<=0 for i in missing):raise CollectorError('ODROID invalid grouped product binding')
            row=read(BASE+'products?'+urlencode({'include':','.join(map(str,sorted(missing))),'per_page':100,'page':1}))
            for child in row['data']:
                if child['id'] not in missing or child['id'] in product_by_id:raise CollectorError('ODROID unexpected grouped child')
                product_by_id[child['id']]=child
        diagnostics['unpublished_group_references']=sorted(linked_ids-set(product_by_id))
        parents={}
        for parent in groups_by_id.values():
            if not parent.get('grouped_products'):raise CollectorError('ODROID empty configuration group')
            for identity in parent['grouped_products']:
                child=product_by_id.get(identity)
                if child is None:continue  # Public API excludes unpublished products; never resurrect them.
                child_name=unescape(child['name']);child_name=re.sub(r'\s*[–-]\s*(US|UK|KR|AU|EU)\s+plug$','',child_name,flags=re.I)
                if child_name!=unescape(parent['name']):raise CollectorError('ODROID grouped identity/configuration conflict')
                if identity in parents:raise CollectorError('ODROID multiply bound SKU')
                parents[identity]=parent
        references={}
        for p in products:
            name=unescape(p['name']);name=re.sub(r'\s*[–-]\s*(US|UK|KR|AU|EU)\s+plug$','',name,flags=re.I)
            if re.fullmatch(r'ODROID-HC4 with OLED',name,re.I):name='ODROID-HC4'
            model,_,_=o._model_and_config(name)
            references.setdefault(o._board_slug(model),[]).append(p)
        for key,rows in references.items():
            rows.sort(key=lambda p:(p.get('type')!='grouped','IO Header' in p['name'],int(p['id'])))
        selected=[p for p in product_by_id.values() if p.get('type')!='grouped']
        page_drafts=[]
        for p in selected:
            parent=parents.get(p['id'])
            if parent and not p.get('description','').strip():
                p=dict(p,description=parent['description'])
            drafts,info=parse_record(p,started_at);require_document_role(drafts,info,'detail')
            for draft in drafts:
                anchor=references[draft.board_slug][0]['permalink']
                draft.raw_fields['reference_urls']=[p['permalink']]+([parent['permalink']] if parent else [])
                draft.page_url=anchor
                draft.native_fields={'heading':draft.marketing_name,'page_url':anchor}
            observations.extend(drafts);diagnostics['documents'].append(info);page_drafts.append((p['permalink'],drafts))
        groups={}
        for draft in observations:groups.setdefault(draft.board_slug,[]).append(draft)
        for group in groups.values():
            availability=(Availability.IN_STOCK if any(d.availability==Availability.IN_STOCK for d in group)
                else Availability.OUT_OF_STOCK if all(d.availability==Availability.OUT_OF_STOCK for d in group) else Availability.UNKNOWN)
            ram=','.join(sorted({d.variant.ram for d in group if d.variant.ram!=UNKNOWN})) or UNKNOWN
            storage=','.join(sorted({d.variant.storage for d in group if d.variant.storage!=UNKNOWN})) or UNKNOWN
            for draft in group:
                draft.availability=availability
                draft.spec.ram_options=ram
                draft.spec.emmc_options=storage
        if not observations:raise CollectorError('ODROID no PRODUCT observations')
    except (OSError,ValueError,KeyError,TypeError,CollectorError) as e:
        observations=[];diagnostics['errors'].append(str(e))
    return CollectorRunRequest(run_id=run_id,source_key=o.SOURCE_KEY,collector_key=o.SOURCE_KEY,
        started_at=started_at,observations=observations,ok=bool(observations) and not diagnostics['errors'],
        error='incomplete public ODROID collection' if diagnostics['errors'] else None,diagnostics=diagnostics)
