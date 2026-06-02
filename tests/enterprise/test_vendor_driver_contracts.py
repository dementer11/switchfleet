from app.core.transport_strategy import DeviceFamily
from app.core.vendor_driver_contracts import ApplySupportLevel, VendorOperation, get_vendor_driver_contract, list_vendor_driver_contracts


def test_vendor_contracts_cover_all_families_and_no_production_certification() -> None:
    contracts = {contract.family: contract for contract in list_vendor_driver_contracts()}

    assert set(contracts) == set(DeviceFamily)
    assert all(not contract.production_certified for contract in contracts.values())
    assert contracts[DeviceFamily.unknown].apply_support_level == ApplySupportLevel.unsupported
    assert VendorOperation.password_change not in contracts[DeviceFamily.icmp].supported_operations
    assert VendorOperation.password_change not in contracts[DeviceFamily.generic_ssh].supported_operations
    assert contracts[DeviceFamily.eltex].apply_support_level == ApplySupportLevel.read_only_only
    assert contracts[DeviceFamily.bulat].apply_support_level == ApplySupportLevel.read_only_only
    assert contracts[DeviceFamily.cisco_ios].apply_support_level == ApplySupportLevel.lab_apply_candidate
    assert contracts[DeviceFamily.huawei_vrp].apply_support_level == ApplySupportLevel.lab_apply_candidate


def test_contract_for_unknown_fails_closed() -> None:
    contract = get_vendor_driver_contract(DeviceFamily.unknown)

    assert not contract.supports_operation(VendorOperation.vlan_create)
    assert contract.preferred_transport.value == "unsupported"
