# Foundation 0

Board Clank Foundation 0 establishes architecture only.

## In scope

- Hierarchical identity
- SoC graph
- Normalized spec contract
- Source planes and authority
- Event taxonomy
- Delivery policy (outbox, no send)
- SQLite schema and compatibility barrier
- Silent first baseline
- Chronology separate from canonical payload
- Inert Phase-1 adapters
- Fixtures A–O and hermetic tests
- CLI and non-root container contract

## Out of scope

- Production web scraping
- Scheduler installation
- Discord webhook
- Deployment
- Third-party discovery mesh
- Reddit ingestion
- GitHub-release harvesting
- Notification activation
- AI classification
- Fuzzy auto-merge
- Vendor-specific Selenium / Playwright
- Price-alert strategy beyond contracts
- Automatic source promotion
- NVIDIA Jetson domain

## Roster state

Phase-1 vendors are `REGISTERED` / `EXPERIMENTAL` only:

- raspberry-pi
- orange-pi
- radxa
- banana-pi
- hardkernel-odroid
- pine64

Phase-2 names are placeholders. Jetson is mothballed / out of scope.

## Laws applied

- Clank SQLite is domain truth.
- UNKNOWN remains UNKNOWN.
- observation → internal review → external delivery authority.
- experimental sources fail closed.
- soak → review → explicit human promotion.
- silent first baseline is mandatory.
- first_seen != market novelty.
- invocation != outcome.
- identity merges must be conservative.
- provenance must be preserved.
- missing authority fails closed.

## Acceptance

Foundation 0 is ready for review when the repository installs, tests pass hermetically, schema initializes from empty, health is read-only, no source is promoted, and no Discord contact is possible.
