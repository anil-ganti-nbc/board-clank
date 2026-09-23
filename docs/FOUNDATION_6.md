# Foundation 6 — Pine64 PRODUCT adapter (sixth and final vendor of the expansion programme)

Foundation 6A admits exactly one sixth vendor:

- source: `pine64`
- plane: `PRODUCT`
- key: `pine64-product`

REGISTERED and EXPERIMENTAL; disabled by default. No scheduler, no Discord,
no delivery, no promotion. **This is the final vendor-expansion tranche**;
the next programme is production-readiness / fleet onboarding. Mission:
ClankOps COPS-000064 (ADR-0015 control).

## Official surfaces (observed 2026-09-23)

- `https://pine64.org/devices/` — DISCOVERY **and the category authority**:
  device boxes pair a display name with a slug under section headings.
  Role: DISCOVERY + SCOPE.
- `https://pine64.org/devices/<slug>/` — thin static product pages.
  PRODUCT_IDENTITY lives in `<title>` (no device-name h2 on live pages);
  PRODUCT_SPEC/VARIANT_EVIDENCE are prose and labelled lists.
- `store.pine64.org` (TLS principal mismatch), `pine64.com` (commerce-only),
  `linux.pine64.org` (blog), `wiki.pine64.org` (documentation) — COMMERCE/
  DOCUMENTATION_ONLY, refused by the host allowlist; never ingested.

## Product scope (the sixth-vendor test)

Pine64's ecosystem spans SBCs, compute modules, laptops, phones, tablets,
e-ink devices, smartwatches, earbuds, soldering irons, power supplies, IoT
devices, cameras and maker tools. The index's own section headings gate
scope: only `Single Board Computers` and `Clusters and Compute Modules` are
board scope; every other category is recorded as rejected scope evidence.
**SoC presence never defeats the scope gate** — the PinePhone page names the
Allwinner A64 and is still rejected. Non-board regression: PinePhone,
Pinebook Pro, PineTime, Pinecil.

## Structural findings

- **Identity = `<title>` minus the site suffix** (real pages have no
  device-name h2); nav menus must not poison box/slug pairing on the index.
- **"PINE A64 and PINE A64+" is one catalogue entry** — the plus is the
  page's own documented option (optional WiFi module), so one board
  identity; the index names it "PINE A64 (+)".
- **Families from first-party series**: quartz (Model A/B/Zero), rock
  (ROCK64/ROCKPro64), star (STAR64/StarPro64), pine-a64 (A64, A64-LTS),
  so* compute modules (SOPINE/SOQuartz/SOEdge) as their own line.
- **A64-LTS is a distinct board** (Allwinner R18, industrial A64) in the
  pine-a64 family — LTS is a board, not a variant.
- **Companion rejection**: radios named with WiFi/Bluetooth context never
  become SoCs; heterogeneous multi-core SoCs (BL808: RV64 + dual RV32) are
  one SoC identity, not a conflict.
- **eMMC modules are separately purchased accessories** → storage dimension
  (`none`/`module`/capacity), never board identity.
- **"up to NGB RAM"** states a matrix (1..N); a single `2GB LPDDR3` is one
  configuration.
- **Thin pages** (SOQuartz identity-only sentence on live) fail closed as
  durable insufficient conditions while still admitting identity when the
  page names its SoC (SOQuartz names RK3566 → compute module).

## Generic changes (one, with the required justification)

`WHY THIS CANNOT REMAIN ADAPTER-LOCAL`: with all six Phase-1 vendors now
live-capable, `get_adapter` raises `KeyError` for any other source. The
CLI's `collect` path previously let that escape as an unhandled traceback
(exit 1, non-JSON) — a fail-closed violation in the generic CLI layer,
exposed by this mission because the refusal-path tests could no longer use
an inert Phase-1 vendor as their example. Fix: `cmd_collect` catches
`KeyError` and returns `{"status": "refused"}` with exit 2
(`src/board_clank/cli.py`). No vendor logic involved; regression-tested
with the unregistered `friendlyelec-product` placeholder.

## Verification law

Per mission order, pytest success is gated on **exit code + complete
summary line** (never grep): local `240 passed` / exit 0; hermetic
`240 passed` / exit 0. (Interim runs during development did surface
"2 failed, 238 passed" states that grep-based gating would have hidden.)

## Live soak (3 passes, isolated state)

`C:\Users\anil\Clanks\_Soak\foundation-6a-pine64-live-soak\`: 22/22 fetches
OK per run; 11 boards / 25 variants / 8 SoC keys (Allwinner A64, Bouffalo
BL808, Rockchip RK1808/RK3328/RK3399/RK3566/RK3566T, StarFive JH-7110;
ARM + RISC-V) stable; thin live pages fail closed as idempotent
insufficient conditions; run 1 fully baseline-silent; runs 2–3: 0 new
diagnostic events, 0 outbox additions, 0 NEW_BOARD, 0 NEW_VARIANT,
FIELD_CHANGED 0, `stable: true`.

## Carried debt (for the production-readiness tranche)

- **ODROID H-series live parser coverage**: live comparison-table markup
  still fails closed as durable insufficient conditions (adapter-local,
  non-blocking while EXPERIMENTAL).
- Backup/restore hook + restore test (architecture production gate).
- Event code-revision provenance (Fleet Law 6 limitation).
- Motherclank observer manifest/adapter onboarding (via Diagnostic Clank).

## How to run

```bash
PYTHONPATH=src python -m board_clank.cli collect --source pine64-product --db /tmp/bc-p64.sqlite
PYTHONPATH=src python -m board_clank.cli collect --source pine64-product \
  --experimental-live --run-id p64-live-1 --db /tmp/bc-p64-live.sqlite
```

Tests remain offline and hermetic. `--experimental-live` never runs in tests.
