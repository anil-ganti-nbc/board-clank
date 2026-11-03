# Seven-source Board incident — status published 3 November 2026

## Latest verified state

Read-only NAS readback at **2026-11-03T05:32:58Z** reconfirmed collector
`STOPPED_FAIL_CLOSED`, 24 completed natural cycles, retained `inflight=25`.
The separate sender readback at **05:32:58Z** reconfirmed
`SENDER_STOPPED_BEFORE_CONFIRMED_FINITE_END`. Neither service was restarted.

The detailed findings below are the **2 November 13:09–13:10 UTC diagnostic
snapshot**, not freshly recounted database totals. Later status confirmation
establishes continued failure, not a new forensic integrity pass.

Accepted/deployed native source: `d9e294c5cf6e55c86129a3dcbfea105b798cf564`.
Historical accelerated production acceptance remains a historical decision;
it is not current availability or recovery acceptance. Raspberry Pi, ODROID
and Hardkernel remain mothballed. No new source requests or Discord calls
were made for this publication.

## 3. Board: first failure and causal chain

### 3.1 Confirmed collector failure

**Severity: HIGH — FACT.**

The first observed post-release collection failure is scheduled slot 25. Its native child returned a typed refusal with `BlockingIOError`, empty stdout and exit 2. The outer hourly controller then exited 1.

Relevant control flow:

1. `production_runtime.py:168–180` performs preliminary admission/seal checks and attempts the canonical `runtime.lock`.
2. That lock is nonblocking. `production_ledger.py:155–178` raises when another holder owns it.
3. The durable cycle claim and source permits occur **after** this lock acquisition (`production_runtime.py:201–208`).
4. Native CLI error handling emits the typed refusal to stderr and leaves stdout empty.
5. The hourly controller calls `json.loads(stdout)` at line 37 **before** checking the child return code at line 38.
6. Parsing the empty stdout produces a secondary `JSONDecodeError`; the controller records `STOPPED_FAIL_CLOSED` and preserves `completed=24, inflight=25`.

The JSON parsing error therefore **masks the actionable native refusal**. Correcting that parsing alone would improve diagnosis but would not fix the lock-contention failure.

### 3.2 Confirmed locking asymmetry; probable contender

**Design behavior: FACT. Historical contender: strong INFERENCE.**

Both the collector and the delivery process use the same canonical runtime lock. The sender explicitly catches Linux `EAGAIN`, records `SKIPPED_LOCK` and tries again on its next permitted poll. The collector has no equivalent transient-contention handling: its single native invocation refuses and the hourly controller terminates.

A bounded offline contrast, executing the exact native lock-helper AST on owned state, established:

- collector-side acquisition raises `BlockingIOError` while another holder owns the lock;
- acquisition succeeds after that holder releases it;
- opposite-direction contention can be handled as the sender’s `SKIPPED_LOCK`;
- empty stdout reproduces the controller’s secondary JSON parsing failure.

The sender was running against the same runtime and wrote a successful delivery-pass receipt at **10:37:06.551179 UTC**, immediately after the collector’s failed startup window. It is therefore the strongest retained contender.

**What is not proved:** the receipt is written after the drain returns and contains neither lock-acquisition time nor historical holder PID. Another same-authority runtime user cannot be retrospectively excluded. The precise historical lock owner remains **UNKNOWN**. The deterministic contrast proves the failure mechanism, not that missing ownership fact.

### 3.3 Sender failure after collection stopped

**Severity: HIGH — strongly supported INFERENCE.**

The native sender refuses delivery unless the latest complete collection is at most 3,600 seconds old. Relevant code is `discord_delivery.py:221–225`.

The operational ledger records the last COMPLETE finish at **09:54:45.959864 UTC**. The sender’s last successful poll was **10:54:25.647883 UTC**, just inside that freshness window. Its next nominal poll was **10:55:25.647883 UTC**, outside it. Docker records sender exit 2 at **10:55:26.746840 UTC**, with retained `REFUSED / ValueError` output.

An exact guard-AST replay:

- passes at the last successful poll;
- rejects at the next nominal poll;
- rejects at the actual process-exit time.

This strongly supports **collector loss → stale COMPLETE cycle → sender refusal**. The historical exception text/stack was intentionally not retained in detail, so this is not a recovered exact exception message. Nothing in the retained delivery ledger establishes a Discord outage, revoked webhook or failed product POST.

### 3.4 Incident timeline

| Event | UTC, 31 October | IST, 31 October |
|---|---|---|
| Last complete cycle 24 starts | 09:37:08.218647 | 15:07:08.218647 |
| Cycle 24 native receipt finishes | 09:54:45.933262 | 15:24:45.933262 |
| Slot 25 due | 10:37:03.276788 | 16:07:03.276788 |
| Slot 25 dispatched | 10:37:04.102972 | 16:07:04.102972 |
| Controller records failure | 10:37:05.978193 | 16:07:05.978193 |
| Collector exits | 10:37:06.057704 | 16:07:06.057704 |
| Correlated sender pass receipt | 10:37:06.551179 | 16:07:06.551179 |
| Collector failure alert run begins | 10:45:00 | 16:15:00 |
| Collector alert recorded delivered | 10:50:18 | 16:20:18 |
| Last successful sender poll | 10:54:25.647883 | 16:24:25.647883 |
| Sender exits | 10:55:26.746840 | 16:25:26.746840 |
| Sender alert run begins | 10:59:00 | 16:29:00 |
| Sender alert recorded delivered | 11:02:08 | 16:32:08 |

The receipt finish and operational-ledger finish are separate clocks, approximately 27 milliseconds apart; the freshness calculation uses the **operational-ledger** finish.

Slot 25 dispatch-to-terminal was **1.875221 seconds**. Due-to-Docker-exit was **2.780916 seconds**. It did **not** run for 55 minutes. The later `INFLIGHT_OVERRUN` label is the age of a retained failed-inflight marker, not the original child’s execution duration.

---

## 4. Board: effects, integrity, budget and notification evidence

### 4.1 What persisted

| Population | Verified count |
|---|---:|
| Complete natural cycles | 24 |
| Durable cycle rows, including retained failure and initialization stage | 26 |
| Native slot-25 cycle / source-run / source-permit rows | **0 / 0 / 0** |
| Boards | 178 |
| Canonical observations | 865 |
| Processed run receipts | 177 |
| Events / notification records | 1,932 / 1,932 |
| Diagnostic conditions | 105: 101 OPEN, 4 RESOLVED |
| Automatic sender receipts | 1,315 |
| Successful no-op delivery passes | 967 |
| Legitimate sender lock skips | 348 |
| Automatic product delivery attempts / sends | **0 / 0** |
| Owner destination-confirmation records | 1 |

There is no native slot-25 run directory and no later request reservation. The native refusal’s generic “collection or delivery claimed UNKNOWN” can be narrowed using the independently queried ledger and the code ordering: this attempt did not reach the admitted source-acquisition path.

**Correction to earlier reporting:** the 1,932 events are **1,924 baseline-silent events plus 8 non-silent historical offline-role-replay events**, not 1,932 silent events. The eight predate activation. There are two historical PUSH/outbox notification records, but those are not proof of eligible post-activation alerts or actual sends. All automatic sender receipt result arrays are empty and the delivery-attempt ledger is empty.

The single previously verified manual connectivity test is a separate historical action. It must not be counted as an automatic product notification, launch detection or natural collection.

### 4.2 Integrity and limits

Both Board SQLite forensic copies return `integrity_check=ok`; original database file hashes match before and after inspection. The last successful cycle records zero FK errors. **A current Board FK check was not separately rerun**, and integrity checks alone do not authenticate every historical semantic interpretation.

The seven baselines and all 101 acknowledged OPEN uncertainties remain. There is no evidence that a new parser error, identity-condition transition or manufacturer-policy rejection caused slot 25.

Both stopped objects have `OOMKilled=false`, restart count 0 and restart policy `no`. Current free-space evidence does not establish historical disk conditions, but the retained failure is not a 3,300-second timeout or an OOM termination. No host-reboot cause is established.

### 4.3 Accounting: do not reset it

The operational ledger contains **8,017 request reservations**, including historical predecessor records; the seven retained sources account for 8,010 and an older excluded-source row accounts for seven. These are reservation records, not a claim that all were successful HTTP responses.

| Retained source | Lifetime request reservations |
|---|---:|
| Banana Pi | 979 |
| Forlinx | 1,656 |
| FriendlyELEC | 1,131 |
| Khadas | 581 |
| Orange Pi | 1,330 |
| Pine64 | 579 |
| Radxa | 1,754 |

The aggregate cycle limit is 170 and 26 rows exist, leaving **144 unclaimed cycle units**. That is **not** authority for 144 new hours, catch-up work or an extended campaign. Slot 25 remains a failed controller attempt even though it never acquired a native cycle reservation. Nothing should be refunded or rewritten to make it appear successful.

Per-source ceilings remain 300 requests/cycle, 600/hour and 7,200/day, with one concurrent request, one-second minimum spacing, 25-second request timeout, 450-second source deadline, 8 MB/response, 128 MB/source-cycle and no HTTP retries. Retained body-file sizes are not HTTP wire totals or complete unknown-charge accounting.

---

## 6. Monitoring, stale status and the verification gap

The collector alert was recorded delivered on **31 October at 16:20 IST**, and the sender alert on the same day at **16:32 IST**. Further sender messages concerned confirmation of the stopped service and a transient observer-read failure. They were not repairs.

| Monitor | Recorded executions at audit snapshot | Delivered outputs | Suppressed outputs |
|---|---:|---:|---:|
| Board collection | 247 | 2, including the earlier first-natural milestone | 245 |
| Board Discord | 236 | 3 | 233 |

These counts are **monitor executions, not collection cycles or product messages**. All jobs remain enabled. A `last_status=ok` means the monitoring operation completed; `no_change` means the projection did not change. Neither means the observed application is healthy.

The execution ledger records delivery and the detailed alert transcripts survive in separate cron sessions. Their configured route is the original local Hermes origin, not the Board product webhook. **Human receipt/read/acknowledgement is not established.** Exact old delivery-queue rows/tombstones were not retained; the surviving execution records and alert sessions do not prove an end-to-end human read.

At the start of this diagnosis, deployment-registry entries were dated captures that still said Board was running; they had not automatically synchronized with the incident. The parent has now appended fresh, read-back-verified observations recording both Board services as stopped and Anker r2 as running under probation. Earlier captures remain unchanged. This corrects the status record, **not the failed runtime**. The stale-inflight overrun label and the sender stopped-path’s zero currently scanned receipts also need correct interpretation, not destructive edits to retained evidence.

### Verification gap and accountability

The October activation checks genuinely established the reviewed adapter, a live first native delivery pass and then-normal collection. **They did not exercise the full bidirectional scheduling conflict: the sender holding the shared lock exactly when the one-shot collector starts.** Testing that the sender politely skips a busy collector does not establish that the collector tolerates a busy sender.

That is the integration case missed by the prior qualification. The subsequent monitors reported the incident, but were deliberately observation-only and did not recover it. Earlier `production accepted` and `alerts enabled` statements describe their verified activation times—not permanent uptime, automatic recovery or current health. This report corrects the current-state interpretation and the event-silence count without rewriting those historical records.

---

## 7. Minimum next actions — recommendations only

### Board: repair the demonstrated compatibility issue before any recovery

1. Preserve stopped containers, slot-25 dispatch/terminal evidence, existing catalogue, seal/review/approval, all 26 cycle rows and 8,017 request reservations. Preserve the failed dispatch even though it has no native cycle claim.
2. On an owned offline replica, make genuine lock contention a deliberately bounded scheduling outcome instead of a fatal collection error. The exact strategy requires a small reviewed change; do not simply bypass the shared lock, replace it with unrelated locks, or catch every filesystem error as “busy.” Any wait/defer behavior must fit the approved dispatch window and recheck current authority/time.
3. Correct controller handling of nonzero, empty or malformed native output so the typed refusal remains visible. This is a separate diagnostic defect, not sufficient recovery by itself.
4. Require bounded regressions in **both directions**, normal useful operation, no duplicate reservations/requests, contention before versus after a claim, explicit cancellation/stop, and preserved no-catch-up/deadline behavior. Do not reopen the large historical test suites by default.
5. Specify and approve a state-preserving prospective recovery. Startup currently refuses retained `inflight=25`; merely clearing it or restarting would either fail again or conceal history. Missed hours are not successful observations and may not be backfilled. Preserve the 24 completed cycles and obtain an explicit prospective schedule decision—**not another automatic full-week prerequisite and not a new empty catalogue**.
6. Only after a genuinely fresh complete collection and valid current authority should the sender resume. Preserve its original not-before, deduplication and ambiguity history; do not manufacture a product event or send another connectivity test to make the recovery look successful.

Original limits remain unchanged: final collection due **6 Nov 09:37:03 UTC / 15:07:03 IST**; delivery policy ends **6 Nov 11:32:03 UTC / 17:02:03 IST**; Board grant expires **7 Nov 06:17:51 UTC / 11:47:51 IST**. This report authorizes none of their extension.


## Evidence and repository integration

Parent verified all 16 Board indexed evidence entries by size/SHA-256 and
investigator Session closure. Original diagnostic records and raw evidence
remain private in the mission evidence store; no credentials, raw captures,
production databases, grants or enabled delivery policy are published here.

The unchanged historical hourly controller and reviewed seven-source delivery
adapter are preserved under `ops/reviewed-sidecars/`, together with its original
synthetic test file and explicit known-failure documentation. This preservation
is **not a fix or a new operational approval**. Repository integration does not
deploy the merged tree, amend finite authority, clear slot 25 or qualify recovery.

The independent Anker lane developed a **later** slot-5 PARTIAL failure on
2 November after the diagnostic snapshot. Current failure status is documented
in its own repository and coordination issue; the older healthy snapshot must
not be presented as today's health.
