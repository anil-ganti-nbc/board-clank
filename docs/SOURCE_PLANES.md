# Source planes and authority

A board may have evidence across separate planes. Plane appearance does not automatically establish novelty.

## Planes

| Plane | Example | Novelty implication |
| --- | --- |
| PRODUCT | official catalogue | not automatically a launch |
| COMMERCE | official store / SKU / stock | store appearance ≠ announcement |
| DOCUMENTATION | wiki / manual / datasheet | docs appearance ≠ launch |
| ANNOUNCEMENT | official blog / newsroom | announcement is evidence, not first_seen |
| SOFTWARE | images / firmware / releases | high-churn; delivery suppressed |
| REGULATORY | filings | supporting only |
| DISCOVERY_ONLY | third-party news / forum / social | investigation trigger only |

## Authority

- `FIRST_PARTY_CANONICAL`
- `FIRST_PARTY_SUPPORTING`
- `FIRST_PARTY_COMMERCE`
- `THIRD_PARTY_DISCOVERY`
- `UNVERIFIED`

Board truth prefers first-party canonical / supporting sources. Third-party sources may raise `IDENTITY_ANOMALY` but must not silently override canonical identity or specs.

## Promotion states

`REGISTERED` `EXPERIMENTAL` `SOAKING` `PROMOTED` `MOTHBALLED`

Foundation 0: Phase-1 sources are registered and experimental. Enabled live collection is false. No source is promoted because an adapter exists.

## Phase-2 placeholders

friendlyelec, milk-v, beagleboard, libre-computer, khadas, up-board, seeed-studio, firefly, lattepanda.

NVIDIA Jetson remains explicitly out of scope for Foundation 0.
