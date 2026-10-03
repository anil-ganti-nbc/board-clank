# Forlinx Foundation 9A shared-contract repair qualification

Mission COPS-000097; source-only; 2026-10-03.

This document preserves historical observations and describes the new source
repairs. It does not claim that an earlier test, live execution or review
qualifies a changed candidate. The supervisor's final review packet must bind
all current receipts to its exact candidate SHA/tree. No independent approval
or acceptance is asserted here.

## Repairs following review of 2fcfe03e

The prior independent Sol review identified incomplete catalogue discovery,
inconsistent observer compatibility/schema reporting and missing matching
qualification receipts in its packet. The source findings are confirmed.

Catalogue validation now requires the qualified, complete numbered pagination
control, one active current page, consistent previous/next boundaries and
closed product-card structure. The qualified surface has ten card slots per
non-final page and one to ten on its final page, including explicitly excluded
non-SBC cards. Changes to these coverage canaries require requalification.
Discovery follows newly exposed pages to closure within sixteen pages, then
rejects inconsistent page sets and duplicate product routes. Required fetch
or structural failures discard the whole candidate batch; only failed-run
and error-provenance records may persist, never inventory/diagnostic changes.

Read-only observer projections use inspected schema versions rather than the
binary's expected version. Older, newer, partial, unstamped, malformed, empty
and corrupt state remain incompatible or UNKNOWN, yield degraded aggregate
health and do not receive current-schema domain queries. Inspection never
migrates or writes. The expected binary schema remains separately identified.

The shared PRODUCT boundary also checks disabled EXPERIMENTAL state and the
placeholder/out-of-scope flags against both the declared registry and durable
row before any write or replay shortcut. The runtime lock now satisfies the
project's PyYAML requirement, with `pip check` in hermetic CI. These repairs
are implemented locally on this lineage without importing integration work.

Regression coverage exercises root pagination loss, newly exposed pages,
structural truncation, inconsistent pagination, duplicate routes, all-table
failure atomicity, registry/durable authority drift before fresh admission or
exact replay, and byte-unchanged read-only incompatible observer projections.
Forlinx CPU configuration, application-SoC identity, companion-core isolation,
memory uncertainty, source-scoped diagnostics, historical baseline silence,
schema v3 and disabled/unpromoted sources retain their existing contracts.

## Historical evidence and packet correction

The earlier implementation/live execution SHA was
`4b2af9969cecc36cfecc66458b6237bc0473cbe7`, tree
`d71653a39128a1e7cec1e54bbeda2369d455278d`.
Its supervisor-run immutable Git archive passed **568 tests in 322.10s** with
actual process exit 0. The matching sanitized receipt and full-log digest are
committed in `docs/qualification_receipts/forlinx-4b-pytest.json`.
The independently retrieved historical GitHub receipts identified Foundation
run 37129047144 and Fleet Laws run 37129047131 as completed success on that
implementation SHA; their public links are in the same evidence file.

The later reporting candidate `2fcfe03e6830f6b31af91fb9cd26356c47de7217`
had its own **568 tests in 186.29s**, actual exit 0, and successful CI runs
37132309809/37132309736. Its review packet contained those later receipts,
not the earlier 322.10s receipt. Sol's inability to trace the earlier statement
from that packet was valid; it does not establish that the earlier run was
invented. The old evidence qualifies only its named SHA and remains preserved.

Historical manual Forlinx qualification recorded three passes of 65 public
first-party documents each, 46 resolved Boards, 11 insufficient documents and
two MCU-only rejections. Inventory held 46 boards/revisions/variants and
30 SoCs; events were 215/0/0, initially silent with notifications suppressed.
The missing third pass after power loss ran on a verified SQLite-safe backup
of the completed two-pass experimental soak; original soak bytes remained
unchanged. The subsequent supervisor audit reparsed the retained 195 inputs
offline and checked provenance, stable semantic hashes, integrity/FKs,
observer read-only behavior, all-table backup equality and restored replay.
Those observations do not claim an exact-final-SHA HTTP execution.

## Current candidate gates

Changed code requires fresh targeted regressions and full unfiltered pytest
with actual process receipts from an immutable exact-commit archive, relevant
byte-retaining isolated manual live passes, exact/later/restored replay,
byte-stable observer and complete backup/restore verification, and exact-SHA
CI. The external final packet records their actual outcomes; this document
does not predict success. Independent Hermes/Sol review must name that same
final SHA/tree, and every later change invalidates the prior review.

All work remains bounded experimental source qualification. It grants no
deployment, runtime restart, main merge, promotion, source enablement,
delivery, scheduler or CNX authority.
