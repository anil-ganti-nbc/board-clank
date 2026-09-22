# Foundation 1 — Raspberry Pi PRODUCT adapter

Foundation 1 adds exactly one live-capable source adapter:

- source: `raspberry-pi`
- plane: `PRODUCT`
- key: `raspberry-pi-product`

The adapter is REGISTERED and EXPERIMENTAL. It is disabled by default.
There is no scheduler, no Discord, no webhook, no promotion, and no
delivery activation.

Foundation 1A keeps BOARD canonical comparison free of variant
dimensions. Enumerating RAM / storage / wireless options in one run is
VARIANT birth only. `FIELD_CHANGED` remains reserved for material board
specification transitions.

## Official surfaces

Parser and live path may read first-party Raspberry Pi product surfaces only:

- `https://www.raspberrypi.com/products/` (catalogue index = leads)
- `https://www.raspberrypi.com/products/raspberry-pi-5/`
- `https://www.raspberrypi.com/products/raspberry-pi-4-model-b/`
- `https://www.raspberrypi.com/products/raspberry-pi-zero-2-w/`
- `https://www.raspberrypi.com/products/compute-module-4/`
- `https://www.raspberrypi.com/products/raspberry-pi-3-model-b/`
- `https://pip.raspberrypi.com/` (Product Information Portal)
- `https://pip.raspberrypi.com/categories/505-computers`
- `https://pip.raspberrypi.com/categories/616-modules`

PIP is a first-party evidence surface under `raspberry-pi-product`, not a
second vendor. Roles: DISCOVERY on category indexes; PRODUCT_IDENTITY and
SKU/model references on product categories; CHANGE_EVIDENCE on PCN listings;
PRODUCT_SPEC / REVISION_EVIDENCE only when the document actually names a
processor or hardware revision.

SCxxxx identifiers are references. They do not mint a new BOARD.
A Product Change Note is not a launch announcement. Only a PCN that
explicitly names a hardware revision may record revision evidence.

Raspberry Pi 400 / 500 / 500+, desktop kits, IO boards, cases, monitors,
mice, Pico, and accessories are `NON_BOARD_CATALOGUE_ITEM` for this
SBC/module system. Compute Modules remain in scope.

Index and navigation pages identify leads. They do not establish board
identity or novelty by themselves.

## Default path

`board-clank collect --source raspberry-pi-product` replays the packaged
HTML corpus. Tests never require network access.

`--live` remains refused.

`--experimental-live` is a manual human opt-in for raspberry-pi-product
only. It does not enable the source, promote it, or open delivery.
Foundation 1D makes PIP the primary live surface; raspberrypi.com/products/
is supplementary and optional. CSRF tokens are excluded from semantic
evidence hashes so transport churn is not intelligence churn.

## Semantics preserved from Foundation 0

- First seen by Board Clank is not market-new.
- The first successful corpus ingest is a silent source-scoped baseline.
- Historical catalogue products may be `FIRST_SEEN_BY_CLANK` /
  `HISTORICAL_DISCOVERY` without becoming `NEW_BOARD` for delivery.
- A second official URL is `NEW_REFERENCE`, not a new board.
- RAM / storage / wireless options remain variants.
- PCB revision tokens are recorded only when first-party text names them.
- Insufficient or conflicting evidence fails closed as
  `NOVELTY_UNRESOLVED` / `IDENTITY_ANOMALY`.
- The other five Phase-1 vendors stay inert registry entries.

## Out of scope for this foundation

Orange Pi, Radxa, Banana Pi, ODROID, PINE64, schedulers, Discord,
automatic promotion, third-party pages.
