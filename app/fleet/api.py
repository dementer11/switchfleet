"""Standalone local HTTP API for SwitchFleet."""
from __future__ import annotations

import csv
import io
import ipaddress
import json
import os
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, PlainTextResponse, Response

from app.fleet.ansible_engine import AnsibleEngine
from app.fleet.profiles import list_profiles
from app.fleet.service import FleetService
from app.fleet.store import FleetStore
from app.services.excel_inventory import load_excel_inventory
from app.utils.masking import mask_secrets

WEB_ROOT = Path(__file__).resolve().parent / "web"
MAX_INVENTORY_BYTES = 20 * 1024 * 1024
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "testserver"}
_FAMILY_BY_HINT = {
    "ios": "cisco_ios", "ciscoiosdriver": "cisco_ios", "vrp": "huawei_vrp", "huaweivrpdriver": "huawei_vrp",
    "comware": "hpe_comware", "hpcomwaredriver": "hpe_comware", "procurve": "hpe_procurve", "hpeprocurvedriver": "hpe_procurve",
    "dell": "dell_os", "dellpowerconnectdriver": "dell_os", "bulat": "bulat", "bulatbsdriver": "bulat",
    "qtech": "qtech", "qtechqswdriver": "qtech", "mes": "eltex", "eltexmesdriver": "eltex",
    "generic": "generic_ssh", "genericsshdriver": "generic_ssh", "icmp": "icmp", "limited_web": "limited_web", "non_switch": "non_switch",
}
_FAMILY_BY_HINT.update({row["family"]: row["family"] for row in list_profiles()})


def create_fleet_app(state_dir: Path | None = None, engine: Any | None = None) -> FastAPI:
    default_dir = os.environ.get("SWITCHFLEET_DATA_DIR") or str(Path.home() / ".switchfleet")
    store = FleetStore(state_dir or Path(default_dir))
    service = FleetService(store, engine or AnsibleEngine())

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            service.shutdown()
            store.close()

    app = FastAPI(title="SwitchFleet Fleet API", version="0.4.0", lifespan=lifespan)
    app.state.fleet_service = service

    configured_origins = [item.strip() for item in os.environ.get("SWITCHFLEET_ALLOWED_ORIGINS", "").split(",") if item.strip()]
    if configured_origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=configured_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
            allow_headers=["Content-Type"],
        )

    @app.middleware("http")
    async def protect_local_writes(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            allowed = set(configured_origins)
            host = request.headers.get("host", "").strip().casefold()
            parsed_host = urlsplit(f"//{host}").hostname
            origin = request.headers.get("origin")
            if parsed_host not in _LOCAL_HOSTS and origin not in allowed:
                return PlainTextResponse("Local requests only", status_code=403)
            if origin:
                parsed_origin = urlsplit(origin)
                origin_host = (parsed_origin.hostname or "").casefold()
                request_url = urlsplit(str(request.base_url))
                origin_port = parsed_origin.port or (443 if parsed_origin.scheme == "https" else 80)
                request_port = request_url.port or (443 if request_url.scheme == "https" else 80)
                local_origin = (
                    parsed_origin.scheme in {"http", "https"}
                    and origin_host in _LOCAL_HOSTS
                    and origin_host == (request_url.hostname or "").casefold()
                    and parsed_origin.scheme == request_url.scheme
                    and origin_port == request_port
                )
                if origin not in allowed and not local_origin:
                    return PlainTextResponse("Origin is not allowed", status_code=403)
        return await call_next(request)

    @app.exception_handler(Exception)
    async def safe_error_handler(_request: Request, exc: Exception) -> PlainTextResponse:
        # Avoid serializing exception strings from network/engine failures: those
        # can contain credentials. Known validation errors are handled locally.
        return PlainTextResponse(mask_secrets(type(exc).__name__), status_code=500)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, _exc: RequestValidationError) -> PlainTextResponse:
        return PlainTextResponse("Invalid request", status_code=422)

    @app.get("/api/fleet/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "engine": service.engine_status(), "device_count": len(store.list_devices())}

    @app.get("/api/fleet/inventory")
    def get_inventory() -> dict[str, Any]:
        inventory = store.get_inventory()
        if inventory is None:
            return {"devices": [], "summary": {"device_count": 0, "vendors": {}, "families": {}}}
        return inventory

    @app.post("/api/fleet/inventory")
    async def upload_inventory(request: Request, filename: str = "inventory.xlsx") -> dict[str, Any]:
        if len(filename) > 255 or Path(filename).suffix.casefold() not in {".xlsx", ".csv", ".json"}:
            raise HTTPException(status_code=400, detail="filename extension must be .xlsx, .csv or .json")
        content = await request.body()
        if not content:
            raise HTTPException(status_code=400, detail="Inventory upload is empty")
        if len(content) > MAX_INVENTORY_BYTES:
            raise HTTPException(status_code=413, detail="Inventory upload exceeds 20 MiB")
        suffix = Path(filename).suffix.casefold()
        target = store.root / f"inventory-{uuid.uuid4().hex}{suffix}"
        target.write_bytes(content)
        try:
            target.chmod(0o600)
        except OSError:
            pass
        try:
            devices = _parse_inventory(target, suffix)
        except (ValueError, TypeError, UnicodeDecodeError) as exc:
            target.unlink(missing_ok=True)
            detail = str(exc) if isinstance(exc, (ValueError, UnicodeDecodeError)) else "Unable to parse inventory"
            raise HTTPException(status_code=400, detail=mask_secrets(detail)) from exc
        inventory = _inventory_response(devices)
        store.save_inventory(inventory)
        for old in store.root.glob("inventory-*.*"):
            if old != target:
                old.unlink(missing_ok=True)
        return inventory

    @app.get("/api/fleet/profiles")
    def profiles() -> dict[str, Any]:
        return {"profiles": list_profiles()}

    @app.patch("/api/fleet/devices/{device_id}")
    def update_device(device_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict) or not payload or set(payload) - {"family", "port", "credential_ref"}:
            raise HTTPException(status_code=400, detail="Only family, port and credential_ref may be changed")
        fields: dict[str, Any] = {}
        if "family" in payload:
            family = payload["family"]
            if family not in {row["family"] for row in list_profiles()} | {"unknown", "icmp", "limited_web", "non_switch"}:
                raise HTTPException(status_code=400, detail="Unknown device family")
            fields["family"] = family
        if "port" in payload:
            port = payload["port"]
            if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
                raise HTTPException(status_code=400, detail="port must be in range 1..65535")
            fields["port"] = port
        if "credential_ref" in payload:
            ref = payload["credential_ref"]
            if ref is not None and (not isinstance(ref, str) or not store.credential(ref)):
                raise HTTPException(status_code=400, detail="Credential was not found")
            fields["credential_ref"] = ref
        device = store.update_device(device_id, fields)
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")
        return device

    @app.get("/api/fleet/credentials")
    def credentials() -> dict[str, Any]:
        return {"credentials": store.list_credentials()}

    @app.post("/api/fleet/credentials")
    def create_credential(payload: dict[str, Any]) -> dict[str, Any]:
        name, username, password = payload.get("name"), payload.get("username"), payload.get("password")
        if not all(isinstance(item, str) and item.strip() for item in (name, username, password)):
            raise HTTPException(status_code=400, detail="name, username and password are required")
        enable_password = cast(str | None, payload.get("enable_password"))
        if enable_password is not None and not isinstance(enable_password, str):
            raise HTTPException(status_code=400, detail="enable_password must be a string")
        if len(enable_password or "") > 4096 or len(cast(str, password)) > 4096:
            raise HTTPException(status_code=400, detail="Credential value is too long")
        return store.put_credential(
            name=cast(str, name).strip(),
            username=cast(str, username).strip(),
            password=cast(str, password),
            enable_password=enable_password,
        )

    @app.post("/api/fleet/plans")
    def create_plan(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return service.create_plan(payload)
        except (ValueError, TypeError) as exc:
            parameters = payload.get("parameters")
            secret = parameters.get("new_password", "") if isinstance(parameters, dict) else ""
            secrets = [secret] if isinstance(secret, str) and secret else []
            raise HTTPException(status_code=400, detail=mask_secrets(str(exc), explicit_secrets=secrets)) from exc

    @app.post("/api/fleet/jobs")
    def create_job(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return service.enqueue(payload)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=mask_secrets(str(exc))) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=mask_secrets(str(exc))) from exc

    @app.get("/api/fleet/jobs")
    def list_jobs() -> dict[str, Any]:
        return {"jobs": [_job_summary(job) for job in store.list_jobs()]}

    @app.get("/api/fleet/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return job

    @app.post("/api/fleet/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict[str, Any]:
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if job["status"] not in {"queued", "running"}:
            raise HTTPException(status_code=409, detail="Job is already finished")
        updated = store.update_job(job_id, cancel_requested=True)
        return _job_summary(updated or job)

    @app.get("/api/fleet/jobs/{job_id}/backups/{device_id}")
    def download_backup(job_id: str, device_id: str) -> PlainTextResponse:
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        result = next((item for item in job.get("results", []) if item.get("device_id") == device_id), None)
        if not isinstance(result, dict):
            raise HTTPException(status_code=404, detail="Backup not found for this device")
        backup = result.get("backup_text")
        if not isinstance(backup, str) or not backup:
            raise HTTPException(status_code=404, detail="Backup not found for this device")
        safe_device = re.sub(r"[^A-Za-z0-9._-]+", "_", str(result.get("ip_address") or device_id)).strip("._-") or "device"
        return PlainTextResponse(backup, headers={"Content-Disposition": f'attachment; filename="switchfleet-backup-{safe_device}.txt"'})

    @app.get("/api/fleet/audit")
    def audit() -> dict[str, Any]:
        return {"events": store.audit_tail(200)}

    if WEB_ROOT.is_dir():
        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(WEB_ROOT / "index.html")

        @app.get("/assets/{asset_path:path}", include_in_schema=False)
        def asset(asset_path: str) -> FileResponse:
            root = (WEB_ROOT / "static").resolve()
            path = (root / asset_path).resolve()
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise HTTPException(status_code=404, detail="Asset not found") from exc
            if not path.is_file():
                raise HTTPException(status_code=404, detail="Asset not found")
            return FileResponse(path)

    return app


def _parse_inventory(path: Path, suffix: str) -> list[dict[str, Any]]:
    if suffix == ".xlsx":
        from dataclasses import asdict

        rows = [asdict(item) for item in load_excel_inventory(path)]
    elif suffix == ".json":
        loaded = json.loads(path.read_text(encoding="utf-8"))
        rows = loaded.get("devices", []) if isinstance(loaded, dict) else loaded
        if not isinstance(rows, list):
            raise ValueError("JSON inventory must be an array or an object with a devices array")
    else:
        rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig"))))
    result: list[dict[str, Any]] = []
    seen_ips: set[str] = set()
    seen_ids: set[str] = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise TypeError(f"Inventory row {index} must be an object")
        original_ip = row.get("ip_address") or row.get("IP Address") or row.get("ip")
        try:
            ip_address = str(ipaddress.ip_address(str(original_ip).strip()))
        except ValueError as exc:
            raise ValueError(f"Inventory row {index} has an invalid IP address") from exc
        if ip_address in seen_ips:
            raise ValueError(f"Duplicate IP address {ip_address}")
        seen_ips.add(ip_address)
        vendor = str(row.get("vendor") or row.get("Vendor") or "Unknown").strip()
        model = str(row.get("model") or row.get("Model") or "Unknown").strip()
        original_vendor = str(row.get("original_vendor") or vendor)
        original_model = str(row.get("original_model") or model)
        identifier = str(row.get("id") or uuid.uuid5(uuid.NAMESPACE_URL, f"switchfleet:{ip_address}").hex)
        if identifier in seen_ids:
            raise ValueError(f"Duplicate device ID {identifier}")
        seen_ids.add(identifier)
        raw_hint = row.get("family") or row.get("platform") or row.get("driver_name")
        if not raw_hint:
            from app.services.excel_inventory import infer_runtime_hints

            inferred_driver, inferred_platform = infer_runtime_hints(vendor, model, str(row.get("category") or row.get("Device Category") or ""))
            raw_hint = inferred_platform or inferred_driver
        hint = str(raw_hint or "").casefold()
        family = _FAMILY_BY_HINT.get(hint, "unknown")
        port = row.get("port", 22)
        try:
            port = int(port or 22)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Inventory row {index} has an invalid port") from exc
        if not 1 <= port <= 65535:
            raise ValueError(f"Inventory row {index} has an invalid port")
        result.append({
            "id": identifier,
            "label": str(row.get("label") or row.get("Device Label") or row.get("hostname") or ip_address).strip(),
            "ip_address": ip_address,
            "vendor": vendor,
            "model": model,
            "original_model": original_model,
            "original_vendor": original_vendor,
            "family": family,
            "status": row.get("status") or row.get("Status") or "unknown",
            "category": row.get("category") or row.get("Device Category"),
            "port": port,
            "credential_ref": row.get("credential_ref"),
        })
    return result


def _inventory_response(devices: list[dict[str, Any]]) -> dict[str, Any]:
    vendors: dict[str, int] = {}
    families: dict[str, int] = {}
    for device in devices:
        vendors[device["vendor"]] = vendors.get(device["vendor"], 0) + 1
        families[device["family"]] = families.get(device["family"], 0) + 1
    return {"devices": devices, "summary": {"device_count": len(devices), "vendors": vendors, "families": families}}


def _job_summary(job: dict[str, Any]) -> dict[str, Any]:
    results = job.get("results", [])
    return {
        "id": job.get("id"),
        "plan_id": job.get("plan_id"),
        "operation": job.get("operation"),
        "status": job.get("status"),
        "device_count": job.get("device_count", len(results)),
        "success_count": sum(item.get("status") == "succeeded" for item in results),
        "failure_count": sum(item.get("status") in {"failed", "unsupported"} for item in results),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "started_at": job.get("started_at"),
        "cancel_requested_at": job.get("cancel_requested_at"),
        "finished_at": job.get("finished_at"),
        "error": job.get("error"),
    }


app = create_fleet_app()
