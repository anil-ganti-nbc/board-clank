"""Notification policy is separate from event generation. Events never depend on Discord."""
from __future__ import annotations
from board_clank.taxonomy import DeliveryDisposition, EventType

PUSH_EVENTS = frozenset({EventType.NEW_BOARD, EventType.BOARD_REVISION, EventType.SOC_CHANGED, EventType.PORTS_CHANGED, EventType.IDENTITY_ANOMALY, EventType.EOL})
REVIEW_EVENTS = frozenset({EventType.NEW_VARIANT, EventType.RAM_VARIANT_ADDED, EventType.STORAGE_VARIANT_ADDED, EventType.PRICE_CHANGED, EventType.AVAILABILITY_CHANGED, EventType.PRODUCT_REMOVED, EventType.FIELD_CHANGED})
SUPPRESSED_EVENTS = frozenset({EventType.OS_SUPPORT_ADDED, EventType.OS_SUPPORT_REMOVED, EventType.IMAGE_RELEASED, EventType.CLASSIFICATION_CHANGED, EventType.SOURCE_DEGRADED})
DEFAULT_POLICY = {}
for _event in EventType:
    if _event in PUSH_EVENTS:
        DEFAULT_POLICY[_event] = DeliveryDisposition.PUSH
    elif _event in SUPPRESSED_EVENTS:
        DEFAULT_POLICY[_event] = DeliveryDisposition.SUPPRESSED
    else:
        DEFAULT_POLICY[_event] = DeliveryDisposition.REVIEW

def disposition_for(event_type, *, baseline_silent=False):
    if baseline_silent:
        return DeliveryDisposition.SUPPRESSED
    return DEFAULT_POLICY.get(EventType(str(event_type)), DeliveryDisposition.REVIEW)
