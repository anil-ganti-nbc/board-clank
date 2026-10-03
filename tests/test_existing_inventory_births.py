"""First seen after baseline does not turn qualified catalogue inventory into market novelty."""
from __future__ import annotations

import pytest
from dataclasses import replace

from board_clank.collectors import get_adapter
from board_clank.models import CollectorRunRequest
from board_clank.pipeline import Pipeline
from board_clank.taxonomy import PHASE1_VENDORS, PHASE2_ADMITTED, NoveltyStatus

OBS = "2026-10-03T00:00:00Z"


@pytest.mark.parametrize("vendor", (*PHASE1_VENDORS, *PHASE2_ADMITTED))
def test_delayed_existing_catalogue_board_and_variants_are_silent(store, vendor):
    full = get_adapter(vendor + "-product").collect(vendor + "-inventory", OBS)
    assert full.ok and len({draft.board_slug for draft in full.observations}) > 1
    first = full.model_copy(deep=True)
    first.run_id += "-baseline"
    first.observations = first.observations[:1]
    assert Pipeline(store).accept_run(first).baseline
    delayed = full.model_copy(deep=True)
    delayed.run_id += "-delayed"
    delayed.observations = delayed.observations[1:]
    for draft in delayed.observations:
        # Use the adapter's actual catalogue evidence, without the fixture's historical shortcut.
        draft.historical_known = False
        draft.novelty.novelty_status = NoveltyStatus.EXISTING_PRODUCT
        assert draft.novelty.official_announcement_at == "UNKNOWN"
    result = Pipeline(store).accept_run(delayed)
    assert not result.baseline
    assert store.count("boards") > 1
    births = store.all("SELECT event_type,baseline_silent FROM events WHERE run_id=? AND from_hash='UNKNOWN'", (delayed.run_id,))
    assert births and all(row["baseline_silent"] for row in births)
    assert not store.one("SELECT n.event_key FROM notifications n JOIN events e ON e.event_key=n.event_key WHERE e.run_id=? AND n.disposition<>'SUPPRESSED'", (delayed.run_id,))
    events = store.count("events")
    assert Pipeline(store).accept_run(delayed).replayed
    repeated = delayed.model_copy(deep=True)
    repeated.run_id += "-repeat"
    assert Pipeline(store).accept_run(repeated).events == []
    assert store.count("events") == events


@pytest.mark.parametrize("evidence", ["existing", "historical", "historical-known"])
def test_delayed_known_variant_and_revision_births_silent_but_actual_transition_is_live(store, evidence):
    draft = get_adapter("radxa-product").collect("seed", OBS).observations[0]
    draft.historical_known = False
    draft.novelty.novelty_status = NoveltyStatus.UNKNOWN
    draft.revision_kind = "PCB"
    draft.revision_token = "fixture-1"
    request = CollectorRunRequest(run_id="first", source_key=draft.source_key,
                                 collector_key=draft.source_key, started_at=OBS, observations=[draft])
    assert Pipeline(store).accept_run(request).baseline
    changed = request.model_copy(deep=True)
    changed.run_id = "delayed-variant"
    current = changed.observations[0]
    current.variant = replace(current.variant, sku="explicit-pre-existing-fixture-sku")
    current.revision_token = "fixture-2"
    current.spec.ethernet = "explicit changed Ethernet evidence"
    if evidence == "historical-known":
        current.historical_known = True
    else:
        current.novelty.novelty_status = NoveltyStatus.EXISTING_PRODUCT if evidence == "existing" else NoveltyStatus.HISTORICAL
    assert not Pipeline(store).accept_run(changed).baseline
    births = store.all("SELECT event_type,baseline_silent FROM events WHERE run_id='delayed-variant' AND from_hash='UNKNOWN'")
    assert {row['event_type'] for row in births} >= {"BOARD_REVISION", "NEW_VARIANT"}
    assert all(row['baseline_silent'] for row in births)
    port_transition = store.one("SELECT event_key,baseline_silent FROM events WHERE run_id='delayed-variant' AND event_type='PORTS_CHANGED'")
    assert port_transition is not None and not port_transition['baseline_silent']
    assert store.one("SELECT disposition FROM notifications WHERE event_key=?", (port_transition['event_key'],))[0] == "PUSH"
    assert store.one("SELECT official_announcement_at FROM novelty_evidence")[0] == "UNKNOWN"
