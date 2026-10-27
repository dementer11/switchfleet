from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
from importlib import metadata
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from app.fleet.ansible_engine import AnsibleEngine


def _plan(device_id: str = "switch-1") -> dict[str, Any]:
    return {
        "device_id": device_id,
        "ip_address": "192.0.2.10",
        "port": 22,
        "label": "lab-switch",
        "family": "cisco_ios",
        "operation": "password_change",
        "commands": ["username account-to-change secret __SWITCHFLEET_NEW_PASSWORD__"],
        "setup_commands": [],
        "save_commands": [],
        "verify_commands": [],
        "requires_backup": True,
        "backup_commands": ["show running-config"],
        "timeout": 45,
    }


def _network_result(device_id: str = "switch-1", **overrides: Any) -> dict[str, Any]:
    result = {
        "device_id": device_id,
        "operation": "password_change",
        "status": "succeeded",
        "changed": True,
        "output": "Password updated",
        "backup_text": "sanitized backup",
        "error": None,
        "duration_seconds": 2,
        "verification": {"status": "passed"},
    }
    result.update(overrides)
    return result


def _runner_module(monkeypatch: pytest.MonkeyPatch, run: Any) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setitem(sys.modules, "ansible_runner", SimpleNamespace(run=run))


def test_available_is_explicitly_unsupported_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    response = AnsibleEngine().available()
    assert response["available"] is False
    assert "Linux" in str(response["error"])
    assert response["version"] is None


def test_available_requires_ansible_core_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    response = AnsibleEngine().available()
    assert response["available"] is False
    assert "ansible-playbook" in str(response["error"])


def test_available_reports_ansible_core_version_when_core_and_runner_exist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/ansible-playbook" if name == "ansible-playbook" else None)

    def fake_import(module_name: str) -> ModuleType:
        return ModuleType(module_name)

    monkeypatch.setattr("app.fleet.ansible_engine.importlib.import_module", fake_import)
    monkeypatch.setattr(metadata, "version", lambda distribution: "2.18.0" if distribution == "ansible-core" else "2.4.0")
    response = AnsibleEngine().available()
    assert response == {"available": True, "version": "2.18.0", "error": None}


def test_runner_receives_secret_free_request_and_local_inventory_and_cleans_temp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    callback_events: list[dict[str, Any]] = []
    password = "S3cret!OnlyInCredentialMap"
    credentials = {
        "switch-1": {
            "username": "operator",
            "password": password,
            "enable_password": "Enable!Secret",
            "new_password": "New!Secret",
        }
    }

    def fake_run(**kwargs: Any) -> Any:
        captured.update(kwargs)
        request_path = Path(kwargs["envvars"]["SWITCHFLEET_REQUEST_FILE"])
        credentials_path = Path(kwargs["envvars"]["SWITCHFLEET_CREDENTIALS_FILE"])
        inventory_path = Path(kwargs["inventory"])
        captured["temp_root"] = request_path.parent
        captured["request_text"] = request_path.read_text(encoding="utf-8")
        captured["credentials_text"] = credentials_path.read_text(encoding="utf-8")
        captured["inventory"] = json.loads(inventory_path.read_text(encoding="utf-8"))
        private_data_dir = Path(kwargs["private_data_dir"])
        assert private_data_dir.is_dir()
        if os.name != "nt":
            assert private_data_dir.stat().st_mode & 0o777 == 0o700
        if os.name != "nt":
            assert credentials_path.stat().st_mode & 0o777 == 0o600
        kwargs["event_handler"](
            {
                "event": "runner_on_ok",
                "event_data": {
                    "host": "switchfleet_0000",
                    "res": {"switchfleet_result": _network_result()},
                },
            }
        )
        return SimpleNamespace(status="successful")

    _runner_module(monkeypatch, fake_run)
    results = AnsibleEngine().run([_plan()], credentials, on_event=callback_events.append, forks=100)

    assert results[0]["status"] == "succeeded"
    assert "forks" in captured and captured["forks"] == 32
    assert captured["timeout"] == 165  # connect + command + backup, each at 45 seconds, plus margin
    assert captured["inventory"]["all"]["hosts"]["switchfleet_0000"] == {
        "ansible_connection": "local",
        "device_id": "switch-1",
        "ansible_host": "192.0.2.10",
        "ansible_port": 22,
    }
    for secret in (password, "Enable!Secret", "New!Secret"):
        assert secret not in captured["request_text"]
        assert secret not in repr(callback_events)
    assert "__SWITCHFLEET_NEW_PASSWORD__" in captured["request_text"]
    assert captured["credentials_text"]
    assert all(str(value).startswith(str(captured["temp_root"])) for value in captured["envvars"].values())
    assert any(event["event"] == "runner_on_ok" for event in callback_events)
    assert any(event["event"] == "switchfleet_device_result" for event in callback_events)
    assert not captured["temp_root"].exists()


def test_missing_event_after_cancel_is_classified_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    _runner_module(monkeypatch, lambda **kwargs: SimpleNamespace(status="canceled") if kwargs["cancel_callback"]() else SimpleNamespace(status="successful"))
    result = AnsibleEngine().run([_plan()], {}, is_cancelled=lambda: True)[0]
    assert result["status"] == "cancelled"
    assert "cancel" in str(result["error"]).casefold()


def test_runner_timeout_covers_all_command_budgets_and_caps_at_one_hour() -> None:
    plan = _plan()
    plan.update(
        {
            "commands": ["write"] * 10,
            "backup_commands": ["backup"] * 3,
            "setup_commands": ["setup"] * 2,
            "save_commands": ["save"],
            "verify_commands": ["verify"] * 2,
        }
    )
    assert AnsibleEngine._runner_timeout([plan], forks=5) == 885
    plan["commands"] = ["write"] * 100
    assert AnsibleEngine._runner_timeout([plan], forks=1) == 3600


def test_runner_failure_and_unreachable_event_are_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(**kwargs: Any) -> Any:
        kwargs["event_handler"](
            {
                "event": "runner_on_unreachable",
                "event_data": {
                    "host": "switchfleet_0000",
                    "res": {"device_id": "switch-1", "msg": "connection unavailable"},
                },
            }
        )
        return SimpleNamespace(status="failed")

    _runner_module(monkeypatch, fake_run)
    result = AnsibleEngine().run([_plan()], {})[0]
    assert result["status"] == "failed"
    assert "connection unavailable" in str(result["error"])


def test_runner_failed_without_device_event_never_silently_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    _runner_module(monkeypatch, lambda **_kwargs: SimpleNamespace(status="failed"))
    result = AnsibleEngine().run([_plan()], {})[0]
    assert result["status"] == "failed"
    assert "runner failed" in str(result["error"]).casefold()


def test_runner_global_failure_preserves_terminal_per_host_results(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(**kwargs: Any) -> Any:
        kwargs["event_handler"](
            {
                "event": "runner_on_ok",
                "event_data": {
                    "host": "switchfleet_0000",
                    "res": {"switchfleet_result": _network_result()},
                },
            }
        )
        kwargs["event_handler"](
            {
                "event": "runner_on_failed",
                "event_data": {
                    "host": "switchfleet_0001",
                    "res": {"switchfleet_result": _network_result("switch-2", status="failed", error="command rejected")},
                },
            }
        )
        return SimpleNamespace(status="failed")

    _runner_module(monkeypatch, fake_run)
    results = AnsibleEngine().run([_plan(), _plan("switch-2")], {})
    assert results[0]["status"] == "succeeded"
    assert results[0]["error"] is None
    assert results[1]["status"] == "failed"
    assert results[1]["error"] == "command rejected"


def test_username_may_be_a_password_change_target_but_password_values_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _runner_module(monkeypatch, lambda **_kwargs: pytest.fail("runner must not be invoked"))
    plan = _plan()
    credentials = {"switch-1": {"username": "admin", "password": "SSHLoginSecret"}}
    plan["commands"] = ["username admin secret SSHLoginSecret"]
    with pytest.raises(ValueError, match="credential material"):
        AnsibleEngine().run([plan], credentials)


def test_plan_with_admin_target_and_separate_ssh_password_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(**kwargs: Any) -> Any:
        assert "username admin secret __SWITCHFLEET_NEW_PASSWORD__" in Path(
            kwargs["envvars"]["SWITCHFLEET_REQUEST_FILE"]
        ).read_text(encoding="utf-8")
        kwargs["event_handler"](
            {
                "event": "runner_on_ok",
                "event_data": {
                    "host": "switchfleet_0000",
                    "res": {"switchfleet_result": _network_result()},
                },
            }
        )
        return SimpleNamespace(status="successful")

    _runner_module(monkeypatch, fake_run)
    plan = _plan()
    plan["commands"] = ["username admin secret __SWITCHFLEET_NEW_PASSWORD__"]
    result = AnsibleEngine().run(
        [plan],
        {"switch-1": {"username": "admin", "password": "SSHLoginSecret", "new_password": "TargetSecret"}},
    )[0]
    assert result["status"] == "succeeded"


def test_action_plugin_delegates_plan_and_credentials_to_network_layer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[dict[str, Any], dict[str, Any], int, Any]] = []
    request_path = tmp_path / "request.json"
    credentials_path = tmp_path / "credentials.json"
    cancel_path = tmp_path / "cancelled"
    request_path.write_text(json.dumps({"plans": [_plan()]}), encoding="utf-8")
    device_credentials = {"username": "login", "password": "private"}
    credentials_path.write_text(json.dumps({"switch-1": device_credentials}), encoding="utf-8")
    monkeypatch.setenv("SWITCHFLEET_REQUEST_FILE", str(request_path))
    monkeypatch.setenv("SWITCHFLEET_CREDENTIALS_FILE", str(credentials_path))
    monkeypatch.setenv("SWITCHFLEET_CANCEL_FILE", str(cancel_path))

    ansible = ModuleType("ansible")
    plugins = ModuleType("ansible.plugins")
    action_base = ModuleType("ansible.plugins.action")
    action_base.ActionBase = type("ActionBase", (), {})
    monkeypatch.setitem(sys.modules, "ansible", ansible)
    monkeypatch.setitem(sys.modules, "ansible.plugins", plugins)
    monkeypatch.setitem(sys.modules, "ansible.plugins.action", action_base)

    network = ModuleType("app.fleet.network")

    def execute_device(plan: dict[str, Any], credentials: dict[str, Any], timeout: int, cancelled: Any) -> dict[str, Any]:
        calls.append((plan, credentials, timeout, cancelled))
        return _network_result()

    network.execute_device = execute_device
    monkeypatch.setitem(sys.modules, "app.fleet.network", network)

    plugin_path = Path(__file__).parents[2] / "app" / "fleet" / "ansible" / "project" / "action_plugins" / "switchfleet_device.py"
    spec = importlib.util.spec_from_file_location("test_switchfleet_device_plugin", plugin_path)
    assert spec is not None and spec.loader is not None
    plugin_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plugin_module)
    plugin = plugin_module.ActionModule()
    plugin._task = SimpleNamespace(args={"device_id": "switch-1"})

    result = plugin.run(task_vars={})

    assert result["switchfleet_result"]["status"] == "succeeded"
    assert len(calls) == 1
    assert calls[0][0]["device_id"] == "switch-1"
    assert calls[0][1] == device_credentials
    assert calls[0][2] == 45
    assert callable(calls[0][3])
    assert calls[0][3]() is False
