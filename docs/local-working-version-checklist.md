# SwitchFleet Local Working Version Checklist

This checklist verifies that SwitchFleet Local is usable from a normal checkout or installed package as an Excel-first local admin tool.

The primary workflow does not require PostgreSQL, Alembic, FastAPI startup, Redis, Docker, or database imports. The enterprise backend remains optional.

## Install And Smoke

From a clean checkout:

```powershell
python -m pip install -e .
switchfleet --help
python scripts/excel_lab.py --help
```

The `switchfleet` command and the source-checkout compatibility script should both start without database configuration.
Interactive terminals show table/section output by default. Use `--human` to force that view through wrappers or captured terminals, and `--json` for machine-readable output.

## Example Inventory

Use the bundled documentation-range inventory for a safe smoke test:

```powershell
switchfleet examples/lab/inventory.example.xlsx doctor
switchfleet examples/lab/inventory.example.xlsx summary
switchfleet examples/lab/inventory.example.xlsx list
switchfleet examples/lab/inventory.example.xlsx check-runtime --device 192.0.2.30
switchfleet examples/lab/inventory.example.xlsx check-runtime --all
```

Expected properties:

- `doctor` reports that the Excel file is readable.
- `doctor` reports that database and Alembic setup are not required.
- `summary` shows vendor, family, transport, backup, and apply support counts.
- `list` shows normalized runtime decisions for each device.
- `check-runtime` shows original and normalized vendor/model, family, driver, transport, backup status, apply status, reasons, and warnings.

## Required Excel Columns

The Excel inventory must contain these columns:

- `Status`
- `Device Label`
- `Model`
- `IP Address`
- `Vendor`
- `Device Category`
- `Location`
- `Contact`

Rows that are empty or clearly not device rows should be ignored. Unknown, ambiguous, ICMP-only, and non-switch rows must fail closed for config apply.

Use IP address as the operator-facing device selector. Internal generated IDs are implementation details and should not be used in normal CLI workflows.

## Primary Command Order

For a real lab inventory, the operator flow is:

```powershell
switchfleet inventory.xlsx doctor
switchfleet inventory.xlsx summary
switchfleet inventory.xlsx list
switchfleet inventory.xlsx check-runtime --device 192.0.2.67
switchfleet inventory.xlsx check-runtime --all
switchfleet inventory.xlsx add-credential --name lab-admin --username admin --password-prompt
switchfleet inventory.xlsx backup --device 192.0.2.67 --credential lab-admin
switchfleet inventory.xlsx dry-run --device 192.0.2.67 --operation vlan_create --vlan-id 123 --name TEST_VLAN
switchfleet inventory.xlsx evaluate-apply --device 192.0.2.67 --credential lab-admin --operation vlan_create --vlan-id 123 --name TEST_VLAN --simulation-hash <hash-from-dry-run>
switchfleet inventory.xlsx certify --device 192.0.2.67 --capability vlan_create --credential lab-admin
switchfleet inventory.xlsx execute-apply --device 192.0.2.67 --credential lab-admin --operation vlan_create --vlan-id 123 --name TEST_VLAN --simulation-hash <hash-from-dry-run> --real-lab
```

For inventory-wide read-only and planning stages, use `--all`:

```powershell
switchfleet inventory.xlsx backup --all --credential lab-admin
switchfleet inventory.xlsx dry-run --all --operation vlan_create --vlan-id 123 --name TEST_VLAN
switchfleet inventory.xlsx evaluate-apply --all --credential lab-admin --operation vlan_create --vlan-id 123 --name TEST_VLAN
switchfleet inventory.xlsx certify --all --capability vlan_create --credential lab-admin
```

The same parameters can be stored in a JSON profile:

```powershell
switchfleet inventory.xlsx dry-run --all --profile examples/lab/vlan-profile.example.json
switchfleet inventory.xlsx evaluate-apply --all --profile examples/lab/vlan-profile.example.json
switchfleet inventory.xlsx execute-apply --device 192.0.2.67 --profile examples/lab/vlan-profile.example.json --simulation-hash <hash-from-dry-run> --real-lab
```

For one safe inventory-wide workflow:

```powershell
switchfleet inventory.xlsx workflow --profile examples/lab/vlan-profile.example.json
switchfleet inventory.xlsx workflow --profile examples/lab/vlan-profile.example.json --with-backup
```

Bulk commands continue after per-device failures and report status for each IP. Bulk real-lab execution is intentionally disabled; execute real changes per device after reviewing its backup, dry-run hash, gate evaluation, and certification state.
`workflow` also writes a readable Markdown report and a JSON report under `.switchfleet_lab/reports/`.

## Local State

By default, local state is written under `.switchfleet_lab/`:

- encrypted credential metadata and payloads;
- sanitized backups;
- dry-run records;
- evaluation records;
- lab certification records;
- lock records;
- execution records;
- audit JSONL.

This directory is local operator state. It must not be committed.

## Credential Setup

Set a local encryption key before adding a credential:

```powershell
$env:NCP_SECRET_KEY = "replace-with-long-random-lab-secret"
switchfleet inventory.xlsx add-credential --name lab-admin --username admin --password-prompt
```

Passwords must be entered through a prompt or trusted environment variable. Plaintext password CLI arguments are not supported. CLI output must not print credential payloads.

## Read-Only Backup

Allowlist the lab device before backup:

```powershell
$env:NCP_LAB_DEVICE_ALLOWLIST = "192.0.2.67"
switchfleet inventory.xlsx backup --device 192.0.2.67 --credential lab-admin
```

Expected properties:

- backup uses vendor contract read-only commands;
- backup requires a usable encrypted credential reference;
- backup output is sanitized before storage;
- command echo, pager markers, ANSI/control artifacts, and final prompts are removed from stored backup content;
- failed or incomplete backups do not satisfy apply gates.

## Dry-Run And Evaluate

Dry-run renders the intended command plan without decrypting credentials or opening SSH:

```powershell
switchfleet inventory.xlsx dry-run --device 192.0.2.67 --operation vlan_create --vlan-id 123 --name TEST_VLAN
```

Use the returned command hash for evaluation:

```powershell
switchfleet inventory.xlsx evaluate-apply --device 192.0.2.67 --credential lab-admin --operation vlan_create --vlan-id 123 --name TEST_VLAN --simulation-hash <hash-from-dry-run>
```

Expected properties:

- evaluation does not decrypt credentials;
- evaluation does not create transport sessions;
- backup and dry-run are mandatory;
- evaluation is bound to runtime family, driver, transport, device, credential, operation, and command hash.

## Lab Certification

Certification records lab-only evidence. It is not production certification:

```powershell
switchfleet inventory.xlsx certify --device 192.0.2.67 --capability vlan_create --credential lab-admin
switchfleet inventory.xlsx certification-report
```

Config capability certification requires the same device, credential, runtime profile, command hash, fresh sanitized backup, and a matching recorded evaluation.

## Real Lab Execute

Real lab execution is explicit and remains lab-only:

```powershell
$env:NCP_ALLOW_REAL_DEVICE_APPLY = "true"
$env:NCP_LAB_REAL_APPLY_ENABLED = "true"
$env:NCP_PRODUCTION_REAL_APPLY_ENABLED = "false"
switchfleet inventory.xlsx execute-apply --device 192.0.2.67 --credential lab-admin --operation vlan_create --vlan-id 123 --name TEST_VLAN --simulation-hash <hash-from-dry-run> --real-lab
```

Before decrypting credentials or creating a transport, execution revalidates:

- production apply disabled;
- lab flags enabled;
- device allowlist;
- runtime family and transport;
- operation support;
- credential reference;
- fresh sanitized backup;
- matching dry-run hash;
- matching certification/evaluation records;
- forbidden commands;
- device lock ownership.

## Safety Invariants

- Production apply remains disabled.
- No generic unsafe `/apply` endpoint exists.
- No destructive `/run` endpoint exists for the Excel-first workflow.
- Dry-run and evaluate do not open SSH.
- Dry-run and evaluate do not decrypt credentials.
- Backup and dry-run are mandatory before config apply evaluation.
- Unknown, GenericSSH, ICMP-only, unmanaged, and non-switch devices fail closed for config apply.
- QTECH, Eltex, and Bulat config apply remains blocked unless exact lab-certified policy and templates allow it.
- The enterprise DB/FastAPI path is optional and must not be presented as production real-device execution while it uses simulated transport.

## Release Candidate Gate

Before declaring the local working version ready, run:

```powershell
python -m pytest -q
python -m compileall -q app src tests
python -m compileall -q scripts
python -m ruff check app tests
python -m mypy app
python -m pip check
python -m pip wheel --no-deps --wheel-dir dist/wheelhouse .
switchfleet --help
python scripts/excel_lab.py --help
git diff --check
```

Then repeat the example inventory smoke commands:

```powershell
switchfleet examples/lab/inventory.example.xlsx doctor
switchfleet examples/lab/inventory.example.xlsx summary
switchfleet examples/lab/inventory.example.xlsx list
```

Real device behavior still requires controlled lab validation for prompts, paging, save/commit behavior, device type mapping, timing, and vendor firmware differences.
