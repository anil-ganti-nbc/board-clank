# Board v8 and supporting evidence integration (COPS-000096)

This source-only integration starts from Khadas development tip
`7a3c2a409721fd25917522b3edb862755c2523d4` and merges Todd's completed reporting
tip `04e901a2022fc3b2f3fb7326eb3810aa6a5c4a7a`. Todd qualified implementation
`58a199b599826ca359ddaa350220c671d038ba54` from shared base
`613c3a13c0e52088eeb33d6266b6ca7b2b783000`. Both completed input histories are
retained. The admitted runtime remains a separate fact; this branch is not a
deployment, promotion or collection enablement.

## Source authority decision

The eight `sources` manifest entries remain canonical first-party PRODUCT
adapters. The additive `supporting_sources` declaration contains the bounded
`radxa-rock5b-documentation-poc` source with vendor `radxa`, plane
`DOCUMENTATION`, authority `FIRST_PARTY_SUPPORTING`, registered state
`REGISTERED`, promotion state `EXPERIMENTAL`, and `enabled=false`.

Both repository and packaged registries declare this same disabled source.
The runtime manifest validates each section against its matching registry
selection. Supporting evidence cannot satisfy a missing PRODUCT vendor in the
foundation roster. The manifest report retains `source_count` for canonical
PRODUCT sources and adds a separate `supporting_source_count`. The existing
observer source-summary shape is unchanged and now honestly describes all 17
declared rows: eight PRODUCT, one supporting, and eight placeholders.

The generic PRODUCT factory and `collect --source` command do not dispatch
the supporting collector. Its existing explicit isolated qualification module
remains the entry point. A supporting source key in either a generic request
or one of its drafts fails before any writes. The firewall checks declared
supporting keys as well as durable supporting authority, so a forged PRODUCT
plane or changed durable authority cannot grant PRODUCT admission. Existing
unregistered Foundation-0 fixture semantics are retained; the new registered
source does not broaden that historical fixture contract.

## Evidence boundaries

`DOCUMENTATION_REFERENCE` remains a separate typed namespace in schema v3.
The seven bounded ROCK 5B hardware-reference assertions link only to exactly
one already validated first-party PRODUCT Board. They cannot mint a Board,
revision or variant, move PRODUCT current pointers, change market novelty, or
create notification/outbox rows. Missing or ambiguous targets fail closed.
Dates absent from first-party claims remain `UNKNOWN`. Each historical new
reference is a silent `NEW_REFERENCE` audit transition; subsequent semantically
unchanged passes add occurrences only. Exact-run replay is a complete SQL no-op.

Todd's original architecture and qualification documents describe the historical
isolated POC before global registration. This integration document supersedes
their global-roster/manifest statements for this branch; their qualified SHA,
tree, pass counts and raw-byte evidence remain historical facts.

## Integration proof

`tests/test_v8_evidence_integration.py` seeds all eight qualified PRODUCT adapters
and proves authority separation, all-table firewall/exact-replay immutability,
PRODUCT state preservation during three reference passes, same-run and new-run
PRODUCT replay, scoped diagnostics, observer read-only byte stability, and
SQLite-safe backup/restore equivalence including observation occurrences.
Todd's existing parser, ambiguity, raw-response-byte, partial-failure and typed
event proofs remain in the full suite. Schema and migrations are unchanged.

The merge resolves package-data semantically by retaining FriendlyELEC,
Khadas and documentation fixture assets, and explicitly packages the manifest.
Both CI workflow branch triggers include `integration-v8-evidence-plane` so the
exact pushed candidate runs hermetic tests, non-root container checks and Fleet
Laws. Qualification evidence is retained outside this worktree under
`C:\Users\anil\Clanks\_Reconciliation\board-v8-evidence`.

No final acceptance is asserted here. Full pytest process evidence, isolated
live reference receipts and exact-SHA CI must be followed by independent review
and canonical ClankOps gates before this Mission can complete.
