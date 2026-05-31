# VLAN Workflow Hardening

VLAN Workflow Hardening is an enterprise preparation workflow for VLAN changes.

It validates intent, checks device readiness, builds impact previews, generates dry-run commands, prepares rollback text, records approval state, and writes a VLAN-specific audit trail. It does not apply VLAN changes to devices.

## Scope

Supported operations:

- `create_vlan`
- `rename_vlan`
- `delete_vlan`
- `assign_access_vlan`
- `remove_access_vlan`
- `add_trunk_vlan`
- `remove_trunk_vlan`

Supported scopes:

- `device_ids`
- `site`
- `tag`
- `query`

Interface operations require `scope_filter.interface`. The workflow never invents ports.

## Validation

Validation checks:

- VLAN ID is in `1..4094`;
- VLAN 1 and legacy VLANs `1002..1005` are blocked;
- VLAN name is limited to letters, numbers, `_`, and `-`;
- target devices have a supported driver and VLAN capability metadata;
- Generic SSH and ICMP-only devices are blocked;
- Bulat and Eltex remain blocked unless explicit destructive capability metadata is already present;
- a fresh config snapshot exists, default freshness window is 24 hours;
- matching approved lab validation exists for the VLAN capability.

Validation is per-device. One blocked device does not prevent the other devices from being evaluated.

## Backup Requirement

The workflow requires an existing fresh sanitized config snapshot. It does not collect a backup as part of VLAN validation unless a caller uses the separate Config Backup workflow first.

The snapshot source is `config_snapshots`; raw unsanitized config is not used.

## Lab Validation Requirement

The workflow uses the Lab Validation Framework and requires an approved, non-expired validation matching:

- vendor;
- model pattern;
- driver;
- capability.

Accepted capabilities are the exact operation, `vlan_management`, or `vlan_change`.

## Impact Preview

Impact preview reads the latest sanitized config snapshot and estimates:

- whether the VLAN already exists;
- access ports potentially using the VLAN;
- trunk ports potentially allowing the VLAN;
- risk level;
- warnings and blockers.

Risk levels:

- `low`: create VLAN with no affected ports detected;
- `medium`: rename VLAN or low-impact detected changes;
- `high`: trunk changes or VLAN delete without active access ports;
- `critical`: delete/remove access VLAN when access ports are detected.

Impact parsing is best-effort and does not connect to devices.

## Dry-Run Plan

Plan generation returns command strings only. Commands are never sent to devices.

Dry-run renderers cover:

- Huawei VRP;
- Cisco IOS;
- HP Comware;
- HPE ProCurve;
- Dell PowerConnect.

Unsupported vendors are marked unsupported or blocked with no commands generated.

## Rollback Plan

Rollback plans are dry-run text only:

- `create_vlan` -> delete VLAN;
- `rename_vlan` -> restore detected previous name;
- `delete_vlan` -> recreate VLAN and detected name;
- `assign_access_vlan` -> restore detected previous access VLAN;
- `remove_access_vlan` -> restore detected access VLAN;
- trunk add/remove -> inverse trunk command.

If the snapshot cannot support a safe rollback preview, the device remains blocked before approval.

## Approval And Audit

Workflow states:

`draft -> validated -> pending_approval -> approved -> ready`

Blocked requests move to `blocked`. Cancelled requests move to `cancelled`.

Every state change writes a VLAN audit event. Ready means preparation is complete; it is not permission to execute against devices.

## API

Base path: `/api/v1/vlan-workflows`

Endpoints:

- `POST /requests`
- `GET /requests`
- `GET /requests/{request_id}`
- `POST /requests/{request_id}/validate`
- `GET /requests/{request_id}/validation-report`
- `POST /requests/{request_id}/preview`
- `GET /requests/{request_id}/impact-preview`
- `POST /requests/{request_id}/plan`
- `GET /requests/{request_id}/plan`
- `GET /requests/{request_id}/rollback-plan`
- `POST /requests/{request_id}/submit`
- `POST /requests/{request_id}/approve`
- `POST /requests/{request_id}/reject`
- `POST /requests/{request_id}/cancel`
- `GET /requests/{request_id}/audit`
- `GET /requests/{request_id}/report`

There is no `/apply` endpoint and no `/run` endpoint.

## RBAC

- `viewer` and `network_operator`: read VLAN workflow records;
- `network_operator`, `network_admin`, `admin`, `super_admin`: plan VLAN workflows;
- `network_admin`, `admin`, `super_admin`: manage VLAN workflows;
- `security_admin`, `admin`, `super_admin`: approve VLAN workflows.

No role can apply VLAN changes because no apply endpoint exists.

## Safety

This workflow does not enable real device apply, open transports, call `send_config`, call `save_config`, run `write memory`, enter `configure terminal` on a device, call `commit`, run `copy running-config startup-config`, or change password/VLAN/ACL/port state.

Future real apply must remain gated by dry-run, approval, fresh backup, lab validation, verification, locks, audit, and the `NCP_ALLOW_REAL_DEVICE_APPLY=false` default safety gate.
