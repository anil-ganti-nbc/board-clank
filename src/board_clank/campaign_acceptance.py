"""Prospective campaign evidence. Operator files are authority, not cryptographic consent.

No acquisition, schedule installation, activation, promotion or notification here.
"""

from __future__ import annotations

import json
from pathlib import Path

from board_clank.eight_source_campaign import roster_hash
from board_clank.source_profiles import ProfileId, profile_manifest
from board_clank.models import CollectorRunRequest
from board_clank.production_policy import digest, Evidence, StrictModel, utc
from datetime import datetime, timezone, timedelta
from typing import Literal
from uuid import UUID
from pydantic import Field, StrictInt
import sqlite3
from contextlib import closing


class Campaign(StrictModel):
    format: StrictInt = Field(ge=1, le=1)
    profile_id: ProfileId
    attempt_id: str
    sources: list[str]
    roster_sha256: str
    revision: str
    code_sha256: str
    root: str
    admitted_at: str
    baseline_slot: str
    mode: Literal["OPERATIONAL", "SYNTHETIC"]
    scheduler: Evidence
    target: Evidence


def slot_time(slot):
    value = datetime.strptime(slot, "%Y%m%dT%H0000Z").replace(tzinfo=timezone.utc)
    if slot != value.strftime("%Y%m%dT%H0000Z"):
        raise ValueError("noncanonical hourly slot")
    return value


def campaign_spec(approval, directory):
    if approval.campaign is None:
        return None
    spec = Campaign.model_validate_json(approval.campaign.read(directory))
    if (
        str(UUID(spec.attempt_id)) != spec.attempt_id
        or spec.profile_id != approval.profile_id
        or spec.sources != list(approval.sources)
        or spec.roster_sha256 != roster_hash(list(approval.sources))
        or spec.revision != approval.revision
        or spec.code_sha256 != approval.code_sha256
        or not Path(spec.root).is_absolute()
        or utc(spec.admitted_at) < utc(approval.approved_at)
        or utc(spec.admitted_at) > slot_time(spec.baseline_slot) + timedelta(hours=1)
    ):
        raise ValueError("campaign identity/scope/clock mismatch")
    for ref, role in ((spec.scheduler, "scheduler"), (spec.target, "target")):
        proof = json.loads(ref.read(directory))
        if (
            proof.get("attempt_id") != spec.attempt_id
            or proof.get("root") != spec.root
            or proof.get("mode") != spec.mode
            or not proof.get("evidence_references")
        ):
            raise ValueError("unbound external campaign " + role + " witness")
        if role == "scheduler" and (
            not proof.get("scheduler_id") or proof.get("cadence_seconds") != 3600
        ):
            raise ValueError("hourly scheduler witness required")
        if role == "target" and (
            proof.get("revision") != spec.revision or proof.get("code_sha256") != spec.code_sha256
        ):
            raise ValueError("target artifact witness mismatch")
    return spec


def read_json(ref, root):
    return json.loads(Evidence.model_validate(ref).read(Path(root)))


def cycle_binding(root, admission, slot, *, native_execution):
    value = identity(admission)
    spec = campaign_spec(admission.approval, admission.path.parent)
    value.update(mode="UNADMITTED", role="manual", dispatch=None)
    if spec is None:
        return value
    if Path(root).resolve() != Path(spec.root).resolve():
        raise ValueError("attempt is bound to a different runtime root")
    if (
        not slot_time(spec.baseline_slot)
        <= slot_time(slot)
        <= slot_time(spec.baseline_slot) + timedelta(hours=168)
    ):
        raise ValueError("slot outside admitted finite window")
    path = Path(root) / "scheduler" / (slot + ".json")
    ref = file_ref(path, root)
    dispatch = read_json(ref, root)
    scheduler = read_json(spec.scheduler.model_dump(), admission.path.parent)
    if (
        dispatch.get("attempt_id") != spec.attempt_id
        or dispatch.get("approval_sha256") != admission.raw_hash
        or dispatch.get("scheduler_id") != scheduler["scheduler_id"]
        or dispatch.get("slot") != slot
        or dispatch.get("mode") != spec.mode
        or not dispatch.get("dispatch_id")
        or dispatch.get("role") != ("baseline" if slot == spec.baseline_slot else "scheduled")
        or not slot_time(slot)
        <= utc(dispatch["dispatched_at"])
        < slot_time(slot) + timedelta(hours=1)
        or utc(dispatch["dispatched_at"]) < utc(spec.admitted_at)
    ):
        raise ValueError("dispatch witness does not authenticate this attempt/slot")
    if spec.mode == "OPERATIONAL" and not native_execution:
        raise ValueError("operational campaign requires native transport and actual clock")
    value.update(
        attempt_id=spec.attempt_id,
        campaign_sha256=admission.approval.campaign.sha256,
        mode=spec.mode,
        role=dispatch["role"],
        dispatch=ref,
        natural_eligible=spec.mode == "OPERATIONAL" and native_execution,
    )
    return value


def identity(admission):
    profile = profile_manifest(admission.approval.profile_id)
    return {
        "profile_id": profile["campaign_id"],
        "attempt_id": None,
        "sources": list(admission.sources),
        "roster_sha256": roster_hash(list(admission.sources)),
        "revision": admission.revision,
        "code_sha256": admission.approval.code_sha256,
        "approval_sha256": admission.raw_hash,
        "natural_eligible": False,
    }


def file_ref(path, root):
    path, root = Path(path), Path(root)
    return {"path": path.relative_to(root).as_posix(), "sha256": digest(path.read_bytes())}


def native_facts(store, request):
    """Rejoin semantic input to actual accepted native scalar rows and counts."""
    from board_clank.pipeline import _product_input_receipt

    run = store.one("SELECT * FROM collector_runs WHERE run_id=?", (request.run_id,))
    receipt = store.one("SELECT * FROM processed_run_receipts WHERE run_id=?", (request.run_id,))
    if (
        not run
        or not receipt
        or run["source_key"] != request.source_key
        or run["collector_key"] != request.collector_key
        or run["status"] != "accepted"
        or run["fixture_scenario"] != request.fixture_scenario
        or not run["finished_at"]
        or run["started_at"] != request.started_at
        or receipt["source_key"] != request.source_key
        or receipt["receipt_hash"] != _product_input_receipt(request)
        or receipt["observation_count"] != len(request.observations)
    ):
        raise ValueError("native accepted run/input mismatch")
    counts = {}
    for key, table in (
        ("occurrences", "observation_occurrences"),
        ("events", "events"),
        ("diagnostics", "diagnostic_sightings"),
    ):
        counts[key] = store.one(f"SELECT COUNT(*) FROM {table} WHERE run_id=?", (request.run_id,))[
            0
        ]
    if counts["events"] != receipt["event_count"]:
        raise ValueError("native event count mismatch")
    baseline = store.one("SELECT * FROM source_baselines WHERE source_key=?", (request.source_key,))
    return dict(
        counts,
        run_id=request.run_id,
        source_key=request.source_key,
        status=run["status"],
        fixture_scenario=run["fixture_scenario"],
        started_at=run["started_at"],
        finished_at=run["finished_at"],
        observations=receipt["observation_count"],
        distinct_items=store.one(
            "SELECT COUNT(DISTINCT entity_key) FROM observation_occurrences WHERE run_id=?",
            (request.run_id,),
        )[0],
        receipt_hash=receipt["receipt_hash"],
        baseline_run_id=baseline["baseline_run_id"] if baseline else None,
    )


def captures(root, directory, source):
    """Authenticate retained native transport bodies, not caller completeness flags."""
    http_path = Path(directory) / (source + ".http.json")
    ref = file_ref(http_path, root)
    http = read_json(ref, root)
    records = http["requests"]
    if http.get("source") != source or not records or http.get("request_count") != len(records):
        raise ValueError("native transport request coverage missing")
    bodies = []
    for record in records:
        if record.get("status") == "REDIRECT_FOLLOWED":
            if not any(
                r.get("attempt") == record.get("response_attempt") and r.get("body_complete")
                for r in records
            ):
                raise ValueError("redirect response provenance missing")
            continue
        if not record.get("body_complete") or not record.get("body_file"):
            raise ValueError("incomplete capture cannot qualify")
        path = Path(record["body_file"])
        body = file_ref(path, root)
        raw = Evidence.model_validate(body).read(root)
        if len(raw) != record["body_bytes"] or body["sha256"] != record["body_sha256"]:
            raise ValueError("native response body mismatch")
        bodies.append(dict(body, bytes=len(raw)))
    if sum(b["bytes"] for b in bodies) != http["response_bytes"]:
        raise ValueError("native response byte aggregate mismatch")
    return {"http": ref, "bodies": bodies}


def reconcile(root, admission):
    """Bounded read-only receipt/native reconciliation, under the existing root lock.

    No caller-provided eligibility flags or receipt-only hashes are trusted.
    Missing/past/failing slots remain visible; a changed window needs new authority.
    """
    from board_clank.production_ledger import exclusive_lock
    from board_clank.compatibility import inspect_path
    from types import SimpleNamespace

    root = Path(root).resolve()
    admission.validate()
    spec = campaign_spec(admission.approval, admission.path.parent)
    if spec is None:
        return {"status": "NOT_ADMITTED", "natural_credit": 0, "t0": "UNKNOWN_NOT_ACTIVATED"}
    if root != Path(spec.root).resolve() or not (root / "runtime.lock").is_file():
        raise ValueError("initialized attempt root required")
    if inspect_path(root / "board.sqlite").state.value != "COMPATIBLE":
        raise ValueError("compatible native state required")
    with exclusive_lock(root / "runtime.lock"):
        admission.validate()
        init = json.loads((root / "initialization-complete.json").read_bytes())
        if init["approval"] != admission.raw_hash or init.get("campaign") != identity_for_root(
            root, admission
        ):
            raise ValueError("initialization does not bind this attempt")
        with (
            closing(sqlite3.connect((root / "board.sqlite").as_uri() + "?mode=ro", uri=True)) as db,
            closing(
                sqlite3.connect((root / "operations.sqlite").as_uri() + "?mode=ro", uri=True)
            ) as ops,
        ):
            for connection in (db, ops):
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only=ON")
                connection.execute("BEGIN")
            store = SimpleNamespace(
                one=lambda sql, args=(): db.execute(sql, args).fetchone(),
                all=lambda sql, args=(): db.execute(sql, args).fetchall(),
            )
            from board_clank.production_policy import validate_state
            validate_state(store, admission)
            if (
                db.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                or db.execute("PRAGMA foreign_key_check").fetchall()
            ):
                raise ValueError("native integrity failure")
            cycles = ops.execute("SELECT * FROM cycles ORDER BY slot").fetchall()
            if len(cycles) > 169:
                raise ValueError("bounded campaign exceeds baseline plus 168 slots")
            paths = list((root / "runs").glob("*/cycle.json"))
            if {p.parent.name for p in paths} != {c["slot"] for c in cycles}:
                raise ValueError("cycle receipt/ledger membership mismatch")
            rows = []
            dispatch_ids = set()
            for cycle in cycles:
                slot = cycle["slot"]
                directory = root / "runs" / slot
                path = directory / "cycle.json"
                row = read_json(file_ref(path, root), root)
                expected = cycle_binding(
                    root, admission, slot, native_execution=spec.mode == "OPERATIONAL"
                )
                if (
                    row["campaign"] != expected
                    or row["slot"] != slot
                    or row["approval_sha256"] != admission.raw_hash
                    or row["revision"] != spec.revision
                    or cycle["approval"] != admission.raw_hash
                    or cycle["status"] != row["status"]
                    or row["status"] != "COMPLETE"
                    or row["integrity"] != "ok"
                    or row["foreign_key_errors"] != 0
                    or set(row["sources"]) != set(admission.sources)
                ):
                    raise ValueError("cycle identity/status/roster mismatch")
                dispatch = read_json(expected["dispatch"], root)
                start, finish = utc(row["started_utc"]), utc(row["finished_utc"])
                if (
                    dispatch["dispatch_id"] in dispatch_ids
                    or not slot_time(slot) <= start <= finish < slot_time(slot) + timedelta(hours=1)
                    or not utc(dispatch["dispatched_at"])
                    <= start
                    <= utc(dispatch["dispatched_at"]) + timedelta(minutes=5)
                    or abs(cycle["started"] - start.timestamp()) > 5
                    or abs(cycle["finished"] - finish.timestamp()) > 5
                ):
                    raise ValueError("duplicate dispatch or untruthful cycle clocks")
                dispatch_ids.add(dispatch["dispatch_id"])
                source_rows = ops.execute(
                    "SELECT * FROM source_runs WHERE slot=?", (slot,)
                ).fetchall()
                if {
                    r["source"]
                    for r in source_rows
                    if r["status"] == "ACCEPTED"
                    and Path(r["receipt"]).resolve() == directory.resolve()
                } != set(admission.sources):
                    raise ValueError("operational source ledger mismatch")
                for source, result in row["sources"].items():
                    request = CollectorRunRequest.model_validate(read_json(result["request"], root))
                    native = native_facts(store, request)
                    if (
                        request.run_id != slot + "-" + source
                        or request.source_key != source
                        or request.collector_key != source
                        or not request.ok
                        or request.fixture_scenario is not None
                        or not request.observations
                        or result["status"] != "ACCEPTED"
                        or result["result"]["status"] != "accepted"
                        or result["result"]["replayed"]
                        or json.dumps(result["native"], sort_keys=True)
                        != json.dumps(native, sort_keys=True)
                        or result["result"]["run_id"] != request.run_id
                        or result["result"]["observations"] != native["observations"]
                        # RunResult.occurrences counts admitted input drafts;
                        # native occurrences count BOARD/REVISION/VARIANT rows.
                        or len(result["result"]["events"]) != native["events"]
                        or not start <= utc(native["started_at"]) <= finish
                        or not start.replace(microsecond=0) <= utc(native["finished_at"]) <= finish
                        or utc(native["started_at"])
                        >= utc(native["finished_at"]) + timedelta(seconds=1)
                    ):
                        raise ValueError("source native/result/clock mismatch")
                    baseline_id = spec.baseline_slot + "-" + source
                    if native["baseline_run_id"] != baseline_id:
                        raise ValueError("baseline belongs to another attempt/window")
                    baseline = db.execute(
                        "SELECT * FROM source_baselines WHERE source_key=?", (source,)
                    ).fetchone()
                    if slot == spec.baseline_slot and (
                        baseline["observation_count"] != native["observations"]
                        or db.execute(
                            "SELECT 1 FROM events WHERE run_id=? AND baseline_silent=0",
                            (request.run_id,),
                        ).fetchone()
                    ):
                        raise ValueError("baseline is not silent/complete")
                    if spec.mode == "OPERATIONAL":
                        if result.get("captures") != captures(root, directory, source):
                            raise ValueError("capture provenance mismatch")
                        permit = ops.execute(
                            "SELECT * FROM source_permits WHERE slot=? AND source=?", (slot, source)
                        ).fetchone()
                        if (
                            not permit
                            or permit["approval"] != admission.raw_hash
                            or permit["consumed"] != 1
                        ):
                            raise ValueError("native source execution permit missing")
                rows.append(row)
            observed_at = (
                max((utc(r["finished_utc"]) for r in rows), default=datetime.now(timezone.utc))
                if spec.mode == "SYNTHETIC"
                else datetime.now(timezone.utc)
            )
            report = assess_window(spec, rows, observed_at=observed_at)
            if spec.mode == "OPERATIONAL" and rows:
                baseline = next((r for r in rows if r["slot"] == spec.baseline_slot), None)
                if baseline is not None:
                    report.update(
                        t0=baseline["finished_utc"],
                        natural_credit=report["eligible_slots"],
                        status="ACCEPTANCE_WINDOW_COMPLETE"
                        if report["window_complete"]
                        else "PENDING",
                    )
            report.update(
                profile_id=spec.profile_id,
                attempt_id=spec.attempt_id,
                roster_sha256=spec.roster_sha256,
                approval_sha256=admission.raw_hash,
                production_promotion=False,
            )
            return report


def identity_for_root(root, admission):
    result = identity(admission)
    spec = campaign_spec(admission.approval, admission.path.parent)
    if spec is not None:
        if Path(root).resolve() != Path(spec.root).resolve():
            raise ValueError("attempt root mismatch")
        result.update(
            attempt_id=spec.attempt_id,
            campaign_sha256=admission.approval.campaign.sha256,
            mode=spec.mode,
        )
    return result


def assess_window(spec, rows, *, observed_at=None):
    """Pure fixed-window kernel; public callers cannot turn it into natural credit.

    Only reconcile() authenticates producer/native context and awards natural credit.
    """
    by_slot = {row["slot"]: row for row in rows}
    if len(by_slot) != len(rows):
        raise ValueError("duplicate slot")
    baseline = by_slot.get(spec.baseline_slot)
    result = {
        "status": "PENDING",
        "natural_credit": 0,
        "t0": "UNKNOWN_NOT_ACTIVATED",
        "eligible_slots": 0,
        "synthetic_slots": 0,
        "missing_slots": [],
        "consecutive_valid_dates": 0,
        "elapsed_seconds": 0,
        "window_complete": False,
    }
    if baseline is None:
        return result
    t0 = utc(baseline["finished_utc"])
    first = slot_time(spec.baseline_slot) + timedelta(hours=1)
    wanted = [(first + timedelta(hours=n)).strftime("%Y%m%dT%H0000Z") for n in range(168)]
    if set(by_slot) - {spec.baseline_slot} - set(wanted):
        raise ValueError("receipt outside fixed campaign window")
    eligible = []
    for slot in wanted:
        row = by_slot.get(slot)
        if row is None:
            result["missing_slots"].append(slot)
            continue
        if (
            row["campaign"]["role"] != "scheduled"
            or utc(row["started_utc"]) <= t0
            or row["status"] != "COMPLETE"
        ):
            raise ValueError("non-postbaseline scheduled cycle")
        eligible.append(row)
    dates = sorted({utc(row["started_utc"]).date() for row in eligible})
    streak = best = 0
    prior = None
    for date in dates:
        streak = streak + 1 if prior is not None and date - prior == timedelta(days=1) else 1
        best = max(best, streak)
        prior = date
    observed_at = observed_at or datetime.now(timezone.utc)
    collecting = (
        max((utc(r["finished_utc"]) - t0).total_seconds() for r in eligible) if eligible else 0
    )
    elapsed = (observed_at - t0).total_seconds()
    result.update(
        eligible_slots=len(eligible),
        consecutive_valid_dates=best,
        elapsed_seconds=elapsed,
        collecting_seconds=collecting,
        observed_at=observed_at.isoformat(),
        window_complete=len(eligible) == 168 and best >= 7 and elapsed >= 604800,
    )
    if spec.mode == "SYNTHETIC":
        result.update(
            status="SYNTHETIC_WINDOW_COMPLETE"
            if result["window_complete"]
            else "SYNTHETIC_PENDING",
            synthetic_slots=len(eligible),
            synthetic_t0=t0.isoformat(),
        )
    return result
