from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.core.exceptions import ApprovalRequiredError


class Role(str, Enum):
    viewer = "viewer"
    network_operator = "network_operator"
    operator = "operator"
    network_admin = "network_admin"
    security_admin = "security_admin"
    auditor = "auditor"
    admin = "admin"
    super_admin = "super_admin"


class Permission(str, Enum):
    read_devices = "read_devices"
    read_jobs = "read_jobs"
    read_backups = "read_backups"
    read_audit = "read_audit"
    run_job = "run_job"
    change_vlan = "change_vlan"
    change_port = "change_port"
    change_acl = "change_acl"
    change_password = "change_password"
    manage_credentials = "manage_credentials"
    approve_job = "approve_job"
    run_approved_job = "run_approved_job"
    cancel_job = "cancel_job"
    read_lab_validations = "read_lab_validations"
    manage_lab_validations = "manage_lab_validations"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.viewer: frozenset({Permission.read_devices, Permission.read_jobs, Permission.read_backups}),
    Role.network_operator: frozenset(
        {Permission.read_devices, Permission.read_jobs, Permission.run_job, Permission.read_lab_validations}
    ),
    Role.operator: frozenset({Permission.read_devices, Permission.read_jobs, Permission.run_job}),
    Role.network_admin: frozenset(
        {
            Permission.read_devices,
            Permission.read_jobs,
            Permission.read_backups,
            Permission.run_job,
            Permission.change_vlan,
            Permission.change_port,
            Permission.approve_job,
            Permission.cancel_job,
            Permission.run_approved_job,
        }
    ),
    Role.security_admin: frozenset(
        {
            Permission.read_devices,
            Permission.read_jobs,
            Permission.run_job,
            Permission.change_acl,
            Permission.change_password,
            Permission.manage_credentials,
            Permission.read_lab_validations,
            Permission.manage_lab_validations,
            Permission.approve_job,
            Permission.cancel_job,
        }
    ),
    Role.auditor: frozenset({Permission.read_devices, Permission.read_jobs, Permission.read_backups, Permission.read_audit}),
    Role.admin: frozenset(set(Permission)),
    Role.super_admin: frozenset(set(Permission)),
}


@dataclass(frozen=True)
class Actor:
    username: str
    roles: frozenset[Role]

    @property
    def permissions(self) -> frozenset[Permission]:
        combined: set[Permission] = set()
        for role in self.roles:
            combined.update(ROLE_PERMISSIONS[role])
        return frozenset(combined)


def require_permission(actor: Actor, permission: Permission) -> None:
    if permission not in actor.permissions:
        raise ApprovalRequiredError(f"Actor {actor.username!r} does not have permission {permission.value!r}")
