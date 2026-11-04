# Prospective Board recovery plan — not executed

This is a **state-preserving prospective plan** for the 3 November 2026
Board incident. Offline tests passing, this document, and local source
edits **do not** recover runtime, deploy, clear `inflight=25`, refund
reservations, rearm schedules, or resume Discord.

## Frozen facts to preserve

- Collector `STOPPED_FAIL_CLOSED`; sender
  `SENDER_STOPPED_BEFORE_CONFIRMED_FINITE_END` (readback 2026-11-03T05:32:58Z).
- 24 complete natural cycles; retained `inflight=25` with **zero** native
  slot-25 cycle / source-run / source-permit rows.
- 8,017 request reservations unchanged. Slot 25 never acquired a native
  cycle claim. Do not refund, rewrite, or present it as successful.
- Historical sidecar bytes remain:
  - `ops/reviewed-sidecars/hourly_controller.py`
    `4e6d95a3a56f1a66895786ebc8745aa9c74f459a2303224c84ae56887d4dd035`
  - `ops/reviewed-sidecars/seven_delivery.py`
    `fafe732c0e0a66bae50d84d0f2c0cc815274248bcbfa4c6fb0c989fd9f29ee19`
- Original windows (do not extend): last collection due
  2026-11-06T09:37:03Z; delivery policy end 2026-11-06T11:32:03Z;
  grant expiry 2026-11-07T06:17:51Z.
- Raspberry Pi, ODROID and Hardkernel stay mothballed.

## Offline repair delivered (reviewable local only)

1. Genuine nonblocking `runtime.lock` busy becomes `DEFERRED_LOCK`
   **before** any cycle/source claim. The shared lock is not bypassed.
   Arbitrary filesystem errors are not treated as busy.
2. Native CLI prints `DEFERRED_LOCK` JSON on stdout with exit 0.
   Other refusals still use stderr typed JSON and empty stdout / exit 2.
3. New `board_clank.native_slot_outcome.interpret_native_output` inspects
   returncode before stdout, keeping typed `BlockingIOError` visible.
4. New `board_clank.hourly_dispatch.dispatch_native_slot` retries only
   `DEFERRED_LOCK` inside `due+120s`, rechecks stop/expiry, and refuses
   catch-up. Historical controller bytes are not modified.
5. Targeted regressions:
   `tests/test_board_incident_lock_output.py`.

## Sequential validation (COPS-000214 / t_561999ff) — offline only

Predecessor HEAD `12caebc2` in an isolated owned copy already failed the same
four application-adjacent nodes as the dirty candidate:

- `test_child_requires_parent_and_retains_own_acquisition_lock` (no-parent-lock,
  child-lock-held, accepted) — `CollectorError` Raspberry Pi adapter lookup disabled.
- `test_init_and_hourly_replay_keep_odroid_mothballed` — expected `COMPLETE`,
  got `DEGRADED` because collect called `get_adapter(SOURCES[0])`.

This is an obsolete eight-source `get_adapter` fixture versus current RPi
mothball, **not** a lock/output source regression. Historical sidecars and the
pinned production lock/output bytes were left unchanged.

Harness correction (tests only): admitted synthetic retained-source receipts
never look up Raspberry Pi / ODROID adapters. Meaningful `COMPLETE` assertions
were restored (not `COMPLETE`-or-`DEGRADED`). Child ownership uses the first
non-mothballed admitted source (`orange-pi-product`).

Final relevant pytest (network proxies black-holed, `python -B`,
`-p no:cacheprovider`, `uv run --offline --extra dev`): **25 passed**,
0 failed, 0 skipped, exit 0. Log:
`docs/operations/2026-11-03-board-validation-offline-pytest.txt`.

Independent review, packaging/CI, and runtime recovery remain separate gates.

## Gates that remain closed

- Independent review of this exact local candidate.
- Deployment / image rebuild / container restart.
- Any live publisher or Discord request.
- Clearing or rewriting operational `progress.json` inflight.
- Automatic new-week or catch-up collection.
- Sender resume (requires a later fresh COMPLETE cycle under current
  authority, then original not-before / dedup / ambiguity history).

## If recovery is later authorised (do not do this now)

1. Keep stopped containers, catalogue, seal/review/approval, all 26 cycle
   rows and 8,017 reservations.
2. Install only the reviewed successor native + dispatch helper. Do not
   restart the historical sidecar controller as-is.
3. Record slot 25 as a failed controller attempt that never claimed;
   **do not** delete `inflight=25` to manufacture a clean start. A
   separately reviewed progress transition may mark that inflight as
   terminal-failed without creating a native cycle row.
4. Next collection is the next **future** due slot under remaining
   authority and original cutoff. Missed hours are not observations.
5. Resume sender only after one genuine fresh COMPLETE and valid current
   freshness; do not send a connectivity test or fabricate an event.

COPS-000213 remains COMPLETED (first bounded lock/output repair).
COPS-000214 is the sequential offline validation-correction. Runtime recovery
is a later operator decision.
