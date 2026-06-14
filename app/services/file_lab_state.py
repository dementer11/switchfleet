from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.exceptions import SafetyError
from app.utils.config_sanitizer import sanitize_config
from app.services.report_sanitizer import sanitize_audit_metadata
from app.utils.masking import mask_secrets


class FileLabStateError(ValueError):
    """Raised when the file-based lab state cannot be read safely."""


@dataclass(frozen=True)
class FileLabStatePaths:
    root: Path
    credentials: Path
    backups: Path
    audit: Path
    locks: Path
    dry_runs: Path
    lab_validations: Path
    executions: Path


class FileLabState:
    def __init__(self, state_dir: str | Path = ".switchfleet_lab"):
        root = Path(state_dir)
        self.paths = FileLabStatePaths(
            root=root,
            credentials=root / "credentials.json",
            backups=root / "backups",
            audit=root / "audit.jsonl",
            locks=root / "locks.json",
            dry_runs=root / "dry_runs.json",
            lab_validations=root / "lab_validations.json",
            executions=root / "executions",
        )
        self.ensure()

    def ensure(self) -> None:
        self.paths.root.mkdir(parents=True, exist_ok=True)
        self.paths.backups.mkdir(parents=True, exist_ok=True)
        self.paths.executions.mkdir(parents=True, exist_ok=True)
        defaults: tuple[tuple[Path, dict[str, Any]], ...] = (
            (self.paths.credentials, {"credentials": []}),
            (self.paths.locks, {"locks": []}),
            (self.paths.dry_runs, {"dry_runs": []}),
            (self.paths.lab_validations, {"lab_validations": []}),
        )
        for path, default in defaults:
            if not path.exists():
                self._write_json(path, default)
        if not self.paths.audit.exists():
            self.paths.audit.write_text("", encoding="utf-8")

    def read_credentials(self) -> list[dict[str, Any]]:
        return list(self._read_json(self.paths.credentials, {"credentials": []}).get("credentials", []))

    def write_credentials(self, credentials: list[dict[str, Any]]) -> None:
        self._write_json(self.paths.credentials, {"credentials": credentials})

    def read_dry_runs(self) -> list[dict[str, Any]]:
        return list(self._read_json(self.paths.dry_runs, {"dry_runs": []}).get("dry_runs", []))

    def save_dry_run(self, record: dict[str, Any]) -> dict[str, Any]:
        dry_runs = [
            item
            for item in self.read_dry_runs()
            if not (
                item.get("command_hash") == record.get("command_hash")
                and item.get("device_id") == record.get("device_id")
                and item.get("operation") == record.get("operation")
            )
        ]
        stored = {"id": record.get("id") or _new_id("dry-run"), "created_at": _now(), **record}
        dry_runs.append(stored)
        self._write_json(self.paths.dry_runs, {"dry_runs": sorted(dry_runs, key=lambda item: item.get("created_at", ""))})
        return stored

    def get_dry_run(self, command_hash: str, *, device_id: str | None = None, operation: str | None = None) -> dict[str, Any] | None:
        for item in self.read_dry_runs():
            if item.get("command_hash") != command_hash:
                continue
            if device_id is not None and item.get("device_id") != device_id:
                continue
            if operation is not None and item.get("operation") != operation:
                continue
            return item
        return None

    def read_lab_validations(self) -> list[dict[str, Any]]:
        return list(self._read_json(self.paths.lab_validations, {"lab_validations": []}).get("lab_validations", []))

    def save_lab_validation(self, record: dict[str, Any]) -> dict[str, Any]:
        validations = self.read_lab_validations()
        stored = {
            **record,
            "id": record.get("id") or _new_id("validation"),
            "created_at": _now(),
            "status": "approved",
            "production_certified": False,
        }
        validations.append(stored)
        self._write_json(self.paths.lab_validations, {"lab_validations": validations})
        return stored

    def latest_validation_for(self, device_id: str, capability: str) -> dict[str, Any] | None:
        matches = [
            item
            for item in self.read_lab_validations()
            if item.get("device_id") == device_id
            and item.get("capability") == capability
            and item.get("status") == "approved"
        ]
        return sorted(matches, key=lambda item: item.get("created_at", ""), reverse=True)[0] if matches else None

    def read_locks(self) -> list[dict[str, Any]]:
        return list(self._read_json(self.paths.locks, {"locks": []}).get("locks", []))

    def has_active_lock(self, device_id: str) -> bool:
        return any(item.get("device_id") == device_id and item.get("status") == "reserved" for item in self.read_locks())

    def reserve_lock(self, device_id: str, reason: str) -> dict[str, Any]:
        if self.has_active_lock(device_id):
            raise SafetyError(f"Device {device_id} already has an active lab lock")
        locks = self.read_locks()
        lock = {"id": _new_id("lock"), "device_id": device_id, "status": "reserved", "reason": reason, "created_at": _now()}
        locks.append(lock)
        self._write_json(self.paths.locks, {"locks": locks})
        return lock

    def release_locks(self, device_id: str) -> None:
        locks = self.read_locks()
        for lock in locks:
            if lock.get("device_id") == device_id and lock.get("status") == "reserved":
                lock["status"] = "released"
                lock["released_at"] = _now()
        self._write_json(self.paths.locks, {"locks": locks})

    def save_backup(self, device_id: str, config_text: str, metadata: dict[str, Any]) -> dict[str, Any]:
        backup_id = _new_id("backup")
        device_dir = self.paths.backups / device_id
        device_dir.mkdir(parents=True, exist_ok=True)
        config_path = device_dir / f"{backup_id}.txt"
        sanitized = sanitize_config(config_text)
        config_path.write_text(sanitized.text, encoding="utf-8")
        safe_metadata = dict(metadata)
        safe_metadata.setdefault("config_hash", sanitized.config_hash)
        safe_metadata.setdefault("redaction_types", sanitized.redaction_types)
        record = {
            "id": backup_id,
            "device_id": device_id,
            "created_at": _now(),
            "sanitized": True,
            "config_path": str(config_path.relative_to(self.paths.root)),
            **safe_metadata,
        }
        index_path = self.paths.backups / "index.json"
        index = self._read_json(index_path, {"backups": []}) if index_path.exists() else {"backups": []}
        backups = [item for item in index.get("backups", []) if item.get("id") != backup_id]
        backups.append(record)
        self._write_json(index_path, {"backups": backups})
        return record

    def list_backups(self) -> list[dict[str, Any]]:
        index_path = self.paths.backups / "index.json"
        if not index_path.exists():
            return []
        return list(self._read_json(index_path, {"backups": []}).get("backups", []))

    def latest_backup_for(self, device_id: str) -> dict[str, Any] | None:
        matches = [item for item in self.list_backups() if item.get("device_id") == device_id and item.get("sanitized") is True]
        return sorted(matches, key=lambda item: item.get("created_at", ""), reverse=True)[0] if matches else None

    def save_execution(self, record: dict[str, Any]) -> dict[str, Any]:
        execution = {"id": record.get("id") or _new_id("exec"), "created_at": _now(), **record}
        path = self.paths.executions / f"{execution['id']}.json"
        self._write_json(path, execution)
        return execution

    def append_audit(self, *, action: str, actor: str, object_type: str, object_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
        event = {
            "id": _new_id("audit"),
            "created_at": _now(),
            "actor": actor,
            "action": action,
            "object_type": object_type,
            "object_id": object_id,
            "metadata": _sanitize(metadata),
        }
        with self.paths.audit.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        return event

    def audit_tail(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.paths.audit.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in self.paths.audit.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise FileLabStateError(f"Corrupt audit event in {self.paths.audit}") from exc
        return events[-limit:]

    def _read_json(self, path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return default
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise FileLabStateError(f"Corrupt JSON state file: {path}") from exc
        if not isinstance(loaded, dict):
            raise FileLabStateError(f"State file must contain a JSON object: {path}")
        return loaded

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temp, path)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return sanitize_audit_metadata(value)
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return mask_secrets(value)
    return value
