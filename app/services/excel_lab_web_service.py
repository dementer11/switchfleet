from __future__ import annotations

import argparse
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import Any, cast


class ExcelLabWebError(ValueError):
    """Raised when a local Excel web command cannot be completed safely."""


EXCEL_LAB_WEB_COMMANDS = {
    "doctor",
    "summary",
    "list",
    "check-runtime",
    "add-credential",
    "backup",
    "dry-run",
    "evaluate-apply",
    "certify",
    "certification-report",
    "workflow",
    "execute-apply",
    "audit-tail",
}


class ExcelLabWebService:
    """Thin web adapter over the existing Excel-first local workflow.

    This service intentionally delegates to the same file-mode orchestration
    used by ``scripts/excel_lab.py``. It does not import DB repositories and it
    does not create an independent driver/runtime path.
    """

    def run(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        if command not in EXCEL_LAB_WEB_COMMANDS:
            raise ExcelLabWebError(f"Unsupported Excel web command: {command}")
        args = self._args(command, payload)
        try:
            result = self._dispatch()(args)
        except SystemExit as exc:
            message = str(exc)
            if not message:
                message = "Command was rejected by the Excel lab workflow"
            raise ExcelLabWebError(message) from exc
        except Exception as exc:
            raise ExcelLabWebError(str(exc)) from exc
        return result

    def _dispatch(self) -> Callable[[argparse.Namespace], dict[str, Any]]:
        excel_cli = import_module("scripts.excel_lab")
        return cast(Callable[[argparse.Namespace], dict[str, Any]], getattr(excel_cli, "_dispatch"))

    def _args(self, command: str, payload: dict[str, Any]) -> argparse.Namespace:
        inventory_path = payload.get("inventory_path")
        if not inventory_path:
            raise ExcelLabWebError("inventory_path is required")
        state_dir = payload.get("state_dir") or ".switchfleet_lab"
        profile_path = payload.get("profile_path")
        return argparse.Namespace(
            command=command,
            inventory_path=Path(str(inventory_path)),
            state_dir=str(state_dir),
            debug=bool(payload.get("debug", False)),
            json=True,
            human=False,
            vendor=payload.get("vendor"),
            category=payload.get("category"),
            status=payload.get("status"),
            allowlisted_only=bool(payload.get("allowlisted_only", False)),
            limit=self._optional_int(payload.get("limit")),
            device=payload.get("device") or payload.get("ip"),
            all=bool(payload.get("all_devices", False)),
            name=payload.get("name"),
            username=payload.get("username"),
            password_prompt=False,
            password_env=None,
            password_value=payload.get("password"),
            purpose=payload.get("purpose") or "lab_apply",
            credential=payload.get("credential") or payload.get("credential_ref"),
            profile=Path(str(profile_path)) if profile_path else None,
            operation=payload.get("operation"),
            vlan_id=self._optional_int(payload.get("vlan_id")),
            new_password_prompt=False,
            new_password_env=None,
            new_password_value=payload.get("new_password"),
            level=self._optional_int(payload.get("level")) or 15,
            interface=payload.get("interface"),
            simulation_hash=payload.get("simulation_hash"),
            capability=payload.get("capability"),
            real_lab=bool(payload.get("real_lab", False)),
            with_backup=bool(payload.get("with_backup", False)),
        )

    def _optional_int(self, value: Any) -> int | None:
        if value in (None, ""):
            return None
        return int(value)
