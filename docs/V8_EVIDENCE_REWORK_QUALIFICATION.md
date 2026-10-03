# Board v8 evidence-plane review rework qualification

Historical qualification for the independently reviewed 7136/fe5 candidate,
which received REQUEST_CHANGES. The current repairs and fresh gates are recorded
in [V8_EVIDENCE_SECOND_REWORK_QUALIFICATION.md](V8_EVIDENCE_SECOND_REWORK_QUALIFICATION.md).

Mission: COPS-000096. Date: 2026-10-03. Source-only.

Qualified implementation/live-execution SHA:
`fe5e1bbdaac350b5e68227511e89693816d38c7a`.

Qualified implementation tree:
`4b40396c1451baeb90d0635a6927302909211e81`.

The prior exact `2531db26b9edac3fed097074f91ccd917488e7c6` candidate received
independent REQUEST_CHANGES. All four actionable findings are addressed. The
supervisor additionally required registered vendor provenance and correction of
an inherited `FIRST_SEEN != novelty` violation. No finding or test was waived.
This document follows the qualified implementation as a reporting-only change.
Final reporting SHA/tree and exact-SHA CI remain external receipts; independent
review and canonical ClankOps acceptance remain separate gates.

## Repairs and regressions

1. The wheel now contains all eight PRODUCT corpora (manifests and HTML) and the
   Radxa documentation provenance manifest. `tools/qualify_wheel.py` builds a
   wheel from an exact Git archive, then exercises the unpacked distribution in
   a fresh directory and isolated Python process. Every collector resolves its
   corpus inside that distribution. No repository fixtures or editable module
   imports may satisfy this qualification. The complete full suite includes this
   proof; setuptools is pinned in the development lock for offline wheel builds.
2. Generic admission rejects supporting sources, unknown sources, mixed draft
   source keys, inverse planes, inconsistent durable authority/plane/registered
   state and cross-vendor draft identity before any writes or receipt lookup.
   Every registered draft must match its request source and trusted registry
   vendor/plane. The historical unregistered E/F/M synthetic fixtures are
   available only through explicit fixture admission with fixed source, plane,
   collector and scenario bindings. Fixture admission cannot override registered
   provenance. Rejections are checked against all SQL tables.
3. New backup metadata and standard durable snapshots enumerate
   `observation_occurrences`. Genuine previous v1 metadata with the exact old
   table set is still accepted, with explicit `LEGACY_PARTIAL` coverage and the
   unverified occurrence table declared. Arbitrary omissions are rejected.
   Restore compares all observed current table counts with the verified backup
   image; image SHA-256 and integrity still protect the full copy. New metadata,
   older metadata, mismatched occurrence counts and arbitrary subsets are tested.
4. The parser's text hash is honestly named `decoded_text_sha256`. HTTP fetch
   metadata's `raw_sha256` still hashes the received bytes before decoding.
   UTF-8 BOM and Windows-1252 regressions prove exact byte preservation and
   semantic/diagnostic stability when decoding and UTF-8 re-encoding differ.
5. The supervisor-authorized novelty fix changes only birth-event silence for
   EXISTING_PRODUCT, HISTORICAL or explicitly historical inventory. Source
   baseline state and actual existing-entity transitions remain unchanged.
   Delayed inventory is audited as `known-inventory`; no launch date is invented.
   Eight actual adapter corpora test delayed Boards/variants, with explicit
   revision/variant stress cases and genuine unsuppressed port transitions.

Six inherited tests expected live inventory births despite catalogue-only or
historical evidence. Those assertions now require retained silent audit events
and no market novelty, while preserving real transition and replay checks.
The failed full run against intermediate `6020aa9` is retained, as are its
successful wheel/live receipts; none is attributed to the corrected SHA.
That run also exposed a Windows pytest subprocess handle issue in wheel
preflight, corrected by using owned stdin and output handles. Earlier focused
test-setup failures are retained and corrected. No tests were skipped.

## Exact implementation qualification

Full pytest: **414 passed in 178.74s**, actual process exit **0**. Complete output
and an independent exit receipt are retained. Foundation roster, runtime and
declared manifests, and source/tool compilation each returned exit 0.

The standalone exact-archive wheel build and isolated proof returned exit 0.
Offline accepted observation counts were Raspberry Pi 42, Orange Pi 69, Radxa
42, Banana Pi 49, ODROID 14, Pine64 43, FriendlyELEC 32 and Khadas 19. These are
fixture observation counts, not Board counts or live-catalogue censuses. Both
direct supporting admission and the packaged documentation CLI resolved seven
references. The wheel proof also passed exact/new-run replay, observer, online
backup and restore with complete occurrence coverage.

## Three fresh manual live reference invocations

The corrected SHA used a new isolated qualification directory and schema-v3 DB
under `rework-2/live-fe5e1bb`. All eight PRODUCT adapters seeded deterministic
first-party fixtures offline; only the bounded Radxa documentation page was
collected live. Each live pass was a separate explicit command invocation.
Runtime event and backup `code_revision` were explicitly set to the exact
implementation SHA, and the driver asserted Git HEAD before every invocation.

| Pass | Resolved mappings | Silent reference transitions | Actual process exit |
| --- | ---: | ---: | ---: |
| 1 | 7 | 7 | 0 |
| 2 | 7 | 0 | 0 |
| 3 | 7 | 0 | 0 |

Each mapping links to existing `radxa:rock-5b`. Effective/document dates remain
UNKNOWN. The live responses were retained byte-for-byte, with matching saved
size and raw SHA-256. Raw hashes:

1. `817663ddfbf0d8b66981f350afb909e6b7b61129c328829896eb78fe54444abc`
2. `d7d322754848a0fb5248d4def99783011ecd5466b91874e7b2d30d246aa8cc9d`
3. `4799b370246d0611743138f715f5709acdde40c48453394800bab3d4622e6af4`

All retained semantic hash
`bee852a08cba6cb49d4fd243b2b822df99684af2006c57b765588ff98382e8b5`.
Supporting admission preserved all PRODUCT tables, current pointers, PRODUCT
occurrences, novelty and outbox. Exact-run replay after every pass changed no SQL
table. There were no documentation notifications, delivered notifications,
non-silent reference events or FIELD_CHANGED transitions. Observer before/after
DB byte hashes matched and contract/schema remained stable.

The driver audited SQLite connection paths and refused any path outside its
isolated qualification root. Every recorded connection was isolated, including
backup and restore; canonical/production/historical DB connections were zero.
No existing DB was migrated. Original evidence directories were preserved.

## Backup and retained evidence

New online-backup metadata enumerated 951 observation occurrences, including 21
reference occurrences. Integrity was `ok`; restored metadata coverage was
`COMPLETE`. All SQL tables matched the source after restore, and restored exact
replay was a complete SQL no-op. Backup image SHA-256:
`caa488b216f95478851a6889c526c6dc1d8538101eb274270d51fed72c91b1e5`.

Complete corrected receipts live under
`C:\Users\anil\Clanks\_Reconciliation\board-v8-evidence\rework-2`, including
all HTTP metadata/captures, seven mappings, semantic hashes, raw-size checks,
PRODUCT before/after state, observer byte hashes, SQLite connection audit,
backup pair, restored DB, full pytest/exit receipts and exact archive-wheel proof.
The earlier independent-review packet and failed/superseded receipts remain in
their original directories.

Documentation text provenance is retained with source URL, Radxa attribution,
CC BY 4.0 and a modification notice. Linked artifact URLs are pointers; no
artifact contents were downloaded or assigned the documentation-text license.

This is builder qualification. A normal isolated-branch push and exact final CI
must precede fresh independent review. Mission completion and acceptance are
owned by the supervisor through ClankOps. All sources remain disabled and
EXPERIMENTAL; no deployment, scheduler, delivery, main merge or runtime replacement
occurred.
