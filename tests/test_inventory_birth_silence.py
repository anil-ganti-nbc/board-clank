"""Known inventory discovered later cannot manufacture editorial chronology."""
import pytest

from board_clank.collectors import get_adapter
from board_clank.taxonomy import PHASE1_VENDORS, NoveltyStatus, RevisionKind

OBS = '2026-10-03T00:00:00Z'


def admitted_drafts(source):
    request = get_adapter(source).collect('seed', OBS)
    boards = {}
    for draft in request.observations:
        if not draft.evidence_insufficient and not draft.identity_conflict:
            boards.setdefault(draft.board_slug, draft)
    assert len(boards) >= 2
    return request, list(boards.values())


@pytest.mark.parametrize('vendor', (*PHASE1_VENDORS, 'friendlyelec', 'khadas', 'forlinx'))
def test_nine_vendor_delayed_existing_inventory_is_silent(vendor, pipeline, store):
    request, boards = admitted_drafts(vendor + '-product')
    # Explicit inventory evidence in this synthetic partial-catalogue sequence;
    # do not infer dates or modify the fixture's hardware/specification facts.
    for draft in boards[:2]:
        draft.novelty.novelty_status = NoveltyStatus.EXISTING_PRODUCT
    request.observations = boards[:1]
    assert pipeline.accept_run(request).baseline
    request.run_id = 'delayed-existing-' + vendor
    request.observations = boards[1:2]
    result = pipeline.accept_run(request)
    assert result.status == 'accepted' and not result.baseline
    events = store.all('SELECT baseline_silent FROM events WHERE run_id=?', (request.run_id,))
    assert events and all(row['baseline_silent'] for row in events)
    assert not store.all("SELECT n.* FROM notifications n JOIN events e ON e.event_key=n.event_key WHERE e.run_id=? AND n.disposition!='SUPPRESSED'", (request.run_id,))
    counts = {t: store.count(t) for t in ('boards', 'board_revisions', 'board_variants', 'events', 'notifications')}
    assert pipeline.accept_run(request).replayed
    request.run_id += '-later'
    repeat = pipeline.accept_run(request)
    assert repeat.status == 'accepted' and repeat.events == [] and repeat.notifications == 0
    assert counts == {t: store.count(t) for t in counts}
    if vendor == 'forlinx':
        assert boards[1].novelty.official_announcement_at == 'UNKNOWN'
        assert boards[1].novelty.official_sale_at == 'UNKNOWN'
        assert boards[1].novelty.official_shipping_at == 'UNKNOWN'


@pytest.mark.parametrize('status,historical_known', [
    (NoveltyStatus.EXISTING_PRODUCT, False), (NoveltyStatus.HISTORICAL, False),
    (NoveltyStatus.UNKNOWN, True)])
def test_delayed_real_sku_variant_birth_silent(status, historical_known, pipeline, store):
    # Actual explicit Khadas Edge2 SKU/package bindings, not a manufactured matrix.
    request = get_adapter('khadas-product').collect('sku-seed', OBS)
    variants = [d for d in request.observations if d.marketing_name == 'Edge2']
    assert len(variants) == 4
    for draft in variants:
        draft.novelty.novelty_status = status
        draft.historical_known = historical_known
    request.observations = variants[:1]
    pipeline.accept_run(request)
    request.run_id = 'delayed-real-sku'
    request.observations = variants[1:2]
    result = pipeline.accept_run(request)
    assert result.status == 'accepted'
    events = store.all('SELECT event_type,baseline_silent FROM events WHERE run_id=?', (request.run_id,))
    assert events and any(e['event_type'] == 'NEW_VARIANT' for e in events)
    assert all(e['baseline_silent'] for e in events)
    assert not store.all("SELECT n.* FROM notifications n JOIN events e ON e.event_key=n.event_key WHERE e.run_id=? AND n.disposition!='SUPPRESSED'", (request.run_id,))
    assert store.count('boards') == 1 and store.count('board_variants') == 2


def test_known_inventory_revision_birth_silent_without_transition_suppression(pipeline, store):
    request, boards = admitted_drafts('forlinx-product')
    first = boards[0]
    first.revision_kind, first.revision_token = RevisionKind.PCB, 'synthetic-known-pcb-1'
    request.observations = [first]
    pipeline.accept_run(request)
    later = first.model_copy(deep=True)
    later.revision_token = 'synthetic-known-pcb-2'
    request.run_id, request.observations = 'delayed-known-pcb', [later]
    pipeline.accept_run(request)
    births = store.all("SELECT baseline_silent FROM events WHERE run_id=? AND event_type IN ('BOARD_REVISION','NEW_VARIANT')", (request.run_id,))
    assert births and all(e['baseline_silent'] for e in births)
    assert not store.all("SELECT n.* FROM notifications n JOIN events e ON e.event_key=n.event_key WHERE e.run_id=? AND n.disposition!='SUPPRESSED'", (request.run_id,))


@pytest.mark.parametrize('change,event_type', [('clock', 'FIELD_CHANGED'), ('soc', 'SOC_CHANGED'), ('port', 'PORTS_CHANGED')])
def test_known_existing_board_material_transition_remains_observable(change, event_type, pipeline, store):
    request, boards = admitted_drafts('forlinx-product')
    request.observations = [boards[0]]
    pipeline.accept_run(request)
    draft = boards[0].model_copy(deep=True)
    if change == 'clock':
        draft.native_fields['product_summary']['frequency'] = 'synthetic-changed-2GHz'
    elif change == 'soc':
        draft.soc_vendor, draft.soc_marketing_name = 'rockchip', 'RK3399'
        draft.spec.soc, draft.spec.soc_key = 'RK3399', 'rockchip:rk3399'
    else:
        draft.spec.ethernet = 'synthetic-changed-2x2.5GbE'
    request.run_id, request.observations = 'real-transition-' + change, [draft]
    pipeline.accept_run(request)
    events = store.all('SELECT event_type,baseline_silent FROM events WHERE run_id=?', (request.run_id,))
    target = [e for e in events if e['event_type'] == event_type]
    assert target and all(not e['baseline_silent'] for e in target)
