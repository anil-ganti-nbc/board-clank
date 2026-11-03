# Seven-source one-use initialization

This additive path separates acquisition from baseline authority. Historical grants,
ordinary `once`, original rosters and old failed slots retain their meanings.
Nothing here installs a scheduler, fetches during finalization, enables delivery,
refunds a reservation, extends a lease, or claims synthetic work as operational.

## Admission and custody

Use the normal strict Approval loader and all existing gates. Add optional
`initialization: {path, sha256}` referencing a strict `Initialization` object.
The object must name `format:1`, `enabled:true`,
`phase:INITIALIZATION_ACQUISITION`, the existing campaign attempt/root/revision,
code digest, exact `board-seven-production-v1` ordered source list, original
absolute `expires_at`, and `image_sha256` matching the campaign target witness.
It also names `approved_by`, `decision_id`, and the finite allowed `reviewers`.
Bind `recovery_sha256` to the authenticated recovery-manifest **input** digest,
not the resulting recovery receipt (which itself includes the approval hash).

The reservation fields are explicit: `aggregate_reservations:170`,
`predecessor_consumed:1`, `baseline_reservations:1`, `future_slots:168`,
`charged_requests:92`, and the actual retained `predecessor_slot`.
This is the parent's conditional +1 amendment, not a refund or a generic renewal.
The supported `scripts/successor_prepare.py` composes the accepted native
initializer and paired restore. Its additive branch verifies the packet binding,
unchanged predecessor expiry and unchanged publisher/source caps. It reports 169
remaining reservations from actual admission, rather than its historical 168.
It remains paused until separately admitted by the operator; it never collects.
Its receipt and all packet history remain retained in the new root.

For the current parent amendment the immutable expiry is
`2026-11-07T06:17:51.812169+00:00`; a full new seven-day window requires successful
finalization no later than `2026-10-31T06:17:51.812169+00:00`.

## Acquisition and exact review

`board-clank-hourly --root ROOT --approval APPROVAL stage` uses the same lock,
ledger, source permits, bounded native children, HTTP/publisher/robots fences,
Pipeline and Store as ordinary production. A caller flag without separately
bound authority/custody/phase cannot admit it. The campaign's one baseline
scheduler witness is required, but is not an enabled hourly scheduler.
One durable initialization claim consumes the one new baseline reservation.
Interrupted, failed and partial work stays consumed; there is no automatic retry.

During that claim, genuine native IDENTITY_ANOMALY/NOVELTY_UNRESOLVED conditions
may remain OPEN with unchanged UNKNOWN semantics. Native condition identities,
payload hashes, registry, integrity, stop, permission and resource checks remain
strict. All stage events are silent, including on restored sources that already
have a baseline. Source baseline IDs and historical semantic rows are not reset.
Successful acquisition is `STAGED_PENDING_REVIEW`, never COMPLETE or t0.
It retains the complete source receipts, logical Store digest and exact current
condition inventory in `runs/SLOT/cycle.json`. Failure is not a healthy baseline.

A separate reviewer produces a file **inside the runtime root** containing:

- `format:1`, approved `reviewed_by`, nonempty `decision_id`, exact
  `approval_sha256`, `attempt_id`, and `stage:{path,sha256}`.
- The stage's exact `store_sha256` and full `conditions` inventory (including
  status, state hash, payload digest and full-row digest; resolved facts too).
- `dispositions`: all and only OPEN conditions, each using the existing strict
  Disposition fields: condition/source/state/payload identity, precise
  `accepted_uncertainty` or `excluded_coverage`, rationale, matching reviewer,
  and hash-bound evidence inside the root. No blanket waiver and no fake fix.

`board-clank-hourly --root ROOT --approval APPROVAL finalize --review REVIEW`
fetches zero and reserves zero. It rejoins all seven accepted real native run and
request receipts, stage/current Store, grant/campaign/image/custody, condition
facts, evidence and dispositions before writing the seal. Changed, partial,
foreign, missing or unapproved facts refuse. The grant is not edited after stage.
A valid seal is immutable and joined to its hash in the operations ledger.
Only successful finalization records actual current UTC in `sealed_utc` and,
for OPERATIONAL mode only, `t0`. Synthetic mode exposes no operational t0/credit.

## Subsequent operation

The first due time is seal UTC +3600 seconds, not the failed/stage clock or an
immediate baseline refetch. A scheduled witness retains the existing fields and
adds `sequence` (1..168) and `baseline_seal_sha256`; its role is `scheduled`.
Slot is the UTC hour containing seal UTC + sequence hours; dispatch and execution
must occur in that due interval. No catchup or manual/fixture credit is admitted.
All 168 naturally spaced cycles and 604800 actual seconds are required for full
acceptance, within the original absolute lease. The aggregate 170 cap includes
the old failed reservation and the stage. `reconcile` authenticates this additive
window separately and keeps the predecessor failure uncredited and visible.
Ordinary grants without `initialization` retain the original fail-closed path.

## Concrete NAS operator sequence (NOT executed by this change)

Parent owns independent review, publication/build, actual target/source admission
and activation. Do not use a synthetic approval, a local source commit alone, or
an unreviewed image. Bind ROOT, APPROVAL, PACKET, IMAGE and the helper path from
the **new** reviewed target/campaign manifest; do not reuse/modify the failed
namespace, its PAUSED/HUMAN_REQUIRED markers, predecessor grant or old controller.

1. Read back the installed immutable image digest, measured code digest and
   source-access/lease evidence; match the new target and admission exactly.
   Verify the authenticated paired packet and exact reviewed helper checksum.
2. In that installed image, with the new root mounted read-write, approval/packet
   and helper mounted read-only, networking disabled, run:
   `python /handover/successor_prepare.py --root "$ROOT" --approval "$APPROVAL" --packet "$PACKET"`
   and then the identical command with `--write`. Require PREPARED_PAUSED,
   26/260 retained interpretation, old 25/235/614 semantic history, all 92
   charges/unknown reservations, old failed slot, and 169 remaining reservations.
3. Authenticate the finite stage authority and current publisher permissions.
   Parent alone removes the **new successor's** preparation PAUSED marker after
   this admission. Supply the single attempt-bound baseline dispatch witness.
   Leave all old markers intact. With permitted network, run:
   `board-clank-hourly --root "$ROOT" --approval "$APPROVAL" stage`.
   Retain its actual terminal, all seven native receipts and request charges.
   On failure, stop; never clear its consumed claim to retry.
4. Keep scheduling/delivery off. Same designated reviewer examines exact current
   conditions and source evidence and deposits REVIEW plus its referenced proofs
   in the root. No grant rewrite or ad-hoc mass resolution.
5. With networking disabled, run:
   `board-clank-hourly --root "$ROOT" --approval "$APPROVAL" finalize --review "$REVIEW"`.
   Read back the seal and durable matching hash; then run
   `board-clank-hourly --root "$ROOT" --approval "$APPROVAL" reconcile`.
   Require actual UTC t0, no second baseline fetch/reservation and zero initial
   natural credit. If the full remaining lease no longer fits, refuse; no renewal.
6. Only after that successful readback, parent enables the existing hourly
   controller with first due from the seal, sequence 1..168, exact seal digest and
   unchanged lease/caps. Do not dispatch the old baseline again. Verify enabled
   schedule configuration without waiting for or manufacturing a natural cycle.
   Notifications remain disabled. Mission acceptance is still parent-owned.
