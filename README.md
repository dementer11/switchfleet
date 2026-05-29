# SwitchFleet

Enterprise platform for safe multi-vendor switch management.

SwitchFleet is built for controlled operations across mixed network estates: dry-run first, approval required, encrypted credentials, backup before change, verification before save, per-device locks, audit logs, and vendor-specific drivers behind a vendor-neutral intent API.

## What It Manages

Supported and modeled families:

- Huawei VRP: S17xx, S23xx, S24xx, S57xx, S67xx, CE68xx
- Cisco IOS: Catalyst, Cat2960
- HP/HPE/3Com Comware: HPE 1910, 1920, 5130; 3Com S4210, S5500
- HPE ProCurve / ArubaOS-Switch: 2510, 2530
- Eltex MES: dry-run only until lab templates are confirmed
- Bulat BS2500/BS6300: dry-run only until lab templates are confirmed
- Dell PowerConnect
- QTECH QSW and D-Link DES in the CLI driver layer
- Generic SSH and ICMP-only read-only profiles

## Capabilities

- Intent-based VLAN dry-run workflow through FastAPI.
- CLI operations for password, ACL, VLAN, port changes, and config backup.
- Hybrid transport strategy: Scrapli/Netmiko in the enterprise layer; Netmiko/Paramiko in the CLI layer.
- Encrypted credentials with Fernet.
- Approval workflow for jobs.
- Per-device job tasks and status transitions.
- Encrypted backup storage and masked diffs.
- Device locks with expiration.
- Structured audit events with secret masking.
- CSV/XLSX/JSON inventory import support.
- Offline installers and Windows portable release bundles.

Real device apply is disabled by default in the enterprise executor. The current safe executor uses `DummyTransport`; lab-only real apply must be explicitly enabled with `NCP_ALLOW_REAL_DEVICE_APPLY=true` after driver templates are validated.

## Install For Development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Run local infrastructure:

```powershell
docker compose up -d postgres redis
```

Run the API:

```powershell
uvicorn app.main:app --reload
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
```

## Enterprise API Workflow

Create a VLAN change job. This generates a masked dry-run, creates per-device tasks, and leaves the job in `pending_approval`.

```powershell
$body = @{
  requested_by = "alice"
  devices = @(
    @{ ip_address = "10.0.0.1"; vendor = "Huawei"; model = "S5735" }
  )
  intent = @{ vlan_id = 100; name = "USERS"; state = "present" }
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/jobs/vlan-change" `
  -Headers @{ "X-Actor" = "alice"; "X-Roles" = "network_admin" } `
  -ContentType "application/json" `
  -Body $body
```

Approve and run a job:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/jobs/<job_id>/approve" `
  -Headers @{ "X-Actor" = "lead"; "X-Roles" = "network_admin" }

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/jobs/<job_id>/run" `
  -Headers @{ "X-Actor" = "lead"; "X-Roles" = "network_admin" }
```

The run path enforces approval, backup-before-apply, verification commands, device locks, and save-after-verification. Real Scrapli/Netmiko apply remains blocked unless explicitly enabled for a lab.

## Credentials

Set an encryption key before production use:

```powershell
$env:NCP_SECRET_KEY = "replace-with-long-random-secret"
```

Create credentials:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/credentials" `
  -Headers @{ "X-Actor" = "sec"; "X-Roles" = "security_admin" } `
  -ContentType "application/json" `
  -Body '{"name":"core","username":"admin","password":"secret-value"}'
```

API responses never return password material.

## CLI Workflow

Inspect inventory:

```powershell
netops inventory ".\inventory.xlsx"
```

Plan a password change without exposing the password in output:

```powershell
$env:NEW_SWITCH_PASS = "new-secret"
netops plan-password inventory.csv --username admin --new-password-env NEW_SWITCH_PASS --level admin
```

Capture a backup:

```powershell
$env:SWITCH_PASS = "current-secret"
netops backup inventory.csv --login netadmin --password-env SWITCH_PASS --output-dir ".\backups" --limit 1
```

Apply with pre/post backup and audit:

```powershell
netops apply inventory.csv `
  --login netadmin `
  --password-env SWITCH_PASS `
  --operation vlan `
  --vlan-id 220 `
  --name USERS `
  --port GigabitEthernet0/0/1 `
  --pre-backup `
  --post-backup `
  --audit-log ".\audit\run.jsonl" `
  --limit 1
```

## Offline And Portable Release Assets

GitHub releases include:

- `switchfleet-windows-offline-<version>.zip`
- `switchfleet-linux-offline-<version>.tar.gz`
- `switchfleet-redos-7.3.6-offline-<version>.tar.gz`
- `switchfleet-windows-portable-<version>.zip`
- `.sha256` files for every archive

Windows offline:

```powershell
.\install.cmd
.\switchfleet.cmd --help
.\switchfleet-api.cmd
```

Linux / RED OS:

```bash
./install.sh
./switchfleet --help
./switchfleet-api
```

Windows portable:

```powershell
.\switchfleet.cmd --help
.\switchfleet-api.cmd
```

## Safety Rules

- Never log passwords.
- Never return passwords through API.
- Never run destructive apply without dry-run, approval, backup, verification, and audit.
- Never save config before verification succeeds.
- Never run real device apply by default.
- Never run destructive operations for Bulat, Eltex, or Generic SSH until templates are lab-confirmed.
- Password changes must use canary rollout before broad execution.

## Documentation

- [Enterprise platform architecture](docs/enterprise-platform.md)
- [Driver validation checklist](docs/lab-validation.md)
- [Original architecture notes](docs/architecture.md)

