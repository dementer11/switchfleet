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
- Controlled password-change workflow through FastAPI with encrypted temporary secret storage and canary rollout.
- CLI operations for password, ACL, VLAN, port changes, and config backup.
- Hybrid transport strategy: Scrapli/Netmiko in the enterprise layer; Netmiko/Paramiko in the CLI layer.
- Encrypted credentials with Fernet.
- Approval workflow for jobs.
- Per-device job tasks and status transitions.
- PostgreSQL-backed enterprise runtime for devices, credentials, jobs, job tasks, encrypted backups, audit events, and device locks.
- PostgreSQL-backed password rollout batches, rollout batch tasks, and encrypted password-change execution secrets.
- Lab validation records, sanitized transcripts, checklists, and a future real-apply safety gate.
- Inventory onboarding batches, normalized device metadata, driver resolution reports, credential assignment checks, and read-only discovery status.
- Config backup jobs, persisted schedules, sanitized snapshots, sanitized diffs, drift reports, retention policy, and restore plan previews.
- Hardened VLAN workflow records with validation, impact preview, dry-run command plans, rollback previews, approvals, and audit events.
- Simulation-only change execution orchestration for password rollout, VLAN workflow, and config-backup dependency timelines.
- Read-only operator console backend summaries for health, safety posture, pending approvals, activity, and risk.
- Read-only observability, audit export, compliance snapshots, operational reports, device readiness reports, and metrics summaries.
- Vendor-aware transport strategy and driver runtime decisions for Netmiko, Paramiko, custom CLI, ICMP-only, and unsupported profiles.
- Encrypted backup storage and masked diffs.
- Device locks with expiration.
- Structured audit events with secret masking before database write.
- CSV/XLSX/JSON inventory import support.
- Offline installers and Windows portable release bundles.

Real device apply is disabled by default in the enterprise executor. The current safe executor uses `DummyTransport`; dry-run entries that request Scrapli or Netmiko are rejected while `NCP_ALLOW_REAL_DEVICE_APPLY=false`. The flag is a safety gate for future lab execution, not a production-ready real-device apply switch in this release.

Lab validation records are now available for future real-device enablement. They do not enable real apply by themselves: even if `NCP_ALLOW_REAL_DEVICE_APPLY=true` is set in a lab, a matching approved validation for vendor, model pattern, driver, and capability is required before the future real-transport gate can pass.

## Inventory Onboarding

Inventory onboarding is a safe pre-change workflow. It imports JSON/API inventory records, normalizes vendor/model/platform and tags, resolves the expected driver, validates optional credential assignment by credential name, and can run a read-only reachability check. It does not run destructive operations.

Dry-run import validates and stores an import batch/report without creating device records:

```powershell
$body = @{
  source_type = "api"
  filename = "inventory.json"
  dry_run = $true
  items = @(
    @{ ip = "10.0.0.1"; hostname = "sw-core-1"; vendor = "Huawei"; model = "S5735"; site = "HQ"; tags = @("core") }
  )
} | ConvertTo-Json -Depth 6

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/inventory/import" `
  -Headers @{ "X-Actor" = "netadmin"; "X-Roles" = "network_admin" } `
  -ContentType "application/json" `
  -Body $body
```

Set `dry_run=false` to create or update device metadata. Follow-up reports are available under `/api/v1/inventory/imports/<batch_id>/validation-report`, `/driver-resolution-report`, and `/discovery-report`.

## Config Backup Scheduling

Config backup scheduling is a read-only workflow for collecting sanitized running-config snapshots and detecting drift. It does not restore or apply configuration to devices.

Create and run a backup job:

```powershell
$body = @{
  name = "HQ safe backup"
  scope_type = "site"
  scope_filter = @{ site = "HQ" }
} | ConvertTo-Json -Depth 6

$job = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/config-backups/jobs" `
  -Headers @{ "X-Actor" = "netadmin"; "X-Roles" = "network_admin" } `
  -ContentType "application/json" `
  -Body $body

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/config-backups/jobs/$($job.job.id)/run" `
  -Headers @{ "X-Actor" = "netop"; "X-Roles" = "network_operator" }
```

Manual snapshot import sanitizes config before storage. Schedules are persisted and calculate `next_run_at`; this release does not start a scheduler daemon. Restore plans are preview-only records and have no apply endpoint.

## VLAN Workflow Hardening

The hardened VLAN workflow prepares VLAN changes without applying them to devices. It validates the request, requires a fresh sanitized config snapshot, requires matching lab validation, builds an impact preview, renders dry-run vendor commands, prepares rollback text, records approval metadata, and writes a VLAN audit trail.

Create a preparation request:

```powershell
$body = @{
  title = "Add VLAN 120 to HQ access switches"
  scope_type = "site"
  scope_filter = @{ site = "HQ" }
  operation = "create_vlan"
  vlan_id = 120
  vlan_name = "CAMERAS"
} | ConvertTo-Json -Depth 6

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/vlan-workflows/requests" `
  -Headers @{ "X-Actor" = "netadmin"; "X-Roles" = "network_admin" } `
  -ContentType "application/json" `
  -Body $body
```

Follow-up endpoints under `/api/v1/vlan-workflows` validate, preview impact, build dry-run plans, prepare rollback plans, submit for approval, approve/reject/cancel, and read audit/report data. There is no VLAN `/apply` endpoint and no VLAN `/run` endpoint.

## Change Execution Orchestrator

The Change Execution Orchestrator connects existing preparation workflows into a single simulation timeline. It is simulation-only: it validates source readiness, checks fresh backups and lab validation, reserves database-only orchestration locks, builds dry-run steps, simulates per-device actions, and writes audit events without opening transports or applying changes.

Supported sources:

- password rollout jobs;
- VLAN workflow requests;
- config backup jobs as dependency checks;
- manual/composite metadata simulations.

Create a simulation:

```powershell
$body = @{
  title = "Simulate VLAN rollout"
  change_type = "vlan_change"
  source_type = "vlan_workflow"
  source_id = "<vlan_workflow_request_id>"
} | ConvertTo-Json -Depth 6

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/change-executions" `
  -Headers @{ "X-Actor" = "netadmin"; "X-Roles" = "network_admin" } `
  -ContentType "application/json" `
  -Body $body
```

The workflow under `/api/v1/change-executions` supports validate, plan, submit, approve/reject, reserve-locks, mark-ready, simulate, cancel, reports, audit, and locks. There is no `/apply` endpoint and no destructive `/run` endpoint.

## Operator Console Backend

The Operator Console Backend prepares the API surface for a future UI. It is read-only and aggregates platform state across inventory, credentials, lab validation, config backups, VLAN workflows, password rollouts, change execution simulations, approvals, audit activity, risk, and safety posture.

Endpoints are available under `/api/v1/operator-console`:

- `GET /dashboard`
- `GET /health`
- `GET /safety`
- `GET /workflows`
- `GET /pending-approvals`
- `GET /recent-activity`
- `GET /risk-summary`
- `GET /device-health`
- `GET /change-executions`

No operator-console endpoint runs discovery, validation, simulation, backup collection, restore, apply, or device commands. Responses contain only summaries and sanitized metadata.

## Observability And Reporting

The Observability layer is a read-only/export-only reporting API for audit exports, operational reports, compliance snapshots, safety posture, workflow activity, device readiness, and metrics summaries.

Endpoints are available under `/api/v1/observability`:

- `GET /audit-events`
- `GET /audit-export`
- `GET /operational-report`
- `GET /compliance-snapshot`
- `GET /safety-posture`
- `GET /workflow-activity`
- `GET /device-readiness`
- `GET /metrics-summary`

JSON reports require `read_observability`. CSV/full audit exports require `export_audit_reports`. Export limits default to 100 records and are capped at 5000 records.

This layer never runs workflow execution, simulation, config backup collection, lab validation, credential validation, transport open, or device commands. Metadata is recursively sanitized before JSON and CSV output, and reports never return raw configs, passwords, tokens, private keys, command output, or credential secret material.

## Transport Strategy And Driver Runtime

The Driver Runtime layer is a read-only decision API for selecting the safest transport strategy by vendor/model/platform.

Endpoints are available under `/api/v1/driver-runtime`:

- `GET /profiles`
- `GET /profiles/{family}`
- `GET /decision`
- `GET /devices/{device_id}/decision`
- `GET /summary`
- `GET /safety`

Netmiko is preferred for profiled Cisco, Huawei, HPE/Comware, ProCurve/ArubaOS-Switch, and Dell families. Paramiko is used where direct SSH/session control is the safer strategy. `custom_cli` is used for nonstandard Eltex/Bulat style CLIs. ICMP is health-only. Unknown devices are explicitly unsupported.

This layer does not open sessions, does not run commands, does not expose `/apply` or `/run`, and keeps `config_apply_allowed=false` and `real_apply_certified=false` for every runtime decision.

The legacy CLI runtime now uses a compatibility bridge to this matrix. It can still render plans and dry-run previews, and it can run read-only backups for supported profiles, but `netops apply` is blocked by default before credentials are requested or SSH transports are created. `NCP_LEGACY_CLI_REAL_APPLY=true` and `NCP_ALLOW_REAL_DEVICE_APPLY=true` do not enable legacy real apply in this stage.

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

The run path enforces approval, backup-before-apply, verification commands, device locks, and save-after-verification. Real Scrapli/Netmiko apply remains blocked by default; this release still executes the enterprise apply path through `DummyTransport`.

Create a password change job:

```powershell
$body = @{
  requested_by = "sec"
  devices = @(
    @{ ip_address = "10.0.0.1"; vendor = "Cisco"; model = "Cat2960-48" }
    @{ ip_address = "10.0.0.2"; vendor = "Huawei"; model = "S5735" }
  )
  username = "admin"
  new_password = $env:NCP_NEW_PASSWORD
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/jobs/password-change" `
  -Headers @{ "X-Actor" = "sec"; "X-Roles" = "security_admin" } `
  -ContentType "application/json" `
  -Body $body
```

Password jobs cannot be run through the generic `/run` endpoint. They must be approved and then executed one canary batch at a time:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/jobs/<job_id>/approve" `
  -Headers @{ "X-Actor" = "sec"; "X-Roles" = "security_admin" }

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/jobs/<job_id>/run-next-batch" `
  -Headers @{ "X-Actor" = "sec"; "X-Roles" = "security_admin" }
```

`GET /api/v1/jobs/<job_id>/rollout-plan` shows the current canary batches. `POST /pause` and `POST /resume` can pause or resume the password rollout between batches.

## Persistence Layer Status

The Enterprise API runtime is backed by SQLAlchemy repositories and PostgreSQL-compatible models. API routers call services, services call repositories, and repositories encapsulate database operations.

Persisted enterprise objects:

- imported devices;
- encrypted credentials;
- jobs and job tasks;
- dry-run payloads;
- encrypted config backups;
- audit logs;
- per-device locks.
- password rollout batches and encrypted password-change execution secrets.
- lab driver validations, sanitized lab transcripts, and checklist items.
- inventory import batches and normalized import rows.
- config backup jobs, persisted schedules, sanitized snapshots, sanitized diffs, and restore plan previews.
- VLAN workflow requests, per-device validation rows, approvals, and VLAN workflow audit events.
- change execution simulations, steps, database-only locks, approvals, and audit events.
- operator console read-only summaries derived from existing persisted objects.

Alembic migration `20260530_0001` creates the enterprise tables. Migration `20260530_0002` adds password rollout batches, rollout batch tasks, and encrypted password-change secrets. Migration `20260530_0003` adds lab validation records, sanitized transcripts, and checklists. Migration `20260530_0004` adds inventory onboarding metadata, import batches, and import rows. Migration `20260531_0005` adds config backup jobs, schedules, snapshots, diffs, and restore plan previews. Migration `20260531_0006` adds VLAN workflow validation, planning, approvals, and audit tables. Migration `20260531_0007` adds simulation-only change execution orchestration tables. All migrations support downgrade. SQLite is supported for unit and integration tests through portable UUID, JSON, and INET column mappings.

The CLI workflow under `src/netops_orchestrator` remains separate. It can render plans, produce dry-run previews, and run read-only backups from inventory files. Destructive legacy `netops apply` is blocked by the unified runtime safety bridge before any SSH transport is created. The Enterprise API workflow stores operational state in the database and keeps destructive apply guarded by approval, backup, verification, locks, and audit.

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
  -Body (@{ name = "core"; username = "admin"; password = $env:NCP_CREDENTIAL_PASSWORD } | ConvertTo-Json)
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

Preview a legacy apply plan with dry-run:

```powershell
netops apply inventory.csv `
  --operation vlan `
  --vlan-id 220 `
  --name USERS `
  --port GigabitEthernet0/0/1 `
  --dry-run `
  --limit 1
```

Running `netops apply` without `--dry-run` exits with a controlled safety error. Real CLI apply remains postponed until the Apply Safety Kernel and lab-only real apply stages.

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
- Password changes must use the Enterprise API canary rollout endpoint before broad execution.
- Password-change secrets are temporary encrypted execution records and are deleted after a successful rollout.
- Lab validation approval never bypasses dry-run, approval, backup, verification, locks, audit, or the default real-apply-off gate.
- Inventory onboarding and discovery are read-only metadata workflows and never run config, save, password, VLAN, ACL, or port commands.
- Config backup scheduling stores sanitized snapshots and restore previews only; it never applies restore plans to devices.
- VLAN workflow hardening is preparation-only; it validates, previews, plans, and approves but never sends VLAN commands to devices.
- Change execution orchestration is simulation-only; it never opens transports, never sends commands, and exposes no `/apply` or destructive `/run`.
- Operator console endpoints are GET-only; they never execute workflows, collect backups, validate labs, simulate changes, or return secrets/raw configs.
- Observability endpoints are GET-only read/export routes; they never execute workflows, collect backups, validate labs, simulate changes, open transports, or return secrets/raw configs.
- Driver runtime endpoints are GET-only decision routes; they never open sessions, execute commands, expose `/apply` or `/run`, or mark any device real-apply certified.

## Documentation

- [Enterprise platform architecture](docs/enterprise-platform.md)
- [Inventory onboarding](docs/inventory-onboarding.md)
- [Config backup scheduling](docs/config-backup-scheduling.md)
- [VLAN workflow hardening](docs/vlan-workflow-hardening.md)
- [Change execution orchestrator](docs/change-execution-orchestrator.md)
- [Operator console backend](docs/operator-console-backend.md)
- [Observability audit reporting](docs/observability-audit-reporting.md)
- [Transport strategy and driver runtime](docs/transport-strategy-driver-runtime.md)
- [Driver validation checklist](docs/lab-validation.md)
- [Lab validation framework](docs/lab-validation-framework.md)
- [Password change rollout](docs/password-change-rollout.md)
- [Original architecture notes](docs/architecture.md)
- [Security policy](SECURITY.md)
