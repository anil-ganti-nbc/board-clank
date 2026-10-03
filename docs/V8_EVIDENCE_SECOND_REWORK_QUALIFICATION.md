# Board v8 evidence-plane second review rework qualification

Historical implementation report: superseded for current acceptance by the exact
`0da9b99a` independent REQUEST_CHANGES review and the third rework disposition.
Its recorded executions remain evidence only for the implementation SHA named
below; its earlier no-blocker/metadata assessment is not a current gate result.

Mission: COPS-000096. Date: 2026-10-03. Source-only.

Qualified implementation/live-execution SHA:
`034c8b11f2eeb72b1df838417b129b12632f1997`.

Qualified implementation tree:
`0b1a0c98652f81dd0dc72b2a9060055f678da43e`.

The independently reviewed `7136aa65d949405d81f958340b62bd9b231e6b23`
candidate received REQUEST_CHANGES. All four actionable findings are repaired,
including the supervisor's concrete required-document-role probes. This report
is a reporting-only descendant of the qualified implementation. Final SHA/tree,
exact-SHA CI and independent review are recorded separately; this document is
not a promotion, self-certification or Mission completion.

## Source repairs and meaningful regressions

1. Raspberry Pi, Orange Pi, Radxa, Banana Pi, ODROID and Pine64 validate every
   redirect before following it and validate the final URL before reading its
   body, using their existing first-party host/path/plane policies. Redirects
   are bounded to five hops and two repetitions. Required indexes keep their
   selected coverage route and DISCOVERY role; PCNs keep the selected change
   route and CHANGE_EVIDENCE role. Allowed PRODUCT-to-PRODUCT redirects retain
   actual final URL provenance. No unproved cross-product alias restriction was
   added.
2. Required fetch/parser failures, blank detail bodies, missing discovery
   coverage and unexpected document roles fail the whole collection with empty
   observations. This includes a successful detail followed by an allowed
   index fallback. Required details positively return resolved observations,
   nonempty conflict/insufficient-evidence drafts, or an explicit evidence-backed
   NON_BOARD_CATALOGUE_ITEM rejection with heading/reason and no drafts.
   Raspberry Pi uncertainty drafts are retained; its supplementary marketing
   catalogue remains optional. Failed-run diagnostics are durably retained in
   a versioned JSON message without admitting PRODUCT state or closing conditions.
3. PRODUCT replay uses `product-input-v1:<sha256>` in the existing receipt TEXT
   field. The immutable pre-admission projection includes source, collector,
   success flag, fixture scenario and ordered complete draft JSON. It omits
   only draft observed_at, price observed_at, novelty first_seen_at and
   raw_fields.html_excerpt, and excludes run start/error/transport diagnostics.
   It preserves all remaining raw/native/spec/variant/editorial-date/identity
   evidence, order and multiplicity. Admission deep-copies its request so
   identity resolution cannot alter the caller's evidence. Replay requires
   matching source plus recognized semantic fingerprint before any write.
   Changed evidence, source/collector/success collisions and failed-attempt IDs
   reject as all-table no-ops. Exact same-object/reconstructed replay and
   backup/restore replay are exercised.
4. Root, packaged and generated manifests now declare Python >=3.12, matching
   pyproject.toml and the built wheel's Requires-Python metadata.

FriendlyELEC and Khadas now retain labelled CPU clauses and vendor-qualified
candidate keys in draft raw fields. Unresolved candidate and labelled-text
changes are fingerprinted and produce diagnostic state changes on distinct
runs. Empty CPU evidence is omitted from diagnostic state so the historical
six-field hashes of the other six adapters remain exactly unchanged. The
existing-inventory birth-silence and registered source/plane/vendor firewall
from the prior rework remain enforced.

## Qualification at the implementation SHA

- Full pytest: 582 passed, 3 warnings in 335.84s (0:05:35); actual process exit 0. Complete log and
  exit receipt are retained outside the worktree. The three inherited
  Pydantic serializer warnings arise from existing tests assigning a string
  PCB enum; no test was skipped or waived.
- Focused positive role probes: 161 passed, exit 0; final per-index coverage
  probes: 8 passed, exit 0. Full-suite coverage includes all final regressions.
- Exact Git-archive wheel build/proof: build exit 0, proof exit 0, repository
  fallback false. All eight installed adapters ran: Raspberry Pi 42,
  Orange Pi 69, Radxa 42, Banana Pi 49, ODROID 14, Pine64 43, FriendlyELEC 32,
  Khadas 19 observed drafts. The packaged documentation provenance manifest
  and dedicated collector produced seven mappings. Wheel metadata, complete
  occurrence backup coverage and isolated restore were verified.
- Foundation roster, runtime/declared manifests and source/tools compile:
  actual exit 0 for each. Schema remains v3.
- Three fresh, separately invoked manual Radxa DOCUMENTATION live passes:
  actual exit 0/0/0; seven mappings in every pass, seven/zero/zero silent
  NEW_REFERENCE transitions. Exact-run replay is an all-table SQL no-op.

The eight PRODUCT vendors were seeded from qualified deterministic fixtures.
The current fresh network gate fetched only Radxa DOCUMENTATION; the six
PRODUCT redirect/partial-failure paths are proven by adversarial mocked
transport and real fixture parsers. This report does not claim fresh live
qualification of all eight PRODUCT sites.

## Raw bytes, semantic replay and persistence isolation

Actual received byte SHA-256 values for the three DOCUMENTATION captures:

- `8ce2adc188804292276dc4ad5a452ed401b8ca4f28f43454faeba253e5cd0cd4`
- `e832440494d80cd41a6928f4c2f24d7723f019add6aa66568871eeb076186f91`
- `1ce5c16d7e6ae42f004d16cc8475bd94e3f73a1c638619cd5d51eb2f39a43db9`

Semantic hash in all three passes:
`bee852a08cba6cb49d4fd243b2b822df99684af2006c57b765588ff98382e8b5`.

All reference keys/content hashes mapped to the same existing Radxa ROCK 5B
Board. Dates remain UNKNOWN. All PRODUCT graphs, current pointers,
occurrences, novelty, baselines, diagnostics and notification/outbox state
remained unchanged. Supporting evidence produced no notifications, non-silent
events, delivery or source enablement. Observer before/after database byte
hashes matched.

SQLite connection audit hooks reject any path outside the fresh isolation
root. Canonical/production connections: zero. The online SQLite backup SHA-256
is `aed752054ff0197b5dea51fc061fde3926287d678dbceb95907b6025e05fc216`.
It records the exact implementation revision and all 951 occurrence rows.
Original/backup/restored tables, including occurrences, match; integrity and
foreign-key checks pass, metadata coverage is COMPLETE, restored exact replay
is a SQL no-op. No production or historical database was migrated or replaced.

## Compatibility and retained history

Unprefixed old PRODUCT receipt values are outcome hashes, not input proof.
Their run IDs now refuse replay read-only as unverifiable; an operator must
use a fresh manually selected run ID. They are not relabelled or migrated.
Legacy v1 backup metadata may explicitly report LEGACY_PARTIAL occurrence
coverage while verified restored database bytes still retain all rows.

The prior 2531/08ec and 7136/fe5 reports, raw logs and receipts remain historical
evidence. Intermediate d87/341 full/wheel/live gates are preserved and
superseded by the role-corrected implementation. Initial targeted test-authoring
failures and the corrected CLI invocation receipt are retained without waiver.

No deployment, scheduler, source enablement, promotion, delivery authority
change, main merge or history rewrite occurred. Independent exact-SHA review
and canonical ClankOps acceptance remain supervisor-owned pending gates.

