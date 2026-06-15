from app.drivers.bulat_bs import BulatBSDriver
from app.drivers.cisco_ios import CiscoIOSDriver
from app.drivers.generic_ssh import GenericSSHDriver
from app.drivers.hp_comware import HPComwareDriver
from app.drivers.hpe_procurve import HPEProCurveDriver
from app.drivers.huawei_vrp import HuaweiVRPDriver
from app.drivers.readonly_icmp import ReadOnlyICMPDriver
from app.drivers.registry import DriverResolver
from app.schemas.device import DeviceInput


def test_resolves_huawei_vrp_families() -> None:
    match = DriverResolver().resolve(DeviceInput(ip_address="192.0.2.1", vendor="Huawei", model="S5735-L48T4X-A1"))

    assert match.driver_class is HuaweiVRPDriver


def test_resolves_hp_comware_families() -> None:
    match = DriverResolver().resolve(DeviceInput(ip_address="192.0.2.2", vendor="HPE", model="HPE 5130-48G-4SFP+ EI"))

    assert match.driver_class is HPComwareDriver


def test_resolves_hpe_procurve_families() -> None:
    match = DriverResolver().resolve(DeviceInput(ip_address="192.0.2.3", vendor="HPE", model="HPE 2530-8G-PoE+"))

    assert match.driver_class is HPEProCurveDriver


def test_resolves_bulat_families() -> None:
    match = DriverResolver().resolve(DeviceInput(ip_address="192.0.2.4", vendor="Bulat", model="BS2500-48G4S-A"))

    assert match.driver_class is BulatBSDriver


def test_resolves_cisco_families() -> None:
    match = DriverResolver().resolve(DeviceInput(ip_address="192.0.2.5", vendor="Cisco", model="Cat2960-48"))

    assert match.driver_class is CiscoIOSDriver


def test_unknown_requires_generic_discovery_driver() -> None:
    match = DriverResolver().resolve(DeviceInput(ip_address="192.0.2.6", vendor="Unknown", model="Unknown SNMP Product"))

    assert match.driver_class is GenericSSHDriver


def test_icmp_only_is_read_only() -> None:
    match = DriverResolver().resolve(DeviceInput(ip_address="192.0.2.7", vendor="", model="ICMP-only devices"))

    assert match.driver_class is ReadOnlyICMPDriver

