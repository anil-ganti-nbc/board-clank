"""Prospective integration only: all authority/transport/clock witnesses synthetic."""

from datetime import datetime, timezone, timedelta
from uuid import uuid4
import pytest
from board_clank.production_policy import digest
from board_clank.eight_source_campaign import roster_hash
import json

import test_production_runtime as runtime_fixtures
from board_clank.collectors import get_adapter
from board_clank.production_policy import SOURCES
from board_clank.production_runtime import initialize, run_once


load = runtime_fixtures.load


@pytest.fixture
def approval_file(tmp_path):
    return runtime_fixtures.approval_file.__wrapped__(tmp_path)


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    runtime_fixtures.offline_only.__wrapped__(monkeypatch)


def synthetic_collect(root, admission, source, slot, directory):
    request = get_adapter(source).collect(
        slot + "-" + source, datetime.now(timezone.utc).isoformat()
    )
    request.fixture_scenario = None  # Explicit synthetic transport, never natural evidence.
    request.observations = [
        d for d in request.observations if not d.evidence_insufficient and not d.identity_conflict
    ][:1]
    return request


def test_real_producer_retains_profile_attempt_and_native_evidence(approval_file, tmp_path):
    admission = load(approval_file)
    root = tmp_path / "runtime"
    initialize(root, admission)
    receipt = run_once(root, admission, collect=synthetic_collect)
    assert receipt["status"] == "COMPLETE"
    assert receipt["campaign"]["profile_id"] == "board-eight-production-v1"
    assert receipt["campaign"]["attempt_id"] is None
    assert receipt["campaign"]["natural_eligible"] is False
    assert receipt["campaign"]["sources"] == list(SOURCES)
    assert receipt["campaign"]["approval_sha256"] == admission.raw_hash
    for source, result in receipt["sources"].items():
        assert result["native"]["run_id"] == receipt["slot"] + "-" + source
        assert result["native"]["observations"] == 1
        assert result["native"]["fixture_scenario"] is None
        assert result["request"]["sha256"]
    assert json.loads((root / "runs" / receipt["slot"] / "cycle.json").read_text()) == json.loads(
        json.dumps(receipt)
    )


def test_bound_synthetic_producer_is_consumed_without_natural_credit(approval_file, tmp_path):
    from board_clank.campaign_acceptance import reconcile

    admission = load(approval_file)
    root = tmp_path / "runtime"
    initialize(root, admission)
    run_once(root, admission, collect=synthetic_collect)
    report = reconcile(root, admission)
    assert report["status"] == "NOT_ADMITTED"
    assert report["natural_credit"] == 0
    assert report["t0"] == "UNKNOWN_NOT_ACTIVATED"


@pytest.fixture
def campaign(approval_file, tmp_path, monkeypatch):
    root = tmp_path / "bound-runtime"
    raw = json.loads(approval_file.read_text())
    baseline = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    raw["approved_at"] = (baseline - timedelta(minutes=2)).isoformat()
    attempt = str(uuid4())

    def proof(name, value):
        path = approval_file.parent / name
        path.write_text(json.dumps(value))
        return {"path": name, "sha256": digest(path.read_bytes())}

    spec = {
        "format": 1,
        "profile_id": "board-eight-production-v1",
        "attempt_id": attempt,
        "sources": list(SOURCES),
        "roster_sha256": roster_hash(list(SOURCES)),
        "revision": raw["revision"],
        "code_sha256": raw["code_sha256"],
        "root": str(root.resolve()),
        "admitted_at": (baseline - timedelta(minutes=1)).isoformat(),
        "baseline_slot": baseline.strftime("%Y%m%dT%H0000Z"),
        "mode": "SYNTHETIC",
        "scheduler": proof(
            "scheduler.json",
            {
                "scheduler_id": "SYNTHETIC-NOT-INSTALLED",
                "attempt_id": attempt,
                "root": str(root.resolve()),
                "cadence_seconds": 3600,
                "mode": "SYNTHETIC",
                "evidence_references": ["synthetic offline scheduler witness"],
            },
        ),
        "target": proof(
            "target.json",
            {
                "attempt_id": attempt,
                "root": str(root.resolve()),
                "revision": raw["revision"],
                "code_sha256": raw["code_sha256"],
                "mode": "SYNTHETIC",
                "evidence_references": ["synthetic transport/client/target; NOT NAS"],
            },
        ),
    }
    raw["campaign"] = proof("campaign.json", spec)
    approval_file.write_text(json.dumps(raw))
    admission = load(approval_file)
    initialize(root, admission)
    clock = [baseline + timedelta(seconds=5)]
    monkeypatch.setattr("board_clank.production_runtime.stamp", lambda: clock[0].isoformat())
    monkeypatch.setattr("board_clank.pipeline._now", lambda: clock[0].isoformat())
    monkeypatch.setattr("board_clank.production_ledger.time.time", lambda: clock[0].timestamp())

    def tick(hour, fail=False):
        clock[0] = baseline + timedelta(hours=hour, seconds=5)
        slot = clock[0].strftime("%Y%m%dT%H0000Z")
        directory = root / "scheduler"
        directory.mkdir(exist_ok=True)
        witness = {
            "attempt_id": attempt,
            "approval_sha256": admission.raw_hash,
            "scheduler_id": "SYNTHETIC-NOT-INSTALLED",
            "slot": slot,
            "dispatch_id": str(uuid4()),
            "dispatched_at": clock[0].isoformat(),
            "role": "baseline" if hour == 0 else "scheduled",
            "mode": "SYNTHETIC",
        }
        (directory / (slot + ".json")).write_text(json.dumps(witness))

        def collect(*args):
            r = synthetic_collect(*args)
            r.started_at = clock[0].isoformat()
            if fail and args[2] == SOURCES[0]:
                r.ok = False
                r.error = "synthetic source failure"
            return r

        return run_once(root, admission, collect=collect, now=clock[0])

    return root, admission, tick, baseline


def test_actual_bound_producer_to_reconciler(campaign):
    from board_clank.campaign_acceptance import reconcile

    root, admission, tick, baseline = campaign
    first = tick(0)
    second = tick(1)
    assert first["campaign"]["attempt_id"]
    assert second["campaign"]["attempt_id"] == first["campaign"]["attempt_id"]
    report = reconcile(root, admission)
    assert report["status"] == "SYNTHETIC_PENDING"
    assert report["synthetic_slots"] == 1
    assert report["natural_credit"] == 0
    assert report["t0"] == "UNKNOWN_NOT_ACTIVATED"
    assert report["synthetic_t0"] == first["finished_utc"]
    from board_clank.production_runtime import main

    assert main(["--root", str(root), "--approval", str(admission.path), "reconcile"]) == 0
    with pytest.raises(ValueError):
        tick(169)  # finite-window refusal precedes acquisition


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong-attempt",
        "wrong-roster",
        "old-nine",
        "counts",
        "replayed",
        "clock",
        "failure",
        "request-drift",
        "dispatch-drift",
    ],
)
def test_producer_evidence_contradictions_cannot_count(campaign, mutation):
    from board_clank.campaign_acceptance import reconcile

    root, admission, tick, baseline = campaign
    tick(0)
    row = tick(1, fail=mutation == "failure")
    path = root / "runs" / row["slot"] / "cycle.json"
    if mutation == "wrong-attempt":
        row["campaign"]["attempt_id"] = str(uuid4())
    elif mutation == "wrong-roster":
        row["campaign"]["sources"] = list(reversed(SOURCES))
    elif mutation == "old-nine":
        row["campaign"]["profile_id"] = "cops-000182-seven-day-d952-r2"
    elif mutation == "counts":
        row["sources"][SOURCES[0]]["native"]["observations"] += 1
    elif mutation == "replayed":
        row["sources"][SOURCES[0]]["result"]["status"] = "replayed"
    elif mutation == "clock":
        row["started_utc"] = (baseline - timedelta(hours=1)).isoformat()
    elif mutation == "request-drift":
        p = root / row["sources"][SOURCES[0]]["request"]["path"]
        p.write_text("{}")
    elif mutation == "dispatch-drift":
        p = root / "scheduler" / (row["slot"] + ".json")
        p.write_text("{}")
    path.write_text(json.dumps(row))  # Deliberate corruption only in owned synthetic state.
    with pytest.raises(ValueError):
        reconcile(root, admission)


@pytest.mark.parametrize(
    "control",
    [
        "complete",
        "elapsed-short",
        "gap",
        "duplicate",
        "manual",
        "bootstrap",
        "origin-only",
        "prebaseline",
    ],
)
def test_fixed_window_kernel_synthetic_population_is_not_natural(campaign, control):
    # Population is synthetic kernel input, NOT 169 DB cycles or elapsed time.
    from board_clank.campaign_acceptance import assess_window, campaign_spec
    import copy

    root, admission, tick, baseline = campaign
    first = tick(0)
    second = tick(1)
    rows = [first]
    for hour in range(1, 169):
        row = copy.deepcopy(second)
        start = baseline + timedelta(hours=hour, seconds=5)
        row.update(
            slot=start.strftime("%Y%m%dT%H0000Z"),
            started_utc=start.isoformat(),
            finished_utc=start.isoformat(),
        )
        rows.append(row)
    if control == "elapsed-short":
        rows[-1]["finished_utc"] = (baseline + timedelta(hours=168, seconds=4)).isoformat()
    elif control == "gap":
        rows.pop(20)
    elif control == "duplicate":
        rows.append(copy.deepcopy(rows[-1]))
    elif control in ("manual", "bootstrap", "origin-only"):
        rows[-1]["campaign"]["role"] = control
    elif control == "prebaseline":
        rows[1]["started_utc"] = first["finished_utc"]
    spec = campaign_spec(admission.approval, admission.path.parent)
    if control in ("duplicate", "manual", "bootstrap", "origin-only", "prebaseline"):
        with pytest.raises(ValueError):
            assess_window(spec, rows)
    else:
        report = assess_window(
            spec, rows, observed_at=datetime.fromisoformat(rows[-1]["finished_utc"])
        )
        assert report["natural_credit"] == 0 and report["t0"] == "UNKNOWN_NOT_ACTIVATED"
        assert report["window_complete"] is (control == "complete")
        if control == "complete":
            assert report["eligible_slots"] == 168 and report["elapsed_seconds"] == 604800
            assert report["consecutive_valid_dates"] >= 7


def test_native_transport_capture_bytes_are_rejoined(approval_file, tmp_path):
    from board_clank.campaign_acceptance import captures
    from board_clank.production_network import Guard, LimitedResponse
    from board_clank.production_ledger import Ledger
    import io

    root = tmp_path / "capture-root"
    root.mkdir()
    directory = root / "run"
    directory.mkdir()
    admission = load(approval_file)
    source = SOURCES[0]
    guard = Guard(
        source,
        admission.approval.source_budgets[source],
        Ledger(root / "ops.sqlite"),
        root,
        capture_dir=directory / "http",
    )
    record = guard.reserve("https://pip.raspberrypi.com/synthetic", 0)
    record["status"] = 200
    response = LimitedResponse(
        io.BytesIO(b"explicit synthetic native transport body"), 1000, guard, record
    )
    response.read()
    http = {
        "source": source,
        "requests": guard.requests,
        "request_count": guard.count,
        "response_bytes": guard.bytes,
    }
    (directory / (source + ".http.json")).write_text(json.dumps(http))
    facts = captures(root, directory, source)
    assert facts["bodies"][0]["bytes"] == guard.bytes
    assert facts["bodies"][0]["sha256"] == record["body_sha256"]
    from pathlib import Path

    Path(record["body_file"]).write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        captures(root, directory, source)


def test_operational_mode_cannot_use_injected_execution(campaign):
    from board_clank.campaign_acceptance import cycle_binding

    root, admission, tick, baseline = campaign
    tick(0)
    # Explicit synthetic witness files are not reclassified as natural. A real
    # operational admission must be separately provisioned, never minted here.
    binding = cycle_binding(
        root, admission, baseline.strftime("%Y%m%dT%H0000Z"), native_execution=True
    )
    assert binding["mode"] == "SYNTHETIC" and binding["natural_eligible"] is False
