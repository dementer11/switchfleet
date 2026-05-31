# Config Backup Scheduling

Config backup scheduling is a safe, read-only workflow for collecting sanitized configuration snapshots before future network changes.

It does not apply configuration, does not restore configuration, and does not send configuration-mode commands to devices.

## Backup Jobs

Create a backup job:

```powershell
$body = @{
  name = "HQ nightly backup"
  scope_type = "site"
  scope_filter = @{ site = "HQ" }
  description = "Safe running-config snapshot collection"
} | ConvertTo-Json -Depth 6

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/config-backups/jobs" `
  -Headers @{ "X-Actor" = "netadmin"; "X-Roles" = "network_admin" } `
  -ContentType "application/json" `
  -Body $body
```

Supported scopes: `all`, `site`, `tag`, `device_ids`, and `query`.

Run a job manually:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/config-backups/jobs/<job_id>/run" `
  -Headers @{ "X-Actor" = "netop"; "X-Roles" = "network_operator" }
```

The current implementation uses a safe read-only collection path and test dummy collection. Unsupported read-only devices are marked `unsupported` or `skipped` instead of failing the whole job.

## Schedules

Schedules are persisted and calculable. This stage does not start a scheduler daemon or background worker.

Schedules support enable, disable, update, and delete operations. The `next_run_at` value is calculated from the cron expression and timezone.

## Snapshot Import

Manual import is available for lab captures or migrated data:

```powershell
$body = @{
  source = "imported"
  config_type = "running"
  config_text = Get-Content ".\running-config.txt" -Raw
} | ConvertTo-Json -Depth 6

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/config-backups/devices/<device_id>/snapshots/import" `
  -Headers @{ "X-Actor" = "netadmin"; "X-Roles" = "network_admin" } `
  -ContentType "application/json" `
  -Body $body
```

Imported config is sanitized before storage. Raw unsanitized config is never saved.

## Sanitizer

The sanitizer redacts password, secret, username password/secret, SNMP community, RADIUS/TACACS key, NTP authentication key, private key, SSH key, API token, and bearer token material.

Snapshot hashes are calculated from sanitized text.

## Diff And Drift

When a new snapshot differs from the previous snapshot, SwitchFleet stores a sanitized unified diff.

The change summary counts lines added and removed, redacted secret lines, interface changes, VLAN changes, ACL changes, routing changes, and management-plane changes.

Drift endpoints compare the latest two snapshots per device and return whether drift is detected.

## Restore Preparation

Restore plans are preview-only records. A plan contains target device, target snapshot, sanitized target configuration, risk assessment, and warnings.

Approving a restore plan only approves the record. There is no endpoint that applies the plan to a device.

Risk levels:

- `low`: metadata or comments only;
- `medium`: interface descriptions or VLAN names;
- `high`: VLAN membership, ACL, routing, or management config;
- `critical`: authentication, AAA, SNMP community, management IP, firmware, boot, or system lines.

## RBAC

- `viewer` and `network_operator`: read config backup records.
- `network_operator`, `network_admin`, `admin`, and `super_admin`: run backup jobs.
- `network_admin`, `admin`, and `super_admin`: manage backup jobs, schedules, snapshots, and restore plans.
- `security_admin`, `admin`, and `super_admin`: approve restore plans.

## Safety

This workflow does not enable real device apply, call `send_config`, call `save_config`, run `write memory`, enter `configure terminal`, change passwords, change VLANs/ACLs/ports, or restore configuration to devices.

It prepares sanitized config history for later controlled workflows while preserving password-change rollout, Lab Validation, Inventory onboarding, dry-run, approval, backup, verification, locks, and audit safety layers.
