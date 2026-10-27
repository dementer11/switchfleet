"""Ansible action plugin that hands a single plan to SwitchFleet's network layer."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

from ansible.plugins.action import ActionBase  # type: ignore[import-not-found]


class ActionModule(ActionBase):  # type: ignore[misc]
    TRANSFERS_FILES = False

    def run(self, tmp: str | None = None, task_vars: dict[str, Any] | None = None) -> dict[str, Any]:
        del tmp
        task_vars = task_vars or {}
        device_id = str(self._task.args.get("device_id") or task_vars.get("device_id") or "")
        request_path = os.environ.get("SWITCHFLEET_REQUEST_FILE")
        credentials_path = os.environ.get("SWITCHFLEET_CREDENTIALS_FILE")
        cancel_path = os.environ.get("SWITCHFLEET_CANCEL_FILE")
        if not request_path or not credentials_path or not cancel_path:
            return self._failure(device_id, "SwitchFleet request paths are not configured")
        try:
            request = self._read_json(request_path)
            credentials_by_device = self._read_json(credentials_path)
            plans = request.get("plans", [])
            plan = next((item for item in plans if str(item.get("device_id", "")) == device_id), None)
            if plan is None:
                return self._failure(device_id, "No plan was found for this inventory device")
            if Path(cancel_path).exists():
                return {"changed": False, "switchfleet_result": self._cancelled(plan)}
            credentials = credentials_by_device.get(device_id, {})
            from app.fleet.network import execute_device

            result = execute_device(
                plan,
                credentials,
                timeout=max(1, int(plan.get("timeout", 30))),
                cancelled=lambda: Path(cancel_path).exists(),
            )
            if not isinstance(result, dict):
                return self._failure(device_id, "Network execution returned an invalid result")
            normalized = dict(result)
            normalized.setdefault("device_id", device_id)
            normalized.setdefault("operation", str(plan.get("operation", "unknown")))
            return {
                "changed": bool(normalized.get("changed", False)),
                "failed": normalized.get("status") == "failed",
                "switchfleet_result": normalized,
            }
        except Exception as exc:  # noqa: BLE001  # surface action errors as redacted device results
            return self._failure(device_id, f"SwitchFleet device action failed: {exc}")

    @staticmethod
    def _read_json(path: str) -> Any:
        with Path(path).open("r", encoding="utf-8") as stream:
            return json.load(stream)

    @staticmethod
    def _failure(device_id: str, error: str) -> dict[str, Any]:
        return {
            "changed": False,
            "failed": True,
            "switchfleet_result": {
                "device_id": device_id,
                "operation": "unknown",
                "status": "failed",
                "changed": False,
                "output": "",
                "backup_text": None,
                "error": error,
                "duration_seconds": 0,
                "verification": None,
            },
        }

    @classmethod
    def _cancelled(cls, plan: dict[str, Any]) -> dict[str, Any]:
        result = cls._failure(str(plan.get("device_id", "")), "Execution cancelled before this device started")
        result["switchfleet_result"]["status"] = "cancelled"
        return cast(dict[str, Any], result["switchfleet_result"])
