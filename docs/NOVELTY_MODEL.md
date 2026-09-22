# Novelty model

FIRST_SEEN != MARKET_NOVELTY.

First-seen is observation time, not market novelty.

Do not collapse these into one "release date":

- first_seen_at
- official_announcement_at
- official_sale_at
- official_shipping_at
- docs_date
- store_date

## Fields

`novelty_status` `novelty_basis` `novelty_confidence` plus the dated fields above.

## Status values

- `UNKNOWN`
- `HISTORICAL` — newly discovered old board
- `NEWLY_ANNOUNCED`
- `NEWLY_AVAILABLE`
- `EXISTING_PRODUCT`
- `REVISION`
- `VARIANT`

A newly discovered old board is not `NEW_BOARD`.
A new RAM / storage SKU is not `NEW_BOARD`.
A silently revised PCB may be `BOARD_REVISION` even if the product name is unchanged.

Dates are never fabricated. Missing values stay `UNKNOWN`.
