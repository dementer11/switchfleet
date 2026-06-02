from app.services.apply_safety_kernel import ApplySafetyKernel
from app.services.real_lab_apply_runner import LabCommandTransport, RealLabApplyRunner
from app.services.transport_runtime import RuntimeCredentials
from app.transports.base import CommandExecutionResult
from app.db.session import SessionLocal
from tests.enterprise.lab_apply_helpers import allowed_lab_payload, create_lab_device, execute_permissions, lab_settings


class FakeCommandTransport:
    def __init__(self) -> None:
        self.opened = False
        self.commands: list[str] = []

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.opened = False

    def run_command(self, command: str, timeout_seconds: int = 60) -> CommandExecutionResult:
        self.commands.append(command)
        return CommandExecutionResult(command=command, output=f"{command}\nok\n#", success=True)


def test_allowed_cisco_lab_apply_uses_fake_netmiko_transport_and_redacts_secret() -> None:
    session = SessionLocal()
    device = create_lab_device(session)
    payload = allowed_lab_payload(session, device)
    evaluation = ApplySafetyKernel(session, settings=lab_settings(device)).evaluate(payload, actor_permissions=execute_permissions())
    fake = FakeCommandTransport()

    def factory(*_args: object, **_kwargs: object) -> LabCommandTransport:
        return fake

    result = RealLabApplyRunner(transport_factory=factory).execute(
        evaluation,
        RuntimeCredentials(username="admin", password="VerySecret"),
    )

    assert result.executed is True
    assert fake.commands
    assert "VerySecret" in "\n".join(fake.commands)
    assert "VerySecret" not in str(result)


def test_runner_stops_on_vendor_error_pattern() -> None:
    session = SessionLocal()
    device = create_lab_device(session)
    payload = allowed_lab_payload(session, device)
    evaluation = ApplySafetyKernel(session, settings=lab_settings(device)).evaluate(payload, actor_permissions=execute_permissions())

    class ErrorTransport(FakeCommandTransport):
        def run_command(self, command: str, timeout_seconds: int = 60) -> CommandExecutionResult:
            self.commands.append(command)
            return CommandExecutionResult(command=command, output="% Invalid input\n#", success=True)

    def factory(*_args: object, **_kwargs: object) -> LabCommandTransport:
        return ErrorTransport()

    result = RealLabApplyRunner(transport_factory=factory).execute(
        evaluation,
        RuntimeCredentials(username="admin", password="VerySecret"),
    )

    assert result.executed is False
    assert result.failed is True
    assert result.error == "Vendor error pattern detected"
