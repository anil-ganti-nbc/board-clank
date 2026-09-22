from __future__ import annotations

from board_clank.policy import DEFAULT_POLICY, disposition_for
from board_clank.sources import assert_foundation_0_roster, load_sources, phase1_sources, promoted_sources
from board_clank.taxonomy import (
    PHASE1_VENDORS,
    PHASE2_PLACEHOLDERS,
    DeliveryDisposition,
    EventType,
    SourcePlane,
)


def test_phase1_roster_experimental_only() -> None:
    assert_foundation_0_roster()
    phase1 = phase1_sources()
    assert {row.vendor for row in phase1} == set(PHASE1_VENDORS)
    assert all(row.promotion_state == "EXPERIMENTAL" for row in phase1)
    assert all(row.enabled is False for row in phase1)
    assert promoted_sources() == []


def test_phase2_placeholders_exist() -> None:
    vendors = {row.vendor for row in load_sources() if row.placeholder}
    assert set(PHASE2_PLACEHOLDERS).issubset(vendors)
    jetson = [row for row in load_sources() if row.out_of_scope]
    assert any(row.vendor == "nvidia-jetson" for row in jetson)


def test_planes_and_authority_modelled() -> None:
    records = phase1_sources()
    assert all(row.plane is SourcePlane.PRODUCT for row in records)


def test_notification_policy_defaults() -> None:
    assert disposition_for(EventType.NEW_BOARD) is DeliveryDisposition.PUSH
    assert disposition_for(EventType.BOARD_REVISION) is DeliveryDisposition.PUSH
    assert disposition_for(EventType.SOC_CHANGED) is DeliveryDisposition.PUSH
    assert disposition_for(EventType.PORTS_CHANGED) is DeliveryDisposition.PUSH
    assert disposition_for(EventType.IDENTITY_ANOMALY) is DeliveryDisposition.PUSH
    assert disposition_for(EventType.EOL) is DeliveryDisposition.PUSH
    assert disposition_for(EventType.NEW_VARIANT) is DeliveryDisposition.REVIEW
    assert disposition_for(EventType.PRICE_CHANGED) is DeliveryDisposition.REVIEW
    assert disposition_for(EventType.OS_SUPPORT_ADDED) is DeliveryDisposition.SUPPRESSED
    assert disposition_for(EventType.IMAGE_RELEASED) is DeliveryDisposition.SUPPRESSED
    assert disposition_for(EventType.NEW_BOARD, baseline_silent=True) is DeliveryDisposition.SUPPRESSED
    assert EventType.SOURCE_DEGRADED in DEFAULT_POLICY
