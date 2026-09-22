# Event model

Event existence does not depend on Discord. Delivery policy is a separate table.

## Types

- `NEW_BOARD`
- `NEW_VARIANT`
- `BOARD_REVISION`
- `RAM_VARIANT_ADDED`
- `STORAGE_VARIANT_ADDED`
- `SOC_CHANGED`
- `PORTS_CHANGED`
- `FIELD_CHANGED`
- `PRICE_CHANGED`
- `AVAILABILITY_CHANGED`
- `OS_SUPPORT_ADDED`
- `OS_SUPPORT_REMOVED`
- `IMAGE_RELEASED`
- `EOL`
- `PRODUCT_REMOVED`
- `IDENTITY_ANOMALY`
- `CLASSIFICATION_CHANGED`
- `SOURCE_DEGRADED`

Room is left for future types without schema surgery (`event_type` is text).

## Baseline

The first successful run per source is silent. Existing boards discovered during that baseline do not create notification-eligible `NEW_BOARD` events. Events may still be recorded with `baseline_silent=1` for audit.

## Chronology

Canonical payload dedup is separate from sightings.

- A → A: occurrence only, no event
- A → B: event
- B → historical A: event
- A → B → A → B: each real transition has its own durable `event_key` (includes `run_id`)

Current state lives in `current_entity_observations`. It is not inferred from `MAX(payload id)`.

Exact successful run replay is a no-op via `processed_run_receipts`.

## Foundation 0 delivery policy

Push-worthy defaults: `NEW_BOARD` `BOARD_REVISION` `SOC_CHANGED` `PORTS_CHANGED` `IDENTITY_ANOMALY` `EOL`

Review / low-noise: `NEW_VARIANT` `RAM_VARIANT_ADDED` `STORAGE_VARIANT_ADDED` `PRICE_CHANGED` `AVAILABILITY_CHANGED`

Suppressed: `OS_SUPPORT_ADDED` `OS_SUPPORT_REMOVED` `IMAGE_RELEASED` `CLASSIFICATION_CHANGED` `SOURCE_DEGRADED`

Baseline-silent events are always suppressed from the outbox disposition.
