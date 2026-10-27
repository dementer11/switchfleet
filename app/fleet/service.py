"""Application services for the standalone SwitchFleet fleet API."""
from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, cast

from app.fleet.profiles import PASSWORD_PLACEHOLDER, build_device_plan
from app.fleet.store import FleetStore
from app.utils.masking import mask_secrets


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _device_lock_key(device: dict[str, Any]) -> str:
    address = str(device.get("ip_address") or "").casefold()
    if ":" in address and not address.startswith("["):
        address = f"[{address}]"
    return f"{address}:{int(device.get('port', 22))}"


def _redact_public_plan(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact_public_plan(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_public_plan(item) for item in value]
    if isinstance(value, str):
        return mask_secrets(value)
    return value


class FleetService:
    def __init__(self, store: FleetStore, engine: Any):
        self.store = store
        self.engine = engine
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="switchfleet-job")
        self._lifecycle_lock = threading.RLock()
        self._closing = False
        self._active_job_ids: set[str] = set()

    def shutdown(self) -> None:
        with self._lifecycle_lock:
            self._closing = True
            active_job_ids = list(self._active_job_ids)
        for job_id in active_job_ids:
            job = self.store.get_job(job_id)
            if job and job.get("status") in {"queued", "running"}:
                self.store.update_job(job_id, cancel_requested=True)
        # Keep the store owner lock until every engine call has returned.
        self._executor.shutdown(wait=True)

    def engine_status(self) -> dict[str, Any]:
        try:
            available_value = self.engine.available()
            version = None
            if isinstance(available_value, tuple):
                available, error = available_value[0], available_value[1] if len(available_value) > 1 else None
            elif isinstance(available_value, dict):
                available = bool(available_value.get("available"))
                error = available_value.get("error")
                version = available_value.get("version")
            else:
                available, error = bool(available_value), None
                version = getattr(self.engine, "version", None)
            if not isinstance(available_value, dict):
                version = getattr(self.engine, "version", version)
            if callable(version):
                version = version()
            return {"available": available, "version": version, "error": self._safe(error) if error else None}
        except Exception as exc:  # noqa: BLE001 -- engine availability failures are reported as sanitized health state
            return {"available": False, "version": None, "error": self._safe(exc)}

    def create_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        device_ids = payload.get("device_ids")
        operation = payload.get("operation")
        parameters = payload.get("parameters", {})
        credential_ref = payload.get("credential_ref")
        timeout = payload.get("timeout", 30)
        if not isinstance(device_ids, list) or not device_ids or any(not isinstance(item, str) or not item for item in device_ids):
            raise ValueError("device_ids must be a non-empty list of device IDs")
        if len(device_ids) != len(set(device_ids)):
            raise ValueError("device_ids must not contain duplicates")
        if not isinstance(operation, str) or not operation:
            raise ValueError("operation is required")
        if not isinstance(parameters, dict):
            raise TypeError("parameters must be an object")
        for key in parameters:
            folded_key = str(key).casefold()
            if any(token in folded_key for token in ("password", "secret", "token", "private_key", "credential_material")) and key != "new_password":
                raise ValueError(f"Secret-bearing parameter {key!r} is not accepted")
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 600:
            raise ValueError("timeout must be in range 1..600")
        selected = {device["id"]: device for device in self.store.list_devices()}
        if any(device_id not in selected for device_id in device_ids):
            raise ValueError("One or more selected device IDs were not found")
        safe_parameters = dict(parameters)
        new_password = safe_parameters.pop("new_password", None)
        planning_parameters = dict(safe_parameters)
        if operation == "password_change":
            if not isinstance(new_password, str) or not new_password or "\n" in new_password or "\r" in new_password:
                raise ValueError("new_password is required and must be a single line")
            planning_parameters["new_password"] = PASSWORD_PLACEHOLDER
        elif new_password is not None:
            raise ValueError("new_password is accepted only for password_change")

        plans: list[dict[str, Any]] = []
        unsupported: list[dict[str, str]] = []
        credentials: dict[str, str | None] = {}
        for device_id in device_ids:
            device = selected[device_id]
            plan = build_device_plan(device, operation, planning_parameters)
            plan["timeout"] = timeout
            ref = credential_ref or device.get("credential_ref")
            plan["credential_ref"] = ref
            credentials[device_id] = ref
            if plan.get("status") == "unsupported":
                unsupported.append({"device_id": device_id, "error": self._safe(plan.get("error") or "Unsupported operation")})
            plans.append(plan)

        bound_parameters = dict(safe_parameters)
        if new_password:
            bound_parameters["new_password"] = new_password
        bound = {"device_ids": device_ids, "operation": operation, "parameters": bound_parameters, "credential_ref": credential_ref, "timeout": timeout}
        digest = self.store.keyed_hash(json.dumps(bound, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        record = {
            "id": uuid.uuid4().hex,
            "hash": digest,
            "operation": operation,
            "created_at": utcnow(),
            "device_ids": device_ids,
            "parameters": safe_parameters,
            "credential_ref": credential_ref,
            "credentials": credentials,
            "timeout": timeout,
            "devices": plans,
            "unsupported": unsupported,
            "new_password_encrypted": self.store.encrypt(new_password) if new_password else None,
        }
        self.store.save_plan(record)
        public_devices = [_redact_public_plan(device) for device in plans if device.get("status") != "unsupported"]
        return {"id": record["id"], "hash": record["hash"], "operation": operation, "devices": public_devices, "unsupported": unsupported, "created_at": record["created_at"]}

    def enqueue(self, payload: dict[str, Any]) -> dict[str, Any]:
        plan_id, supplied_hash = payload.get("plan_id"), payload.get("plan_hash")
        if not isinstance(plan_id, str) or not isinstance(supplied_hash, str):
            raise TypeError("plan_id and plan_hash are required")
        plan = self.store.get_plan(plan_id)
        if not plan or not __import__("hmac").compare_digest(str(plan["hash"]), supplied_hash):
            raise ValueError("Plan not found or plan_hash does not match")
        requires_confirmation = any(device.get("requires_backup") or device.get("operation") not in {"facts", "backup"} for device in plan["devices"] if device.get("status") != "unsupported")
        if requires_confirmation and payload.get("confirmed") is not True:
            raise ValueError("Explicit confirmation is required for this plan")
        supported = [device for device in plan["devices"] if device.get("status") != "unsupported"]
        for device in supported:
            ref = device.get("credential_ref")
            if not ref or not self.store.credential(str(ref)):
                raise ValueError(f"Credential is missing for device {device.get('device_id')}")
        status = self.engine_status()
        if supported and not status["available"]:
            raise RuntimeError(status.get("error") or "Ansible execution engine is unavailable")
        forks = payload.get("forks", 5)
        if isinstance(forks, bool) or not isinstance(forks, int) or not 1 <= forks <= 100:
            raise ValueError("forks must be in range 1..100")
        job_id = uuid.uuid4().hex
        initial_results = [
            {"device_id": item["device_id"], "ip_address": item.get("ip_address"), "status": "unsupported", "error": item.get("error")}
            for item in plan["devices"] if item.get("status") == "unsupported"
        ]
        job = {
            "id": job_id,
            "plan_id": plan_id,
            "plan_hash": plan["hash"],
            "operation": plan["operation"],
            "device_count": len(plan["device_ids"]),
            "status": "queued",
            "created_at": utcnow(),
            "started_at": None,
            "finished_at": None,
            "cancel_requested": False,
            "results": initial_results,
            "error": None,
        }
        lock_keys = [_device_lock_key(device) for device in supported]
        with self._lifecycle_lock:
            if self._closing:
                raise RuntimeError("SwitchFleet is shutting down and is not accepting new jobs")
            self.store.enqueue_job(job, lock_keys)
            if supported:
                self._active_job_ids.add(job_id)
                try:
                    self._executor.submit(self._run_job, job_id, plan, supported, forks)
                except Exception:
                    self._active_job_ids.discard(job_id)
                    self.store.update_job(job_id, status="failed", error="Unable to submit job", finished_at=utcnow())
                    raise
            else:
                self.store.update_job(job_id, status="partial", finished_at=utcnow())
        return {"id": job_id, "status": "queued", "created_at": job["created_at"]}

    def _run_job(self, job_id: str, plan: dict[str, Any], device_plans: list[dict[str, Any]], forks: int) -> None:
        self.store.update_job(job_id, status="running", started_at=utcnow())
        credential_map: dict[str, dict[str, Any]] = {}
        secrets: list[str] = []
        try:
            for device in device_plans:
                row = self.store.credential(str(device["credential_ref"]))
                if row is None:
                    raise ValueError("A selected credential is no longer available")
                credentials = {
                    "username": row["username"],
                    "password": self.store.decrypt(row["encrypted_password"]),
                    "enable_password": self.store.decrypt(row["encrypted_enable_password"]) if row.get("encrypted_enable_password") else None,
                }
                secrets.extend(
                    value for key, value in credentials.items()
                    if key in {"password", "enable_password"} and isinstance(value, str) and value
                )
                if plan.get("new_password_encrypted"):
                    credentials["new_password"] = self.store.decrypt(plan["new_password_encrypted"])
                    secrets.append(credentials["new_password"])
                credential_map[device["device_id"]] = credentials
            existing_unsupported = [item for item in (self.store.get_job(job_id) or {}).get("results", []) if item.get("status") == "unsupported"]
            if self.store.is_cancelled(job_id):
                cancelled_results = existing_unsupported + [
                    {"device_id": device["device_id"], "ip_address": device.get("ip_address"), "status": "cancelled"}
                    for device in device_plans
                ]
                self.store.update_job(job_id, status="cancelled", results=cancelled_results, finished_at=utcnow())
                return
            try:
                raw_results = self.engine.run(
                    device_plans,
                    credential_map,
                    on_event=lambda event: self._event(job_id, event, secrets),
                    is_cancelled=lambda: self.store.is_cancelled(job_id),
                    forks=forks,
                )
                normalized = [self._safe_result(item, secrets) for item in (raw_results or [])]
                result_ids = {str(item.get("device_id")) for item in normalized}
                normalized.extend(
                    {"device_id": device["device_id"], "ip_address": device.get("ip_address"), "status": "failed", "error": "Engine returned no result for this device"}
                    for device in device_plans if device["device_id"] not in result_ids
                )
                results = existing_unsupported + normalized
            except Exception as exc:  # noqa: BLE001 -- engine boundary converts runner faults to per-device failures
                results = existing_unsupported + [
                    {"device_id": device["device_id"], "ip_address": device.get("ip_address"), "status": "failed", "error": self._safe(exc, secrets)}
                    for device in device_plans
                ]
            statuses = {str(item.get("status", "failed")) for item in results}
            if self.store.is_cancelled(job_id):
                final = "cancelled"
            elif statuses <= {"succeeded"}:
                final = "succeeded"
            elif "succeeded" in statuses or "unsupported" in statuses:
                final = "partial"
            else:
                final = "failed"
            self.store.update_job(job_id, status=final, results=results, finished_at=utcnow())
        except Exception as exc:  # noqa: BLE001 -- job boundary persists a sanitized terminal failure
            self.store.update_job(job_id, status="failed", error=self._safe(exc, secrets), finished_at=utcnow())
        finally:
            with self._lifecycle_lock:
                self._active_job_ids.discard(job_id)

    def _event(self, job_id: str, event: Any, secrets: list[str]) -> None:
        job = self.store.get_job(job_id)
        if not job:
            return
        events = list(job.get("events", []))
        if isinstance(event, dict):
            safe_event = self._safe_value(event, secrets)
            events.append(safe_event)
        else:
            safe_event = {"message": self._safe(event, secrets)}
            events.append(safe_event)
        fields: dict[str, Any] = {"events": events[-500:]}
        if isinstance(safe_event, dict) and safe_event.get("event") == "switchfleet_device_result":
            device_id = str(safe_event.get("device_id") or "")
            result = safe_event.get("result")
            if device_id and isinstance(result, dict):
                results = [item for item in job.get("results", []) if item.get("device_id") != device_id]
                results.append(result)
                fields["results"] = results
        self.store.update_job(job_id, **fields)

    def _safe_result(self, result: Any, secrets: list[str]) -> dict[str, Any]:
        if hasattr(result, "model_dump"):
            result = result.model_dump()
        elif hasattr(result, "__dict__"):
            result = vars(result)
        if not isinstance(result, dict):
            return {"status": "failed", "error": "Engine returned an invalid device result"}
        return cast(dict[str, Any], self._safe_value(result, secrets))

    def _safe_value(self, value: Any, secrets: list[str], key: str = "") -> Any:
        if isinstance(value, dict):
            return {str(k): ("<redacted>" if any(token in str(k).casefold() for token in ("password", "secret", "credential_material")) else self._safe_value(v, secrets, str(k))) for k, v in value.items()}
        if isinstance(value, list):
            return [self._safe_value(item, secrets, key) for item in value]
        if isinstance(value, str):
            return self._safe(value, secrets)
        return value

    @staticmethod
    def _safe(value: Any, secrets: list[str] | None = None) -> str:
        return mask_secrets(str(value or ""), explicit_secrets=secrets or [])
