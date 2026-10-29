# Board eight-source successor contract v1

## Scope and identity

Owner authority: `direct-owner-authority.json`, explicit new eight-source baseline
and qualification, preserving failed nine-source history. Source base
`3c9bfe89b07c6837e814d84ea0c4c0ca3baf5f7b`, branch
`hermes/board-eight-readiness-20261028`. This is COPS-000200, not a resumption
of mothballed COPS-000198. The versioned identity is
`board-eight-production-v1`; authoritative roster bytes are
`src/board_clank/eight-source-campaign.v1.json`.

Exactly: Raspberry Pi, Orange Pi, Radxa, Banana Pi, Pine64, FriendlyELEC,
Khadas, Forlinx PRODUCT. `hardkernel-odroid-product` remains MOTHBALLED.
No Hardkernel parser execution, fixture campaign, search or acquisition is part
of this qualification. Legacy nine-era code, fixtures and historical manifests
remain preserved for historical compatibility, not selected by the successor.
The old campaign `cops-000182-seven-day-d952-r2`, its seven seals/receipts,
NAS database and Task 18 are untouched. Its zero healthy nine-source days remain
zero; they cannot seed the successor's acceptance clock.

## Actual offline milestone

`board-clank-eight manifest` reports a disabled, packaged, versioned contract.
`board-clank-eight qualify-offline --root <fresh-owned-root>` exercises all eight
complete shipped baseline corpora through real adapters and native Pipeline,
exact-receipt replay, a later unchanged sweep, a real fixture revision, SQLite
backup, distinct restore and restored replay. It creates only new owned offline
state, never an actual production baseline or an Approval. Producer fixtures
remain fixture-labelled, including later adapters whose legacy optional label
is absent. No observations are trimmed to manufacture eight-source success.
Native proposed PUSH classification is not delivery; disabled source registry,
null delivered_at and no sender invocation remain explicit.

Mandatory contrasts: unknown/missing/duplicate/wrong roster, mothballed source
refusal before adapter lookup, missing approval/authority, source failure,
registry/integrity drift, repeated-run suppression, useful postbaseline signal,
backup integrity and isolated recovery. Existing admission, budgets, global
registry/integrity preflight, one-use source permits, parent/child locks and
truthful UNKNOWN reporting are retained, not replaced with a second scheduler.
Secure Discord capability remains a separately confirmed, disabled-by-default
entrypoint; no real credential or webhook is used.

## Fresh seven-day acceptance clock (not started)

Operational admission must separately bind exact installed candidate/image,
client, target, configuration, current eight-source source-access/budget evidence,
reviewed diagnostics, new state identity and campaign identity. Start time is
UNKNOWN until an admitted fresh baseline completes 8/8. Clock t0 is its actual
completion, not approval creation, fixture time or historical launch. Baseline,
manual tests, replay, duplicate slots, bootstrap and origin-only launches earn
zero natural credit. The next naturally scheduled cycle must start after t0.

Acceptance requires at least 604800 real elapsed seconds after t0 and a complete
hourly scheduled observation window (168 distinct postbaseline scheduled slots,
no missing/duplicate/catch-up substitutes). Each credited cycle must carry exact
campaign/attempt/revision/approval/roster identity and 8/8 ACCEPTED, native run
IDs/status, source-local item/observation/event/diagnostic counts and capture
hash/provenance. COMPLETE is not inferred from HTTP200, parser completion or
parent exit. DEGRADED, FAILED, HUMAN_REQUIRED or UNKNOWN never count as healthy.
Preserve zero results as actual zero only when source completeness supports it;
otherwise unknown. A failed slot blocks acceptance; operator must disposition
it and authorise any new window, never erase it or silently reset the clock.

## Executable prospective acceptance seam (still not activated)

`board-clank-hourly --root <owned-runtime> --approval <external-approval> reconcile`
uses `campaign_acceptance.reconcile`, the same root lock, immutable `cycle.json`,
operational ledger and read-only native SQL joins. It does not collect or install
anything and may inspect stopped roots. `Approval.campaign` is an optional hashed
`Evidence` reference; without it existing guarded runtime behavior remains usable,
but acceptance reports NOT_ADMITTED, zero credit and UNKNOWN t0. It is not a new
scheduler. Existing initialized roots without an attempt binding are not adoptable
by editing a receipt; a separately authorized fresh root/attempt is required.

The external JSON `Campaign` schema in `campaign_acceptance.py` is the executable
contract: format1, exact profile/ordered eight-source roster/roster hash, a fresh
canonical UUID attempt, candidate revision/code digest, absolute runtime root,
admission UTC time, baseline hourly slot, mode OPERATIONAL or SYNTHETIC, and
hashed scheduler/target `Evidence` references relative to the approval directory.
The approval hash binds the entire effective configuration and this record;
there is no self-referential approval hash inside its own dependency closure.
Scheduler evidence binds scheduler_id, attempt_id, root, mode, cadence_seconds3600
and external evidence_references. Target evidence binds attempt/root/mode,
revision/code hash and external client/target evidence_references. These files
are operator-provisioned authority under the existing Admission trust boundary:
hashes authenticate retained bytes/joins, **not consent or NAS origin**. Real
source permissions, intended client, target and scheduler attestation remain
separate external qualifications; synthetic files establish none of them.

A separately admitted external scheduler must retain an operator-controlled
`<root>/scheduler/<YYYYMMDDTHH0000Z>.json` before invoking `once`: exact attempt,
approval_sha256, scheduler_id, slot, unique dispatch_id, dispatched_at, mode and
role (`baseline` for the pinned baseline slot, otherwise `scheduled`). Dispatch
and actual start must be in the same hour, within five minutes, after admission.
There is one baseline plus168 consecutive subsequent hourly slots; no catch-up,
window replacement or historical attempt import. Runtime refuses injected
transport/clock for OPERATIONAL mode and authenticates the dispatch again inside
the root lock before the ledger claim/acquisition. No scheduler is supplied or
enabled by this implementation. SYNTHETIC mode always has zero natural credit.

Each accepted source retains the full accepted request hash and native run,
semantic receipt, baseline, observation/occurrence/distinct-item/event/diagnostic
counts. Native execution additionally retains verified HTTP manifest and original
body hashes/lengths; reconciliation reopens the captures, source permits, ledger
and native rows rather than trusting caller counts/flags. Empty source requests
are conservatively ineligible: none of the eight current catalogue contracts
qualifies a legitimate empty production baseline. Replay/manual/fixture/failed/
origin-only evidence cannot supply a credited cycle. Terminal native timestamps
have whole-second precision; reconciliation preserves this declared interval
rather than manufacturing subsecond clocks. Accepted baselines must be silent.

The bounded consumer authenticates at most169 cycles. It reports missing slots,
consecutive valid UTC dates, collecting span and elapsed observer time separately.
Full acceptance requires168 eligible postbaseline slots, at least seven
consecutive valid dates and604800 elapsed seconds since actual baseline finish.
An early last-slot finish can be reconciled later without another collection;
waiting cannot repair a missing or failed slot. The pure `assess_window` kernel
never awards natural credit; only the native-joined consumer can do so. Synthetic
kernel populations are not DB runs and keep actual t0 UNKNOWN. No automatic
promotion follows any acceptance result.

## Remaining admission gates, in order

1. Parent verifies frozen candidate and performs fresh independent review.
2. Locked Python3.12 CI; source test and native Linux results are separate.
3. Real container/image build and immutable byte/revision readback on an
   explicitly authorised local daemon (Dockerfile alone is NOT_RUN).
4. Current intended-runtime default-client permission, DNS/TLS, policy and
   complete eight-source acquisition under measured request/byte/time budgets.
   Offline fixture PASS supplies none of this permission or capability evidence.
5. Exact persistent target ownership/permissions, mounts, isolation/resource
   enforcement, capacity/retention, locks and compatible state qualification.
6. Actual diagnostic dispositions, SQLite-safe pre-cutover backup/integrity,
   distinct staging restore and post-restore replay; no production reset.
7. New baseline and source access activation authority, then ONE separately
   authorised new hourly task. Leave old Task18 origin-only and nonoverlapping.
8. Run the new seven-day window; reconcile every source and slot. Explicit
   operator promotion after evidence review, never automatically on green tests.
9. Discord optional: separately confirmed Board destination/event scope,
   owner-only secret mount/terminal route, current policy and delivery authority.

## Abort, backup and rollback

Stop the exact new task on scope/approval/registry/integrity drift, access denial,
request/byte/deadline exhaustion, incomplete source, unknown outcome, unexpected
diagnostics or delivery ambiguity. Use existing PAUSED/HUMAN_REQUIRED markers;
never remove stops automatically. Preserve domain DB, operational ledger,
requests/captures, terminal receipts and source failures. SQLite-safe backup must
cover domain state and stopped operational authority state consistently; verify
integrity, hashes, roster/attempt/revision and replay. Restore only to distinct
verified staging with delivery/scheduling disabled. Reconcile consumed request
budgets and ambiguous sends before re-admission; restoration replenishes neither.
Rollback pins last authorised image/config while keeping stopped new evidence;
it does not restart nine-source collection, revive Hardkernel, overwrite the NAS
baseline, edit Task18, delete new history or infer a lease renewal.
