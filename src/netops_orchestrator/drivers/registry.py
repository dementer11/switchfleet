from __future__ import annotations

from app.core.transport_strategy import DeviceFamily

from ..models import Device
from ..runtime_compat import runtime_decision_for_device
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
    decision = runtime_decision_for_device(device)
    if decision.family in {DeviceFamily.unknown, DeviceFamily.icmp, DeviceFamily.generic_ssh}:
        if "qtech" in vendor or "qsw" in model:
            return QtechQswDriver(device)
        if "d-link" in vendor or "des" in model:
            return DlinkDesDriver(device)
        return UnsupportedDriver(device)
    if "securitycode" in vendor or "continent" in model:
        return UnsupportedDriver(device)
    if "1820" in model or "1620" in model or "1905" in model:
        return UnsupportedDriver(device)
    if decision.family == DeviceFamily.huawei_vrp:
        return HuaweiVrpDriver(device)
    if decision.family in {DeviceFamily.cisco_ios, DeviceFamily.cisco_nxos, DeviceFamily.cisco_asa}:
        return CiscoIosDriver(device)
    if decision.family == DeviceFamily.hpe_comware:
        if "3com" in vendor or model.startswith("3com"):
            return ComwareLegacyDriver(device)
        if "5130" in model:
            return Comware7Driver(device)
        return ComwareSmbDriver(device)
    if decision.family in {DeviceFamily.hpe_procurve, DeviceFamily.aruba_os_switch}:
        return HpeProcurveDriver(device)
    if decision.family == DeviceFamily.bulat:
        return BulatBsDriver(device)
    if decision.family == DeviceFamily.eltex:
        return EltexMesDriver(device)
    if decision.family == DeviceFamily.dell_os:
        return DellPowerConnectDriver(device)
    if "qtech" in vendor or "qsw" in model:
        return QtechQswDriver(device)
    if "d-link" in vendor or "des" in model:
        return DlinkDesDriver(device)
    return UnsupportedDriver(device)
