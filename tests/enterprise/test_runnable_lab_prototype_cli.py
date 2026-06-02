import json

from app.core.config import get_settings
from app.db.models.credential import CredentialSecret
from app.db.models.device import Device
from app.db.session import SessionLocal
from scripts.lab_prototype import main


def _last_json(captured: str) -> dict:
    return json.loads(captured)


def test_lab_prototype_import_devices_and_dry_run(tmp_path, capsys) -> None:
    path = tmp_path / "devices.yaml"
    path.write_text(
        """
devices:
  - hostname: sw1-lab
    management_ip: 192.168.88.11
    vendor: Cisco
    model: Catalyst 2960
    platform: ios
    driver_name: CiscoIOSDriver
    site: lab
    tags:
      lab: true
      environment: lab
""",
        encoding="utf-8",
    )

    main(["import-devices", str(path)])
    imported = _last_json(capsys.readouterr().out)
    main(["dry-run", "--device", "sw1-lab", "--operation", "vlan_create", "--vlan-id", "123", "--name", "TEST_VLAN"])
    dry_run = _last_json(capsys.readouterr().out)

    assert imported["devices"][0]["hostname"] == "sw1-lab"
    assert dry_run["command_hash"]
    assert "write memory" in [command["command"] for command in dry_run["commands"]]
    assert SessionLocal().query(Device).filter(Device.hostname == "sw1-lab").one_or_none() is not None


def test_lab_prototype_import_devices_refuses_non_lab_tags(tmp_path) -> None:
    path = tmp_path / "devices.yaml"
    path.write_text(
        """
devices:
  - hostname: prod-sw
    management_ip: 192.168.88.50
    vendor: Cisco
    model: Catalyst 2960
    tags:
      lab: false
""",
        encoding="utf-8",
    )

    try:
        main(["import-devices", str(path)])
    except SystemExit as exc:
        assert "lab=false" in str(exc)
    else:
        raise AssertionError("Prototype import accepted a device explicitly tagged lab=false")


def test_lab_prototype_add_credential_uses_prompt_without_plaintext(monkeypatch, capsys) -> None:
    monkeypatch.setenv("NCP_SECRET_KEY", "prototype-test-secret")
    get_settings.cache_clear()
    monkeypatch.setattr("getpass.getpass", lambda _prompt: "PlainSecret")

    main(["add-credential", "--name", "lab-admin", "--username", "admin", "--password-prompt"])
    output = _last_json(capsys.readouterr().out)

    stored = SessionLocal().query(CredentialSecret).filter(CredentialSecret.name == "lab-admin").one()
    assert output["credential_ref"]
    assert "PlainSecret" not in json.dumps(output)
    assert stored.encrypted_payload != "PlainSecret"


def test_lab_prototype_real_lab_execute_requires_explicit_simulation_hash() -> None:
    try:
        main(
            [
                "execute-apply",
                "--device",
                "missing-device",
                "--credential",
                "missing-credential",
                "--operation",
                "vlan_create",
                "--vlan-id",
                "123",
                "--name",
                "TEST_VLAN",
                "--real-lab",
            ]
        )
    except SystemExit as exc:
        assert "simulation-hash" in str(exc)
    else:
        raise AssertionError("Real lab execution did not require an explicit simulation hash")


def test_lab_prototype_backup_requires_credential_use_permission() -> None:
    try:
        main(
            [
                "--roles",
                "viewer",
                "backup",
                "--device",
                "sw1-lab",
                "--credential",
                "lab-admin",
            ]
        )
    except SystemExit as exc:
        assert "use_credential_secrets" in str(exc)
    else:
        raise AssertionError("Viewer was allowed to start lab backup credential use")
