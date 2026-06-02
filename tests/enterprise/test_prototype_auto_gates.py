from app.core.config import get_settings
from app.db.models.change_execution import ChangeExecutionLock
from app.db.models.lab_validation import LabDriverValidation
from app.db.session import SessionLocal
from scripts.lab_prototype import _build_apply_payload
from tests.enterprise.lab_apply_helpers import SECRET_KEY, create_lab_device, create_secret, create_snapshot


class Args:
    device: str
    operation = "password_change"
    credential: str
    username = "admin"
    new_password_env: str | None = None
    new_password_prompt = False
    vlan_id: int | None = None
    name: str | None = None
    interface: str | None = None
    level = 15
    backup_snapshot: str | None = None
    lab_validation: str | None = None
    approval: str | None = None
    simulation_hash: str | None = None
    lock = False
    prototype_auto_gates = True


def test_prototype_auto_gates_create_records_but_use_kernel_payload(monkeypatch) -> None:
    session = SessionLocal()
    device = create_lab_device(session)
    create_snapshot(session, device)
    credential_ref = create_secret(session)
    monkeypatch.setenv("NCP_SECRET_KEY", SECRET_KEY)
    monkeypatch.setenv("NCP_LAB_DEVICE_ALLOWLIST", str(device.id))
    get_settings.cache_clear()
    args = Args()
    args.device = str(device.id)
    args.credential = credential_ref
    monkeypatch.setenv("NEW_PASSWORD", "VerySecret")
    args.new_password_env = "NEW_PASSWORD"

    payload = _build_apply_payload(session, args)  # noqa: SLF001

    assert payload.backup_snapshot_id is not None
    assert payload.lab_validation_id is not None
    assert payload.lock_id is not None
    assert payload.approval_status == "approved"
    assert session.get(LabDriverValidation, payload.lab_validation_id) is not None
    assert session.get(ChangeExecutionLock, payload.lock_id) is not None


def test_prototype_auto_gates_require_existing_sanitized_backup(monkeypatch) -> None:
    session = SessionLocal()
    device = create_lab_device(session)
    credential_ref = create_secret(session)
    monkeypatch.setenv("NCP_SECRET_KEY", SECRET_KEY)
    monkeypatch.setenv("NCP_LAB_DEVICE_ALLOWLIST", str(device.id))
    get_settings.cache_clear()
    args = Args()
    args.device = str(device.id)
    args.credential = credential_ref
    monkeypatch.setenv("NEW_PASSWORD", "VerySecret")
    args.new_password_env = "NEW_PASSWORD"

    try:
        _build_apply_payload(session, args)  # noqa: SLF001
    except SystemExit as exc:
        assert "sanitized backup" in str(exc).casefold()
    else:
        raise AssertionError("Prototype auto-gates created gates without a sanitized backup")


def test_prototype_auto_gates_refuse_existing_reserved_lock(monkeypatch) -> None:
    session = SessionLocal()
    device = create_lab_device(session)
    create_snapshot(session, device)
    credential_ref = create_secret(session)
    monkeypatch.setenv("NCP_SECRET_KEY", SECRET_KEY)
    monkeypatch.setenv("NCP_LAB_DEVICE_ALLOWLIST", str(device.id))
    get_settings.cache_clear()
    args = Args()
    args.device = str(device.id)
    args.credential = credential_ref
    monkeypatch.setenv("NEW_PASSWORD", "VerySecret")
    args.new_password_env = "NEW_PASSWORD"
    first = _build_apply_payload(session, args)  # noqa: SLF001
    assert first.lock_id

    try:
        _build_apply_payload(session, args)  # noqa: SLF001
    except SystemExit as exc:
        assert "reserved lock" in str(exc).casefold()
    else:
        raise AssertionError("Prototype auto-gates reused an existing reserved lock")
