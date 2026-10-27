"""Small, durable local file store for the standalone SwitchFleet app."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, cast

from cryptography.fernet import Fernet


class FleetStore:
    """Atomic JSON persistence with encrypted secrets and in-process locking."""

    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._chmod_private(self.root, directory=True)
        self._lock = threading.RLock()
        self._owner_lock_handle: BinaryIO | None = self._acquire_owner_lock()
        self._key_path = self.root / "local.key"
        try:
            if self._key_path.exists():
                key = self._key_path.read_bytes()
            else:
                key = Fernet.generate_key()
                self._write_bytes(self._key_path, key)
                self._chmod_private(self._key_path)
            self._fernet = Fernet(key)
            self._hash_key = hashlib.sha256(key + b"switchfleet-plan-hash").digest()
            self._state_path = self.root / "state.json"
            with self._lock:
                state = self._read()
                changed = False
                for job in state["jobs"].values():
                    if job.get("status") in {"queued", "running"}:
                        recovered_at = datetime.now(timezone.utc).isoformat()
                        job.update(status="failed", error="Interrupted by service restart", finished_at=recovered_at, updated_at=recovered_at)
                        state["audit"].append({"id": uuid.uuid4().hex, "created_at": recovered_at, "action": "job.interrupted", "actor": "local", "metadata": {"job_id": job.get("id")}})
                        changed = True
                if state["locks"]:
                    state["locks"] = {}
                    changed = True
                for plan_id, plan in list(state["plans"].items()):
                    if "encrypted_payload" not in plan:
                        state["plans"][plan_id] = self._encrypt_plan(plan_id, plan)
                        changed = True
                if changed:
                    self._save(state)
        except Exception:
            self.close()
            raise

    def _acquire_owner_lock(self) -> BinaryIO:
        path = self.root / "instance.lock"
        handle = path.open("a+b")
        self._chmod_private(path)
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
        except (OSError, ImportError) as exc:
            handle.close()
            raise RuntimeError("Another SwitchFleet instance already owns this data directory") from exc
        return handle

    def close(self) -> None:
        handle = getattr(self, "_owner_lock_handle", None)
        if handle is None:
            return
        self._owner_lock_handle = None
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]
        except (OSError, ImportError):
            pass
        finally:
            handle.close()

    def __del__(self) -> None:
        self.close()

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {"inventory": None, "devices": [], "credentials": {}, "plans": {}, "jobs": {}, "audit": [], "locks": {}}

    def _read(self) -> dict[str, Any]:
        if not self._state_path.exists():
            return self._empty()
        try:
            value = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Fleet state file is unreadable") from exc
        if not isinstance(value, dict):
            raise TypeError("Fleet state file must contain an object")
        state = self._empty()
        state.update(value)
        return state

    def _save(self, state: dict[str, Any]) -> None:
        data = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        temp = self.root / f".state-{uuid.uuid4().hex}.tmp"
        try:
            self._write_bytes(temp, data)
            os.replace(temp, self._state_path)
            self._chmod_private(self._state_path)
        finally:
            temp.unlink(missing_ok=True)

    @staticmethod
    def _write_bytes(path: Path, data: bytes) -> None:
        with path.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _chmod_private(path: Path, *, directory: bool = False) -> None:
        try:
            path.chmod(0o700 if directory else 0o600)
        except OSError:
            pass

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")

    def keyed_hash(self, value: bytes) -> str:
        return hmac.new(self._hash_key, value, hashlib.sha256).hexdigest()

    def _change(self, action: str, *, actor: str = "local", metadata: dict[str, Any] | None = None) -> None:
        state = self._read()
        state["audit"].append({
            "id": uuid.uuid4().hex,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "actor": actor,
            "metadata": metadata or {},
        })
        state["audit"] = state["audit"][-1000:]
        self._save(state)

    def get_inventory(self) -> dict[str, Any] | None:
        with self._lock:
            return cast(dict[str, Any] | None, self._read()["inventory"])

    def save_inventory(self, inventory: dict[str, Any]) -> None:
        with self._lock:
            state = self._read()
            state["inventory"] = inventory
            state["devices"] = inventory["devices"]
            state["plans"] = {}
            self._save(state)
            self._change("inventory.imported", metadata={"device_count": len(inventory["devices"])})

    def list_devices(self) -> list[dict[str, Any]]:
        with self._lock:
            return cast(list[dict[str, Any]], self._read()["devices"])

    def update_device(self, device_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            state = self._read()
            device = next((item for item in state["devices"] if item["id"] == device_id), None)
            if device is None:
                return None
            device.update(fields)
            if state["inventory"] is not None:
                state["inventory"]["devices"] = state["devices"]
            state["plans"] = {}
            self._save(state)
            self._change("device.updated", metadata={"device_id": device_id, "fields": sorted(fields)})
            return dict(device)

    def put_credential(self, *, name: str, username: str, password: str, enable_password: str | None = None) -> dict[str, Any]:
        with self._lock:
            state = self._read()
            existing = next((item for item in state["credentials"].values() if item["name"] == name), None)
            identifier = str(existing["id"]) if existing else uuid.uuid4().hex
            state["credentials"][identifier] = {
                "id": identifier,
                "name": name,
                "username": username,
                "encrypted_password": self.encrypt(password),
                "encrypted_enable_password": self.encrypt(enable_password) if enable_password else None,
            }
            self._save(state)
            self._change("credential.saved", metadata={"credential_id": identifier, "name": name})
            return {"id": identifier, "name": name, "username": username, "has_secret": True}

    def list_credentials(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {key: value[key] for key in ("id", "name", "username")} | {"has_secret": True}
                for value in self._read()["credentials"].values()
            ]

    def credential(self, reference: str) -> dict[str, Any] | None:
        with self._lock:
            state = self._read()
            row = state["credentials"].get(reference) or next(
                (item for item in state["credentials"].values() if item["name"] == reference), None
            )
            return dict(row) if row else None

    def save_plan(self, plan: dict[str, Any]) -> None:
        with self._lock:
            state = self._read()
            state["plans"][plan["id"]] = self._encrypt_plan(plan["id"], plan)
            self._save(state)
            self._change("plan.created", metadata={"plan_id": plan["id"], "operation": plan["operation"]})

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        with self._lock:
            plan = self._read()["plans"].get(plan_id)
            if not plan:
                return None
            encrypted_payload = plan.get("encrypted_payload")
            if not encrypted_payload:
                return dict(plan)
            return cast(dict[str, Any], json.loads(self.decrypt(encrypted_payload)))

    def _encrypt_plan(self, plan_id: str, plan: dict[str, Any]) -> dict[str, str]:
        payload = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return {"id": plan_id, "encrypted_payload": self.encrypt(payload)}

    def enqueue_job(self, job: dict[str, Any], device_ids: list[str]) -> None:
        with self._lock:
            state = self._read()
            conflicts = [device_id for device_id in device_ids if device_id in state["locks"]]
            if conflicts:
                raise ValueError("One or more selected devices already have a running job")
            state["jobs"][job["id"]] = job
            job["updated_at"] = datetime.now(timezone.utc).isoformat()
            for device_id in device_ids:
                state["locks"][device_id] = job["id"]
            state["audit"].append({"id": uuid.uuid4().hex, "created_at": datetime.now(timezone.utc).isoformat(), "action": "job.queued", "actor": "local", "metadata": {"job_id": job["id"], "device_count": job.get("device_count", len(device_ids))}})
            self._save(state)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._read()["jobs"].get(job_id)
            return dict(job) if job else None

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            return sorted(self._read()["jobs"].values(), key=lambda item: item.get("created_at", ""), reverse=True)

    def update_job(self, job_id: str, **fields: Any) -> dict[str, Any] | None:
        with self._lock:
            state = self._read()
            job = state["jobs"].get(job_id)
            if job is None:
                return None
            previous_status = job.get("status")
            previous_cancel = job.get("cancel_requested", False)
            job.update(fields)
            job["updated_at"] = datetime.now(timezone.utc).isoformat()
            if fields.get("cancel_requested") and not previous_cancel:
                job["cancel_requested_at"] = job["updated_at"]
                state["audit"].append({"id": uuid.uuid4().hex, "created_at": job["updated_at"], "action": "job.cancel_requested", "actor": "local", "metadata": {"job_id": job_id}})
            if fields.get("status") in {"succeeded", "partial", "failed", "cancelled"}:
                if previous_status not in {"succeeded", "partial", "failed", "cancelled"}:
                    state["audit"].append({"id": uuid.uuid4().hex, "created_at": job.get("finished_at") or job["updated_at"], "action": "job.completed", "actor": "local", "metadata": {"job_id": job_id, "status": fields["status"]}})
                for device_id, owner in list(state["locks"].items()):
                    if owner == job_id:
                        del state["locks"][device_id]
            elif fields.get("status") == "running" and previous_status != "running":
                state["audit"].append({"id": uuid.uuid4().hex, "created_at": job.get("started_at") or job["updated_at"], "action": "job.started", "actor": "local", "metadata": {"job_id": job_id}})
            state["audit"] = state["audit"][-1000:]
            self._save(state)
            return dict(job)

    def is_cancelled(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        return bool(job and job.get("cancel_requested"))

    def audit_tail(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            return cast(list[dict[str, Any]], self._read()["audit"][-max(0, min(limit, 200)):])
