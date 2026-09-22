"""Notification policy is separate from event generation. Events never depend on Discord."""

from __future__ import annotations

from board_clank.taxonomy import DeliveryDisposition, EventType

PUSH_EVENTS = frozenset(
    {
        EventType.NEW_BOARD,
        EventType.BOARD_REVISION,
        EventType.SOC_CHANGED,
        EventType.PORTS_CHANGED,
        EventType.IDENTITY_ANOMALY,
        EventType.EOL,
    }
)

REVIEW_EVENTS = frozenset(
    {
        EventType.NEW_VARIANT,
        EventType.RAM_VARIANT_ADDED,
        EventType.STORAGE_VARIANT_ADDED,
        EventType.PRICE_CHANGED,
        EventType.AVAILABILITY_CHANGED,
        EventType.PRODUCT_REMOVED,
        EventType.FIELD_CHANGED,
    }
)

SUPPRESSED_EVENTS = frozenset(
    {
        EventType.OS_SUPPORT_ADDED,
        EventType.OS_SUPPORT_REMOVED,
        EventType.IMAGE_RELEASED,
        EventType.CLASSIFICATION_CHANGED,
        EventType.SOURCE_DEGRADED,
        EventType.BASELINE_ENTITY,
        EventType.HISTORICAL_DISCOVERY,
        EventType.FIRST_SEEN_BY_CLANK,
        EventType.NEW_REFERENCE,
        EventType.REGION_ADDED,
        EventType.NOVELTY_UNRESOLVED,
        EventType.DIAGNOSTIC_RESOLVED,
    }
)

DEFAULT_POLICY: dict[EventType, DeliveryDisposition] = {}
for _event in EventType:
    if _event in PUSH_EVENTS:
        DEFAULT_POLICY[_event] = DeliveryDisposition.PUSH
    elif _event in SUPPRESSED_EVENTS:
        DEFAULT_POLICY[_event] = DeliveryDisposition.SUPPRESSED
    else:
        DEFAULT_POLICY[_event] = DeliveryDisposition.REVIEW


def disposition_for(event_type: EventType | str, *, baseline_silent: bool = False) -> DeliveryDisposition:
    if baseline_silent:
        return DeliveryDisposition.SUPPRESSED
    parsed = EventType(str(event_type))
    return DEFAULT_POLICY.get(parsed, DeliveryDisposition.REVIEW)


def load_policy_rows() -> list[tuple[str, str, str]]:
    rows = []
    for event_type, disposition in DEFAULT_POLICY.items():
        if event_type in PUSH_EVENTS:
            note = "foundation-0 high-interest default"
        elif event_type in SUPPRESSED_EVENTS:
            note = "foundation-0 suppressed default"
        else:
            note = "foundation-0 review / low-noise default"
        rows.append((event_type.value, disposition.value, note))
    return rows
