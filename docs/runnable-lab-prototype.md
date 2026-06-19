# Runnable Lab Prototype

The runnable lab prototype is now Excel-first. It is designed for operators who already have an inventory spreadsheet and want to test SwitchFleet on 3-4 controlled lab devices without PostgreSQL, Alembic, FastAPI, or DB imports.

This mode does not enable production apply, does not add a generic `/apply`, and does not add a destructive `/run`.

Use the installed `switchfleet` command for the primary local workflow. When running directly from a source checkout, `python scripts/excel_lab.py` remains available as a compatibility form.

## Excel Inventory

The Excel file is the primary lab input. Required columns:

- `Status`
- `Device Label`
- `Model`
- `IP Address`
- `Vendor`
- `Device Category`
- `Location`
- `Contact`

Rows with empty device data or explicit service rows are ignored. Unknown or ambiguous vendor/model rows fail closed through the existing driver runtime matrix.

The repository includes `examples/lab/inventory.example.xlsx` for local smoke tests. It uses documentation IP addresses and covers the main runtime classifications, including candidate switch families, QTECH, unmanaged D-Link, non-switch SecurityCode Continent, Unknown SNMP inventory-only records, and ICMP health-only records.

## State

Excel lab mode stores local state under `.switchfleet_lab/` by default:

```text
.switchfleet_lab/
  credentials.json
  backups/
  audit.jsonl
  locks.json
  lockfiles/
  dry_runs.json
  evaluations.json
  lab_validations.json
  executions/
```

Credential payloads are encrypted with `NCP_SECRET_KEY`. Plaintext secrets are not written to state, output, audit, or reports.
`lockfiles/` contains atomic per-device execution guards; an existing guard fails closed rather than allowing concurrent lab apply for the same device.

## Doctor

```powershell
switchfleet inventory.xlsx doctor
```

Doctor verifies that the Excel file is readable, required columns are present, file state is available, lab env vars are visible, Netmiko/Paramiko availability can be detected, and database/Alembic setup is not required.

## List And Runtime

```powershell
switchfleet inventory.xlsx summary
switchfleet inventory.xlsx list
switchfleet inventory.xlsx check-runtime --device 192.0.2.67
```

Runtime decisions reuse `DriverCapabilityMatrix`, `VendorDriverContracts`, and `VendorCommandTemplateService`. Excel inventory is not certification. Unknown, ICMP, GenericSSH, Eltex, and Bulat remain blocked for config apply unless a future certified contract changes that.

## Credential Ref

```powershell
$env:NCP_SECRET_KEY = "replace-with-long-random-lab-secret"
switchfleet inventory.xlsx add-credential --name lab-admin --username admin --password-prompt
```

The password is read interactively or from `--password-env`; plaintext password arguments are intentionally unsupported.

## Backup

```powershell
$env:NCP_LAB_DEVICE_ALLOWLIST = "192.0.2.67"
switchfleet inventory.xlsx backup --device 192.0.2.67 --credential lab-admin
```

Backup is read-only. It uses the existing vendor contract read-only commands, decrypts the credential only after allowlist/runtime checks, sanitizes output, stores a local backup file, and writes an audit event. Unknown and ICMP devices are denied.

## Dry Run

```powershell
switchfleet inventory.xlsx dry-run --device 192.0.2.67 --operation vlan_create --vlan-id 123 --name TEST_VLAN
```

Dry-run does not open SSH and does not decrypt credentials. It renders existing vendor templates, redacts secret commands, stores a dry-run record, and returns a command hash.

## Evaluate

```powershell
switchfleet inventory.xlsx evaluate-apply --device 192.0.2.67 --credential lab-admin --operation vlan_create --vlan-id 123 --name TEST_VLAN --simulation-hash <hash-from-dry-run>
```

Evaluate does not open SSH and does not decrypt credentials. It checks allowlist, credential reference, fresh sanitized backup, lab certification record, dry-run hash for the same device and operation, runtime decision, vendor contract, and lock conflicts. It stores a sanitized evaluation record bound to the device, credential reference, runtime decision, operation, and command hash.

## Certification

```powershell
switchfleet inventory.xlsx certify --device 192.0.2.67 --capability vlan_create --credential lab-admin
switchfleet inventory.xlsx certification-report
```

Certification records lab-only evidence in local file state. It is not production certification and does not run commands by itself. Backup capability certification requires a fresh sanitized backup captured for the same device. Config capability certification requires a usable credential reference, allowlisted device, fresh sanitized backup, stored dry-run, and a matching stored evaluation bound to the same vendor, model, driver, platform, family, transport, credential, and command hash. Before certification, that evaluation may be denied only because the lab-validation gate has not yet been satisfied.

## Execute

Fake/default-safe execution remains available for local verification:

```powershell
switchfleet inventory.xlsx execute-apply --device 192.0.2.67 --credential lab-admin --operation vlan_create --vlan-id 123 --name TEST_VLAN --simulation-hash <hash-from-dry-run>
```

Real lab execution requires explicit lab flags and `--real-lab`:

```powershell
$env:NCP_ALLOW_REAL_DEVICE_APPLY = "true"
$env:NCP_LAB_REAL_APPLY_ENABLED = "true"
$env:NCP_PRODUCTION_REAL_APPLY_ENABLED = "false"
switchfleet inventory.xlsx execute-apply --device 192.0.2.67 --credential lab-admin --operation vlan_create --vlan-id 123 --name TEST_VLAN --simulation-hash <hash-from-dry-run> --real-lab
```

Credential decrypt and transport creation happen only after the file-mode safety decision allows the request.

## Audit

```powershell
switchfleet inventory.xlsx audit-tail --limit 20
```

Audit payloads are JSONL and sanitized.

## Enterprise DB Mode

`scripts/lab_prototype.py` remains available as DB-backed enterprise prototype mode. It writes through SQLAlchemy models and is useful only when you intentionally run the backend database path.

Excel lab users do not need to run PostgreSQL, Alembic, or import inventory into a DB.

## Known Limitations

Controlled lab testing is still required for:

- prompt handling;
- paging behavior;
- vendor-specific save/commit behavior;
- Netmiko device type accuracy per firmware;
- Paramiko timing;
- command output/error-pattern coverage;
- rollback behavior on real devices.
