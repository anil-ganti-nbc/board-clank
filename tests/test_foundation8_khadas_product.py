import json
import re

import pytest

from board_clank.collectors import get_adapter
from board_clank.collectors.base import CollectorError
from board_clank.collectors import khadas as k
from board_clank.observer import source_summary
from board_clank.sources import assert_foundation_0_roster, load_sources
from board_clank.taxonomy import PHASE1_VENDORS

OBS='2026-10-03T00:00:00Z'


def html(slug):
    return (k.CORPUS_DIR/'html'/('product-page-'+slug+'.html')).read_text(encoding='utf-8')


def market(slug):
    return k.marketing_evidence((k.CORPUS_DIR/'html'/(slug+'.html')).read_text(),k.BASE+'/'+slug)


def parse(slug,marketing=None,body=None):
    return k.parse_product_html(body or html(slug),page_url=k.BASE+'/product-page/'+slug,
                                observed_at=OBS,marketing=market(marketing or slug))


def collect(run):
    return k.KhadasProductAdapter().collect(run,OBS)


def mutate(slug,func):
    p=k.product_data(html(slug),k.BASE+'/product-page/'+slug)
    func(p)
    return '<h1>'+p['name']+'</h1><script id="wix-warmup-data">'+json.dumps({'product':p})+'</script>'


def test_registration_governance():
    assert_foundation_0_roster()
    a=get_adapter('khadas-product')
    assert isinstance(a,k.KhadasProductAdapter)
    assert a.supports_experimental_live and not a.experimental_live and not a.live_network
    rows=[r for r in load_sources() if r.vendor=='khadas']
    assert len(rows)==1
    r=rows[0]
    assert (r.source_key,r.authority,r.plane,r.promotion_state,r.registered_state,r.enabled,r.placeholder)==('khadas-product','FIRST_PARTY_CANONICAL','PRODUCT','EXPERIMENTAL','REGISTERED',False,False)


@pytest.mark.parametrize('url',['http://www.khadas.com/vim2','https://docs.khadas.com/products/sbc/edge-2l/hardware/start',
    'https://dl.khadas.com/products/edge-2l/','https://forum.khadas.com/','https://www.khadas.com/mind',
    'https://www.khadas.com/tea','https://evil.example/vim2','https://www.khadas.com@evil.example/vim2'])
def test_url_scope(url):
    with pytest.raises(CollectorError): k.official_url(url)


def test_discovery_ignores_non_sbc_and_downloads():
    body='<a href="/vim2">VIM2</a><a href="/edge2">Edge2</a><a href="/mind">Mind</a><a href="https://dl.khadas.com/products/edge-2l/">Edge-2L</a>'
    assert k.links(body,k.BASE+'/family')==[k.BASE+'/edge2',k.BASE+'/vim2']


def test_purchase_links_do_not_fetch_stale_accessory_navigation():
    # Distilled actual VIM3L anchor labels: the RCA accessory currently returns404.
    body='<a href="/product-page/vim3l-bare-board"><span>Buy Now</span></a><a href="/product-page/vim3l-htpc-kit">Buy Now</a><a href="/product-page/rca-to-3-5mm-cable">RCA to 3.5mm Converter</a>'
    assert k.purchase_links(body,market('vim3l'))==[k.BASE+'/product-page/vim3l-bare-board',k.BASE+'/product-page/vim3l-htpc-kit']
    with pytest.raises(CollectorError,match='purchase link'):
        k.purchase_links('<a href="/product-page/cable">Cable</a>',market('vim3l'))


@pytest.mark.parametrize('slug,marketing,soc',[('vim3','vim3','A311D'),('vim3l-bare-board','vim3l','S905D3'),
    ('khadas-vim1','vim1','S905X'),('vim1s','vim1s','S905Y4'),('edge','edge1','RK3399'),('edge-v','edge-v','RK3399'),('edge2','edge2','RK3588S2')])
def test_identity_and_silicon(slug,marketing,soc):
    ds,info=parse(slug,marketing)
    assert info['status']=='resolved'
    assert {d.soc_marketing_name for d in ds}=={soc}
    assert {d.family_slug for d in ds}=={'vim' if marketing.startswith('vim') else 'edge'}
    assert ds[0].board_slug==('edge' if marketing=='edge1' else marketing)


def test_vim2_revision_matrix_wireless():
    ds,_=parse('new-vim2','vim2')
    assert {d.board_slug for d in ds}=={'vim2'}
    assert {d.revision_kind for d in ds}=={'PCB'}
    assert {d.revision_token for d in ds}=={'1.4'}
    assert {(d.variant.ram,d.variant.storage,d.variant.wireless) for d in ds}=={
        ('2GB','16GB eMMC','AP6356S'),('3GB','32GB eMMC','AP6398S'),('3GB','64GB eMMC','AP6398S')}


def test_edge2_one_board_four_explicit_packages():
    ds,_=parse('edge2')
    assert len(ds)==4
    assert {d.board_slug for d in ds}=={'edge2'}
    assert {d.variant.bundle for d in ds}=={'Edge2 Maker Kit','Edge2 ARM PC'}
    assert {(d.variant.ram,d.variant.storage) for d in ds}=={('8GB','32GB eMMC'),('16GB','64GB eMMC')}
    assert len({d.variant.sku for d in ds})==4
    assert len({json.dumps(d.native_fields,sort_keys=True) for d in ds})==1


@pytest.mark.parametrize('slug',['diy-case','3705-cooling-fan','new-vim-heatsink','vim3l-htpc-kit','tea'])
def test_real_accessory_and_duplicate_bundle_rejection(slug):
    ds,info=k.parse_product_html(html(slug),page_url=k.BASE+'/product-page/'+slug,observed_at=OBS)
    assert ds==[] and info['status']=='rejected-non-sbc'


def test_non_sbc_processor_not_authority():
    body=mutate('edge2',lambda p:p.update(name='Mind Pro'))  # explicitly synthetic scope mutation
    ds,info=k.parse_product_html(body,page_url=k.BASE+'/product-page/edge2',observed_at=OBS)
    assert not ds and info['status']=='rejected-non-sbc'


def test_no_borrowed_marketing_identity():
    with pytest.raises(CollectorError,match='matching current'):
        k.parse_product_html(html('edge'),page_url=k.BASE+'/product-page/edge',observed_at=OBS,marketing=market('vim2'))


def test_companion_chips_and_conflict():
    assert k.silicon('GPU Mali-G610; WiFi AP6275P; MCU STM32; codec ES8389')==[]
    assert k.silicon('Rockchip RK808 PMIC; Rockchip RK9999 Wi-Fi module')==[]
    body=mutate('edge2',lambda p:p.update(description=p['description']+'<p>CPU: Rockchip RK3576 SoC</p>'))
    ds,info=parse('edge2',body=body)
    assert info['status']=='conflict' and all(d.identity_conflict for d in ds)


def test_unbound_options_fail_closed():
    body=mutate('edge2',lambda p:p['productItems'][0].update(optionsSelections=[99999]))
    with pytest.raises(CollectorError,match='unbound'):
        parse('edge2',body=body)


def test_price_stock_options_remain_semantic_evidence():
    _,a=parse('edge2')
    body=mutate('edge2',lambda p:p['productItems'][0].update(price=999))
    _,b=parse('edge2',body=body)
    assert a['semantic_evidence_hash']!=b['semantic_evidence_hash']
    _,c=parse('edge2',body=html('edge2')+'<script>volatile_session_id=1234</script><style>.x{color:red}</style>')
    assert a['semantic_evidence_hash']==c['semantic_evidence_hash']


def test_baseline_replay_and_observer(pipeline,store,db_path):
    first=pipeline.accept_run(collect('k1'))
    assert first.status=='accepted' and first.baseline
    counts={t:store.count(t) for t in ('boards','board_families','board_revisions','board_variants','events','notifications')}
    assert counts['boards']==9 and counts['board_variants']==19
    assert all(r['baseline_silent'] for r in store.all('SELECT baseline_silent FROM events'))
    assert all(r['disposition']=='SUPPRESSED' for r in store.all('SELECT disposition FROM notifications'))
    assert pipeline.accept_run(collect('k1')).replayed
    for run in ('k2','k3'):
        request=collect(run); request.started_at='2026-10-03T03:00:00Z'
        for d in request.observations:d.observed_at=request.started_at
        result=pipeline.accept_run(request)
        assert result.status=='accepted' and result.notifications==0
        assert counts=={t:store.count(t) for t in counts}
    summary=source_summary(db_path)
    row=next(r for r in summary if r['source_key']=='khadas-product')
    assert not row['enabled'] and row['promotion_state']=='EXPERIMENTAL'
    assert set(row)=={'source_key','vendor','plane','authority','enabled','promotion_state','registered_state'}


def test_eight_vendor_isolation(pipeline,store):
    for vendor in (*PHASE1_VENDORS,'friendlyelec'):
        assert pipeline.accept_run(get_adapter(vendor+'-product').collect(vendor,OBS)).status=='accepted'
    tables=('boards','board_families','board_revisions','board_variants')
    before={t:[dict(r) for r in store.all('SELECT * FROM '+t)] for t in tables}
    pipeline.accept_run(collect('khadas'))
    for t,rows in before.items():
        after=[dict(r) for r in store.all('SELECT * FROM '+t)]
        assert all(r in after for r in rows)
    assert len({r['vendor_key'] for r in store.all('SELECT vendor_key FROM boards')})==8
    assert not store.all("SELECT * FROM events WHERE event_type='FIELD_CHANGED'")
    shared=store.all("SELECT r.soc_key,COUNT(DISTINCT b.vendor_key) AS n FROM board_revisions r JOIN boards b ON r.board_key=b.board_key GROUP BY r.soc_key HAVING n>1")
    assert any(r['soc_key']=='rockchip:rk3399' for r in shared)


def test_uncertainty_replay_and_atomic_failure(monkeypatch,pipeline,store):
    body=mutate('edge2',lambda p:p.update(description='<p>Application processor UNKNOWN</p>'))
    m=market('edge2'); m['description']='No silicon evidence'
    ds,_=k.parse_product_html(body,page_url=k.BASE+'/product-page/edge2',observed_at=OBS,marketing=m)
    req=collect('u1'); req.observations=ds
    pipeline.accept_run(req)
    count=store.count('events')
    req.run_id='u2'; pipeline.accept_run(req)
    assert store.count('events')==count
    before=[dict(r) for r in store.all('SELECT * FROM diagnostic_conditions')]
    def fail(url):raise OSError('synthetic offline fetch failure')
    monkeypatch.setattr(k,'fetch',fail)
    failed=k.KhadasProductAdapter(experimental_live=True).collect('failed',OBS)
    assert failed.diagnostics['fetches']==[{'requested_url':k.INDEXES[0],'ok':False,'error':'synthetic offline fetch failure'}]
    result=pipeline.accept_run(failed)
    assert result.status=='failed'
    assert before==[dict(r) for r in store.all('SELECT * FROM diagnostic_conditions')]


def test_other_source_uncertainty_not_closed(pipeline,store):
    from board_clank.collectors.pine64 import collect_corpus
    pipeline.accept_run(collect_corpus('insufficient',run_id='pine-u',started_at=OBS))
    before=[dict(r) for r in store.all("SELECT * FROM diagnostic_conditions WHERE source_key='pine64-product'")]
    assert before
    pipeline.accept_run(collect('khadas'))
    assert before==[dict(r) for r in store.all("SELECT * FROM diagnostic_conditions WHERE source_key='pine64-product'")]
