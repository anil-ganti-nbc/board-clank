"""Empirical Forlinx corpus and deliberately labelled synthetic reject/mutation probes."""
from collections import Counter
import hashlib
import json

import pytest

from board_clank.backup import create_backup, durable_state_snapshot, restore_backup, verify_backup
from board_clank.cli import main
from board_clank.collectors import forlinx as f, get_adapter
from board_clank.collectors.base import CollectorError
from board_clank.observer import full_snapshot, source_summary
from board_clank.pipeline import Pipeline
from board_clank.sources import assert_foundation_0_roster, load_sources
from board_clank.store import Store
from board_clank.taxonomy import PHASE1_VENDORS

OBS = '2026-10-03T00:00:00Z'
MANIFEST = json.loads((f.CORPUS_DIR / 'manifest.json').read_text(encoding='utf-8'))


def entry(model):
    return next(e for e in MANIFEST['corpora']['baseline'] if e['catalogue_model'] == model)


def parse(model, body=None):
    e = entry(model)
    return f.parse_product_html(body if body is not None else (f.CORPUS_DIR / e['file']).read_text(encoding='utf-8'),
        page_url=e['page_url'], observed_at=OBS, catalogue_model=model)


def collect(run):
    return f.ForlinxProductAdapter().collect(run, OBS)


def synthetic(name='OK999-C', cpu='Rockchip RK3399', architecture='Cortex-A72', ram='2GB DDR4', rom='8GB eMMC'):
    return (f'<div class="product-cp"><h3>{name} Single Board Computer</h3>'
            f'<p>CPU: {cpu}</p><p>Architecture: {architecture}</p>'
            f'<p>Frequency: 1.2GHz</p><p>RAM: {ram}</p><p>ROM: {rom}</p><p>System: Linux</p></div>')


def test_registration_disabled_and_cli_live_refusal(tmp_path):
    assert_foundation_0_roster()
    a = get_adapter('forlinx-product')
    assert isinstance(a, f.ForlinxProductAdapter) and a.supports_experimental_live
    assert not a.experimental_live and not a.live_network
    rows = [s for s in load_sources() if s.vendor == 'forlinx']
    assert len(rows) == 1
    s = rows[0]
    assert (s.source_key, s.plane, s.authority, s.registered_state, s.promotion_state, s.enabled, s.placeholder) == (
        'forlinx-product', 'PRODUCT', 'FIRST_PARTY_CANONICAL', 'REGISTERED', 'EXPERIMENTAL', False, False)
    path = tmp_path / 'must-not-exist.sqlite'
    assert main(['--db', str(path), 'collect', '--source', 'forlinx-product', '--live']) != 0
    assert not path.exists()


@pytest.mark.parametrize('url', [
    'http://www.forlinx.net/product/rk3399-103.html', 'https://forlinx.net/product/rk3399-103.html',
    'https://www.forlinx.net@evil.example/product/rk3399-103.html', 'https://evil.example/product/rk3399-103.html',
    'https://docs.forlinx.net/', 'https://community.forlinx.net/', 'https://www.forlinx.net/news-center/sbc-1.html',
    'https://www.forlinx.net/system-on-module/rk3399-103.html', 'https://www.forlinx.net/download/brief.pdf',
    'https://www.forlinx.net/product/rk3399-103.html?sku=1', 'https://www.forlinx.net/product/rk3399-103.html#spec',
    'https://www.forlinx.net/product/../news-103.html', 'https://www.forlinx.net/product-list-1.html'])
def test_first_party_surface_refusal(url):
    with pytest.raises(CollectorError):
        f.official_url(url)


def test_current_catalogue_cards_and_pagination_only():
    e = MANIFEST['catalogues'][0]
    cards, pages, excluded = f.catalogue((f.CORPUS_DIR / e['file']).read_text(encoding='utf-8'), e['page_url'])
    assert cards and len(pages) == 6
    # Actual newer first-party roster: UP5 is distinct from the -C model.
    all_cards = collect('cards').diagnostics['catalogue_models']
    assert 'OK3576J-UP5' in all_cards.values() and 'OK3576-C' in all_cards.values()
    assert any(c['heading'] == 'AM62L32 Local EVM' for c in collect('cards').diagnostics['excluded_cards'])
    with pytest.raises(CollectorError, match='title'):
        f.catalogue('<title>System on Module</title><a href="/product/x-1.html"><h3>OK999-C Single Board Computer</h3></a>', f.INDEX)


@pytest.mark.parametrize('model,vendor,soc', [
    ('OK-MX9352-C', 'nxp', 'i.MX93'), ('OKMX6Q-C', 'nxp', 'i.MX6Q'),
    ('OK3399-C', 'rockchip', 'RK3399'), ('OK3506J-C', 'rockchip', 'RK3506J'),
    ('OK153-S', 'allwinner', 'T153'), ('OKT507-C', 'allwinner', 'T507'),
    ('OK-G2LD-C', 'renesas', 'RZ/G2L'), ('OK7110-C', 'starfive', 'JH7110'),
    ('OK-MA35-S21', 'nuvoton', 'MA35D1'), ('OK335xD', 'texas-instruments', 'AM3354'),
    ('OK4418-C2', 'samsung', 'S5P4418')])
def test_diverse_application_soc_only(model, vendor, soc):
    ds, info = parse(model)
    assert info['status'] == 'resolved' and len(ds) == 1
    assert (ds[0].soc_vendor, ds[0].soc_marketing_name) == (vendor, soc)
    assert ds[0].architecture == ('RISCV' if vendor == 'starfive' else 'ARM')
    assert ds[0].revision_kind == 'UNKNOWN' and ds[0].revision_token == 'UNKNOWN'


def test_exact_suffix_models_distinct_and_internal_som_never_minted():
    pairs = [('OK-MX9352-C', 'OK-MX9352-UP4'), ('OK3576-C', 'OK3576J-UP5'),
             ('OK3506J-C', 'OK3506J-S'), ('OK153-S', 'OK153-S12'), ('OK4418-C', 'OK4418-C2')]
    for a, b in pairs:
        da, db = parse(a)[0][0], parse(b)[0][0]
        assert da.board_slug != db.board_slug
        assert da.soc_marketing_name == db.soc_marketing_name
    request = collect('identity')
    assert len({d.board_slug for d in request.observations}) == len(request.observations)
    assert all(d.marketing_name.startswith('OK') and not d.marketing_name.startswith('FET') for d in request.observations)


@pytest.mark.parametrize('model', ['OK3568-C', 'OK3568-UP4', 'OK3588-C', 'OK3588J-UP5',
                                  'OK1126Bx-S', 'OK1126Bx-C', 'OK62xx-C', 'OKMX8MPx-C'])
def test_explicit_processor_alternatives_preserved_as_uncertainty(model):
    ds, info = parse(model)
    assert info['status'] == 'insufficient' and ds[0].evidence_insufficient
    assert ds[0].soc_marketing_name == ds[0].resolved_soc_key() == 'UNKNOWN'
    assert info['semantic_evidence']['fields']['cpu'] == ds[0].raw_fields['cpu']
    assert not ds[0].identity_conflict  # manufacturer options do not allege a contradiction


def test_unpaired_memory_not_cartesian_and_single_pair():
    ds, _ = parse('OK3576J-UP5')
    assert len(ds) == 1 and ds[0].variant.ram == ds[0].variant.storage == 'UNKNOWN'
    assert '8GB' in ds[0].spec.ram_options and '64GB' in ds[0].spec.emmc_options
    ds, _ = parse('OK-MX9352-C')
    assert (ds[0].variant.ram, ds[0].variant.storage) == ('1GB', '8GB eMMC')
    for ram, rom in [('1GB/2GB DDR4', '8GB/16GB eMMC'), ('2GB DDR4(optional)', '8GB eMMC'),
                     ('512/256MB DDR3L', '8GB eMMC'), ('1GB DDR3 + 2GB DDR3', '8GB eMMC')]:
        assert f.memory_pair({'ram': ram, 'rom': rom}).ram == 'UNKNOWN'


@pytest.mark.parametrize('model', ['OK1052-C', 'OK1061-S'])
def test_actual_mcu_only_catalogue_products_rejected(model):
    ds, info = parse(model)
    assert ds == [] and info['status'] == 'rejected-mcu-only'


@pytest.mark.parametrize('name,cpu', [
    ('FET3568-C System on Module', 'Rockchip RK3568'), ('FCU3501 Embedded Computer', 'NXP i.MX93'),
    ('OK3568 Carrier Board', 'Rockchip RK3568'), ('OK3568 Development Kit', 'Rockchip RK3568'),
    ('OK3568 Cooling Accessory', 'Rockchip RK3568'), ('AI Accelerator Card', 'Rockchip RK3588'),
    ('OKJetson Single Board Computer', 'NVIDIA Jetson Orin')])
def test_synthetic_out_of_scope(name, cpu):
    body = synthetic().replace('OK999-C Single Board Computer', name).replace('Rockchip RK3399', cpu)
    ds, info = f.parse_product_html(body, page_url=f.BASE + '/product/probe-999.html', observed_at=OBS)
    assert ds == [] and info['status'] == 'rejected-non-sbc'


@pytest.mark.parametrize('cpu', ['GPU Mali-G610', 'Rockchip RK808 PMIC', 'RK9999 Wi-Fi module',
                                'Nuvoton Cortex-M4 MCU', 'PHY RTL8211', 'codec ES8388', 'RISC-V E907 DSP',
                                'Rockchip RK3399 + NXP i.MX93'])
def test_companion_and_ambiguous_cpu_values_not_silicon(cpu):
    assert f.silicon(cpu) == ('UNKNOWN', 'UNKNOWN')


def test_missing_linkage_and_duplicate_labels_fail_closed():
    e = entry('OK3399-C')
    body = (f.CORPUS_DIR / e['file']).read_text(encoding='utf-8')
    with pytest.raises(CollectorError, match='matching current'):
        f.parse_product_html(body, page_url=e['page_url'], observed_at=OBS, catalogue_model='OK3568-C')
    with pytest.raises(CollectorError, match='duplicate'):
        parse('OK3399-C', body.replace('</div>', '<p>CPU: NXP i.MX93</p></div>'))


def test_semantic_projection_preserves_facts_and_decodes_clock_presentation():
    ds, a = parse('OK-MX9352-C')
    assert 'Cortex-A55@' in ds[0].spec.cpu_config and 'Cortex-M33' in ds[0].spec.cpu_config
    body = (f.CORPUS_DIR / entry('OK-MX9352-C')['file']).read_text(encoding='utf-8')
    replacement = 'Cortex-A55@1.7GHz'
    masked = bytes([55, *(ord(c) ^ 55 for c in replacement)]).hex()
    import re
    changed = re.sub(r'data-cfemail="[a-f0-9]+"', f'data-cfemail="{masked}"', body)
    _, b = parse('OK-MX9352-C', changed + '<script>volatile=123</script><style>.x{color:red}</style>')
    assert a['semantic_evidence_hash'] == b['semantic_evidence_hash']
    _, c = parse('OK-MX9352-C', body.replace('1.5GHz', '1.6GHz'))
    assert a['semantic_evidence_hash'] != c['semantic_evidence_hash']
    assert parse('OK-MX9352-C', body.replace('1.5GHz', '1.6GHz'))[0][0].canonical_payload() != ds[0].canonical_payload()


def test_baseline_receipt_and_new_run_replay(pipeline, store):
    first = pipeline.accept_run(collect('f1'))
    assert first.status == 'accepted' and first.baseline
    assert Counter(d['status'] for d in collect('fixture').diagnostics['documents']) == {
        'resolved': 46, 'insufficient': 11, 'rejected-mcu-only': 2}
    counts = {t: store.count(t) for t in ('boards', 'board_variants', 'board_revisions', 'socs', 'events', 'notifications', 'diagnostic_conditions')}
    assert counts['boards'] == counts['board_variants'] == 46
    assert all(r['baseline_silent'] for r in store.all('SELECT baseline_silent FROM events'))
    assert all(r['disposition'] == 'SUPPRESSED' for r in store.all('SELECT disposition FROM notifications'))
    assert pipeline.accept_run(collect('f1')).replayed
    for run in ('f2', 'f3'):
        result = pipeline.accept_run(collect(run))
        assert result.status == 'accepted' and not result.events and not result.notifications
        assert counts == {t: store.count(t) for t in counts}
    assert all(r['open_occurrences'] == 3 for r in store.all('SELECT open_occurrences FROM diagnostic_conditions'))


def test_nine_vendor_identity_and_diagnostic_isolation(pipeline, store, db_path):
    from board_clank.collectors.pine64 import collect_corpus
    for vendor in (*PHASE1_VENDORS, 'friendlyelec', 'khadas'):
        assert pipeline.accept_run(get_adapter(vendor + '-product').collect(vendor, OBS)).status == 'accepted'
    pipeline.accept_run(collect_corpus('insufficient', run_id='pine-u', started_at=OBS))
    tables = ('boards', 'board_families', 'board_revisions', 'board_variants', 'diagnostic_conditions')
    before = {t: [dict(r) for r in store.all('SELECT * FROM ' + t)] for t in tables}
    observer_before = source_summary(db_path)
    assert pipeline.accept_run(collect('f-nine')).status == 'accepted'
    for t, rows in before.items():
        after = [dict(r) for r in store.all('SELECT * FROM ' + t)]
        assert all(row in after for row in rows)
    assert len({r['vendor_key'] for r in store.all('SELECT vendor_key FROM boards')}) == 9
    assert not store.all("SELECT * FROM events WHERE event_type IN ('FIELD_CHANGED','DIAGNOSTIC_RESOLVED') AND source_key='forlinx-product'")
    assert observer_before == source_summary(db_path)
    assert all(set(row) == set(observer_before[0]) for row in observer_before)


@pytest.mark.parametrize('failure', ['fetch', 'parse'])
def test_partial_live_failure_is_atomic(monkeypatch, pipeline, store, failure):
    pipeline.accept_run(collect('before'))
    tables = ('boards', 'board_variants', 'board_revisions', 'events', 'notifications', 'diagnostic_conditions', 'source_baselines')
    before = {t: [dict(r) for r in store.all('SELECT * FROM ' + t)] for t in tables}
    lookup = {e['page_url']: (f.CORPUS_DIR / e['file']).read_text(encoding='utf-8') for e in MANIFEST['catalogues'] + MANIFEST['corpora']['baseline']}
    target = MANIFEST['corpora']['baseline'][1]['page_url']
    def fake(url):
        if url == target and failure == 'fetch':
            raise OSError('synthetic required PRODUCT fetch failure')
        body = lookup[url]
        if url == target and failure == 'parse':
            body = body.replace('product-cp', 'missing-hero')
        return {'text': body, 'requested_url': url, 'final_url': url}
    monkeypatch.setattr(f, 'fetch', fake)
    request = f.ForlinxProductAdapter(experimental_live=True).collect('failed-' + failure, OBS)
    assert not request.ok and request.diagnostics['errors']
    assert pipeline.accept_run(request).status == 'failed'
    assert before == {t: [dict(r) for r in store.all('SELECT * FROM ' + t)] for t in tables}


def test_schema_v3_observer_backup_restore_and_replay(pipeline, store, db_path, tmp_path):
    request = collect('recover')
    pipeline.accept_run(request)
    store.close()
    digest = hashlib.sha256(db_path.read_bytes()).hexdigest()
    snapshot = full_snapshot(db_path)
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == digest
    assert snapshot and source_summary(db_path)
    backup = create_backup(db_path, tmp_path / 'backup')
    assert verify_backup(backup.database_path, backup.metadata_path)['verified']
    assert backup.metadata['schema_version'] == 3 and backup.metadata['integrity'] == 'ok'
    target = tmp_path / 'restored.sqlite'
    restore_backup(backup.database_path, backup.metadata_path, target, activate=True)
    assert durable_state_snapshot(target) == durable_state_snapshot(db_path)
    restored = Store(target)
    p = Pipeline(restored)
    assert p.accept_run(request).replayed
    result = p.accept_run(collect('restored-new-run'))
    assert result.status == 'accepted' and result.events == [] and result.notifications == 0
    assert restored.one('PRAGMA integrity_check')[0] == 'ok'
    assert not restored.all('PRAGMA foreign_key_check')
    restored.close()
