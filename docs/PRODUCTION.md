# Explicit Board production capability

This candidate adds a separate, opt-in production entry point. The Foundation
CLI, source registry, observer and default notification/scheduler authority stay
inert. Code capability is not acceptance, deployment or permission to acquire.
Historical daily soak receipts must never be rewritten as production passes.

The production source set is exactly Raspberry Pi, Orange Pi, Radxa, Banana Pi,
Pine64, FriendlyELEC, Khadas and Forlinx PRODUCT. Hardkernel/ODROID is permanently
excluded by this profile and receives a disabled/MOTHBALLED durable registry row.
There is no automatic revival, including through a changed approval file.

## Acceptance and configuration

`board-clank production-manifest` reports installed revision, package/config byte
digest, source scope and cadence without opening state or making requests.
Use [production-approval.schema.json](production-approval.schema.json) or
`Approval.model_json_schema()` from `board_clank.production_policy` for the
strict approval-file schema. A draft is not an approval. No production approval
or real source budgets are shipped in this repository.

An operator-reviewed approval binds the exact candidate revision AND installed
code/config bytes, decision identity, explicit validity within source permissions, all
eight source budgets and content-addressed evidence files inside its directory.
Required gates: source_access, diagnostics, integrity, replay, backup_restore,
tests, locked_ci, container, independent_review and schedule_rollback. Each gate
document records PASS, the same revision/digest, reviewer and evidence references.
These records must describe executed checks; do not populate PASS placeholders.
Local tests deliberately use labelled synthetic approvals, never live authority.

Every source budget must have current permission evidence, exact existing
origins, request caps per cycle/rolling hour/rolling day (including robots,
redirects and retries), response/aggregate byte limits, concurrency, spacing, deadlines and
bounded retries. Daily budget must support 24 declared cycles, and aggregate
source deadlines must fit 3300 seconds. Lack of a published rate limit is not an
automatic measured budget. Account for observed catalogue closure, transient
retries, storage retention and other traffic before approving values.
Server Retry-After cooldowns persist across source processes and future hourly
cycles; a delay longer than the bounded retry window stops the current source
without forgetting the server's later retry time.

Robots is fetched once per approved origin per cycle, before product requests,
under the same budget. Rules, longest-match allow/disallow, query wildcards,
percent encoding and supported crawl-delay/request-rate directives are enforced
for every subsequent request, including redirects and collector worker threads.
403/401 permanently block that source under the permission-evidence digest;
there is no automatic retry next hour or alternate-route fallback. A fresh
operator-reviewed permission record is required to resume it. Non-200 robots
responses fail closed by default. The explicit `allow_missing_robots` flag permits
only 404/410, with matching documented source permission evidence; it never
permits 401/403, challenges or unverified redirects. See
[RFC9309](https://www.rfc-editor.org/rfc/rfc9309.html).

## Diagnostic disposition

`board-clank-diagnostic-export --db <verified-board-db> --out <new-file.json>`
exports a read-only transaction snapshot of the eight sources' conditions. It
does not migrate, suppress, resolve or delete any condition. Preserve the original
payload, source receipts and state hash. The diagnostics gate must reference this
snapshot by content hash. Every open condition requires a reviewer, rationale,
evidence hash and an exact condition/source/state/payload binding. Supported
dispositions explicitly document accepted uncertainty, excluded coverage or a
fixed-by-replay result bound to the exact candidate, successful source run,
retained source capture hashes and a distinct read-only qualification snapshot;
they do not alter canonical data or convert uncertainty to a product identity.
Proven defects must be fixed and replayed into distinct qualification
state, with original evidence preserved and review repeated. New/changed open
conditions block delivery and require fresh review before further acceptance.
A fixed-by-replay disposition never permits that condition to remain OPEN in
current production state, even if its old payload hash matches.

The prior103 conditions are not automatically103 defects or103 distinct boards.
Their actual rows and source captures still require review. Never create a
blanket disposition from counts or a fake replacement snapshot.

## Runtime, evidence and rollback

After every gate passes, initialize a NEW, separately verified production root:

```text
board-clank-hourly --root <new-root> --approval <approval.json> check
board-clank-hourly --root <new-root> --approval <approval.json> init
board-clank-hourly --root <new-root> --approval <approval.json> once
```

Initialization refuses an existing domain DB. It does not touch the canonical
historical database or old soak. There is no implicit migration or data reset.
An interrupted initialization needs inspection; do not delete evidence to retry.
Distinct verified staging restore uses existing backup/restore tools. Record
SQLite-safe backups, integrity/FK checks, full durable-state equivalence and
exact/later/restored replay before any cutover. Do not raw-copy a live SQLite DB.

One externally invoked cycle owns an OS lock and a durable UTC-hour claim. A
duplicate/incomplete hour is never recollected automatically; no catch-up runs
are invented. Each source runs in its own bounded child process, and an owned
timeout kills only that child. Per-source failure is retained and isolated from
other sources. Read HTTP response bodies (complete or partial), metadata, request counts,
raw hashes, CollectorRunRequests, failure records and cycle receipts stay in the
new runtime root. Aggregate byte caps and a free-space check bound acquisition;
retention/capacity must still be approved. Nothing automatically deletes evidence.

Global registry, ODROID mothball state, SQLite integrity/foreign keys and
diagnostic admission are checked before acquisition and delivery. Acquisition
children require an active parent-held runtime lock and a one-use permit bound
to parent process, source, hour and approval. The permit travels over a private
stdin pipe and is consumed durably before HTTP. A separate child-held OS lock
prevents acquisition overlap if the parent exits while its child is finishing.
Failed CLI calls report unknown collection status and point to retained receipts;
an exception is never proof that no acquisition occurred.

`PAUSED` and `HUMAN_REQUIRED.json` are emergency stops; code never removes them.
The runtime stops before acquisition on approval/scope/integrity drift. Missing
or changed diagnostic dispositions prevent a readiness claim or delivery.

An operator may install ONE reversible DSM hourly task only after current NAS
ownership, image ID/revision/code bytes, source budgets and acceptance are
verified. The task invokes `once` once an hour; it does not use the old sealed
nine-source controller, edit its manifest or borrow its acceptance credit. Check
the effective task, old campaign's no-collection guard and non-overlap before
activation. Do not create a duplicate collector. No installer is run by this
repository. Rollback means stop the exact new task, preserve its state/evidence,
pin the last approved image/config and restore only into distinct verified staging
when required. Never resurrect ODROID or other unrelated services during rollback.

## Optional Discord delivery and secure entry

No webhook is supplied, searched, generated, stored or contacted by this change.
The parent/operator must confirm the Board-only channel and exact event scope
before credential entry. Proposed initial scope: newly verified NEW_BOARD,
BOARD_REVISION, SOC_CHANGED, PORTS_CHANGED and EOL intelligence. Baselines,
historical backlog, review/suppressed rows and ODROID are never delivered.
Identity/novelty diagnostics are excluded unless explicitly selected and reviewed.
Source-health alert delivery is not inferred from intelligence-event permission.

The implemented entry route is an interactive, echo-free POSIX terminal running
as the final runtime user, in an existing owner-only secret directory:

```text
board-clank-discord credential-entry --secret-file <private-file>
```

It refuses noninteractive input, Windows without verified POSIX permissions,
existing files and unprivate directories. A terminal unable to disable echo is
refused, without getpass's fallback. It creates a new 0600 file, never prints
the token and performs no network request. It returns only destination/credential hashes.
Use an operator-supported secret mount owned/readable only by the runtime user;
the actual NAS terminal/mount route still needs operational verification. Do not
pass tokens through CLI arguments, environment files, logs, Git or this chat.

A separate DeliveryPolicy (schema from `board_clank.discord_delivery`) must be
explicitly enabled, bind the same revision, destination and credential hashes, confirmed channel,
human confirmation ID, event scope, activation time, expiry and message budgets.
It cannot outlive production approval. Only then may the operator invoke:

```text
board-clank-discord deliver --root <root> --approval <approval.json> --policy <confirmed-policy.json> --secret-file <private-file>
```

This is a separate explicit operation; collection never implicitly sends. Delivery
requires all eight silent baselines, a fresh complete production cycle and no
undispositioned conditions. It uses the same runtime lock, bounded per-run
throughput, persistent destination/global cooldowns and server rate headers.
The POST uses wait=true, disables mentions and requires a message ID acknowledgement.
Only definite 429 responses can retry (bounded attempts, recorded Retry-After).
Permanent 4xx disable the destination. Timeouts, 5xx, missing acknowledgement and
interrupted SENDING claims remain UNKNOWN and are never automatically resent.
This prevents blind duplicate retries; it cannot promise exactly-once remote
delivery after an ambiguous network failure. Manual reconciliation is required.
Original event/outbox rows are not rewritten; the operational delivery ledger is
the send-status authority. Event deduplication uses stable webhook identity, so
credential rotation cannot resend a sent or ambiguous event. A new credential
fingerprint requires a fresh confirmed policy; permanent denial blocks do not
automatically clear under the same confirmation. See Discord's
[execute webhook](https://docs.discord.com/developers/resources/webhook#execute-webhook)
and [rate limits](https://docs.discord.com/developers/topics/rate-limits).

## Validation status

Passing mock tests demonstrates capability and failure handling, not permission
to send or scrape. Actual diagnostic dispositions, current source/cadence budgets,
locked runtime/container, exact-candidate CI and independent review, fresh NAS
configuration/rollback verification and secure credential/destination activation
remain mandatory evidence. No deployment or live notification is implied.

The reviewed operator job entry `scripts/production_hourly.sh` runs one cycle and
stops on degradation. Its optional delivery arguments are only file paths, never
tokens. Supplying those arguments is a separate confirmed activation; the draft
profile has none. Neither this script nor the Python commands install a schedule.
