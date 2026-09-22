# Foundation 3 — Radxa PRODUCT adapter (third-vendor admission)

Foundation 3A admits exactly one third vendor:

- source: `radxa`
- plane: `PRODUCT`
- key: `radxa-product`

The adapter is REGISTERED and EXPERIMENTAL. It is disabled by default.
No scheduler, no Discord, no delivery, no promotion, no fourth vendor.

## Official surfaces (observed 2026-09-22)

- `https://radxa.com/products/` — catalogue index. Role: DISCOVERY.
- `https://radxa.com/products/<category>/<model>/` — product pages. Roles:
  PRODUCT_IDENTITY (h1 name), PRODUCT_SPEC + VARIANT_EVIDENCE (marketing
  spec text: RAM/eMMC matrices, wireless choices), REVISION_EVIDENCE
  ("V1.1: LPDDR4X · V2.1: LPDDR5" hardware versions).
- `https://docs.radxa.com/` and `https://wiki.radxa.com/` — documentation
  planes, DOCUMENTATION_ONLY, not ingested.
- HTTPS only, Cloudflare-fronted (challenge scripts and email-protection
  links injected per request). No interstitial; no bypass needed.

The catalogue's own category taxonomy (`/rock5/`, `/zeros/`, `/cm/`, …)
mirrors the docs sidebar's series grouping, so family identity comes from
first-party taxonomy, not name surgery.

## Generic abstraction defects found and fixed

1. **Revision-realised RAM silicon leaked into BOARD scope.** `ram_type`
   joined `BOARD_SCOPE_EXCLUDED_SPEC_FIELDS`: a board shipped in hardware
   versions with different memory silicon (Radxa ROCK 5C V1.1 LPDDR4X /
   V2.1 LPDDR5) would flip the board's canonical payload every run. A
   board-wide RAM-type transition is by definition a hardware revision and
   surfaces at REVISION scope. (`models.py`)

The §5 audit found no other generic vendor assumptions: identity keys,
diagnostics, capability gating, and payload scoping are vendor-neutral;
family-from-category, URL normalization (including the site's own
doubled `/products/products/` path bug), and companion-chip guards are
adapter-local.

## Semantics preserved

All Foundation 0–2B laws hold: first-seen ≠ market-new, silent baseline,
SKU/configuration ≠ board, new URL ≠ new board, uncertainty fails closed,
persistent uncertainty is state not perpetual novelty. ROCK 5B+ is a
distinct catalogue product (own page, onboard eMMC, different wireless)
from ROCK 5B, in family `rock-5`. CM5's page documents CM5 and CM5 Lite
with different SoCs (and its own description names a third): identity
conflict, fail closed. RP2040 / RTL8852BE / Mali / IMX never become SoCs;
"P1" is a SoC only with adjacent Cix context.

## Three-vendor comparison

| Concern | Raspberry Pi | Orange Pi | Radxa | Generic holds? |
| --- | --- | --- | --- | --- |
| discovery | PIP category indexes | product index | catalogue index | yes |
| canonical identity | product headings | product `<h3>` | product `<h1>` + category path | yes |
| specification evidence | prose heuristics | labelled tables | meta description + marketing spec text | yes — adapters own parsing |
| family taxonomy | numeric series from names | name-derived series | first-party URL categories | yes |
| variants | RAM/storage/wireless | RAM/eMMC/bundle | RAM/eMMC incl. wireless OR-choices | yes |
| revisions | PCB text | pin-definition headings | versioned RAM silicon (V1.1/V2.1) | yes (after fix 1) |
| SoCs | BCM/RP prose rules | row-labelled tables | part-number shapes + vendor context | yes |
| references/SKUs | SCxxxx | page URLs | page URLs; no SKU surface | yes |
| change evidence | PIP PCNs | none formal | none formal | role unused, not violated |
| semantic hashing | CSRF strip | token strip | Cloudflare script/email-protection strip | yes |
| access behaviour | HTTPS | HTTP-only host | Cloudflare-fronted HTTPS | yes — per-vendor policy |
| ambiguity behaviour | fail closed | fail closed | fail closed (CM5) | yes |
| partial failure | per-page error, run continues | same | same | yes — atomicity unchanged |

## How to run

```bash
PYTHONPATH=src python -m board_clank.cli collect --source radxa-product --db /tmp/bc-radxa.sqlite
PYTHONPATH=src python -m board_clank.cli collect --source radxa-product \
  --experimental-live --run-id radxa-live-1 --db /tmp/bc-radxa-live.sqlite
```

Tests remain offline and hermetic. `--experimental-live` never runs in tests.
