from __future__ import annotations

from ..models import Device
from .base import CliDriver
from .bulat import BulatBsDriver
from .cisco_ios import CiscoIosDriver
from .comware import Comware7Driver, ComwareLegacyDriver, ComwareSmbDriver
from .dell_powerconnect import DellPowerConnectDriver
from .dlink import DlinkDesDriver
from .eltex import EltexMesDriver
from .huawei_vrp import HuaweiVrpDriver
from .hpe_procurve import HpeProcurveDriver
from .qtech import QtechQswDriver
from .unsupported import UnsupportedDriver


def driver_for(device: Device) -> CliDriver:
    vendor = device.vendor.casefold()
    model = device.model.casefold()
    if not vendor or "unknown" in vendor or model in {"icmp", "unknown snmp product"}:
        return UnsupportedDriver(device)
    if "securitycode" in vendor or "continent" in model:
        return UnsupportedDriver(device)
    if "1820" in model or "1620" in model or "1905" in model:
        return UnsupportedDriver(device)
    if "huawei" in vendor or model.startswith(("s57", "s67")):
        return HuaweiVrpDriver(device)
    if "cisco" in vendor or "catalyst" in model or "cat2960" in model:
        return CiscoIosDriver(device)
    if "3com" in vendor or model.startswith("3com"):
        return ComwareLegacyDriver(device)
    if "5130" in model:
        return Comware7Driver(device)
    if "2510" in model or "2530" in model:
        return HpeProcurveDriver(device)
    if "hewlett" in vendor or model.startswith("hpe"):
        return ComwareSmbDriver(device)
    if "bulat" in vendor or "bs2500" in model or "bs6300" in model or "bk-" in model:
        return BulatBsDriver(device)
    if "eltex" in vendor or "mes" in model:
        return EltexMesDriver(device)
    if "qtech" in vendor or "qsw" in model:
        return QtechQswDriver(device)
    if "dell" in vendor or "powerconnect" in model:
        return DellPowerConnectDriver(device)
    if "d-link" in vendor or "des" in model:
        return DlinkDesDriver(device)
    return UnsupportedDriver(device)
