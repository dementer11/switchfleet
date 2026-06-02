# Transport Strategy And Driver Runtime

This stage adds a vendor-aware transport strategy and driver runtime decision layer. It does not enable real device apply, does not open SSH sessions from the API, and does not execute commands on devices.

## Purpose

The runtime avoids a one-size-fits-all transport wrapper:

- Netmiko is preferred where the vendor family has mature device profiles, such as Cisco IOS/NX-OS/ASA, Huawei VRP, HPE Comware, HPE ProCurve/ArubaOS-Switch, and Dell PowerConnect.
- Paramiko is used where direct SSH/session control is safer than assuming a Netmiko profile, such as Generic SSH and fallback paths.
- `custom_cli` is used for nonstandard vendor CLI behavior, especially Eltex and Bulat until templates are certified.
- `icmp_only` is health/readiness only and cannot run configuration operations.
- `unsupported` fails closed for unknown vendor/model/platform combinations.

## API

All endpoints are GET-only under `/api/v1/driver-runtime`:

- `GET /profiles`
- `GET /profiles/{family}`
- `GET /decision?vendor=...&model=...&platform=...`
- `GET /devices/{device_id}/decision`
- `GET /summary`
- `GET /safety`

There is no `/apply`, no `/run`, no POST, no PUT, no PATCH, and no DELETE endpoint in this router.

## Capability Matrix

Runtime decisions include:

- selected transport;
- fallback transport;
- driver name;
- device family;
- capabilities;
- read-only allowance;
- safety warnings;
- unsupported reason when the device fails closed.

`config_apply_allowed` is always `false` in this stage. `real_apply_certified` is always `false` in this stage, even for profiles that can model config staging.

## Vendor Strategy

Cisco IOS, Cisco NX-OS, Cisco ASA, Huawei VRP, HPE Comware, HPE ProCurve, ArubaOS-Switch, and Dell PowerConnect prefer Netmiko with safer fallbacks where appropriate.

Eltex and Bulat prefer `custom_cli` with Paramiko fallback. Destructive apply is blocked until confirmed templates and lab certification exist.

Generic SSH is read-only/dry-run only. ICMP is health-only. Unknown devices are unsupported.

## Runtime Contracts

The runtime defines safe session contracts for future work:

- `connect`
- `close`
- `detect_prompt`
- `run_show`
- `enter_privileged_mode`
- `enter_config_mode`
- `stage_config`
- `commit_or_save`
- `rollback_prepare`
- `get_capabilities`

Config-changing methods raise controlled safety exceptions. The API does not call `connect`, does not open real transports, and does not execute read-only commands.

## RBAC

The `read_driver_runtime` permission allows read-only access to runtime decision endpoints.

Roles with this permission:

- `viewer`
- `network_operator`
- `network_admin`
- `security_admin`
- `admin`
- `super_admin`

`read_driver_runtime` does not grant manage, approve, simulate, cancel, run, backup, validate, session-open, or apply permissions.

## Path Toward Real Apply

The intended sequence remains:

1. transport strategy;
2. secrets hardening;
3. apply safety kernel;
4. lab-only real apply;
5. production apply readiness.

This stage implements step 1 only.
