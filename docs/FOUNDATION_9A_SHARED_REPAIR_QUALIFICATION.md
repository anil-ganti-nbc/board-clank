# Forlinx Foundation 9A shared-contract repair qualification

Mission COPS-000097; source-only; 2026-10-03.

Qualified implementation and live execution SHA:
`4b2af9969cecc36cfecc66458b6237bc0473cbe7`.
Implementation tree: `d71653a39128a1e7cec1e54bbeda2369d455278d`.
This reporting-only descendant does not claim independent review or acceptance.
The earlier 7c81617/a459 qualification remains preserved and superseded.

Repairs retain explicit Forlinx CPU configuration, authenticate immutable
PRODUCT inputs with product-input-v1 receipts, reject changed/legacy/cross-source
replays before writes, validate first-party redirects and final provenance,
fail collections atomically when required evidence loses its document role,
and consistently declare Python >=3.12. Meaningful shared regression tests
cover these boundaries independently on the Khadas-derived Forlinx lineage.

At the implementation SHA, the supervisor's immutable Git-archive suite passed
568 tests in 322.10s with actual process exit0 and unchanged candidate bytes.
The separately verified exact implementation CI passed locked Python3.12
hermetic tests, non-root container, Foundation roster/readiness and Fleet Laws.
The existing exact Git-archive wheel proof ran all nine installed adapters
with no repository fallback. Final reporting-SHA checks are recorded separately.

Three separately invoked manual Forlinx live passes each fetched65 documents:
46 resolved Board products,11 insufficient-evidence documents and2 MCU-only
rejections. Inventory retained46 boards/revisions/variants and30 SoCs.
Events were215/0/0; the initial215 were silent and all notifications suppressed.
Later passes produced no new events or outbox entries and semantic hashes
remained stable. Following power loss, only missing pass3 ran on a verified
SQLite-safe backup of the completed two-pass experimental soak; original
soak bytes stayed unchanged. No completed pass was replayed as a new live pass.

The supervisor reparsed all195 captured first-party inputs with immutable
implementation code and independently verified semantic hashes, occurrence
provenance, schema3, integrity/FK checks, disabled/unpromoted sources, zero
eligible/delivered notifications, read-only observer, complete occurrence
backup metadata, full backup table equality and restored replay behavior.
Backup/restore and exact-run replay were SQL no-ops for editorial state;
the later restored run added only operational provenance/sightings.

These are bounded experimental qualification observations. They do not imply
production admission, deployment, promotion, source enablement, delivery or
scheduling authority. Independent Hermes/Sol review must name the exact final
reporting candidate SHA/tree; any rework invalidates candidate-scoped review.
