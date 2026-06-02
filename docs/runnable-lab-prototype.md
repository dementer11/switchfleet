# Runnable Lab Prototype

This stage turns the existing backend into a runnable lab prototype for 3-4 real lab devices. It does not add a frontend, does not enable production apply, does not add a generic `/apply`, and does not add a destructive `/run`.

## Environment

Set safe lab-only environment variables before using real lab execution:

```powershell
$env:NCP_SECRET_KEY = "replace-with-long-random-lab-secret"
$env:NCP_ALLOW_REAL_DEVICE_APPLY = "true"
$env:NCP_LAB_REAL_APPLY_ENABLED = "true"
$env:NCP_PRODUCTION_REAL_APPLY_ENABLED = "false"
$env:NCP_LAB_DEVICE_ALLOWLIST = "sw1-lab,192.168.88.11"
```

Defaults remain safe/off. Without these flags the safety kernel denies lab apply.

## Start Backend And DB

Run migrations before using the prototype:

```powershell
alembic upgrade head
```

For local API testing:

```powershell
uvicorn app.main:app --reload
```

## Prototype CLI

The helper script is:

```powershell
python scripts/lab_prototype.py <command>
```

It prints JSON and writes through the existing SQLAlchemy models/services. Operators do not need to write SQL.

## Bootstrap

```powershell
python scripts/lab_prototype.py bootstrap-admin
```

The command prints the actor/role headers used by local prototype calls and the required lab env vars.

## Import Devices

```powershell
python scripts/lab_prototype.py import-devices examples/lab/devices.example.yaml
python scripts/lab_prototype.py list-devices
```

Devices are tagged with `lab=true` and `environment=lab`. The import does not grant apply permission automatically.

## Credential Ref

```powershell
python scripts/lab_prototype.py add-credential --name lab-admin --username admin --password-prompt
```

`NCP_SECRET_KEY` must be set. The password is read interactively, stored encrypted, and never printed.

## Runtime Decision

```powershell
python scripts/lab_prototype.py check-runtime --device sw1-lab
```

The output includes family, selected transport, driver, warnings, `config_apply_allowed`, `real_apply_certified`, and lab apply support level. Unknown, ICMP, GenericSSH, Eltex, and Bulat explain why config apply is blocked.

## Backup

```powershell
python scripts/lab_prototype.py backup --device sw1-lab --credential lab-admin
```

Backup requires a lab-tagged allowlisted device and credential ref. It uses vendor read-only commands, sanitizes output, stores a `ConfigSnapshot`, and writes audit. ICMP and Unknown are denied.

## Dry Run

```powershell
python scripts/lab_prototype.py dry-run --device sw1-lab --operation vlan_create --vlan-id 123 --name TEST_VLAN
python scripts/lab_prototype.py dry-run --device sw1-lab --operation password_change --username admin --new-password-prompt --level 15
```

Dry-run does not open SSH. It renders vendor templates, redacts secret commands, validates inputs, and prints the command hash.

## Evaluate

```powershell
python scripts/lab_prototype.py evaluate-apply `
  --device sw1-lab `
  --credential lab-admin `
  --operation vlan_create `
  --vlan-id 123 `
  --name TEST_VLAN `
  --backup-snapshot <snapshot-id> `
  --lab-validation <validation-id> `
  --approval approved `
  --simulation-hash <hash> `
  --lock
```

For prototype-only convenience:

```powershell
python scripts/lab_prototype.py evaluate-apply --device sw1-lab --credential lab-admin --operation vlan_create --vlan-id 123 --name TEST_VLAN --prototype-auto-gates
```

`--prototype-auto-gates` creates real lab validation and lock records and uses the latest sanitized backup snapshot. It does not bypass the safety kernel.

## Execute

Fake execution remains the default:

```powershell
python scripts/lab_prototype.py execute-apply --device sw1-lab --credential lab-admin --operation vlan_create --vlan-id 123 --name TEST_VLAN --prototype-auto-gates
```

Real lab execution requires an explicit flag:

```powershell
python scripts/lab_prototype.py execute-apply --device sw1-lab --credential lab-admin --operation vlan_create --vlan-id 123 --name TEST_VLAN --prototype-auto-gates --simulation-hash <hash-from-dry-run> --real-lab
```

The command decrypts the credential and creates Netmiko/Paramiko transport only after the safety kernel allows the request.
Real lab execution requires an explicit simulation hash copied from a prior dry-run so a fresh render cannot silently replace the reviewed plan.

## Audit

```powershell
python scripts/lab_prototype.py audit-tail --limit 20
```

Audit payloads are sanitized and do not include plaintext secrets.

## Troubleshooting

- `NCP_SECRET_KEY is required`: set a lab-only secret key.
- `Device is not in NCP_LAB_DEVICE_ALLOWLIST`: add the device id, hostname, or management IP.
- `Unknown devices cannot run lab backup`: fix inventory vendor/model/platform.
- `Simulation/dry-run hash must match`: rerun dry-run and use the latest hash.
- `A sanitized config snapshot is required`: run `lab backup` first.
- `An approved matching lab validation is required`: create lab validation or use prototype auto-gates in lab only.
- `A reserved per-device lock is required`: pass `--lock` or use prototype auto-gates.
- `Vendor error pattern detected`: inspect the redacted output and vendor CLI syntax.
- Paramiko direct SSH uses bounded prompt reads for the runnable prototype. Firmware prompt and paging differences can still require vendor-specific tuning before any broader lab rollout.
