# Driver & Real Apply Readiness Consolidation

This stage prepares the driver/transport/apply contour for controlled lab-only real apply. It does not enable production apply.

## Scope

Implemented capabilities:

- vendor driver execution contracts;
- explicit vendor command templates;
- credential vault metadata API and encrypted-at-rest payload storage;
- Apply Safety Kernel;
- lab-only apply evaluation and execution API;
- fake lab transport for end-to-end tests;
- transport factory boundary for future Netmiko, Paramiko, and custom CLI lab execution.

## Vendor Contracts

Contracts define supported operations, forbidden operations, read-only commands, config templates, save/commit behavior, rollback strategy, prompt/error patterns, and certification state.

Production certification is false for every contract in this stage.

Lab apply candidates:

- Cisco IOS;
- Cisco NX-OS;
- Huawei VRP;
- HPE Comware;
- HPE ProCurve / ArubaOS-Switch;
- Dell PowerConnect.

Fail-closed or read-only:

- Cisco ASA remains dry-run/read-only until explicit templates are certified;
- Eltex and Bulat are read-only only until explicit custom CLI templates are certified;
- GenericSSH is read-only/dry-run only;
- ICMP is health-only;
- Unknown is unsupported.

## Command Templates

Templates are explicit per family and operation. Secret-bearing rendered commands are marked as secret internally and are redacted in API responses, audit, logs, and reports.

Supported templates include Cisco IOS, Huawei VRP, HPE Comware, HPE ProCurve/ArubaOS-Switch, and Dell PowerConnect where syntax is sufficiently explicit. Eltex and Bulat destructive templates are intentionally not invented.

## Credential Vault

Credential vault endpoints are available under `/api/v1/credential-vault`.

The vault:

- requires `NCP_SECRET_KEY` for secret storage and decryption;
- stores encrypted payload only;
- returns metadata only;
- never returns plaintext secret material;
- supports create, metadata update, rotation, disable, list, and usability checks;
- writes sanitized audit events without secret values.

RBAC:

- `read_credential_metadata`;
- `manage_credential_secrets`;
- `use_credential_secrets`.

## Apply Safety Kernel

The Apply Safety Kernel is the central gate for any real device command send.

Required gates:

- `execution_mode=lab_apply`;
- `NCP_ALLOW_REAL_DEVICE_APPLY=true`;
- `NCP_LAB_REAL_APPLY_ENABLED=true`;
- `NCP_PRODUCTION_REAL_APPLY_ENABLED=false`;
- device explicitly tagged as lab;
- device included in `NCP_LAB_DEVICE_ALLOWLIST`;
- vendor contract lab candidate/certified;
- runtime decision is not unsupported, ICMP, GenericSSH, or unsafe custom profile;
- credential reference exists and is usable;
- sanitized config backup exists;
- matching approved lab validation exists;
- approval metadata is approved;
- dry-run/simulation hash matches the current sanitized command plan;
- command plan matches vendor template and has no forbidden commands;
- rollback preview exists for config operations;
- per-device lock is reserved;
- actor has `execute_lab_apply`.

Every denial returns structured reasons and denied gates.

## Lab Apply API

Endpoints:

- `POST /api/v1/lab-apply/evaluate`
- `POST /api/v1/lab-apply/execute`

There is no production apply endpoint, no generic `/apply`, and no destructive `/run`.

`/evaluate` never creates a transport and never decrypts credentials.

`/execute` denies before credential decrypt and before transport creation unless every safety gate passes. By default it uses `FakeLabTransport`, which records intended redacted commands for test and lab dry-runs. Future real lab transport integration remains behind the same safety kernel and environment gates.

## Environment Defaults

Safe defaults:

```text
NCP_ALLOW_REAL_DEVICE_APPLY=false
NCP_LAB_REAL_APPLY_ENABLED=false
NCP_PRODUCTION_REAL_APPLY_ENABLED=false
NCP_LAB_DEVICE_ALLOWLIST=
NCP_SECRET_KEY=
```

With defaults, no real apply is possible.

## Production Apply

Production apply remains disabled. `production_apply` is denied even if lab flags are enabled.

## Testing Model

Unit and integration tests use fake transports. They do not open Netmiko, Paramiko, Scrapli, or raw SSH sessions. They prove denied requests stop before transport creation and that successful lab-only fake execution redacts secrets.

