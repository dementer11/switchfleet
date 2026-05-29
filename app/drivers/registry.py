from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from app.drivers.base import BaseNetworkDriver
from app.drivers.bulat_bs import BulatBSDriver
from app.drivers.cisco_ios import CiscoIOSDriver
from app.drivers.dell_powerconnect import DellPowerConnectDriver
from app.drivers.eltex_mes import EltexMESDriver
from app.drivers.generic_ssh import GenericSSHDriver
from app.drivers.hp_comware import HPComwareDriver
from app.drivers.hpe_procurve import HPEProCurveDriver
from app.drivers.huawei_vrp import HuaweiVRPDriver
from app.drivers.readonly_icmp import ReadOnlyICMPDriver
from app.schemas.device import DeviceInput

DriverClass: TypeAlias = type[BaseNetworkDriver]


@dataclass(frozen=True)
class DriverMatch:
    driver_class: DriverClass
    reason: str


class DriverResolver:
    def resolve(self, device: DeviceInput) -> DriverMatch:
        vendor = device.vendor.casefold()
        model = device.model.casefold()
        text = f"{vendor} {model}"

        if "icmp" in text:
            return DriverMatch(ReadOnlyICMPDriver, "ICMP-only inventory marker")
        if "unknown snmp product" in text or "unknown product" in text:
            return DriverMatch(GenericSSHDriver, "Unknown platform requires discovery before write operations")
        if "huawei" in vendor or model.startswith(("s57", "s67", "ce68", "s17", "s23", "s24")):
            return DriverMatch(HuaweiVRPDriver, "Huawei VRP model family")
        if any(token in text for token in ("hpe 1910", "hpe 1920", "hpe 5130", "3com s4210", "3com s5500")):
            return DriverMatch(HPComwareDriver, "HP/3Com Comware model family")
        if any(token in text for token in ("hpe 2510", "hpe 2530")):
            return DriverMatch(HPEProCurveDriver, "HPE ProCurve/ArubaOS-Switch model family")
        if "eltex" in vendor or "mes2324" in model or "mes2348" in model or "mes2448" in model:
            return DriverMatch(EltexMESDriver, "Eltex MES model family")
        if "bulat" in vendor or "bs2500" in model or "bs6300" in model:
            return DriverMatch(BulatBSDriver, "Bulat BS model family")
        if "cisco" in vendor or "catalyst" in model or "cat2960" in model:
            return DriverMatch(CiscoIOSDriver, "Cisco IOS model family")
        if "dell" in vendor or "powerconnect" in model:
            return DriverMatch(DellPowerConnectDriver, "Dell PowerConnect model family")
        return DriverMatch(GenericSSHDriver, "No exact driver match; discovery required")


def resolve_driver_class(device: DeviceInput) -> DriverClass:
    return DriverResolver().resolve(device).driver_class

