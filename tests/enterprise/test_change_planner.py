from app.schemas.device import DeviceInput
from app.schemas.job import VlanChangeJobRequest
from app.schemas.vlan import VlanIntentSchema
from app.services.change_planner import ChangePlanner


def test_vlan_change_planner_returns_masked_dry_run() -> None:
    request = VlanChangeJobRequest(
        requested_by="alice",
        devices=[DeviceInput(ip_address="192.0.2.1", vendor="Huawei", model="S5735")],
        intent=VlanIntentSchema(vlan_id=100, name="USERS", state="present"),
    )

    response = ChangePlanner().plan_vlan_change(request)

    assert response.job_type == "vlan_change"
    assert response.approval_required is True
    assert response.apply_allowed is False
    assert response.devices[0].driver == "HuaweiVRPDriver"
    assert response.devices[0].commands == [
        "system-view",
        "vlan 100",
        "description USERS",
        "quit",
        "display vlan 100",
        "save force",
    ]


def test_planner_marks_unconfirmed_bulat_template_as_not_apply_supported() -> None:
    request = VlanChangeJobRequest(
        requested_by="alice",
        devices=[DeviceInput(ip_address="192.0.2.2", vendor="Bulat", model="BS2500-48G4S-A")],
        intent=VlanIntentSchema(vlan_id=100, name="USERS", state="present"),
    )

    response = ChangePlanner().plan_vlan_change(request)

    assert response.devices[0].driver == "BulatBSDriver"
    assert response.devices[0].apply_supported is False
    assert response.devices[0].risks

