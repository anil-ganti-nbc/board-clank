# Architecture

Board Clank is an operational Clank. SQLite is domain truth.

## Ownership

Operational Clank owns:

- domain truth
- SQLite
- source registry / config
- collection contracts
- scheduler contract (inert in Foundation 0)
- baseline
- classification storage
- event generation
- notification / outbox contract

Observer systems remain derived / read-only. Motherclank, Diagnostic Clank, CVC and Standards Clank do not receive domain mutation APIs here.

## Layout

```
config/sources.yaml          registry
migrations/001_initial.sql   schema v1
src/board_clank/identity.py  hierarchical keys
src/board_clank/pipeline.py  transactional admission
src/board_clank/store.py     SQLite + compatibility barrier
src/board_clank/collectors/  inert adapters
fixtures/scenarios           A–O offline evidence
```

## Runtime flow

1. Compatibility is inspected read-only.
2. Only `FRESH`, `COMPATIBLE` or explicit `MIGRATION_REQUIRED` may be admitted.
3. A collector adapter (fixture or inert vendor adapter) produces a `CollectorRunRequest`.
4. `Pipeline.accept_run` binds current state, canonical content, occurrences, events, outbox rows and a processed-run receipt in one `BEGIN IMMEDIATE` transaction.
5. Exact run replay is a no-op.
6. Failure rolls back.

## Compatibility states

`FRESH` `COMPATIBLE` `MIGRATION_REQUIRED` `INCOMPATIBLE_NEWER` `PARTIAL` `CORRUPT` `UNKNOWN`

Health never migrates. Older binaries fail closed against newer schema. Partial migrations fail closed.

## Release channel

`BOARD_CLANK_RELEASE_CHANNEL` defaults to `foundation-0`.
`BOARD_CLANK_SOURCE_REVISION` is the OCI / runtime provenance SHA.
GitHub HEAD is not treated as the deployed SHA.
