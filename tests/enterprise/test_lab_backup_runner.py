from app.core.config import Settings
from app.core.exceptions import SafetyError
from app.db.models.config_backup import ConfigSnapshot
from app.db.session import SessionLocal
from app.services.lab_backup_runner import LabBackupRunner
from app.services.real_lab_apply_runner import LabCommandTransport, LabSshTransportFactory
from app.transports.base import CommandExecutionResult
from tests.enterprise.lab_apply_helpers import SECRET_KEY, create_lab_device, create_secret


class FakeReadOnlyTransport:
    def __init__(self) -> None:
        self.commands: list[str] = []

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    def run_command(self, command: str, timeout_seconds: int = 60) -> CommandExecutionResult:
        self.commands.append(command)
        return CommandExecutionResult(
            command=command,
            output="hostname lab-switch\nusername admin secret SHOULD_NOT_LEAK\n#",
            success=True,
        )


class FakeReadOnlyFactory(LabSshTransportFactory):
    def __init__(self, transport: FakeReadOnlyTransport):
        self.transport = transport

    def create(
        self,
        *_args: object,
        **_kwargs: object,
    ) -> LabCommandTransport:
        return self.transport


def test_lab_backup_runner_creates_sanitized_snapshot_with_fake_transport() -> None:
    session = SessionLocal()
    device = create_lab_device(session)
    credential_ref = create_secret(session)
    fake = FakeReadOnlyTransport()

    result = LabBackupRunner(
        session,
        settings=Settings(
            environment="test",
            secret_key=SECRET_KEY,
            lab_device_allowlist=str(device.id),
        ),
        transport_factory=FakeReadOnlyFactory(fake),
    ).backup_device(device, credential_ref=credential_ref, actor="netadmin")

    snapshot = session.get(ConfigSnapshot, result.snapshot_id)
    assert snapshot is not None
    assert snapshot.sanitized is True
    assert "SHOULD_NOT_LEAK" not in snapshot.config_text
    assert fake.commands == ["show running-config"]


def test_lab_backup_runner_denies_unknown_and_icmp() -> None:
    session = SessionLocal()
    unknown = create_lab_device(session, vendor="Huawei", model="Unknown Product", driver_name="")
    credential_ref = create_secret(session)

    try:
        LabBackupRunner(
            session,
            settings=Settings(environment="test", secret_key=SECRET_KEY, lab_device_allowlist=str(unknown.id)),
            transport_factory=FakeReadOnlyFactory(FakeReadOnlyTransport()),
        ).backup_device(unknown, credential_ref=credential_ref, actor="netadmin")
    except SafetyError as exc:
        assert "Unknown" in str(exc) or "unsupported" in str(exc).casefold()
    else:
        raise AssertionError("Unknown device backup was not denied")


def test_lab_backup_runner_comware_sends_paging_disable_before_backup() -> None:
    session = SessionLocal()
    device = create_lab_device(session, vendor="3Com", model="S4210", driver_name="")
    credential_ref = create_secret(session)
    fake = FakeReadOnlyTransport()

    LabBackupRunner(
        session,
        settings=Settings(
            environment="test",
            secret_key=SECRET_KEY,
            lab_device_allowlist=str(device.id),
        ),
        transport_factory=FakeReadOnlyFactory(fake),
    ).backup_device(device, credential_ref=credential_ref, actor="netadmin")

    assert fake.commands == ["screen-length disable", "screen-length 0 temporary", "display current-configuration"]
