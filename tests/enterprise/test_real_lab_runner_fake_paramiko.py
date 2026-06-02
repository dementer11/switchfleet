from app.core.transport_strategy import DeviceFamily, DriverCapability, TransportDecision, TransportKind
from app.core.vendor_driver_contracts import VendorOperation
from app.db.models.device import Device
from app.schemas.lab_apply import ApplySafetyDecisionRead
from app.services.apply_safety_kernel import ApplySafetyEvaluation
from app.services.real_lab_apply_runner import LabCommandTransport, RealLabApplyRunner
from app.services.transport_runtime import RuntimeCredentials
from app.services.vendor_command_templates import VendorCommandTemplateService, command_hash
from app.transports.base import CommandExecutionResult


class FakeParamikoTransport:
    def __init__(self) -> None:
        self.commands: list[str] = []

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    def run_command(self, command: str, timeout_seconds: int = 60) -> CommandExecutionResult:
        self.commands.append(command)
        return CommandExecutionResult(command=command, output=f"{command}\nok\n]", success=True)


def test_allowed_huawei_evaluation_can_use_fake_paramiko_transport() -> None:
    commands = VendorCommandTemplateService().render(
        DeviceFamily.huawei_vrp,
        VendorOperation.vlan_create,
        {"vlan_id": 123, "name": "TEST_VLAN"},
    )
    hash_value = command_hash(commands)
    decision = TransportDecision(
        vendor="Huawei",
        family=DeviceFamily.huawei_vrp,
        selected_transport=TransportKind.paramiko,
        driver_name="HuaweiVRPDriver",
        capabilities=frozenset({DriverCapability.read_only, DriverCapability.config_staging}),
        read_only_allowed=True,
        device_id="device-id",
        hostname="sw2-lab",
        model="S5720",
        platform="vrp",
    )
    evaluation = ApplySafetyEvaluation(
        decision=ApplySafetyDecisionRead(
            allowed=True,
            command_hash=hash_value,
            simulation_hash=hash_value,
            driver_family=DeviceFamily.huawei_vrp.value,
            selected_transport=TransportKind.paramiko.value,
        ),
        device=Device(
            hostname="sw2-lab",
            ip_address="192.168.88.12",
            management_ip="192.168.88.12",
            vendor="Huawei",
            model="S5720",
            platform="vrp",
            driver_name="HuaweiVRPDriver",
            tags={"lab": True},
        ),
        transport_decision=decision,
        internal_commands=commands,
    )
    fake = FakeParamikoTransport()

    def factory(*_args: object, **_kwargs: object) -> LabCommandTransport:
        return fake

    result = RealLabApplyRunner(transport_factory=factory).execute(
        evaluation,
        RuntimeCredentials(username="admin", password="Secret"),
    )

    assert result.executed is True
    assert fake.commands == [command.command for command in commands]
