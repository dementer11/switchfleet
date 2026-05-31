from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    audit,
    backups,
    change_executions,
    config_backups,
    credentials,
    devices,
    health,
    inventory,
    jobs,
    lab_validations,
    vlan_workflows,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router, tags=["system"])
api_router.include_router(devices.router, prefix="/devices", tags=["devices"])
api_router.include_router(credentials.router, prefix="/credentials", tags=["credentials"])
api_router.include_router(backups.router, tags=["backups"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(lab_validations.router, prefix="/lab-validations", tags=["lab-validations"])
api_router.include_router(inventory.router, prefix="/inventory", tags=["inventory"])
api_router.include_router(config_backups.router, prefix="/config-backups", tags=["config-backups"])
api_router.include_router(vlan_workflows.router, prefix="/vlan-workflows", tags=["vlan-workflows"])
api_router.include_router(change_executions.router, prefix="/change-executions", tags=["change-executions"])
api_router.include_router(audit.router, prefix="/audit", tags=["audit"])
