"""FriendlyELEC admission is manual, source-scoped and never production authority."""
import json

import pytest

from board_clank.collectors import get_adapter
from board_clank.collectors.base import CollectorError
from board_clank.collectors import friendlyelec as fe
from board_clank.identity import UNKNOWN
from board_clank.observer import source_summary
from board_clank.sources import assert_foundation_0_roster, load_sources

OBS = '2026-10-03T00:00:00Z'


def parse(pid, html=None, at=OBS):
    if html is None:
        html = (fe.CORPUS_DIR / f'html/product-{pid}.html').read_text(encoding='utf-8')
    return fe.parse_product_html(html, page_url=fe.BASE+f'index.php?route=product/product&product_id={pid}', observed_at=at)


def collect(run):
    return fe.FriendlyElecProductAdapter().collect(run, OBS)


def test_registration_and_roster():
    assert_foundation_0_roster()
    adapter = get_adapter('friendlyelec-product')
    assert isinstance(adapter, fe.FriendlyElecProductAdapter)
    assert not adapter.experimental_live and not adapter.live_network
    rows = load_sources()
    friendly = [r for r in rows if r.vendor=='friendlyelec']
    assert len(friendly)==1
    assert friendly[0].source_key=='friendlyelec-product'
    assert friendly[0].authority=='FIRST_PARTY_CANONICAL'
    assert not friendly[0].placeholder
    assert all(not r.enabled for r in rows)
    assert all(r.promotion_state=='EXPERIMENTAL' for r in rows if not r.placeholder)


@pytest.mark.parametrize('bad', ['http://www.friendlyelec.com/','https://wiki.friendlyelec.com/',
    'https://dl.friendlyelec.com/','https://evil.example/','https://www.friendlyelec.com@evil.example/',
    fe.BASE+'index.php?route=account/login',fe.BASE+'index.php?route=product/category&path=69&page=11'])
def test_surface_allowlist(bad):
    with pytest.raises(CollectorError): fe.official_url(bad)


def test_navigation_query_not_identity():
    a=fe.BASE+'index.php?route=product/product&product_id=320'
    assert fe.official_url(a)==fe.official_url(a+'&path=69')
    assert len(fe.links(f'<a href="{a}">a</a><a href="{a}&amp;path=69">b</a>',fe.BASE))==1


@pytest.mark.parametrize('pid,soc', [(320,'RK3528A'),(319,'RK3588S'),(309,'RK3576'),(311,'RK3566'),(287,'RK3568B2'),(294,'RK3588')])
def test_labelled_silicon(pid,soc):
    drafts,info=parse(pid)
    assert info['status']=='resolved'
    assert {d.soc_marketing_name for d in drafts}=={soc}


def test_peripheral_tokens_never_application_socs():
    html='<h1>NanoPi Example</h1><table><tr><td>Connectivity</td><td>RTL8211F H3 RK3588</td></tr></table>'
    drafts,info=parse(999,html)
    assert info['status']=='insufficient-evidence'
    assert drafts[0].soc_marketing_name==UNKNOWN
    conflict=html+'<tr><td>CPU</td><td>RK3566 RK3588</td></tr>'
    drafts,info=parse(999,conflict)
    assert info['status']=='identity-conflict' and drafts[0].identity_conflict


def test_names_not_suffix_merged_and_revision_not_invented():
    pairs=[(282,296),(294,299),(291,289),(292,315),(290,287),(320,308)]
    for a,b in pairs:
        da,_=parse(a); db,_=parse(b)
        assert da[0].board_slug!=db[0].board_slug
        assert da[0].revision_token==db[0].revision_token==UNKNOWN
    assert parse(319)[0][0].board_slug=='nanopi-m6v2'
    assert parse(319)[0][0].revision_token==UNKNOWN


def test_paired_matrix_not_cartesian_or_case_variants():
    ds,_=parse(311)
    assert {(d.variant.ram,d.variant.storage) for d in ds}=={('1GB','none'),('2GB','none'),('2GB','32GB eMMC')}
    assert all(d.variant.bundle==UNKNOWN for d in ds)
    ds,_=parse(319)
    assert len(ds)==1 and ds[0].variant.ram=='8GB'
    assert ds[0].variant.storage==UNKNOWN
    assert ds[0].variant.wireless==UNKNOWN and ds[0].spec.wifi=='optional'


def test_natural_selector_spec_disagreement_retained():
    ds,info=parse(290)
    assert info['evidence_warnings']==['selector-spec-storage-disagreement']
    assert {(d.variant.ram,d.variant.storage) for d in ds}=={('2GB','none'),('4GB','64GB eMMC')}
    assert '32GB' in info['spec_storage']


def test_built_in_wireless_and_compute_module():
    ds,_=parse(151)
    assert all(d.variant.wireless=='wifi' and d.spec.bluetooth=='4.0' for d in ds)
    assert parse(294)[0][0].board_type=='COMPUTE_MODULE'
    assert parse(280)[0][0].board_type=='COMPUTE_MODULE'


@pytest.mark.parametrize('pid',[317,281,298,318,188])
def test_accessory_kit_rejected(pid):
    ds,info=parse(pid)
    assert ds==[] and info['status']=='rejected'


def test_baseline_replay_no_churn_or_outbox(pipeline,store):
    first=pipeline.accept_run(collect('fe-1'))
    assert first.status=='accepted' and first.baseline
    before={t:store.count(t) for t in ('boards','board_variants','events','notifications')}
    assert before['boards']>0
    assert all(r['baseline_silent'] for r in store.all('SELECT baseline_silent FROM events'))
    assert all(r['disposition']=='SUPPRESSED' for r in store.all('SELECT disposition FROM notifications'))
    assert pipeline.accept_run(collect('fe-1')).replayed
    for run in ('fe-2','fe-3'):
        req=collect(run); req.started_at='2026-10-03T02:00:00Z'
        for d in req.observations: d.observed_at=req.started_at
        assert pipeline.accept_run(req).status=='accepted'
        assert before=={t:store.count(t) for t in before}


def test_unknown_and_conflict_sightings_are_stable(pipeline,store):
    ds,_=parse(999,'<h1>NanoPi Unknown</h1>')
    req=collect('uncertain1'); req.observations=ds
    pipeline.accept_run(req)
    count=store.count('events')
    req.run_id='uncertain2'; pipeline.accept_run(req)
    assert store.count('events')==count
    assert store.one('SELECT open_occurrences FROM diagnostic_conditions')['open_occurrences']==2


def test_partial_live_run_cannot_close_or_mutate(monkeypatch,pipeline,store):
    ds,_=parse(999,'<h1>NanoPi Unknown</h1>')
    req=collect('uncertain'); req.observations=ds; pipeline.accept_run(req)
    before=[dict(r) for r in store.all('SELECT * FROM diagnostic_conditions')]
    index=fe.official_url(fe.INDEXES[0])
    def fake(url):
        if url==index:
            return {'text':'<a href="index.php?route=product/product&amp;product_id=320">R28S</a>'}
        raise OSError('deliberate partial fetch failure')
    monkeypatch.setattr(fe,'fetch',fake)
    request=fe.FriendlyElecProductAdapter(experimental_live=True).collect('partial',OBS)
    assert not request.ok
    assert pipeline.accept_run(request).status=='failed'
    assert [dict(r) for r in store.all('SELECT * FROM diagnostic_conditions')]==before
    assert store.count('boards')==0


def test_semantic_hash_excludes_clock_markup_and_price():
    html=(fe.CORPUS_DIR/'html/product-311.html').read_text(encoding='utf-8')
    a,ia=parse(311,html)
    b,ib=parse(311,html.replace('(+$19.00)','(+$99.00)')+'<script>volatile=123</script>',at='2026-10-04T00:00:00Z')
    assert ia['semantic_evidence_hash']==ib['semantic_evidence_hash']
    assert [d.canonical_payload() for d in a]==[d.canonical_payload() for d in b]


def test_seven_vendor_isolation_and_observer_shape(pipeline,store,db_path):
    from board_clank.taxonomy import PHASE1_VENDORS
    for vendor in PHASE1_VENDORS:
        assert pipeline.accept_run(get_adapter(vendor+'-product').collect(vendor,OBS)).status=='accepted'
    # Existing six domain entities must be byte-for-byte identical after seventh admission.
    tables=('boards','board_families','board_revisions','board_variants')
    snapshots={t:[dict(r) for r in store.all('SELECT * FROM '+t)] for t in tables}
    old_summary=source_summary(db_path)
    pipeline.accept_run(collect('fe-seven'))
    for table,rows in snapshots.items():
        after=[dict(r) for r in store.all('SELECT * FROM '+table)]
        assert all(row in after for row in rows)
    assert len({r['vendor_key'] for r in store.all('SELECT vendor_key FROM boards')})==7
    assert source_summary(db_path)==old_summary
    assert all(set(row)==set(old_summary[0]) for row in old_summary)
    assert any(r['source_key']=='friendlyelec-product' and not r['enabled'] for r in old_summary)
    assert not store.all("SELECT * FROM events WHERE event_type='FIELD_CHANGED'")


def test_other_source_condition_not_closed(pipeline,store):
    from board_clank.collectors.pine64 import collect_corpus
    pipeline.accept_run(collect_corpus('insufficient',run_id='pine-uncertain',started_at=OBS))
    before=[dict(r) for r in store.all("SELECT * FROM diagnostic_conditions WHERE source_key='pine64-product'")]
    assert before
    pipeline.accept_run(collect('fe'))
    assert before==[dict(r) for r in store.all("SELECT * FROM diagnostic_conditions WHERE source_key='pine64-product'")]
