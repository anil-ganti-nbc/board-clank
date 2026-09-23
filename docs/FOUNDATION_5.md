# Foundation 5 — Hardkernel ODROID PRODUCT adapter (fifth-vendor admission)

Foundation 5A admits exactly one fifth vendor:

- source: `hardkernel-odroid`
- plane: `PRODUCT`
- key: `hardkernel-odroid-product`

REGISTERED and EXPERIMENTAL; disabled by default. No scheduler, no Discord,
no delivery, no promotion, no sixth vendor. This tranche ran under ClankOps
Mission COPS-000063 (ADR-0015 control).

## Official surfaces (observed 2026-09-23)

- `https://www.hardkernel.com/shop/` — WooCommerce catalogue index.
  Role: DISCOVERY.
- `https://www.hardkernel.com/shop/<slug>/` — product pages. Roles:
  PRODUCT_IDENTITY (the `h1` product-title), PRODUCT_SPEC + VARIANT_EVIDENCE
  (labelled spec rows), REVISION_EVIDENCE (H-series comparison-table
  production dates, recorded as raw evidence), availability evidence
  (shop stock status; no discontinuation dates invented).
- `odroid.com` / `wiki.odroid.com` / `forum.odroid.com` — documentation and
  community planes; HTTP 403 from this network; refused regardless, never
  bypassed.

## Fifth-vendor structural findings

- **Identity = h1, not the slug.** The N2+ page's slug omits the plus and
  carries a WooCommerce duplicate suffix; per-RAM storefront slugs
  (`odroid-m1-with-4gbyte-ram`, glued `odroid-c4with2gbyteram`) and
  `+ IO Header` bundle suffixes are configuration/bundle evidence, never
  board identity. Storefront and bundle pages canonicalise onto the base
  product URL; the bundle lands in the variant `bundle` dimension.
- **H-series comparison tables:** one table spans the whole H-series; the
  board's own processor is read from its own column (matched by header
  model), other columns are furniture (Banana Pi rule). Production dates
  in headers are recorded as raw spec-revision evidence.
- **User-fitted memory:** H-series boards have no soldered RAM; RAM options
  stay UNKNOWN instead of inventing a SO-DIMM matrix.
- **Ethernet transceivers** (Realtek RTL8211F) named inside spec rows are
  never promoted to SoC.
- **Lifecycle:** shop stock status is availability evidence; older boards
  (C4, HC4, N2+) ingested with `historical_known` → HISTORICAL_DISCOVERY,
  never market-new.

## Generic changes

**NONE.** All structural handling is adapter-local. (The generic-change
burden of Foundation 5A was met: no invariant failure required generic
modification.)

At the time of Foundation 5A, the live H-series pages parsed as insufficient
evidence (fail-closed diagnostic conditions, zero churn) although the
distilled fixtures resolved. This was adapter-local coverage debt, not an
architecture defect. Production Readiness 1B under COPS-000068 closes that
specific debt; the historical 5A soak evidence below is unchanged.

## Production Readiness 1B H-series addendum (2026-09-23)

Current first-party [H4](https://www.hardkernel.com/shop/odroid-h4/),
[H4+](https://www.hardkernel.com/shop/odroid-h4-plus/),
[H4 Ultra](https://www.hardkernel.com/shop/odroid-h4-ultra/), and
[H5](https://www.hardkernel.com/shop/odroid-h5/) product pages resolve through
their labelled comparison tables. The live model header cells contain nested
paragraphs, and H5 uses shared `colspan` cells. The parser now preserves those
cells, maps the `h1` model to its own column, and extracts the CPU and supported
capabilities only from that column. An unrelated ODROID benchmark table cannot
mask a labelled processor specification. Intel I226-V networking controllers
are not CPU evidence. User-fitted SO-DIMM/eMMC support does not manufacture
factory RAM or storage variants. Production dates remain raw evidence, not
launch-date claims; shop stock status remains availability evidence.

Historical fixture layouts remain intact; two new current-live distillations
cover nested headers, shared cells, companion chips, and column isolation.
The isolated live re-soak uses fresh state and never seeds persistent shadow
deployment. All six sources remain EXPERIMENTAL and disabled; this addendum
does not change Motherclank admission, scheduler, delivery, or promotion.

## Semantics preserved

All Foundation 0–4A laws hold. ODROID-GO ULTRA (handheld console, two
colour storefronts) and the HC4-P chassis/power kit are
`NON_BOARD_CATALOGUE_ITEM`. eMMC modules are separately purchased
accessories (socket storage dimension), not board identity. Five-vendor
isolation is proven.

## Live soak (3 passes, isolated state)

`C:\Users\anil\Clanks\_Soak\foundation-5a-odroid-live-soak\`: 25/25 fetches
OK per run; 5 boards / 11 variants (io-header bundles folded into variant
dimensions) / 4 SoC keys (Intel N300, Rockchip RK3568/RK3566/RK3588S2)
stable; 3 H-series live pages fail closed as idempotent insufficient
conditions (sightings only after run 1); run 1 fully baseline-silent;
runs 2–3: 0 new diagnostic events, 0 outbox additions, 0 NEW_BOARD,
0 NEW_VARIANT, FIELD_CHANGED 0, `stable: true`.

## How to run

```bash
PYTHONPATH=src python -m board_clank.cli collect --source hardkernel-odroid-product --db /tmp/bc-od.sqlite
PYTHONPATH=src python -m board_clank.cli collect --source hardkernel-odroid-product \
  --experimental-live --run-id od-live-1 --db /tmp/bc-od-live.sqlite
```

Tests remain offline and hermetic. `--experimental-live` never runs in tests.
