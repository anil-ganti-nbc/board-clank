# Foundation 4 — Banana Pi PRODUCT adapter (fourth-vendor admission)

Foundation 4A admits exactly one fourth vendor:

- source: `banana-pi`
- plane: `PRODUCT`
- key: `banana-pi-product`

The adapter is REGISTERED and EXPERIMENTAL. It is disabled by default.
No scheduler, no Discord, no delivery, no promotion, no fifth vendor.
This tranche ran under ClankOps Mission COPS-000062 (ADR-0015 control).

## Official surfaces (observed 2026-09-22)

- `https://banana-pi.org/en/banana-pi-sbcs/` and `/en/bananapi-router/` —
  category indexes. Role: DISCOVERY.
- `https://banana-pi.org/en/<category>/<number>.html` — product pages with
  OPAQUE numbered URLs. Roles: PRODUCT_IDENTITY (the page `<title>`),
  PRODUCT_SPEC + VARIANT_EVIDENCE (RAM/eMMC matrices, wireless).
- `wiki.banana-pi.org` / `docs.banana-pi.org` — documentation planes,
  DOCUMENTATION_ONLY, not ingested.
- HTTPS only (http redirects), Cloudflare-fronted with per-request volatile
  markup; the semantic hash strips exactly those artifacts.

## Fourth-vendor structural findings

- **Identity surface = `<title>`, with no h1 on product pages.** Titles
  follow "Banana Pi <BPI-model> with <SoC> ...". URLs carry no names.
- **Cross-product furniture:** every page embeds other products' names and
  SoCs in related/footer blocks, so SoC extraction is title-anchored (title
  + the page's own meta description) and never scans body furniture.
- **Multi-SoC option boards:** some pages document several SoC options for
  one board (BPI-M2 Zero: Allwinner H3 (option H2+/H5)) — identity
  conflict, fail closed, per the standing precedent.
- **Companion radios in titles:** "MediaTek MT7981B ... SoC and MediaTek
  MT7976C dual-band WiFi 6 chipset" — the radio is rejected by its
  wifi/chipset context; the named SoC is admitted. AP6275P, KEIIOT K038
  and Triductor radios never match the SoC shape.
- **WiFi frequency lists:** "2.4G/5G WiFi" must never leak into RAM or
  storage; size lists are classified by their own before/after anchor
  words, not a context window.
- **Families from model generations** (M5/M5 Pro, M7/M7S, M4 Berry/M4
  Zero, R4/R4 Pro share `bpi-<line>` families), mirroring the Radxa
  ROCK-series precedent.

## Generic abstraction defects found and fixed

None. The Banana Pi evidence was representable with the existing
vendor-neutral contracts (identity keys, BOARD-scope payload exclusions,
schema-v2 diagnostics, capability-based live gating); the title-anchored
parsing, opaque-URL discovery and anchor-classified size lists are all
adapter-local.

## Semantics preserved

All Foundation 0–3A laws hold. BPI-M2+ keeps a distinct slug from BPI-M2.
The BPI-MT7615 wifi module and BPI:Bit education microcontroller board are
`NON_BOARD_CATALOGUE_ITEM`. Shared SoCs across vendors (allwinner:h618 is
used by Orange Pi Zero 3/2 W and Banana Pi M4 Berry/M4 Zero) do not merge
boards. Cross-vendor isolation is proven for all four vendors.

## Live soak (3 passes, isolated state)

`C:\Users\anil\Clanks\_Soak\foundation-4a-bpi-live-soak\`: 37/37 fetches OK
per run (2 indexes + 35 product pages); 18 boards / 14 families / 81
variants / 15 SoC keys across 9 silicon vendors (Rockchip, Allwinner,
Amlogic, MediaTek, SpacemiT, Canaan, Siflower, Sunplus, Synaptics; ARM and
RISC-V) stable across all runs; 41 non-board links rejected; run 1 fully
baseline-silent; runs 2–3: 0 new diagnostic events, 0 outbox additions, 0
NEW_BOARD, 0 NEW_VARIANT, FIELD_CHANGED 0, `stable: true`.

## How to run

```bash
PYTHONPATH=src python -m board_clank.cli collect --source banana-pi-product --db /tmp/bc-bpi.sqlite
PYTHONPATH=src python -m board_clank.cli collect --source banana-pi-product \
  --experimental-live --run-id bpi-live-1 --db /tmp/bc-bpi-live.sqlite
```

Tests remain offline and hermetic. `--experimental-live` never runs in tests.
