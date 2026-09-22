# Identity model

A new SKU is not necessarily a new board; a new board revision is not necessarily a new product name.

## Hierarchy

```
Vendor
 └── Family
      └── Board
           └── Board revision
                └── Commercial variant / SKU
```

A vendor marketing page may blur these layers. Board Clank must not.

## Keys

| Entity | Key |
| --- | --- |
| Vendor | slug(vendor) |
| Family | vendor_key:slug(family) |
| Board | vendor_key:slug(board) — never RAM/storage/wireless/region/bundle/SKU |
| Revision | board_key:kind:token |
| Variant | revision_key:sha256(normalized dimensions) |
| SoC | slug(soc vendor):slug(marketing name) |

## Revision kinds

- `MARKETING` — visible token such as `v2.1`
- `PCB` — documented PCB marking
- `SILENT` — identity-critical hardware change under the same marketing name
- `UNKNOWN` — no revision evidence. UNKNOWN stays UNKNOWN.

Silent revision tokens are derived from ports signature + SoC + dimensions. They are not product names.

## Conservative merge

Do not infer identity merges without strong evidence.

Same board slug + same explicit revision token = same revision.

Same board slug + matching SoC and ports under an existing revision = reuse that revision.

Same board slug + identity-critical change without a marketing token = new silent revision, not a new board.

Ambiguous third-party collisions raise `IDENTITY_ANOMALY` and do not auto-merge distinct SoCs into one revision.

## Variants

Example:

```
BOARD raspberry-pi-5
 └── VARIANT 4 GB / no eMMC
 └── VARIANT 8 GB / 32 GB eMMC
 └── VARIANT 16 GB / Wi-Fi / regional SKU
```

A compute module wireless × eMMC matrix is still one board.
