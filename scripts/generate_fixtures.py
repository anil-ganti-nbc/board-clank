#!/usr/bin/env python3
"""Generate Foundation 0 fixture scenarios A–O."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def dump(letter: str, payload: dict) -> None:
    path = ROOT / f"{letter}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def board(
    *,
    source_key: str,
    observed_at: str,
    vendor_key: str,
    family_slug: str,
    board_slug: str,
    marketing_name: str,
    **kwargs,
):
    payload = {
        "source_key": source_key,
        "plane": kwargs.pop("plane", "PRODUCT"),
        "observed_at": observed_at,
        "vendor_key": vendor_key,
        "vendor_name": kwargs.pop("vendor_name", vendor_key),
        "family_slug": family_slug,
        "family_name": kwargs.pop("family_name", family_slug),
        "board_slug": board_slug,
        "marketing_name": marketing_name,
        "board_type": kwargs.pop("board_type", "SBC"),
        "revision_kind": kwargs.pop("revision_kind", "UNKNOWN"),
        "revision_token": kwargs.pop("revision_token", "UNKNOWN"),
        "variant": kwargs.pop("variant", {"ram": "8GB", "storage": "UNKNOWN", "wireless": "wifi", "region": "UNKNOWN", "bundle": "UNKNOWN", "sku": "UNKNOWN"}),
        "soc_vendor": kwargs.pop("soc_vendor", "broadcom"),
        "soc_marketing_name": kwargs.pop("soc_marketing_name", "bcm2712"),
        "architecture": kwargs.pop("architecture", "ARM"),
        "cpu_configuration": kwargs.pop("cpu_configuration", "4xA76"),
        "gpu": kwargs.pop("gpu", "VideoCore VII"),
        "npu": kwargs.pop("npu", "UNKNOWN"),
        "npu_tops": kwargs.pop("npu_tops", "UNKNOWN"),
        "process_node": kwargs.pop("process_node", "16nm"),
        "spec": kwargs.pop(
            "spec",
            {
                "ethernet": "1x gigabit",
                "wifi": "wifi 6",
                "bluetooth": "5.0",
                "hdmi_out": "2x micro-hdmi",
                "usb": "2x usb3 + 2x usb2",
                "gpio_header": "40-pin",
                "microsd": "yes",
                "dimensions": "85x56mm",
            },
        ),
        "availability": kwargs.pop("availability", "IN_STOCK"),
        "supported_os": kwargs.pop("supported_os", ["raspberry-pi-os"]),
        "editorial_context": kwargs.pop("editorial_context", ["RPI_5_CLASS"]),
        "page_url": kwargs.pop("page_url", "https://example.invalid/pi5"),
        "native_fields": kwargs.pop("native_fields", {"vendor_sku_matrix": "kept"}),
        "raw_fields": kwargs.pop("raw_fields", {"title": marketing_name}),
    }
    payload.update(kwargs)
    return payload


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    pi = dict(vendor_key="raspberry-pi", family_slug="raspberry-pi-5", board_slug="raspberry-pi-5", marketing_name="Raspberry Pi 5")

    dump(
        "A",
        {
            "scenario": "A",
            "title": "same board observed twice unchanged",
            "source_key": "raspberry-pi-product",
            "runs": [
                {
                    "run_id": "A-baseline",
                    "source_key": "raspberry-pi-product",
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "observations": [board(source_key="raspberry-pi-product", observed_at="2026-01-01T00:00:00+00:00", **pi)],
                },
                {
                    "run_id": "A-repeat",
                    "source_key": "raspberry-pi-product",
                    "started_at": "2026-01-02T00:00:00+00:00",
                    "observations": [board(source_key="raspberry-pi-product", observed_at="2026-01-02T00:00:00+00:00", **pi)],
                },
            ],
        },
    )

    dump(
        "B",
        {
            "scenario": "B",
            "title": "board gets new RAM variant",
            "source_key": "raspberry-pi-product",
            "runs": [
                {
                    "run_id": "B-baseline",
                    "source_key": "raspberry-pi-product",
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "observations": [board(source_key="raspberry-pi-product", observed_at="2026-01-01T00:00:00+00:00", **pi, variant={"ram": "4GB", "storage": "UNKNOWN", "wireless": "wifi", "region": "UNKNOWN", "bundle": "UNKNOWN", "sku": "RPI5-4"})],
                },
                {
                    "run_id": "B-new-ram",
                    "source_key": "raspberry-pi-product",
                    "started_at": "2026-02-01T00:00:00+00:00",
                    "observations": [
                        board(source_key="raspberry-pi-product", observed_at="2026-02-01T00:00:00+00:00", **pi, variant={"ram": "4GB", "storage": "UNKNOWN", "wireless": "wifi", "region": "UNKNOWN", "bundle": "UNKNOWN", "sku": "RPI5-4"}),
                        board(source_key="raspberry-pi-product", observed_at="2026-02-01T00:00:00+00:00", **pi, variant={"ram": "8GB", "storage": "UNKNOWN", "wireless": "wifi", "region": "UNKNOWN", "bundle": "UNKNOWN", "sku": "RPI5-8"}),
                    ],
                },
            ],
        },
    )

    dump(
        "C",
        {
            "scenario": "C",
            "title": "explicit v2.1 revision",
            "source_key": "radxa-product",
            "runs": [
                {
                    "run_id": "C-baseline",
                    "source_key": "radxa-product",
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "observations": [
                        board(
                            source_key="radxa-product",
                            observed_at="2026-01-01T00:00:00+00:00",
                            vendor_key="radxa",
                            family_slug="rock-5",
                            board_slug="rock-5b",
                            marketing_name="Radxa ROCK 5B",
                            soc_vendor="rockchip",
                            soc_marketing_name="rk3588",
                            revision_kind="MARKETING",
                            revision_token="v1.0",
                            editorial_context=["HIGH_END_ARM"],
                        )
                    ],
                },
                {
                    "run_id": "C-v21",
                    "source_key": "radxa-product",
                    "started_at": "2026-03-01T00:00:00+00:00",
                    "observations": [
                        board(
                            source_key="radxa-product",
                            observed_at="2026-03-01T00:00:00+00:00",
                            vendor_key="radxa",
                            family_slug="rock-5",
                            board_slug="rock-5b",
                            marketing_name="Radxa ROCK 5B v2.1",
                            soc_vendor="rockchip",
                            soc_marketing_name="rk3588",
                            revision_kind="MARKETING",
                            revision_token="v2.1",
                            editorial_context=["HIGH_END_ARM"],
                        )
                    ],
                },
            ],
        },
    )

    silent_v2_spec = {
        "ethernet": "2x 2.5g",
        "wifi": "wifi 6",
        "bluetooth": "5.0",
        "hdmi_out": "1x hdmi",
        "usb": "1x usb3 + 2x usb2",
        "gpio_header": "40-pin",
        "microsd": "yes",
        "dimensions": "85x56mm",
    }
    dump(
        "D",
        {
            "scenario": "D",
            "title": "silent revision changes ports under same marketing name",
            "source_key": "orange-pi-product",
            "runs": [
                {
                    "run_id": "D-baseline",
                    "source_key": "orange-pi-product",
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "observations": [
                        board(
                            source_key="orange-pi-product",
                            observed_at="2026-01-01T00:00:00+00:00",
                            vendor_key="orange-pi",
                            family_slug="orange-pi-5",
                            board_slug="orange-pi-5",
                            marketing_name="Orange Pi 5",
                            soc_vendor="rockchip",
                            soc_marketing_name="rk3588s",
                        )
                    ],
                },
                {
                    "run_id": "D-silent",
                    "source_key": "orange-pi-product",
                    "started_at": "2026-04-01T00:00:00+00:00",
                    "observations": [
                        board(
                            source_key="orange-pi-product",
                            observed_at="2026-04-01T00:00:00+00:00",
                            vendor_key="orange-pi",
                            family_slug="orange-pi-5",
                            board_slug="orange-pi-5",
                            marketing_name="Orange Pi 5",
                            soc_vendor="rockchip",
                            soc_marketing_name="rk3588s",
                            spec=silent_v2_spec,
                        )
                    ],
                },
            ],
        },
    )

    dump(
        "E",
        {
            "scenario": "E",
            "title": "store page appears but historical evidence proves old product",
            "source_key": "pine64-commerce",
            "runs": [
                {
                    "run_id": "E-store",
                    "source_key": "pine64-commerce",
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "observations": [
                        board(
                            source_key="pine64-commerce",
                            plane="COMMERCE",
                            observed_at="2026-01-01T00:00:00+00:00",
                            vendor_key="pine64",
                            family_slug="rock64",
                            board_slug="rock64",
                            marketing_name="ROCK64",
                            soc_vendor="rockchip",
                            soc_marketing_name="rk3328",
                            historical_known=True,
                            novelty={
                                "first_seen_at": "2026-01-01T00:00:00+00:00",
                                "first_seen_source": "pine64-commerce",
                                "official_announcement_at": "2017-06-01",
                                "official_sale_at": "2017-07-01",
                                "novelty_status": "HISTORICAL",
                                "novelty_basis": "announcement_date_precedes_first_seen",
                                "novelty_confidence": "high",
                            },
                        )
                    ],
                }
            ],
        },
    )

    dump(
        "F",
        {
            "scenario": "F",
            "title": "docs page appears before product announcement",
            "source_key": "radxa-docs",
            "runs": [
                {
                    "run_id": "F-docs",
                    "source_key": "radxa-docs",
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "observations": [
                        board(
                            source_key="radxa-docs",
                            plane="DOCUMENTATION",
                            observed_at="2026-01-01T00:00:00+00:00",
                            vendor_key="radxa",
                            family_slug="rock-5",
                            board_slug="rock-5t",
                            marketing_name="Radxa ROCK 5T",
                            soc_vendor="rockchip",
                            soc_marketing_name="rk3588",
                            novelty={
                                "docs_date": "2026-01-01T00:00:00+00:00",
                                "novelty_status": "UNKNOWN",
                                "novelty_basis": "documentation_is_not_launch",
                                "novelty_confidence": "low",
                            },
                        )
                    ],
                }
            ],
        },
    )

    dump(
        "G",
        {
            "scenario": "G",
            "title": "product switches SoC",
            "source_key": "banana-pi-product",
            "runs": [
                {
                    "run_id": "G-baseline",
                    "source_key": "banana-pi-product",
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "observations": [
                        board(
                            source_key="banana-pi-product",
                            observed_at="2026-01-01T00:00:00+00:00",
                            vendor_key="banana-pi",
                            family_slug="bpi-m",
                            board_slug="bpi-m5",
                            marketing_name="Banana Pi BPI-M5",
                            soc_vendor="amlogic",
                            soc_marketing_name="s905x3",
                        )
                    ],
                },
                {
                    "run_id": "G-soc",
                    "source_key": "banana-pi-product",
                    "started_at": "2026-05-01T00:00:00+00:00",
                    "observations": [
                        board(
                            source_key="banana-pi-product",
                            observed_at="2026-05-01T00:00:00+00:00",
                            vendor_key="banana-pi",
                            family_slug="bpi-m",
                            board_slug="bpi-m5",
                            marketing_name="Banana Pi BPI-M5",
                            soc_vendor="amlogic",
                            soc_marketing_name="s905x4",
                        )
                    ],
                },
            ],
        },
    )

    dump(
        "H",
        {
            "scenario": "H",
            "title": "price changes only",
            "source_key": "hardkernel-odroid-product",
            "runs": [
                {
                    "run_id": "H-baseline",
                    "source_key": "hardkernel-odroid-product",
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "observations": [
                        board(
                            source_key="hardkernel-odroid-product",
                            observed_at="2026-01-01T00:00:00+00:00",
                            vendor_key="hardkernel-odroid",
                            family_slug="odroid-m",
                            board_slug="odroid-m1s",
                            marketing_name="ODROID-M1S",
                            soc_vendor="rockchip",
                            soc_marketing_name="rk3566",
                            price={"amount": "45.00", "currency": "USD", "region": "US", "variant_key": "UNKNOWN", "source_key": "hardkernel-odroid-product", "observed_at": "2026-01-01T00:00:00+00:00"},
                            spec={"ethernet": "1x gigabit", "wifi": "UNKNOWN", "hdmi_out": "1x hdmi", "usb": "2x usb2", "gpio_header": "40-pin", "price": "45.00", "currency": "USD"},
                        )
                    ],
                },
                {
                    "run_id": "H-price",
                    "source_key": "hardkernel-odroid-product",
                    "started_at": "2026-06-01T00:00:00+00:00",
                    "observations": [
                        board(
                            source_key="hardkernel-odroid-product",
                            observed_at="2026-06-01T00:00:00+00:00",
                            vendor_key="hardkernel-odroid",
                            family_slug="odroid-m",
                            board_slug="odroid-m1s",
                            marketing_name="ODROID-M1S",
                            soc_vendor="rockchip",
                            soc_marketing_name="rk3566",
                            price={"amount": "39.00", "currency": "USD", "region": "US", "variant_key": "UNKNOWN", "source_key": "hardkernel-odroid-product", "observed_at": "2026-06-01T00:00:00+00:00"},
                            spec={"ethernet": "1x gigabit", "wifi": "UNKNOWN", "hdmi_out": "1x hdmi", "usb": "2x usb2", "gpio_header": "40-pin", "price": "39.00", "currency": "USD"},
                        )
                    ],
                },
            ],
        },
    )

    dump(
        "I",
        {
            "scenario": "I",
            "title": "stock state changes only",
            "source_key": "pine64-product",
            "runs": [
                {
                    "run_id": "I-baseline",
                    "source_key": "pine64-product",
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "observations": [
                        board(
                            source_key="pine64-product",
                            observed_at="2026-01-01T00:00:00+00:00",
                            vendor_key="pine64",
                            family_slug="pine-a64",
                            board_slug="pine-a64-lts",
                            marketing_name="PINE A64-LTS",
                            soc_vendor="allwinner",
                            soc_marketing_name="a64",
                            availability="IN_STOCK",
                        )
                    ],
                },
                {
                    "run_id": "I-oos",
                    "source_key": "pine64-product",
                    "started_at": "2026-07-01T00:00:00+00:00",
                    "observations": [
                        board(
                            source_key="pine64-product",
                            observed_at="2026-07-01T00:00:00+00:00",
                            vendor_key="pine64",
                            family_slug="pine-a64",
                            board_slug="pine-a64-lts",
                            marketing_name="PINE A64-LTS",
                            soc_vendor="allwinner",
                            soc_marketing_name="a64",
                            availability="OUT_OF_STOCK",
                        )
                    ],
                },
            ],
        },
    )

    dump(
        "J",
        {
            "scenario": "J",
            "title": "OS support changes only",
            "source_key": "raspberry-pi-product",
            "runs": [
                {
                    "run_id": "J-baseline",
                    "source_key": "raspberry-pi-product",
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "observations": [board(source_key="raspberry-pi-product", observed_at="2026-01-01T00:00:00+00:00", **pi, supported_os=["raspberry-pi-os"])],
                },
                {
                    "run_id": "J-os",
                    "source_key": "raspberry-pi-product",
                    "started_at": "2026-08-01T00:00:00+00:00",
                    "observations": [board(source_key="raspberry-pi-product", observed_at="2026-08-01T00:00:00+00:00", **pi, supported_os=["raspberry-pi-os", "ubuntu"])],
                },
            ],
        },
    )

    spec_a = {"ethernet": "1x gigabit", "wifi": "wifi 5", "hdmi_out": "1x hdmi", "usb": "4x usb2", "gpio_header": "40-pin"}
    spec_b = {"ethernet": "1x gigabit", "wifi": "wifi 6", "hdmi_out": "1x hdmi", "usb": "4x usb2", "gpio_header": "40-pin"}
    dump(
        "K",
        {
            "scenario": "K",
            "title": "historical content recurrence A→B→A",
            "source_key": "orange-pi-product",
            "runs": [
                {
                    "run_id": "K-A1",
                    "source_key": "orange-pi-product",
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "observations": [
                        board(
                            source_key="orange-pi-product",
                            observed_at="2026-01-01T00:00:00+00:00",
                            vendor_key="orange-pi",
                            family_slug="zero",
                            board_slug="orange-pi-zero-3",
                            marketing_name="Orange Pi Zero 3",
                            soc_vendor="allwinner",
                            soc_marketing_name="h618",
                            spec=spec_a,
                        )
                    ],
                },
                {
                    "run_id": "K-B",
                    "source_key": "orange-pi-product",
                    "started_at": "2026-02-01T00:00:00+00:00",
                    "observations": [
                        board(
                            source_key="orange-pi-product",
                            observed_at="2026-02-01T00:00:00+00:00",
                            vendor_key="orange-pi",
                            family_slug="zero",
                            board_slug="orange-pi-zero-3",
                            marketing_name="Orange Pi Zero 3",
                            soc_vendor="allwinner",
                            soc_marketing_name="h618",
                            spec=spec_b,
                        )
                    ],
                },
                {
                    "run_id": "K-A2",
                    "source_key": "orange-pi-product",
                    "started_at": "2026-03-01T00:00:00+00:00",
                    "observations": [
                        board(
                            source_key="orange-pi-product",
                            observed_at="2026-03-01T00:00:00+00:00",
                            vendor_key="orange-pi",
                            family_slug="zero",
                            board_slug="orange-pi-zero-3",
                            marketing_name="Orange Pi Zero 3",
                            soc_vendor="allwinner",
                            soc_marketing_name="h618",
                            spec=spec_a,
                        )
                    ],
                },
            ],
        },
    )

    dump(
        "L",
        {
            "scenario": "L",
            "title": "exact run replay",
            "source_key": "raspberry-pi-product",
            "runs": [
                {
                    "run_id": "L-exact",
                    "source_key": "raspberry-pi-product",
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "observations": [board(source_key="raspberry-pi-product", observed_at="2026-01-01T00:00:00+00:00", **pi)],
                }
            ],
        },
    )

    dump(
        "M",
        {
            "scenario": "M",
            "title": "ambiguous identity evidence must not auto-merge",
            "source_key": "radxa-product",
            "runs": [
                {
                    "run_id": "M-left",
                    "source_key": "radxa-product",
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "observations": [
                        board(
                            source_key="radxa-product",
                            observed_at="2026-01-01T00:00:00+00:00",
                            vendor_key="radxa",
                            family_slug="zero",
                            board_slug="radxa-zero",
                            marketing_name="Radxa Zero",
                            soc_vendor="amlogic",
                            soc_marketing_name="s905y2",
                        )
                    ],
                },
                {
                    "run_id": "M-right",
                    "source_key": "third-party-discovery",
                    "started_at": "2026-01-02T00:00:00+00:00",
                    "observations": [
                        board(
                            source_key="third-party-discovery",
                            plane="DISCOVERY_ONLY",
                            observed_at="2026-01-02T00:00:00+00:00",
                            vendor_key="radxa",
                            family_slug="zero",
                            board_slug="radxa-zero",
                            marketing_name="Radxa Zero / Zero 2 ambiguous listing",
                            soc_vendor="amlogic",
                            soc_marketing_name="a311d",
                            identity_conflict=True,
                            identity_conflict_reason="third-party listing collides Zero and Zero 2 SoC names without revision evidence",
                        )
                    ],
                },
            ],
        },
    )

    variants = []
    for ram in ("4GB", "8GB", "16GB"):
        variants.append(
            board(
                source_key="raspberry-pi-product",
                observed_at="2026-01-01T00:00:00+00:00",
                **pi,
                variant={"ram": ram, "storage": "UNKNOWN", "wireless": "wifi", "region": "UNKNOWN", "bundle": "UNKNOWN", "sku": f"RPI5-{ram}"},
            )
        )
    dump(
        "N",
        {
            "scenario": "N",
            "title": "same board with 4GB/8GB/16GB variants",
            "source_key": "raspberry-pi-product",
            "runs": [
                {
                    "run_id": "N-matrix",
                    "source_key": "raspberry-pi-product",
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "observations": variants,
                }
            ],
        },
    )

    cm_obs = []
    for wireless in ("none", "wifi"):
        for emmc in ("none", "16GB", "32GB"):
            cm_obs.append(
                board(
                    source_key="raspberry-pi-product",
                    observed_at="2026-01-01T00:00:00+00:00",
                    vendor_key="raspberry-pi",
                    family_slug="compute-module-4",
                    board_slug="cm4",
                    marketing_name="Raspberry Pi Compute Module 4",
                    board_type="COMPUTE_MODULE",
                    soc_vendor="broadcom",
                    soc_marketing_name="bcm2711",
                    editorial_context=["CM4_COMPATIBLE"],
                    variant={"ram": "4GB", "storage": emmc, "wireless": wireless, "region": "UNKNOWN", "bundle": "UNKNOWN", "sku": f"CM4-4-{emmc}-{wireless}"},
                )
            )
    dump(
        "O",
        {
            "scenario": "O",
            "title": "compute module wireless/non-wireless + eMMC matrix",
            "source_key": "raspberry-pi-product",
            "runs": [
                {
                    "run_id": "O-matrix",
                    "source_key": "raspberry-pi-product",
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "observations": cm_obs,
                }
            ],
        },
    )


if __name__ == "__main__":
    main()
