"""Actual primary captures plus explicitly synthetic negative mutations."""
import copy,json
from pathlib import Path
import pytest
from board_clank.collectors import raspberry_pi as r,banana_pi as b,odroid_store as o,forlinx as f
from board_clank.collectors.base import CollectorError
from board_clank.cli import main
from board_clank.identity import UNKNOWN
from board_clank.observer import source_summary

DATA=json.loads(Path(__file__).with_name('fixtures').joinpath('alternate_paths.json').read_text())
OBS='2026-10-06T00:00:00Z'

@pytest.fixture(autouse=True)
def offline_current_shop(monkeypatch):
    # Synthetic discovery projection bound to the captured supplier products.
    body=''.join('<a href="'+p['permalink']+'">'+p['name']+'</a>' for p in DATA['odroid_products'])
    monkeypatch.setattr(o.o,'fetch_official_meta',lambda url:{'text':body,'final_url':url,'requested_url':url})

@pytest.mark.parametrize('letter,sku',[('A','SC0562'),('B','SC0563')])
def test_reviewed_pip_legacy_alias(letter,sku):
    body=DATA['rpi_a_html'].replace('Model A+','Model '+letter+'+').replace('SC0562',sku)
    ds,info=r.parse_product_html(body,page_url='https://pip.raspberrypi.com/categories/573-raspberry-pi-model-'+letter.lower(),observed_at=OBS)
    assert info['status']=='resolved-identity' and ds
    assert {d.board_slug for d in ds}=={'raspberry-pi-1-model-'+letter.lower()+'-plus'}
    assert {d.family_slug for d in ds}=={'raspberry-pi-1'}
    assert all(d.soc_marketing_name==UNKNOWN for d in ds)

def test_legacy_alias_requires_matching_sku():
    with pytest.raises(CollectorError,match='unverified'):
        r.parse_product_html(DATA['rpi_a_html'].replace('SC0562','SC0000'),page_url='https://pip.raspberrypi.com/categories/573-raspberry-pi-model-a',observed_at=OBS)
    assert not r._is_computer_name('Raspberry Pi Pico 2') and not r._is_computer_name('Raspberry Pi 500')

def test_current_pcn_download_title_without_pcn_keyword():
    # Distilled actual 889-pcn anchor, whose display name lacks the letters PCN.
    body='<h1>PCN</h1><p>Product Change Notes</p><a title="Open RP-004577-PC-1-Raspberry Pi 2 Model B, Use of BCM2836 and BCM2837A1 SoC variants.pdf" href="https://pip-assets.raspberrypi.com/categories/889-pcn/documents/RP-004577-PC-1.pdf">Open notice</a>'
    ds,info=r.parse_product_html(body,page_url='https://pip.raspberrypi.com/categories/889-pcn',observed_at=OBS)
    from board_clank.collectors._http import require_document_role
    require_document_role(ds,info,'pcn')
    assert len(info['pcns'])==1 and 'BCM2837A1' in info['pcns'][0]
    bad=body.replace('/categories/889-pcn/documents/','/categories/other/documents/')
    ds,info=r.parse_product_html(bad,page_url='https://pip.raspberrypi.com/categories/889-pcn',observed_at=OBS)
    with pytest.raises(CollectorError):require_document_role(ds,info,'pcn')

def test_real_openwrt_identity_and_companion_safety():
    ds,info=b.parse_product_html(DATA['bpi_openwrt_html'],page_url='https://banana-pi.org/en/bananapi-router/173.html',observed_at=OBS)
    assert ds and info['status']=='resolved'
    assert {d.board_slug for d in ds}=={'openwrt-one'}
    assert {d.soc_marketing_name for d in ds}=={'MT7981B'}
    assert {d.board_type for d in ds}=={'ROUTER_BOARD'}
    assert all(d.revision_token==UNKNOWN for d in ds)

def test_openwrt_manufacturing_claim_required():
    body=DATA['bpi_openwrt_html'].replace('collaboration with Banana Pi','collaboration with Unknown Vendor')
    with pytest.raises(CollectorError,match='manufacturer'):
        b.parse_product_html(body,page_url='https://banana-pi.org/en/bananapi-router/173.html',observed_at=OBS)

@pytest.mark.parametrize('slug',['odroid-c4','odroid-c5','odroid-hc4','odroid-n2-with-4gbyte-ram-2'])
def test_real_odroid_store_records(slug):
    p=next(p for p in DATA['odroid_products'] if p['slug']==slug)
    ds,info=o.parse_record(p,OBS)
    assert ds and info['status']=='resolved' and len(ds)==1
    assert ds[0].variant.sku==p['sku'] and ds[0].variant.storage==UNKNOWN
    assert ds[0].raw_fields['supplier_prices']==p['prices']
    assert ds[0].availability=='IN_STOCK'

def test_genuine_handheld_remains_rejected():
    p=next(p for p in DATA['odroid_products'] if 'go-ultra' in p['slug'])
    ds,info=o.parse_record(p,OBS)
    assert not ds and info['scope']=='NON_BOARD_CATALOGUE_ITEM'

def test_actual_grouped_region_skus_are_one_board(monkeypatch):
    products=DATA['odroid_group_products']
    def grouped(url):
        rows=DATA['odroid_categories'] if 'categories?' in url else products
        return {'data':copy.deepcopy(rows),'pages':'1','total':str(len(rows)),'requested_url':url,'final_url':url}
    monkeypatch.setattr(o,'fetch_api',grouped)
    body=''.join('<a href="'+p['permalink']+'">'+p['name']+'</a>' for p in products)
    monkeypatch.setattr(o.o,'fetch_official_meta',lambda url:{'text':body,'final_url':url})
    request=o.collect_api('grouped',OBS)
    assert request.ok,request.diagnostics
    assert len(request.observations)==5
    assert {d.board_slug for d in request.observations}=={'odroid-m1s'}
    assert {d.variant.region for d in request.observations}=={'US','KR','UK','AU','EU'}
    assert {d.variant.ram for d in request.observations}=={'4GB'}
    assert len({d.variant.sku for d in request.observations})==5
    assert {d.page_url for d in request.observations}=={'https://www.hardkernel.com/shop/odroid-m1s-with-4gbyte-ram/'}

def test_addon_card_cannot_mint_storage_or_handheld():
    p=copy.deepcopy(next(p for p in DATA['odroid_products'] if p['slug']=='odroid-c4'))
    before=o.parse_record(p,OBS)
    p['description']+='<div class="product-small"><p>ODROID-GO ULTRA 256GB eMMC</p></div>'
    after=o.parse_record(p,OBS)
    assert before==after

@pytest.mark.parametrize('url',['http://www.hardkernel.com/wp-json/wc/store/v1/products','https://evil.example/wp-json/wc/store/v1/products','https://www.hardkernel.com/wp-json/wc/v3/orders','https://www.hardkernel.com/wp-json/wc/store/v1/products?password=x','https://www.hardkernel.com/wp-json/wc/store/v1/products?page=-1'])
def test_api_boundary(url):
    with pytest.raises(CollectorError):o.validate_api_url(url)

def stub_api(url):
    if 'categories?' in url:rows=DATA['odroid_categories']
    else:rows=DATA['odroid_products']
    return {'data':copy.deepcopy(rows),'pages':'1','total':str(len(rows)),'requested_url':url,'final_url':url,'status':200}

def test_public_source_baseline_replay_and_observer(monkeypatch,pipeline,store,db_path):
    monkeypatch.setattr(o,'fetch_api',stub_api)
    first=pipeline.accept_run(o.collect_api('api1',OBS));assert first.baseline
    counts={t:store.count(t) for t in ('boards','board_variants','events','notifications')}
    assert counts['boards']==4 and counts['board_variants']==4
    assert pipeline.accept_run(o.collect_api('api1',OBS)).replayed
    for run in ('api2','api3'):
        assert pipeline.accept_run(o.collect_api(run,OBS)).status=='accepted'
        assert counts=={t:store.count(t) for t in counts}
    assert all(not row['enabled'] for row in source_summary(db_path))

def test_api_changed_coverage_fails_atomically(monkeypatch,pipeline,store):
    monkeypatch.setattr(o,'fetch_api',stub_api);pipeline.accept_run(o.collect_api('initial',OBS))
    before={t:store.count(t) for t in ('boards','events','notifications')}
    def partial(url):
        row=stub_api(url)
        if 'categories?' not in url:row['total']='9'
        return row
    monkeypatch.setattr(o,'fetch_api',partial)
    failed=o.collect_api('partial',OBS);assert not failed.ok and not failed.observations
    pipeline.accept_run(failed);assert before=={t:store.count(t) for t in before}

@pytest.mark.parametrize('failure',['blank-spec','foreign-url','duplicate-id','wrong-category','unqualified-variable'])
def test_public_api_required_record_failure_preserves_state(failure,monkeypatch,pipeline,store):
    monkeypatch.setattr(o,'fetch_api',stub_api);pipeline.accept_run(o.collect_api('seed',OBS))
    tables=[r[0] for r in store.all("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    before={t:[tuple(r) for r in store.all('SELECT * FROM '+t)] for t in tables}
    def broken(url):
        row=stub_api(url)
        if 'categories?' not in url:
            p=row['data'][-1]
            if failure=='blank-spec':p['description']=''
            elif failure=='foreign-url':p['permalink']='https://evil.example/shop/odroid-c4/'
            elif failure=='duplicate-id':p['id']=row['data'][0]['id']
            elif failure=='wrong-category':p['categories']=[{'id':-1}]
            else:p['type']='variable'
        return row
    monkeypatch.setattr(o,'fetch_api',broken)
    request=o.collect_api('broken',OBS)
    assert not request.ok and not request.observations
    pipeline.accept_run(request)
    assert all(before[t]==[tuple(r) for r in store.all('SELECT * FROM '+t)] for t in tables if t not in ('collector_runs','run_errors'))

def test_forlinx_durable_capture_closure(monkeypatch,tmp_path):
    from test_scoped_review_repairs import live_lookup
    lookup=live_lookup()
    monkeypatch.setattr(f,'fetch',lambda u:{'text':lookup[u],'requested_url':u,'final_url':u})
    req=f.ForlinxProductAdapter(experimental_live=True,capture_dir=tmp_path).collect('snap',OBS)
    assert req.ok
    root=Path(req.diagnostics['capture_directory']);manifest=json.loads((root/'manifest.json').read_text())
    assert manifest['complete'] and len(manifest['fetches'])==65
    assert len(list(root.glob('*.html')))==65
    assert (root/'progress.json').exists()

def test_capture_refused_for_unsupported_or_offline_before_db(tmp_path):
    db=tmp_path/'absent.db'
    assert main(['--db',str(db),'collect','--source','raspberry-pi-product','--capture-dir',str(tmp_path/'capture')])==2
    assert not db.exists()
