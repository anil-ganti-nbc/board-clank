"""Normalized taxonomies. UNKNOWN stays UNKNOWN. Multi-label editorial context is allowed."""

from __future__ import annotations

from enum import StrEnum


class BoardType(StrEnum):
    """Physical / product type. Separate from editorial use-case context."""

    SBC = "SBC"
    COMPUTE_MODULE = "COMPUTE_MODULE"
    DEVKIT = "DEVKIT"
    ROUTER_BOARD = "ROUTER_BOARD"
    INDUSTRIAL_SBC = "INDUSTRIAL_SBC"
    MINI_ITX_SBC = "MINI_ITX_SBC"
    ZERO_CLASS = "ZERO_CLASS"
    AI_SBC = "AI_SBC"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class Architecture(StrEnum):
    ARM = "ARM"
    X86 = "X86"
    RISCV = "RISCV"
    LOONGARCH = "LOONGARCH"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class SourcePlane(StrEnum):
    PRODUCT = "PRODUCT"
    COMMERCE = "COMMERCE"
    DOCUMENTATION = "DOCUMENTATION"
    ANNOUNCEMENT = "ANNOUNCEMENT"
    SOFTWARE = "SOFTWARE"
    REGULATORY = "REGULATORY"
    DISCOVERY_ONLY = "DISCOVERY_ONLY"


class SourceAuthority(StrEnum):
    FIRST_PARTY_CANONICAL = "FIRST_PARTY_CANONICAL"
    FIRST_PARTY_SUPPORTING = "FIRST_PARTY_SUPPORTING"
    FIRST_PARTY_COMMERCE = "FIRST_PARTY_COMMERCE"
    THIRD_PARTY_DISCOVERY = "THIRD_PARTY_DISCOVERY"
    UNVERIFIED = "UNVERIFIED"


class PromotionState(StrEnum):
    REGISTERED = "REGISTERED"
    EXPERIMENTAL = "EXPERIMENTAL"
    SOAKING = "SOAKING"
    PROMOTED = "PROMOTED"
    MOTHBALLED = "MOTHBALLED"


class EventType(StrEnum):
    NEW_BOARD = "NEW_BOARD"
    NEW_VARIANT = "NEW_VARIANT"
    BOARD_REVISION = "BOARD_REVISION"
    RAM_VARIANT_ADDED = "RAM_VARIANT_ADDED"
    STORAGE_VARIANT_ADDED = "STORAGE_VARIANT_ADDED"
    SOC_CHANGED = "SOC_CHANGED"
    PORTS_CHANGED = "PORTS_CHANGED"
    FIELD_CHANGED = "FIELD_CHANGED"
    PRICE_CHANGED = "PRICE_CHANGED"
    AVAILABILITY_CHANGED = "AVAILABILITY_CHANGED"
    OS_SUPPORT_ADDED = "OS_SUPPORT_ADDED"
    OS_SUPPORT_REMOVED = "OS_SUPPORT_REMOVED"
    IMAGE_RELEASED = "IMAGE_RELEASED"
    EOL = "EOL"
    PRODUCT_REMOVED = "PRODUCT_REMOVED"
    IDENTITY_ANOMALY = "IDENTITY_ANOMALY"
    CLASSIFICATION_CHANGED = "CLASSIFICATION_CHANGED"
    SOURCE_DEGRADED = "SOURCE_DEGRADED"
    # Foundation 1 additive diagnostic / chronology types. Text column stays compatible.
    BASELINE_ENTITY = "BASELINE_ENTITY"
    HISTORICAL_DISCOVERY = "HISTORICAL_DISCOVERY"
    FIRST_SEEN_BY_CLANK = "FIRST_SEEN_BY_CLANK"
    NEW_REFERENCE = "NEW_REFERENCE"
    REGION_ADDED = "REGION_ADDED"
    NOVELTY_UNRESOLVED = "NOVELTY_UNRESOLVED"
    # Foundation 2B diagnostic lifecycle type. Persistent uncertainty is
    # state, not perpetual novelty: an unresolved/anomalous condition that
    # stops appearing closes once (observable), instead of the condition
    # re-opening as fresh intelligence on every collection run.
    DIAGNOSTIC_RESOLVED = "DIAGNOSTIC_RESOLVED"


class NoveltyStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    HISTORICAL = "HISTORICAL"
    NEWLY_ANNOUNCED = "NEWLY_ANNOUNCED"
    NEWLY_AVAILABLE = "NEWLY_AVAILABLE"
    EXISTING_PRODUCT = "EXISTING_PRODUCT"
    REVISION = "REVISION"
    VARIANT = "VARIANT"


class Availability(StrEnum):
    ANNOUNCED = "ANNOUNCED"
    PREORDER = "PREORDER"
    IN_STOCK = "IN_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    DISCONTINUED = "DISCONTINUED"
    EOL = "EOL"
    UNKNOWN = "UNKNOWN"


class RevisionKind(StrEnum):
    MARKETING = "MARKETING"
    PCB = "PCB"
    SILENT = "SILENT"
    UNKNOWN = "UNKNOWN"


class EditorialContext(StrEnum):
    """Descriptive context only. Not a quality ranking. Multi-label is allowed."""

    RPI_ZERO_CLASS = "RPI_ZERO_CLASS"
    RPI_5_CLASS = "RPI_5_CLASS"
    CM4_COMPATIBLE = "CM4_COMPATIBLE"
    CM5_COMPATIBLE = "CM5_COMPATIBLE"
    HIGH_END_ARM = "HIGH_END_ARM"
    X86_SBC = "X86_SBC"
    NAS_ORIENTED = "NAS_ORIENTED"
    ROUTER_ORIENTED = "ROUTER_ORIENTED"
    AI_ORIENTED = "AI_ORIENTED"
    INDUSTRIAL = "INDUSTRIAL"


class DeliveryDisposition(StrEnum):
    PUSH = "PUSH"
    REVIEW = "REVIEW"
    SUPPRESSED = "SUPPRESSED"


class EntityKind(StrEnum):
    VENDOR = "VENDOR"
    FAMILY = "FAMILY"
    BOARD = "BOARD"
    REVISION = "REVISION"
    VARIANT = "VARIANT"
    SOC = "SOC"


class CompatibilityState(StrEnum):
    FRESH = "FRESH"
    COMPATIBLE = "COMPATIBLE"
    MIGRATION_REQUIRED = "MIGRATION_REQUIRED"
    INCOMPATIBLE_NEWER = "INCOMPATIBLE_NEWER"
    PARTIAL = "PARTIAL"
    CORRUPT = "CORRUPT"
    UNKNOWN = "UNKNOWN"


PHASE1_VENDORS = (
    "raspberry-pi",
    "orange-pi",
    "radxa",
    "banana-pi",
    "hardkernel-odroid",
    "pine64",
)

PHASE2_PLACEHOLDERS = (
    "friendlyelec",
    "milk-v",
    "beagleboard",
    "libre-computer",
    "khadas",
    "up-board",
    "seeed-studio",
    "firefly",
    "lattepanda",
)

OUT_OF_SCOPE_FOUNDATION_0 = ("nvidia-jetson",)

IDENTITY_CRITICAL_SPEC_FIELDS = (
    "soc_key",
    "cpu_arch",
    "ports_signature",
    "dimensions",
)

PORT_FIELDS = (
    "ethernet",
    "wifi",
    "bluetooth",
    "hdmi_out",
    "hdmi_in",
    "displayport",
    "mipi_csi",
    "mipi_dsi",
    "usb",
    "gpio_header",
    "m2_m_key",
    "m2_e_key",
    "pcie_lanes",
    "sata",
    "microsd",
    "onboard_emmc",
)
