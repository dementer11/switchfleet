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

## Legacy CLI Safety Alignment

The legacy CLI under `src/netops_orchestrator` remains file-driven and does not depend on the enterprise database, but its runtime decision boundary now aligns with the capability matrix.

The compatibility bridge:

- resolves legacy `Device` and `CommandPlan` objects through `DriverCapabilityMatrix`;
- keeps Huawei Unknown Product and Unknown SNMP Product fail-closed as `unsupported`;
- keeps ICMP devices health-only with no CLI transport;
- keeps Generic SSH read-only/dry-run only;
- keeps Eltex and Bulat on `custom_cli`/Paramiko strategy while blocking config apply;
- exposes safe explanations for runtime decisions without secrets or network calls.

Legacy driver registry alignment:

- known Cisco, Huawei VRP, HPE Comware, HPE ProCurve/ArubaOS-Switch, Dell, Eltex, and Bulat devices map to the same runtime family as the capability matrix;
- unknown, ICMP-only, and Generic SSH devices return `UnsupportedDriver` for CLI config planning;
- legacy QTECH planning is preserved as a compatibility path, but config execution is still blocked at the transport boundary because it is not a certified matrix profile.

Legacy transport factory alignment:

- `auto` follows the runtime decision;
- Netmiko is used only when the runtime decision selected Netmiko and a legacy `netmiko_device_type` exists;
- Paramiko may be used for explicit Paramiko decisions or read-only fallback paths;
- `custom_cli` profiles without a safe legacy read-only fallback fail closed;
- `icmp_only` and `unsupported` never create SSH transports;
- preference flags such as `--transport netmiko` or `--transport paramiko` cannot bypass unsupported, ICMP, Generic SSH, Eltex, Bulat, or unknown safety.

Legacy CLI apply remains disabled:

- `netops apply` without `--dry-run` exits with a controlled safety error before credentials are requested and before any transport is created;
- `netops apply --dry-run` still renders plans;
- `plan-password`, `plan-acl`, `plan-vlan`, `plan-port`, and `plan-backup` still render command plans;
- pre/post backups inside `apply` do not run because the apply path is blocked first;
- setting `NCP_LEGACY_CLI_REAL_APPLY=true` or `NCP_ALLOW_REAL_DEVICE_APPLY=true` does not enable legacy real apply in this stage.

Legacy backup remains read-only:

- backup plans must pass the runtime decision before a transport is created;
- backup commands must remain read-only and must not include config/save phases;
- unsupported and ICMP-only devices skip or fail safely without creating SSH transports;
- no Netmiko `ConnectHandler`, Paramiko `SSHClient`, or Scrapli session is opened by tests.

Real apply is still postponed until the Apply Safety Kernel and lab-only real apply stages.
