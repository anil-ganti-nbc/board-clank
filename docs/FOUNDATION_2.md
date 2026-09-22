# Foundation 2 — Orange Pi PRODUCT adapter (second-vendor admission)

Foundation 2A admits exactly one second vendor:

- source: `orange-pi`
- plane: `PRODUCT`
- key: `orange-pi-product`

The adapter is REGISTERED and EXPERIMENTAL. It is disabled by default.
There is no scheduler, no Discord, no webhook delivery, no promotion, and
no delivery activation. Raspberry Pi remains the REFERENCE adapter and was
not redesigned; only genuinely vendor-neutral defects found by this
admission were fixed in shared layers.

## Official surfaces (observed 2026-09-22)

- `http://www.orangepi.org/html/hardWare/computerAndMicrocontrollers/index.html`
  — product index. Role: DISCOVERY (leads only).
- `http://www.orangepi.org/html/hardWare/computerAndMicrocontrollers/details/<Product>.html`
  — product detail pages. Roles: PRODUCT_IDENTITY, PRODUCT_SPEC,
  VARIANT_EVIDENCE (RAM/eMMC matrices), REVISION_EVIDENCE ("Vx.y Pin
  Definition" headings).
- `http://www.orangepi.cn/` — regional mirror with duplicated identities.
  Documented, NOT ingested (host allowlist refuses it).
- `http://wiki.orangepi.org/` — first-party documentation plane, out of
  scope for 2A.
- AliExpress / Amazon storefronts — first-party commerce, out of scope.

The official site is HTTP-only (TLS is not served), served by plain Apache
with no anti-bot or CDN challenge, no robots.txt and no sitemap. The
adapter's host allowlist admits `http` for `www.orangepi.org` only; this is
the source-local mirror of the Raspberry Pi adapter's HTTPS-only rule for
its TLS-served vendor.

## Parser model

Orange Pi detail pages expose explicit parameter tables — a labelled
SoC / Master Chip row, companion silicon in labelled PMU / Wi-Fi / Ethernet
/ audio rows, RAM matrices, and pin-definition headings. The adapter is
table-driven and never promotes companion silicon (RK806-1 / RK809-5 PMICs,
AP6256 / AP6611 / 20U5622 radios, YT8531C / RTL8125BG Ethernet PHYs, ES8388
codec, AXP313A PMIC) to the SoC slot, whatever row they appear in.

Storefront pages split per configuration (`Orange-Pi-5-32GB.html`) or per
bundle (`...-With-Metal-Case.html`). They are variant evidence for the
board named by their base page: board references canonicalize onto the base
page and the storefront draft adopts the canonical page's board-scope spec.
The storefront's own contribution stays in VARIANT dimensions and raw
reference evidence.

Orange Pi 800 (integrated keyboard computer), CM4/CM5 base/carrier boards,
eMMC modules and Wi-Fi modules are `NON_BOARD_CATALOGUE_ITEM`.

## Semantics preserved

- First seen by Board Clank is not market-new.
- First successful corpus ingest is a silent source-scoped baseline.
- RAM / eMMC / wireless / bundle options are variants, never boards.
- Revision tokens are recorded only when first-party text names them.
- Insufficient or conflicting evidence fails closed
  (`NOVELTY_UNRESOLVED` / `IDENTITY_ANOMALY`).
- The remaining Phase-1 vendors (Radxa, Banana Pi, ODROID, Pine64) stay
  inert.

## Raspberry Pi vs Orange Pi — architectural comparison

| Concern | Raspberry Pi | Orange Pi | Generic abstraction holds? |
| --- | --- | --- | --- |
| discovery | PIP category indexes | product index page | yes — lead surfaces, DISCOVERY role |
| identity surface | PIP/marketing product headings | product `<h3>` headings | yes |
| specs | prose sections (regex heuristics) | labelled parameter tables | yes — adapter owns parsing |
| variants | RAM/storage/wireless matrices | RAM/eMMC/bundle incl. 1.5GB RAM, config storefronts | yes |
| SoCs | BCM/RP tokens from prose | row-labelled SoC/Master Chip/CPU fallback | yes — soc_key is vendor-neutral |
| family taxonomy | per numeric generation, Zero, CM | per numeric generation, Zero, CM, router, RV, AI | yes |
| references/SKUs | SCxxxx SKUs as references | page URLs; storefront URLs canonicalize | yes |
| change evidence | PIP PCNs | none formal on catalogue (news pages out of scope) | yes — role unused, not violated |
| semantic hashing | CSRF/session stripping | static host; token stripping + whitespace collapse | yes |
| failure behaviour | insufficient/conflict fail closed | insufficient/conflict fail closed | yes |

## Generic abstraction defects found and fixed

1. **BOARD-scope payload included variant enumeration matrices.**
   `ram_options` / `emmc_options` (and the `pcb_revision` echo) were part of
   BOARD-level canonical payloads. Any vendor that presents per-configuration
   pages (Orange Pi storefronts) would churn `FIELD_CHANGED` on every run.
   Fixed in `models.py`: BOARD-scope comparison excludes
   `BOARD_SCOPE_EXCLUDED_SPEC_FIELDS`. Foundation 1 never triggered this
   because Raspberry Pi pages always carried identical matrices.
2. **Revision echo churned on identity reuse.** When the pipeline reuses an
   existing revision identity for a draft whose revision evidence is
   UNKNOWN, the draft's echo fields now follow the resolved identity
   (`pipeline.py`). A page that stops naming a revision no longer makes the
   stored revision look changed.

Adapter-local assumptions (deliberate, owned by the Orange Pi adapter):
HTTP-only host allowlist; storefront-suffix canonicalization
(`-32GB`, `-With-Metal-Case`); router/RV/AI family rules; CN mirror not
ingested. Future enhancement (not built): a first-class reference-set model
so a board can hold multiple canonical references without adapter-side
canonicalization.

## How to run

```bash
PYTHONPATH=src python -m board_clank collect --source orange-pi-product --db /tmp/bc-opi.sqlite
PYTHONPATH=src python -m board_clank collect --source orange-pi-product \
  --experimental-live --run-id opi-live-1 --db /tmp/bc-opi-live.sqlite
```

Tests remain offline and hermetic. `--experimental-live` never runs in tests.
