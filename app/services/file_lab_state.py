from __future__ import annotations

import hashlib
import json
import os
import re
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
    lockfiles: Path
    dry_runs: Path
    evaluations: Path
    lab_validations: Path
    executions: Path
    reports: Path


class FileLabState:
    def __init__(self, state_dir: str | Path = ".switchfleet_lab"):
        root = Path(state_dir)
        self.paths = FileLabStatePaths(
            root=root,
            credentials=root / "credentials.json",
            backups=root / "backups",
            audit=root / "audit.jsonl",
            locks=root / "locks.json",
            lockfiles=root / "lockfiles",
            dry_runs=root / "dry_runs.json",
            evaluations=root / "evaluations.json",
            lab_validations=root / "lab_validations.json",
            executions=root / "executions",
            reports=root / "reports",
        )
        self.ensure()

    def ensure(self) -> None:
        self.paths.root.mkdir(parents=True, exist_ok=True)
        self.paths.backups.mkdir(parents=True, exist_ok=True)
        self.paths.executions.mkdir(parents=True, exist_ok=True)
        self.paths.lockfiles.mkdir(parents=True, exist_ok=True)
        self.paths.reports.mkdir(parents=True, exist_ok=True)
        for directory in (self.paths.root, self.paths.backups, self.paths.executions, self.paths.lockfiles, self.paths.reports):
            _chmod_private(directory, directory=True)
        defaults: tuple[tuple[Path, dict[str, Any]], ...] = (
            (self.paths.credentials, {"credentials": []}),
            (self.paths.locks, {"locks": []}),
            (self.paths.dry_runs, {"dry_runs": []}),
            (self.paths.evaluations, {"evaluations": []}),
            (self.paths.lab_validations, {"lab_validations": []}),
        )
        for path, default in defaults:
            if not path.exists():
                self._write_json(path, default)
            else:
                _chmod_private(path)
        if not self.paths.audit.exists():
            self.paths.audit.write_text("", encoding="utf-8")
        _chmod_private(self.paths.audit)

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
        stored = {"id": record.get("id") or _new_id("dry-run"), "created_at": _now(), **_sanitize(record)}
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

    def read_evaluations(self) -> list[dict[str, Any]]:
        return list(self._read_json(self.paths.evaluations, {"evaluations": []}).get("evaluations", []))

    def save_evaluation(self, record: dict[str, Any]) -> dict[str, Any]:
        evaluations = [
            item
            for item in self.read_evaluations()
            if not (
                item.get("command_hash") == record.get("command_hash")
                and item.get("device_id") == record.get("device_id")
                and item.get("operation") == record.get("operation")
                and item.get("simulation_hash") == record.get("simulation_hash")
            )
        ]
        stored = {"id": record.get("id") or _new_id("evaluation"), "created_at": _now(), **_sanitize(record)}
        evaluations.append(stored)
        self._write_json(self.paths.evaluations, {"evaluations": sorted(evaluations, key=lambda item: item.get("created_at", ""))})
        return stored

    def latest_evaluation_for(self, device_id: str, operation: str, command_hash: str) -> dict[str, Any] | None:
        matches = [
            item
            for item in self.read_evaluations()
            if item.get("device_id") == device_id
            and item.get("operation") == operation
            and item.get("command_hash") == command_hash
        ]
        return sorted(matches, key=lambda item: item.get("created_at", ""), reverse=True)[0] if matches else None

    def read_lab_validations(self) -> list[dict[str, Any]]:
        return list(self._read_json(self.paths.lab_validations, {"lab_validations": []}).get("lab_validations", []))

    def save_lab_validation(self, record: dict[str, Any]) -> dict[str, Any]:
        validations = self.read_lab_validations()
        stored = {
            **_sanitize(record),
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

    def latest_validation_for_runtime(
        self,
        device_id: str,
        capability: str,
        *,
        vendor: str | None,
        model: str | None,
        driver_name: str | None,
        platform: str | None,
        family: str,
        selected_transport: str,
    ) -> dict[str, Any] | None:
        criteria = {
            "vendor": vendor,
            "model": model,
            "driver_name": driver_name,
            "platform": platform,
            "family": family,
            "selected_transport": selected_transport,
        }
        matches = [
            item
            for item in self.read_lab_validations()
            if item.get("device_id") == device_id
            and item.get("capability") == capability
            and item.get("status") == "approved"
            and self._validation_matches_runtime(item, criteria)
        ]
        return sorted(matches, key=lambda item: item.get("created_at", ""), reverse=True)[0] if matches else None

    def _validation_matches_runtime(self, validation: dict[str, Any], criteria: dict[str, str | None]) -> bool:
        for key, expected in criteria.items():
            if expected is None:
                continue
            if str(validation.get(key) or "") != str(expected):
                return False
        return True

    def read_locks(self) -> list[dict[str, Any]]:
        return list(self._read_json(self.paths.locks, {"locks": []}).get("locks", []))

    def has_active_lock(self, device_id: str) -> bool:
        return any(item.get("device_id") == device_id and item.get("status") == "reserved" for item in self.read_locks())

    def reserve_lock(
        self,
        device_id: str,
        reason: str,
        *,
        display_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        guard = self._lockfile_for(device_id)
        display = display_name or device_id
        try:
            descriptor = os.open(guard, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise SafetyError(f"Device {display} already has an active lab lock") from exc
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8"):
                pass
            _chmod_private(guard)
            if self.has_active_lock(device_id):
                raise SafetyError(f"Device {display} already has an active lab lock")
            locks = self.read_locks()
            lock = {
                "id": _new_id("lock"),
                "device_id": device_id,
                "status": "reserved",
                "reason": reason,
                "created_at": _now(),
                **_sanitize(metadata or {}),
            }
            locks.append(lock)
            self._write_json(self.paths.locks, {"locks": locks})
            return lock
        except Exception:
            guard.unlink(missing_ok=True)
            raise

    def release_locks(self, device_id: str) -> None:
        locks = self.read_locks()
        for lock in locks:
            if lock.get("device_id") == device_id and lock.get("status") == "reserved":
                lock["status"] = "released"
                lock["released_at"] = _now()
        self._write_json(self.paths.locks, {"locks": locks})
        self._lockfile_for(device_id).unlink(missing_ok=True)

    def save_backup(self, device_id: str, config_text: str, metadata: dict[str, Any]) -> dict[str, Any]:
        backup_id = _new_id("backup")
        safe_metadata = _sanitize(metadata)
        device_dir = self.paths.backups / _backup_storage_name(device_id, safe_metadata)
        device_dir.mkdir(parents=True, exist_ok=True)
        _chmod_private(device_dir, directory=True)
        config_path = device_dir / f"{backup_id}.txt"
        sanitized = sanitize_config(config_text)
        config_path.write_text(sanitized.text, encoding="utf-8")
        _chmod_private(config_path)
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
        matches = [
            item
            for item in self.list_backups()
            if item.get("device_id") == device_id and item.get("sanitized") is True and self._backup_file_is_usable(item)
        ]
        return sorted(matches, key=lambda item: item.get("created_at", ""), reverse=True)[0] if matches else None

    def save_execution(self, record: dict[str, Any]) -> dict[str, Any]:
        execution = {"id": record.get("id") or _new_id("exec"), "created_at": _now(), **_sanitize(record)}
        path = self.paths.executions / f"{execution['id']}.json"
        self._write_json(path, execution)
        return execution

    def save_report(self, kind: str, payload: dict[str, Any], markdown: str) -> dict[str, Any]:
        report_id = _new_id(kind)
        created_at = _now()
        json_path = self.paths.reports / f"{report_id}.json"
        markdown_path = self.paths.reports / f"{report_id}.md"
        self._write_json(
            json_path,
            {
                "id": report_id,
                "kind": kind,
                "created_at": created_at,
                "payload": _sanitize(payload),
            },
        )
        markdown_path.write_text(mask_secrets(markdown), encoding="utf-8")
        _chmod_private(markdown_path)
        return {
            "id": report_id,
            "kind": kind,
            "created_at": created_at,
            "json_path": str(json_path.relative_to(self.paths.root)),
            "markdown_path": str(markdown_path.relative_to(self.paths.root)),
        }

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
        _chmod_private(self.paths.audit)
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
        temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            _chmod_private(temp)
            os.replace(temp, path)
            _chmod_private(path)
        finally:
            temp.unlink(missing_ok=True)

    def _lockfile_for(self, device_id: str) -> Path:
        digest = hashlib.sha256(device_id.encode("utf-8")).hexdigest()
        return self.paths.lockfiles / f"{digest}.lock"

    def _backup_file_is_usable(self, record: dict[str, Any]) -> bool:
        relative_path = record.get("config_path")
        if not isinstance(relative_path, str) or not relative_path:
            return False
        root = self.paths.root.resolve()
        path = (root / relative_path).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            return False
        try:
            return path.is_file() and path.stat().st_size > 0
        except OSError:
            return False


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


def _backup_storage_name(device_id: str, metadata: dict[str, Any]) -> str:
    device_ip = str(metadata.get("device_ip") or metadata.get("ip_address") or "").strip()
    return _safe_path_component(device_ip or device_id)


def _safe_path_component(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    safe = safe.strip("._-")
    return safe or "device"


def _chmod_private(path: Path, *, directory: bool = False) -> None:
    if os.name != "posix":
        return
    try:
        path.chmod(0o700 if directory else 0o600)
    except OSError:
        return
