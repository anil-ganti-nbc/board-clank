"""Synthetic revision ambiguity checks; no restore collision/alias or race execution."""
from __future__ import annotations

import json

import pytest

from board_clank.identity import UNKNOWN, VariantDimensions, silent_revision_token
from board_clank.models import CollectorRunRequest, NormalizedSpec, ObservationDraft
from board_clank.taxonomy import BoardType, RevisionKind, SourcePlane

SOURCE = "raspberry-pi-product"
BOARD = "raspberry-pi:revision-fixture"
OBS = "2026-10-05T00:00:00Z"
PAGE = "https://fixture.invalid/revision-fixture"
DOMAIN_TABLES = (
    "vendors", "board_families", "socs", "boards", "board_revisions", "board_variants",
    "canonical_observations", "current_entity_observations", "observation_occurrences",
    "board_classifications", "novelty_evidence", "price_observations", "software_support",
)


def _draft(kind=RevisionKind.UNKNOWN, token=UNKNOWN, *, soc="Fixture SoC", usb="2xUSB"):
    return ObservationDraft(
        source_key=SOURCE, plane=SourcePlane.PRODUCT, observed_at=OBS,
        vendor_key="raspberry-pi", vendor_name="Raspberry Pi",
        family_slug="revision-fixture", family_name="Revision fixture",
        board_slug="revision-fixture", marketing_name="Revision fixture",
        board_type=BoardType.SBC, revision_kind=kind, revision_token=token,
        variant=VariantDimensions(ram="4GB"), soc_vendor="fixture", soc_marketing_name=soc,
        spec=NormalizedSpec(usb=usb, pcb_revision=token), page_url=PAGE, historical_known=True,
    )


def _request(run_id, drafts):
    return CollectorRunRequest(run_id=run_id, source_key=SOURCE,
                               collector_key="synthetic-revision-regression", started_at=OBS,
                               observations=drafts)


def _snapshot(store, tables=None):
    tables = tables or [row[0] for row in store.all(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )]
    return {name: [tuple(row) for row in store.all(f'SELECT * FROM "{name}" ORDER BY rowid')]
            for name in tables}


def _conditions(store):
    return [dict(row) for row in store.all(
        "SELECT * FROM diagnostic_conditions ORDER BY diagnostic_type"
    )]


@pytest.mark.parametrize("kind", [RevisionKind.PCB, RevisionKind.MARKETING])
@pytest.mark.parametrize("reverse", [False, True])
def test_ambiguous_unknown_revision_is_diagnostic_only(pipeline, store, kind, reverse):
    seeds = [_draft(kind, "v1"), _draft(kind, "v2")]
    pipeline.accept_run(_request("seed", list(reversed(seeds)) if reverse else seeds))
    before = _snapshot(store, DOMAIN_TABLES)
    request = _request("ambiguous-1", [_draft()])
    original = request.model_dump(mode="json")
    result = pipeline.accept_run(request)
    assert result.occurrences == 0
    assert _snapshot(store, DOMAIN_TABLES) == before
    assert request.model_dump(mode="json") == original
    conditions = _conditions(store)
    assert {row["diagnostic_type"] for row in conditions} == {"NOVELTY_UNRESOLVED", "IDENTITY_ANOMALY"}
    expected = sorted(f"{BOARD}:{kind.value}:{token}" for token in ("v1", "v2"))
    for row in conditions:
        page = json.loads(row["payload_json"])["pages"][0]
        assert row["reason"] == page["reason"] == "ambiguous-revision-identity"
        assert row["status"] == "OPEN" and row["source_key"] == SOURCE
        assert page["revision_candidates"] == expected
        assert page["page_url"] == PAGE and page["marketing_name"] == "Revision fixture"
        assert page["revision_evidence"] == {
            "soc_key": "fixture:fixture-soc", "ports_signature": _draft().spec.ports_signature(),
        }
    events = [dict(row) for row in store.all("SELECT * FROM events WHERE run_id='ambiguous-1'")]
    assert len(events) == 2
    assert all(row["revision_key"] == UNKNOWN and row["variant_key"] == UNKNOWN for row in events)
    full_before_replay = _snapshot(store)
    assert pipeline.accept_run(request).replayed
    assert _snapshot(store) == full_before_replay
    event_count, outbox_count = store.count("events"), store.count("notifications")
    later = pipeline.accept_run(_request("ambiguous-2", [_draft()]))
    assert later.occurrences == 0 and later.events == [] and later.notifications == 0
    assert _snapshot(store, DOMAIN_TABLES) == before
    assert (store.count("events"), store.count("notifications")) == (event_count, outbox_count)
    assert all(row["transition_count"] == 0 and row["total_occurrences"] == 2 for row in _conditions(store))
    assert store.count("diagnostic_sightings") == 4


@pytest.mark.parametrize("extra", [None, "other-soc", "other-ports"])
def test_one_matching_revision_is_reused_without_churn(pipeline, store, extra):
    seeds = [_draft(RevisionKind.PCB, "v1")]
    if extra:
        seeds.insert(0, _draft(RevisionKind.PCB, "v2", soc="Other SoC" if extra == "other-soc" else "Fixture SoC",
                              usb="3xUSB" if extra == "other-ports" else "2xUSB"))
    pipeline.accept_run(_request("seed", seeds))
    canonical = _snapshot(store, ("board_revisions", "board_variants", "canonical_observations",
                                  "current_entity_observations"))
    request = _request("unique", [_draft()])
    original = request.model_dump(mode="json")
    result = pipeline.accept_run(request)
    assert result.occurrences == 1 and result.events == []
    assert store.count("diagnostic_conditions") == 0
    assert _snapshot(store, tuple(canonical)) == canonical
    assert request.model_dump(mode="json") == original
    # Only the signature match may own the new revision occurrence.
    occurrence = store.one("SELECT c.revision_key FROM observation_occurrences o JOIN canonical_observations c ON c.observation_id=o.observation_id WHERE o.run_id='unique' AND c.entity_kind='REVISION'")
    assert occurrence["revision_key"] == f"{BOARD}:PCB:v1"
    before_replay = _snapshot(store)
    assert pipeline.accept_run(request).replayed
    assert _snapshot(store) == before_replay


@pytest.mark.parametrize("kind", [RevisionKind.PCB, RevisionKind.MARKETING, RevisionKind.UNKNOWN])
def test_explicit_token_selects_named_revision_among_same_signature(pipeline, store, kind):
    pipeline.accept_run(_request("seed", [_draft(kind, "v1"), _draft(kind, "v2")]))
    first = store.one("SELECT observation_id FROM current_entity_observations WHERE entity_kind='REVISION' AND entity_key=?", (f"{BOARD}:{kind.value}:v1",))["observation_id"]
    changed = _draft(kind, "v2")
    changed.spec.cpu_cores = "8"
    request = _request("explicit", [changed])
    assert pipeline.accept_run(request).occurrences == 1
    assert store.count("board_revisions") == 2 and store.count("diagnostic_conditions") == 0
    assert store.one("SELECT observation_id FROM current_entity_observations WHERE entity_kind='REVISION' AND entity_key=?", (f"{BOARD}:{kind.value}:v1",))["observation_id"] == first
    payload = store.one("SELECT c.payload_json FROM current_entity_observations p JOIN canonical_observations c ON c.observation_id=p.observation_id WHERE p.entity_kind='REVISION' AND p.entity_key=?", (f"{BOARD}:{kind.value}:v2",))
    assert json.loads(payload["payload_json"])["spec"]["cpu_cores"] == "8"
    before_replay = _snapshot(store)
    assert pipeline.accept_run(request).replayed
    assert _snapshot(store) == before_replay


@pytest.mark.parametrize("existing", [False, True])
def test_no_matching_revision_preserves_unknown_and_silent_semantics(pipeline, store, existing):
    if existing:
        pipeline.accept_run(_request("seed", [_draft(RevisionKind.PCB, "v1", usb="3xUSB")]))
    incoming = _draft()
    assert pipeline.accept_run(_request("new-signature", [incoming])).occurrences == 1
    expected = (f"{BOARD}:SILENT:{silent_revision_token(incoming.spec.ports_signature(), incoming.resolved_soc_key(), incoming.spec.dimensions)}"
                if existing else f"{BOARD}:UNKNOWN:UNKNOWN")
    assert store.one("SELECT revision_key FROM board_revisions WHERE revision_key=?", (expected,))
    assert store.count("diagnostic_conditions") == 0


def test_explicit_evidence_resolves_existing_ambiguity_once(pipeline, store):
    pipeline.accept_run(_request("seed", [_draft(RevisionKind.PCB, "v1"), _draft(RevisionKind.PCB, "v2")]))
    pipeline.accept_run(_request("ambiguous", [_draft()]))
    assert len(_conditions(store)) == 2
    request = _request("resolved", [_draft(RevisionKind.PCB, "v2")])
    pipeline.accept_run(request)
    assert all(row["status"] == "RESOLVED" for row in _conditions(store))
    assert len(store.all("SELECT event_id FROM events WHERE event_type='DIAGNOSTIC_RESOLVED'")) == 2
    snapshot = _snapshot(store)
    assert pipeline.accept_run(request).replayed
    assert _snapshot(store) == snapshot
    assert pipeline.accept_run(_request("resolved-later", [_draft(RevisionKind.PCB, "v2")])).events == []
    assert len(store.all("SELECT event_id FROM events WHERE event_type='DIAGNOSTIC_RESOLVED'")) == 2


def test_ambiguity_diagnostics_and_receipt_roll_back_together(pipeline, store, monkeypatch):
    pipeline.accept_run(_request("seed", [_draft(RevisionKind.PCB, "v1"), _draft(RevisionKind.PCB, "v2")]))
    before = _snapshot(store)
    real_batch = pipeline._admit_diagnostic_batch
    def fail_after_diagnostics(*args, **kwargs):
        real_batch(*args, **kwargs)
        raise RuntimeError("synthetic post-diagnostic failure")
    monkeypatch.setattr(pipeline, "_admit_diagnostic_batch", fail_after_diagnostics)
    request = _request("rolled-back", [_draft()])
    with pytest.raises(RuntimeError, match="synthetic post-diagnostic failure"):
        pipeline.accept_run(request)
    assert _snapshot(store) == before
    monkeypatch.setattr(pipeline, "_admit_diagnostic_batch", real_batch)
    assert pipeline.accept_run(request).occurrences == 0
    assert len(_conditions(store)) == 2
