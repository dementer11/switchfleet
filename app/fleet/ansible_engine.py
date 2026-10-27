"""Ansible Runner adapter for executing validated SwitchFleet device plans."""
from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

_PROJECT_DIR = Path(__file__).with_name("ansible") / "project"
_MAX_FORKS = 32
_MAX_TIMEOUT = 3600


class AnsibleEngine:
    """Run plans through ansible-runner and the SwitchFleet action plugin."""

    def available(self) -> dict[str, str | bool | None]:
        if sys.platform == "win32":
            return {
                "available": False,
                "version": None,
                "error": "The Ansible executor requires Linux; it is not available on Windows.",
            }
        if not shutil.which("ansible-playbook"):
            return {
                "available": False,
                "version": None,
                "error": "Ansible Core is unavailable: ansible-playbook was not found on PATH.",
            }
        try:
            ansible = importlib.import_module("ansible")
            importlib.import_module("ansible_runner")
            from importlib.metadata import PackageNotFoundError, version

            try:
                installed_version = version("ansible-core")
            except PackageNotFoundError:
                installed_version = getattr(ansible, "__version__", None)
            return {"available": True, "version": installed_version, "error": None}
        except (ImportError, OSError, ValueError) as exc:
            return {"available": False, "version": None, "error": f"ansible-runner is unavailable: {exc}"}

    def run(
        self,
        plans: list[dict[str, Any]],
        credentials: dict[str, dict[str, Any]],
        on_event: Callable[[dict[str, Any]], Any] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
        forks: int = 5,
    ) -> list[dict[str, Any]]:
        if sys.platform == "win32":
            raise RuntimeError("The Ansible executor requires Linux; it cannot run on Windows.")
        try:
            ansible_runner = importlib.import_module("ansible_runner")
        except Exception as exc:
            raise RuntimeError(f"ansible-runner is unavailable: {exc}") from exc

        if not isinstance(plans, list):
            raise TypeError("plans must be a list")
        credentials = credentials or {}
        safe_plans = [dict(plan) for plan in plans]
        self._reject_plan_secrets(safe_plans, credentials)
        bounded_forks = max(1, min(int(forks), _MAX_FORKS))
        timeout = self._runner_timeout(safe_plans, bounded_forks)
        device_ids = [str(plan.get("device_id", "")) for plan in safe_plans]
        if len(set(device_ids)) != len(device_ids):
            raise ValueError("Each Ansible plan must have a unique device_id")
        device_by_host = {f"switchfleet_{index:04d}": device_id for index, device_id in enumerate(device_ids)}

        results_by_device: dict[str, dict[str, Any]] = {}
        secrets = self._secret_values(credentials)

        with tempfile.TemporaryDirectory(prefix="switchfleet-ansible-") as temp_name:
            private_dir = Path(temp_name)
            request_path = private_dir / "request.json"
            credentials_path = private_dir / "credentials.json"
            inventory_path = private_dir / "inventory.yml"
            cancel_path = private_dir / "cancelled"
            runner_private_dir = private_dir / "runner"
            runner_private_dir.mkdir(mode=0o700)
            os.chmod(runner_private_dir, 0o700)
            self._write_json(request_path, {"plans": safe_plans}, private=False)
            self._write_json(credentials_path, credentials, private=True)
            self._write_json(inventory_path, self._inventory(safe_plans), private=False)

            def emit(event: dict[str, Any]) -> None:
                if on_event is None:
                    return
                clean_event = self._redact(event, secrets)
                try:
                    on_event(clean_event)
                except Exception:  # noqa: BLE001  # callbacks must not interrupt device execution
                    return

            def event_handler(event: dict[str, Any]) -> bool:
                self._process_event(event, results_by_device, device_by_host, emit, secrets)
                return True

            cancellation = {"requested": False}

            def cancel_callback() -> bool:
                cancelled = bool(is_cancelled and is_cancelled())
                if cancelled:
                    cancellation["requested"] = True
                    cancel_path.touch(exist_ok=True)
                return cancelled

            try:
                runner = ansible_runner.run(
                    private_data_dir=str(runner_private_dir),
                    project_dir=str(_PROJECT_DIR),
                    playbook="run.yml",
                    inventory=str(inventory_path),
                    envvars={
                        "SWITCHFLEET_REQUEST_FILE": str(request_path),
                        "SWITCHFLEET_CREDENTIALS_FILE": str(credentials_path),
                        "SWITCHFLEET_CANCEL_FILE": str(cancel_path),
                    },
                    forks=bounded_forks,
                    timeout=timeout,
                    quiet=True,
                    event_handler=event_handler,
                    cancel_callback=cancel_callback,
                )
            except Exception as exc:  # noqa: BLE001  # runner errors must become per-device failures
                message = self._redact_text(f"Ansible runner error: {exc}", secrets)
                for plan in safe_plans:
                    device_id = str(plan.get("device_id", ""))
                    results_by_device.setdefault(device_id, self._failed_result(plan, message))
                runner = None

            status = str(getattr(runner, "status", "") or "").casefold()
            cancelled = status in {"canceled", "cancelled"} or cancellation["requested"] or bool(is_cancelled and is_cancelled())
            for plan in safe_plans:
                device_id = str(plan.get("device_id", ""))
                if device_id not in results_by_device:
                    if cancelled:
                        results_by_device[device_id] = self._cancelled_result(plan)
                    else:
                        message = "Ansible runner ended without a device result"
                        if status == "failed":
                            message = "Ansible runner failed before returning a device result"
                        elif status not in {"successful", "success"}:
                            message = f"Ansible runner ended with status {status or 'unknown'} and no device result"
                        results_by_device[device_id] = self._failed_result(plan, message)
                emit({"event": "switchfleet_device_result", "device_id": device_id, "result": results_by_device[device_id]})

        return [results_by_device[str(plan.get("device_id", ""))] for plan in safe_plans]

    @staticmethod
    def _runner_timeout(plans: list[dict[str, Any]], forks: int) -> int:
        execution_budgets = []
        command_fields = (
            "backup_setup_commands",
            "backup_commands",
            "setup_commands",
            "commands",
            "save_commands",
            "verify_commands",
        )
        for plan in plans:
            try:
                per_command_timeout = max(1, int(plan.get("timeout", 30)))
            except (TypeError, ValueError):
                per_command_timeout = 30
            command_count = 0
            for field in command_fields:
                commands = plan.get(field, [])
                if isinstance(commands, (list, tuple)):
                    command_count += len(commands)
                elif commands:
                    command_count += 1
            # One additional timeout budget covers opening the device connection.
            execution_budgets.append((command_count + 1) * per_command_timeout)
        batches = max(1, (len(plans) + forks - 1) // forks)
        return min(_MAX_TIMEOUT, max(30, max(execution_budgets, default=30) * batches + 30))

    @staticmethod
    def _inventory(plans: list[dict[str, Any]]) -> dict[str, Any]:
        hosts: dict[str, dict[str, Any]] = {}
        for index, plan in enumerate(plans):
            host_vars = {
                "ansible_connection": "local",
                "device_id": str(plan.get("device_id", "")),
                "ansible_host": str(plan.get("ip_address", "")),
                "ansible_port": int(plan.get("port", 22) or 22),
            }
            hosts[f"switchfleet_{index:04d}"] = host_vars
        return {"all": {"hosts": hosts}}

    @staticmethod
    def _write_json(path: Path, value: Any, *, private: bool) -> None:
        with path.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
        os.chmod(path, 0o600 if private else 0o644)

    @classmethod
    def _process_event(
        cls,
        event: dict[str, Any],
        results: dict[str, dict[str, Any]],
        device_by_host: dict[str, str],
        emit: Callable[[dict[str, Any]], None],
        secrets: list[str],
    ) -> None:
        event_name = str(event.get("event", ""))
        event_data = event.get("event_data") or {}
        host = str(event_data.get("host", ""))
        result = event_data.get("res") or {}
        device_id = str(result.get("device_id") or event_data.get("device_id") or device_by_host.get(host, ""))
        if not device_id and isinstance(result.get("switchfleet_result"), dict):
            device_id = str(result["switchfleet_result"].get("device_id", ""))
        if event_name in {"runner_on_ok", "runner_on_failed", "runner_on_unreachable"}:
            network_result = result.get("switchfleet_result")
            if isinstance(network_result, dict) and device_id:
                normalized = cls._redact(network_result, secrets)
                if event_name in {"runner_on_failed", "runner_on_unreachable"} and normalized.get("status") == "succeeded":
                    normalized["status"] = "failed"
                    normalized["error"] = cls._redact_text(
                        str(result.get("msg") or f"Ansible host {host} {event_name.removeprefix('runner_on_')}"),
                        secrets,
                    )
                results[device_id] = normalized
            elif device_id:
                reason = result.get("msg") or result.get("stderr") or f"Ansible host {host or device_id} {event_name.removeprefix('runner_on_')}"
                results[device_id] = {
                    "device_id": device_id,
                    "operation": "unknown",
                    "status": "failed",
                    "changed": False,
                    "output": "",
                    "backup_text": None,
                    "error": cls._redact_text(str(reason), secrets),
                    "duration_seconds": 0,
                    "verification": None,
                }
        if event_name in {"runner_on_ok", "runner_on_failed", "runner_on_unreachable"}:
            emit({"event": event_name, "host": host, "device_id": device_id or None, "result": results.get(device_id)})

    @staticmethod
    def _failed_result(plan: dict[str, Any], error: str) -> dict[str, Any]:
        return {
            "device_id": str(plan.get("device_id", "")),
            "operation": str(plan.get("operation", "unknown")),
            "status": "failed",
            "changed": False,
            "output": "",
            "backup_text": None,
            "error": error,
            "duration_seconds": 0,
            "verification": None,
        }

    @staticmethod
    def _cancelled_result(plan: dict[str, Any]) -> dict[str, Any]:
        result = AnsibleEngine._failed_result(plan, "Execution cancelled before a device result was returned")
        result["status"] = "cancelled"
        return result

    @classmethod
    def _secret_values(cls, credentials: dict[str, dict[str, Any]]) -> list[str]:
        values: set[str] = set()
        for entry in credentials.values():
            if not isinstance(entry, dict):
                continue
            for key in ("password", "enable_password", "new_password", "private_key", "private_key_passphrase"):
                value = entry.get(key)
                if value is not None and str(value):
                    values.add(str(value))
        return sorted(values, key=len, reverse=True)

    @classmethod
    def _reject_plan_secrets(cls, plans: list[dict[str, Any]], credentials: dict[str, dict[str, Any]]) -> None:
        serialized = json.dumps(plans, ensure_ascii=False, default=str)
        leaked = [value for value in cls._secret_values(credentials) if value in serialized]
        if leaked:
            raise ValueError("Plan contains credential material; keep secrets only in the credentials map")

    @classmethod
    def _redact_text(cls, value: str, secrets: list[str]) -> str:
        for secret in secrets:
            value = value.replace(secret, "[REDACTED]")
        return value

    @classmethod
    def _redact(cls, value: Any, secrets: list[str]) -> Any:
        if isinstance(value, dict):
            return {key: cls._redact(item, secrets) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._redact(item, secrets) for item in value]
        if isinstance(value, tuple):
            return [cls._redact(item, secrets) for item in value]
        if isinstance(value, str):
            return cls._redact_text(value, secrets)
        return value
