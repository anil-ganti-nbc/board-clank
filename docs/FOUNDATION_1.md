# Foundation 1 — Raspberry Pi PRODUCT adapter

Foundation 1 adds exactly one live-capable source adapter:

- source: `raspberry-pi`
- plane: `PRODUCT`
- key: `raspberry-pi-product`

The adapter is REGISTERED and EXPERIMENTAL. It is disabled by default.
There is no scheduler, no Discord, no webhook, no promotion, and no
delivery activation.

## Official surfaces

Parser and live path may read first-party Raspberry Pi product surfaces only:

- `https://www.raspberrypi.com/products/` (catalogue index = leads)
- `https://www.raspberrypi.com/products/raspberry-pi-5/`
- `https://www.raspberrypi.com/products/raspberry-pi-4-model-b/`
- `https://www.raspberrypi.com/products/raspberry-pi-zero-2-w/`
- `https://www.raspberrypi.com/products/compute-module-4/`
- `https://www.raspberrypi.com/products/raspberry-pi-3-model-b/`

Index and navigation pages identify leads. They do not establish board
identity or novelty by themselves.

## Default path

`board-clank collect --source raspberry-pi-product` replays the packaged
HTML corpus. Tests never require network access.

`--live` remains refused.

`--experimental-live` is a manual human opt-in for raspberry-pi-product
only. It does not enable the source, promote it, or open delivery.

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
