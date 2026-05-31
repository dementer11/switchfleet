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
    read_inventory = "read_inventory"
    manage_inventory = "manage_inventory"
    run_discovery = "run_discovery"
    read_config_backups = "read_config_backups"
    manage_config_backups = "manage_config_backups"
    run_config_backup = "run_config_backup"
    manage_restore_plans = "manage_restore_plans"
    approve_restore_plans = "approve_restore_plans"
    read_vlan_workflows = "read_vlan_workflows"
    manage_vlan_workflows = "manage_vlan_workflows"
    plan_vlan_workflows = "plan_vlan_workflows"
    approve_vlan_workflows = "approve_vlan_workflows"
    read_change_executions = "read_change_executions"
    manage_change_executions = "manage_change_executions"
    plan_change_executions = "plan_change_executions"
    approve_change_executions = "approve_change_executions"
    simulate_change_executions = "simulate_change_executions"
    cancel_change_executions = "cancel_change_executions"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.viewer: frozenset(
        {
            Permission.read_devices,
            Permission.read_jobs,
            Permission.read_backups,
            Permission.read_inventory,
            Permission.read_config_backups,
            Permission.read_vlan_workflows,
            Permission.read_change_executions,
        }
    ),
    Role.network_operator: frozenset(
        {
            Permission.read_devices,
            Permission.read_jobs,
            Permission.run_job,
            Permission.read_lab_validations,
            Permission.read_inventory,
            Permission.run_discovery,
            Permission.read_config_backups,
            Permission.run_config_backup,
            Permission.read_vlan_workflows,
            Permission.plan_vlan_workflows,
            Permission.read_change_executions,
            Permission.plan_change_executions,
            Permission.simulate_change_executions,
        }
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
            Permission.read_inventory,
            Permission.manage_inventory,
            Permission.run_discovery,
            Permission.read_config_backups,
            Permission.manage_config_backups,
            Permission.run_config_backup,
            Permission.manage_restore_plans,
            Permission.read_vlan_workflows,
            Permission.manage_vlan_workflows,
            Permission.plan_vlan_workflows,
            Permission.read_change_executions,
            Permission.manage_change_executions,
            Permission.plan_change_executions,
            Permission.simulate_change_executions,
            Permission.cancel_change_executions,
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
            Permission.read_inventory,
            Permission.manage_inventory,
            Permission.run_discovery,
            Permission.read_config_backups,
            Permission.approve_restore_plans,
            Permission.read_vlan_workflows,
            Permission.approve_vlan_workflows,
            Permission.read_change_executions,
            Permission.approve_change_executions,
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
