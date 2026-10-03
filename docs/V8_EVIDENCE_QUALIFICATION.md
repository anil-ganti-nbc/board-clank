# Board v8 / supporting evidence qualification

Mission: COPS-000096. Date: 2026-10-03.

Qualified implementation and live-execution SHA:
`08ecf888632931295e83f2a79bfccd2447797b65`.

Qualified tree: `8917d4cbf9dc4524cb6d5cb94ce2daa56fd311cc`.

This is a normal merge with exact parents
`7a3c2a409721fd25917522b3edb862755c2523d4` and
`04e901a2022fc3b2f3fb7326eb3810aa6a5c4a7a`. This reporting-only commit follows
the qualified implementation. Final reporting SHA/tree and exact-SHA CI receipts
are recorded in the external evidence packet and canonical ClankOps; they are
not inferred from this document.

## Local process evidence

The full suite completed on the implementation SHA: **390 passed in 126.03s**,
actual pytest process exit **0**. Complete output and a separate exit-code receipt
are retained at `full-pytest.txt` and `full-pytest.exit`. Foundation roster
assertion, runtime manifest, declared manifest and source compilation passed.
The first focused run had 84 passing tests and one test assertion failure due to
an incorrect backup metadata key (`integrity_check` instead of `integrity`). That
assertion was corrected before the qualified merge commit; its original complete
failure output is retained. No test failure was waived.

## Three manual experimental reference passes

Each pass was a separate explicit command invocation against a newly created
isolated schema-v3 DB under `live-08ecf888`. All eight qualified PRODUCT adapters
seeded that DB using their deterministic first-party fixtures; these were offline
PRODUCT baselines, not eight live vendor collections. The DOCUMENTATION responses
were fetched live from the exact bounded first-party Radxa URL. No production,
canonical or historical baseline DB was opened or migrated.

| Pass | Resolved mappings | Silent NEW_REFERENCE transitions | Process exit |
| --- | ---: | ---: | ---: |
| 1 | 7 | 7 | 0 |
| 2 | 7 | 0 | 0 |
| 3 | 7 | 0 | 0 |

All mappings target existing `radxa:rock-5b`. Effective dates and document
revisions remain `UNKNOWN`. No PRODUCT table/current/occurrence/novelty/outbox
state changed during supporting admission. Supporting events are baseline-silent
`NEW_REFERENCE`; there were no documentation notifications, eligible outbox,
delivered notifications or `FIELD_CHANGED` events. Same-run replay was an
all-table SQL no-op after every live pass.

Exact saved response-byte SHA-256 values:

1. `560d0a7835589799dbcc762ff967dcab1564be3210793cd0e021a6f368be75fb`
2. `45680ae090df3404a5e7e6d7553059de227810f176898acb5081ced703606456`
3. `e4081654baf8a088804fae85c3041dff7ffdc5cdadf16f2ac06e32863b9fdfde`

Every pass retained semantic hash
`bee852a08cba6cb49d4fd243b2b822df99684af2006c57b765588ff98382e8b5`.
Response sizes and raw SHA-256 values matched the exact captured bytes. The first
attempt failed at a read-only Git ownership preflight before creating the
qualification DB; that failure receipt is retained. A command-scoped
`safe.directory` setting allowed exact-HEAD validation without global Git changes.

## Compatibility and restoration

Observer snapshots retained the existing contract shape, reported schema v3 and
17 disabled declared source rows, and left DB bytes unchanged. The isolated
qualified fixture census was 78 Boards, 79 revisions, 310 variants, eight vendors,
seven reference current rows, and 21 reference occurrences. It is not a deployed
runtime census.

SQLite online backup and isolated restore both returned `integrity=ok`.
Backup image SHA-256:
`12c811c644a6b63d55a0e4d0b7571f6c15099eaecc5d68eb7ff528ea4c836ccd`.
Restored state matched every durable SQL table, including
`observation_occurrences` (which legacy backup metadata does not enumerate).
Restored exact-run replay was an all-table no-op. The runtime `code_revision`
field in these locally executed rows/backup metadata remains `UNKNOWN`; the
qualification driver independently asserted exact Git HEAD before each pass and
recorded that implementation SHA separately. No deployment fact is implied.

## Retained evidence and acceptance boundary

Complete evidence lives at
`C:\Users\anil\Clanks\_Reconciliation\board-v8-evidence`, including initial Git
inventory, the manual driver, full test/exit receipts, each raw HTTP capture and
metadata, PRODUCT before/after snapshots, observer snapshots, exact replay
assertions, the SQLite backup pair, restored DB, and `qualification.json`.

The final reporting candidate must receive exact-SHA hermetic CI, non-root
container CI and Fleet Laws checks, then independent exact-candidate review.
This is builder qualification evidence, not self-certification or Mission
completion. Sources stay disabled and EXPERIMENTAL. There is no scheduler,
delivery, deployment, main merge or admitted-runtime replacement.
