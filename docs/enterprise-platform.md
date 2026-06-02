# Enterprise Network Control Platform

## Architecture

The platform is split into explicit layers:

1. API layer: FastAPI routers accept vendor-neutral intents and return sanitized dry-run output.
2. Service layer: planning, driver resolution, inventory import, audit, approval, credentials, locks, backup, and guarded job execution.
3. Driver layer: `BaseNetworkDriver` exposes a vendor-neutral API and concrete drivers render vendor-specific commands.
4. Transport layer: `ScrapliTransport` is the primary SSH backend, `NetmikoTransport` is fallback, `DummyTransport` is for tests.
5. Database layer: PostgreSQL with SQLAlchemy 2.x models for devices, credentials, jobs, tasks, backups, audit, locks, VLANs, ports, and ACL objects.
6. Security layer: RBAC, secret masking, encrypted credential provider, approval-required workflows.

The enterprise API runtime is backed by SQLAlchemy repositories. API routers call services, services call repositories, and repositories encapsulate database operations. Tests use temporary SQLite through portable UUID, JSON, and INET type mappings; production is designed for PostgreSQL.

## Technology Choices

- FastAPI gives typed API contracts and OpenAPI for operators and future UI.
- SQLAlchemy 2.x keeps DB access explicit and migration-friendly.
- PostgreSQL stores inventory, job state, JSON capabilities, and audit data reliably.
- Redis/Celery are prepared for background jobs, retries, cancellation, and distributed workers.
- Scrapli is preferred for modern network CLI sessions; Netmiko remains available for legacy platforms.
- Pydantic v2 validates intents before any command generation.
- Jinja2 templates are present for command families, while first-stage drivers render commands directly for testability.

## Multivendor Risks

- Similar model names may run different firmware trains and CLI dialects.
- Some platforms have interactive save prompts and hidden privilege modes.
- VLAN deletion can break ports if VLAN usage is not verified first.
- Password change can lock out automation if the new credential is not verified.
- ACL syntax and ACL binding semantics differ strongly between vendors.
- Bulat, Eltex, and old SMB/3Com devices require lab-confirmed templates before destructive apply.

## Data Model

The SQLAlchemy model set covers:

- `devices`
- `credentials`
- `credential_assignments`
- `jobs`
- `job_tasks`
- `config_backups`
- `audit_logs`
- `device_locks`
- `vlans`
- `ports`
- `acl_objects`
- `acl_rules`
- `password_rollout_batches`
- `password_rollout_batch_tasks`
- `password_change_secrets`
- `lab_driver_validations`
- `lab_validation_transcripts`
- `lab_validation_checklists`
- `inventory_import_batches`
- `inventory_import_rows`
- `config_backup_jobs`
- `config_backup_job_items`
- `config_backup_schedules`
- `config_snapshots`
- `config_snapshot_diffs`
- `config_restore_plans`
- `vlan_change_requests`
- `vlan_change_devices`
- `vlan_change_approvals`
- `vlan_change_audit_events`
- `change_executions`
- `change_execution_steps`
- `change_execution_locks`
- `change_execution_approvals`
- `change_execution_audit_events`
- `credential_secrets`

UUID primary keys are used for operational entities. Capabilities, dry-run payloads, tags, commands, and audit metadata use JSONB-compatible fields.

Current API endpoints read and write the database-backed repository layer. `RuntimeState` remains only as a legacy test/dummy helper and is not used by the production API service path.

## Persistence Layer Status

Database-backed runtime objects:

- devices imported through the API or created from job dry-run inputs;
- encrypted credentials;
- jobs and job tasks, including dry-run payloads and status transitions;
- audit logs with secrets sanitized before insert;
- encrypted config backups and hashes;
- per-device locks with expiration.
- password rollout batch state and encrypted temporary password-change secrets.
- lab validation approvals, sanitized transcripts, and validation checklists.
- inventory onboarding batches, normalized import rows, discovery state, and driver/credential validation metadata.
- config backup jobs, persisted schedules, sanitized snapshots, sanitized diffs, drift reports, retention policy state, and restore plan previews.
- VLAN workflow validation requests, per-device readiness rows, approval metadata, planned dry-run commands, rollback previews, and audit events.
- simulation-only change execution records, step graphs, orchestration locks, approvals, and audit events.
- read-only operator console summaries derived from existing persisted runtime objects.
- read-only observability and reporting outputs derived from existing persisted runtime objects.
- read-only driver runtime decisions derived from vendor/model/platform metadata.
- encrypted credential vault secret metadata and lab-only apply readiness decisions.

Repositories live under `app/repositories/` and are the only layer that performs SQLAlchemy queries for enterprise runtime objects. Routers do not contain SQLAlchemy queries.

Alembic revision `20260530_0001` creates the core enterprise tables and includes a downgrade path. Revision `20260530_0002` adds password rollout batches, rollout batch tasks, and encrypted password-change execution secrets. Revision `20260530_0003` adds lab validation approvals, sanitized transcripts, and checklists. Revision `20260530_0004` adds inventory onboarding device metadata, import batches, and import rows. Revision `20260531_0005` adds config backup jobs, schedules, snapshots, diffs, and restore plan previews. Revision `20260531_0006` adds VLAN workflow validation, planning, approvals, and audit tables. Revision `20260531_0007` adds simulation-only change execution orchestration tables. Revision `20260602_0008` adds credential vault secret metadata for lab-only apply readiness. The migrations use PostgreSQL-native UUID, JSONB, and INET types on PostgreSQL and portable UUID string, JSON, and string IP columns on SQLite test databases.

## Inventory Onboarding Workflow

Inventory onboarding is the safe pre-change entry point for device records. It is intentionally separate from change jobs and does not execute destructive operations.

The workflow:

1. Operator submits inventory records to `POST /api/v1/inventory/import`.
2. Parser canonicalizes supported columns such as `ip`, `management_ip`, `hostname`, `vendor`, `model`, `platform`, `site`, `location`, `rack`, `role`, `tags`, and `credential_name`.
3. Normalizer validates management IP, normalizes vendor/model/platform, and normalizes tags.
4. Driver resolver maps each normalized device to the expected driver and records warnings for unsupported or unconfirmed families.
5. Credential assignment validation checks only safe credential metadata by `credential_name`; no password or encrypted secret is returned.
6. `dry_run=true` stores a batch and row report without creating devices.
7. `dry_run=false` idempotently creates or updates device metadata by management IP.
8. Read-only discovery can update reachability status and safe facts through `DummyTransport` in tests.

Inventory endpoints:

- `POST /api/v1/inventory/import`
- `GET /api/v1/inventory/imports`
- `GET /api/v1/inventory/imports/{batch_id}`
- `GET /api/v1/inventory/imports/{batch_id}/rows`
- `GET /api/v1/inventory/imports/{batch_id}/validation-report`
- `GET /api/v1/inventory/imports/{batch_id}/driver-resolution-report`
- `GET /api/v1/inventory/devices`
- `GET /api/v1/inventory/devices/{device_id}`
- `PATCH /api/v1/inventory/devices/{device_id}`
- `POST /api/v1/inventory/devices/{device_id}/check-reachability`
- `POST /api/v1/inventory/imports/{batch_id}/check-reachability`
- `GET /api/v1/inventory/imports/{batch_id}/discovery-report`

Inventory RBAC:

- `viewer` and `network_operator` can read inventory.
- `network_admin`, `security_admin`, `admin`, and `super_admin` can manage inventory.
- `network_operator`, `network_admin`, `security_admin`, `admin`, and `super_admin` can run read-only discovery.

Inventory onboarding prepares devices for later lab validation and controlled change workflows. It does not bypass approval, dry-run, backup, verification, locks, audit, password rollout, or lab validation gates.

## Config Backup Scheduling Workflow

Config backup scheduling is the safe configuration history workflow. It is separate from change execution and restore execution.

The workflow:

1. Operator creates a backup job with scope `all`, `site`, `tag`, `device_ids`, or `query`.
2. Service resolves devices from the inventory repository and creates one job item per device.
3. Manual run walks job items and uses only read-only collection.
4. Raw collected or imported config is sanitized before persistence.
5. Snapshot hash is calculated from sanitized config.
6. A sanitized unified diff is created when the latest snapshot differs from the previous one.
7. Drift reports compare latest snapshots and return change summaries.
8. Retention can remove old snapshots by age and max snapshots per device.
9. Restore plans generate preview text and risk level, but never apply to a device.

Config backup endpoints:

- `POST /api/v1/config-backups/jobs`
- `GET /api/v1/config-backups/jobs`
- `GET /api/v1/config-backups/jobs/{job_id}`
- `POST /api/v1/config-backups/jobs/{job_id}/run`
- `GET /api/v1/config-backups/jobs/{job_id}/report`
- `POST /api/v1/config-backups/schedules`
- `GET /api/v1/config-backups/schedules`
- `GET /api/v1/config-backups/schedules/{schedule_id}`
- `PATCH /api/v1/config-backups/schedules/{schedule_id}`
- `POST /api/v1/config-backups/schedules/{schedule_id}/enable`
- `POST /api/v1/config-backups/schedules/{schedule_id}/disable`
- `DELETE /api/v1/config-backups/schedules/{schedule_id}`
- `GET /api/v1/config-backups/devices/{device_id}/snapshots`
- `GET /api/v1/config-backups/snapshots/{snapshot_id}`
- `POST /api/v1/config-backups/devices/{device_id}/snapshots/import`
- `GET /api/v1/config-backups/devices/{device_id}/diffs`
- `GET /api/v1/config-backups/diffs/{diff_id}`
- `GET /api/v1/config-backups/devices/{device_id}/drift`
- `POST /api/v1/config-backups/drift-report`
- `POST /api/v1/config-backups/restore-plans`
- `GET /api/v1/config-backups/restore-plans`
- `GET /api/v1/config-backups/restore-plans/{plan_id}`
- `POST /api/v1/config-backups/restore-plans/{plan_id}/approve`
- `POST /api/v1/config-backups/restore-plans/{plan_id}/reject`

Config backup RBAC:

- `viewer` and `network_operator` can read config backup records.
- `network_operator`, `network_admin`, `admin`, and `super_admin` can run backup jobs.
- `network_admin`, `admin`, and `super_admin` can manage backup jobs, schedules, snapshots, and restore plans.
- `security_admin`, `admin`, and `super_admin` can approve restore plans.

The config sanitizer masks password, secret, username password/secret, SNMP community, TACACS/RADIUS key, NTP authentication key, private key, SSH key, API token, and bearer token material. Raw unsanitized config is not stored.

Restore plan approval only approves the preview record. There is no endpoint that applies a restore plan to a device.

## VLAN Workflow Hardening

The hardened VLAN workflow is a preparation-only control plane for VLAN changes. It does not apply commands to devices and does not expose `/apply` or `/run` endpoints.

The workflow:

1. Operator creates a VLAN change request with scope, operation, VLAN ID, and optional VLAN name.
2. Validation checks VLAN ID/name, target device support, fresh config backup snapshot, and matching lab validation.
3. Impact preview reads the latest sanitized config snapshot and estimates existing VLAN state, potentially affected access/trunk ports, and risk.
4. Dry-run plan renders vendor-specific command text for Huawei VRP, Cisco IOS, HP Comware, HPE ProCurve, and Dell PowerConnect.
5. Rollback plan renders inverse command text where snapshot context is sufficient.
6. Request can be submitted for approval only when validation, backup, lab validation, dry-run plan, and rollback plan are present.
7. Approval marks the request `ready`; ready still means preparation-only and never executes against devices.
8. Every state transition writes a VLAN workflow audit event.

VLAN workflow endpoints:

- `POST /api/v1/vlan-workflows/requests`
- `GET /api/v1/vlan-workflows/requests`
- `GET /api/v1/vlan-workflows/requests/{request_id}`
- `POST /api/v1/vlan-workflows/requests/{request_id}/validate`
- `GET /api/v1/vlan-workflows/requests/{request_id}/validation-report`
- `POST /api/v1/vlan-workflows/requests/{request_id}/preview`
- `GET /api/v1/vlan-workflows/requests/{request_id}/impact-preview`
- `POST /api/v1/vlan-workflows/requests/{request_id}/plan`
- `GET /api/v1/vlan-workflows/requests/{request_id}/plan`
- `GET /api/v1/vlan-workflows/requests/{request_id}/rollback-plan`
- `POST /api/v1/vlan-workflows/requests/{request_id}/submit`
- `POST /api/v1/vlan-workflows/requests/{request_id}/approve`
- `POST /api/v1/vlan-workflows/requests/{request_id}/reject`
- `POST /api/v1/vlan-workflows/requests/{request_id}/cancel`
- `GET /api/v1/vlan-workflows/requests/{request_id}/audit`
- `GET /api/v1/vlan-workflows/requests/{request_id}/report`

VLAN workflow RBAC:

- `viewer` and `network_operator` can read VLAN workflow records.
- `network_operator`, `network_admin`, `admin`, and `super_admin` can build validation, impact, and plan previews.
- `network_admin`, `admin`, and `super_admin` can manage requests and submit/cancel.
- `security_admin`, `admin`, and `super_admin` can approve or reject VLAN workflow requests.

The workflow requires fresh config snapshots from Config Backup Scheduling and matching Lab Validation records. It does not bypass password-change rollout, inventory onboarding, dry-run, approval, backup, verification, locks, audit, or the default real-apply-off safety gate.

## Change Execution Orchestrator

The Change Execution Orchestrator is a simulation-only pipeline for combining existing safe workflows into a single execution timeline. It does not apply commands and does not expose `/apply` or destructive `/run` endpoints.

Supported source types:

- `password_rollout`;
- `vlan_workflow`;
- `config_backup_job`;
- `manual`;
- `composite`.

The workflow:

1. Operator creates a simulation record under `/api/v1/change-executions`.
2. Validation confirms simulation mode, source readiness, fresh backups, lab validation, and no conflicting orchestration locks.
3. Planning builds a deterministic step graph with validation, backup, lab validation, lock, source-plan, approval, per-device simulation, and finalize steps.
4. Submit/approve moves the record through `pending_approval` and `approved`.
5. Lock reservation creates database-only device/workflow reservations.
6. Mark-ready requires validation success, planned steps, reserved locks, and approval if enabled.
7. Simulation updates DB step state and `dry_run_output` only; it never opens transport.
8. Reports are read-only and do not create duplicate audit events.

Change execution endpoints:

- `POST /api/v1/change-executions`
- `GET /api/v1/change-executions`
- `GET /api/v1/change-executions/{execution_id}`
- `POST /api/v1/change-executions/{execution_id}/validate`
- `GET /api/v1/change-executions/{execution_id}/validation-report`
- `POST /api/v1/change-executions/{execution_id}/plan`
- `GET /api/v1/change-executions/{execution_id}/plan`
- `POST /api/v1/change-executions/{execution_id}/submit`
- `POST /api/v1/change-executions/{execution_id}/approve`
- `POST /api/v1/change-executions/{execution_id}/reject`
- `POST /api/v1/change-executions/{execution_id}/reserve-locks`
- `POST /api/v1/change-executions/{execution_id}/mark-ready`
- `POST /api/v1/change-executions/{execution_id}/simulate`
- `POST /api/v1/change-executions/{execution_id}/cancel`
- `GET /api/v1/change-executions/{execution_id}/simulation-report`
- `GET /api/v1/change-executions/{execution_id}/audit`
- `GET /api/v1/change-executions/{execution_id}/locks`
- `GET /api/v1/change-executions/{execution_id}/report`

There is no apply permission because no apply endpoint exists. `viewer` can read, `network_operator` can plan and simulate, `network_admin` can manage and cancel, `security_admin` can approve, and `admin`/`super_admin` have all change execution permissions.

## Operator Console Backend

The Operator Console Backend is a read-only aggregation API for a future UI. It does not add a frontend and does not add any workflow action endpoint.

The console service reads existing tables and returns summaries for:

- health and device readiness;
- real-apply safety posture;
- inventory status;
- config backup status;
- lab validation status;
- password rollout jobs;
- VLAN workflow requests;
- change execution simulations;
- pending approvals;
- recent activity;
- risk summary.

Operator console endpoints:

- `GET /api/v1/operator-console/dashboard`
- `GET /api/v1/operator-console/health`
- `GET /api/v1/operator-console/safety`
- `GET /api/v1/operator-console/workflows`
- `GET /api/v1/operator-console/pending-approvals`
- `GET /api/v1/operator-console/recent-activity`
- `GET /api/v1/operator-console/risk-summary`
- `GET /api/v1/operator-console/device-health`
- `GET /api/v1/operator-console/change-executions`

All operator console endpoints are GET-only. They do not run discovery, credential validation, lab validation, config backup collection, restore planning, VLAN planning, change execution simulation, password rollout batches, or device apply.

RBAC adds `read_operator_console` for `viewer`, `network_operator`, `network_admin`, `security_admin`, `admin`, and `super_admin`. This permission grants no write, approval, simulation, backup, restore, or apply permissions.

Responses intentionally contain only counts, statuses, IDs, timestamps, and sanitized metadata. They do not return passwords, encrypted credential material, raw config text, private keys, or raw transcripts.

## Observability, Audit Export, And Reporting

The Observability layer is a read-only/export-only API for operational reporting and future dashboard/SIEM integration. It adds no workflow execution and no new persisted state.

It aggregates existing tables for:

- unified audit export;
- operational reports;
- compliance snapshots;
- safety posture reports;
- workflow activity reports;
- device readiness reports;
- metrics summaries.

Observability endpoints:

- `GET /api/v1/observability/audit-events`
- `GET /api/v1/observability/audit-export`
- `GET /api/v1/observability/operational-report`
- `GET /api/v1/observability/compliance-snapshot`
- `GET /api/v1/observability/safety-posture`
- `GET /api/v1/observability/workflow-activity`
- `GET /api/v1/observability/device-readiness`
- `GET /api/v1/observability/metrics-summary`

All endpoints are GET-only. There is no apply, run, simulate, backup, validate, POST, PUT, PATCH, or DELETE action in this router.

The report sanitizer recursively masks password, pass, secret, token, API key, private key, credential secret material, auth secret material, raw config, running/startup/candidate config, command output, and backup content fields. It keeps safe IDs, statuses, counts, timestamps, workflow type, device ID, hostname, vendor, and model metadata. Sanitization is deterministic and does not mutate inputs.

RBAC adds:

- `read_observability` for `viewer`, `network_operator`, `network_admin`, `security_admin`, `admin`, and `super_admin`;
- `export_audit_reports` for `network_admin`, `security_admin`, `admin`, and `super_admin`.

`read_observability` grants no manage, approve, simulate, cancel, run, backup, validate, or apply permissions.

## Transport Strategy And Driver Runtime

The Driver Runtime layer is a read-only decision service for vendor-aware transport selection. It does not replace Netmiko where Netmiko is appropriate, and it does not force every device through a universal wrapper.

Transport kinds:

- `netmiko` for profiled Cisco, Huawei, HPE/Comware, HPE ProCurve/ArubaOS-Switch, and Dell families;
- `paramiko` for direct SSH/session-control fallback and Generic SSH read-only profiles;
- `custom_cli` for vendor-specific nonstandard CLI state machines such as Eltex and Bulat;
- `icmp_only` for health/readiness only;
- `unsupported` for unknown or unsafe profiles.

Driver families:

- `cisco_ios`
- `cisco_nxos`
- `cisco_asa`
- `huawei_vrp`
- `hpe_comware`
- `hpe_procurve`
- `aruba_os_switch`
- `eltex`
- `bulat`
- `dell_os`
- `generic_ssh`
- `icmp`
- `unknown`

Endpoints:

- `GET /api/v1/driver-runtime/profiles`
- `GET /api/v1/driver-runtime/profiles/{family}`
- `GET /api/v1/driver-runtime/decision`
- `GET /api/v1/driver-runtime/devices/{device_id}/decision`
- `GET /api/v1/driver-runtime/summary`
- `GET /api/v1/driver-runtime/safety`

All endpoints are GET-only. There is no apply, run, POST, PUT, PATCH, DELETE, session-open, command execution, backup collection, lab validation, or credential validation action in this router.

Every runtime decision keeps:

- `config_apply_allowed=false`;
- `real_apply_certified=false`;
- `real_apply_certified_count=0`.

RBAC adds `read_driver_runtime` for `viewer`, `network_operator`, `network_admin`, `security_admin`, `admin`, and `super_admin`. The permission does not grant manage, approve, simulate, cancel, run, session-open, or apply rights.

### Legacy CLI Safety Alignment

The legacy CLI remains separate from the enterprise database, but its driver registry and transport factory now respect the same runtime capability matrix through a compatibility bridge.

Legacy alignment guarantees:

- `driver_for` uses the matrix for known Cisco, Huawei VRP, HPE Comware, HPE ProCurve/ArubaOS-Switch, Dell, Eltex, and Bulat families;
- Huawei Unknown Product and Unknown SNMP Product fail closed as unsupported instead of matching Huawei VRP only by vendor;
- Generic SSH and ICMP-only devices do not become config-capable CLI targets;
- `transport_for_plan` blocks config-changing plans before Netmiko or Paramiko transports are instantiated;
- `--transport netmiko` and `--transport paramiko` cannot bypass unsupported, ICMP, Generic SSH, Eltex, Bulat, or unknown safety;
- `netops apply` without `--dry-run` exits with a controlled safety error before credentials are requested, pre/post backup is run, or SSH transport is created;
- `netops apply --dry-run` and the `plan-*` commands remain available for planning;
- legacy `backup` remains read-only and must pass runtime decision safety before a transport is created.

No Netmiko `ConnectHandler`, Paramiko `SSHClient`, Scrapli session, config mode, save command, commit command, or copy running-config startup-config operation is enabled by this alignment. Real CLI apply is still postponed until the Apply Safety Kernel and lab-only real apply stages.

## Change Workflow

The intended production flow is:

1. User submits intent.
2. API validates payload.
3. Driver resolver maps each device to the safest available driver.
4. Planner generates dry-run commands, warnings, risks, capabilities, and rollback flags.
5. API returns masked dry-run and marks approval required.
6. Approved job creates per-device tasks.
7. Current VLAN executor locks each device, creates a pre-change backup, applies commands through the safe dummy transport, verifies state, saves only after verification, writes audit, and releases lock.
8. Failures are stored per task without secrets.

`POST /api/v1/jobs/vlan-change` now creates a database-backed job in `pending_approval`, stores the dry-run payload, creates or updates device rows, and creates per-device tasks. `POST /api/v1/jobs/{job_id}/run` executes only approved jobs and still uses the safe `DummyTransport` path. Dry-run entries marked for Scrapli or Netmiko execution are rejected while `NCP_ALLOW_REAL_DEVICE_APPLY=false`.

## Password Change Workflow

`POST /api/v1/jobs/password-change` creates a database-backed password job in `pending_approval`. The service:

- validates selected devices, username, and secret;
- resolves the exact driver per device;
- generates masked vendor-specific password commands;
- stores masked dry-run and masked task commands;
- stores the new password only in `password_change_secrets` encrypted with the configured cipher;
- creates canary rollout batches using 1, 5, 20, then the remainder;
- marks Bulat, Eltex, Generic SSH, and ICMP-only targets as not applyable unless their destructive templates are confirmed.

Password jobs cannot be executed through generic `POST /api/v1/jobs/{job_id}/run`; they must use `POST /api/v1/jobs/{job_id}/run-next-batch`. Each batch task:

1. checks approval, dry-run, backup-before-apply, verification requirement, confirmed driver template, and real-transport safety gates;
2. acquires a per-device lock;
3. creates an encrypted backup record before applying commands;
4. decrypts the new password only in memory;
5. renders exact driver commands in memory and sends them through `DummyTransport`;
6. verifies that the new credential works;
7. saves config only after credential verification succeeds;
8. writes sanitized audit events and releases the lock in the finally path.

If any canary task fails and `stop_on_first_failure=true`, the rollout job becomes `failed` and later batches cannot start. The encrypted password-change secret is deleted after a fully successful rollout.

Password rollout endpoints:

- `POST /api/v1/jobs/password-change`
- `GET /api/v1/jobs/{job_id}/rollout-plan`
- `POST /api/v1/jobs/{job_id}/run-next-batch`
- `POST /api/v1/jobs/{job_id}/pause`
- `POST /api/v1/jobs/{job_id}/resume`

## Credentials Encryption

Credentials are handled by `CredentialService` and `FernetCredentialCipher`.

- Passwords and enable passwords are encrypted before they enter the runtime store.
- API read responses never return password material.
- `NCP_SECRET_KEY` is required in production.
- Local/test environments may use the deterministic test key from settings so automated tests do not need secret provisioning.
- Credential create/delete actions write audit events with secret fields redacted.

Credential endpoints:

- `POST /api/v1/credentials`
- `GET /api/v1/credentials`
- `GET /api/v1/credentials/{credential_id}`
- `DELETE /api/v1/credentials/{credential_id}`

## Approval Workflow

Job statuses:

- `draft`
- `pending_approval`
- `approved`
- `queued`
- `running`
- `succeeded`
- `partially_failed`
- `failed`
- `cancelled`
- `paused`

Task statuses:

- `pending`
- `locked`
- `connecting`
- `backing_up`
- `applying`
- `verifying`
- `saving`
- `succeeded`
- `failed`
- `rollback_required`
- `rollback_succeeded`
- `rollback_failed`
- `skipped`

Approval rules:

- New VLAN jobs are created as `pending_approval`.
- Dry-run is stored on the job record.
- `apply_allowed=false` until a permitted actor approves.
- `POST /api/v1/jobs/{job_id}/approve` moves the job to `approved`.
- Approving an already approved job is idempotent.
- Cancelled jobs cannot be approved.
- `POST /api/v1/jobs/{job_id}/cancel` moves non-running/non-completed jobs to `cancelled` and skips pending tasks.

## Audit Log

`AuditService` writes structured audit events for:

- job creation;
- dry-run generation;
- job approval;
- job cancellation;
- backup creation;
- device lock/unlock;
- task start/success/failure/skip;
- password rollout batch creation/start/success/failure;
- password task backup/apply/credential verification/save events;
- credential creation/deletion.

Each event stores actor, action, object type, object id, optional device id, optional job id, before/after data, metadata, and timestamp. Metadata and nested structures are sanitized before storage.

`GET /api/v1/audit` supports filters:

- `actor`
- `action`
- `object_type`
- `device_id`
- `job_id`
- `date_from`
- `date_to`

## Backup Strategy

`BackupService` stores encrypted config text and a SHA-256 hash of the original config. API responses return masked config text.

Endpoints:

- `POST /api/v1/devices/{device_id}/backup`
- `GET /api/v1/devices/{device_id}/backups`
- `GET /api/v1/backups/{backup_id}`
- `GET /api/v1/backups/{backup_id}/diff/{other_backup_id}`

Diff output is produced with `difflib.unified_diff` and masked before it leaves the service.

## Device Locking

`LockService` provides per-device locks with expiration.

- A second task cannot lock a device while an active lock exists.
- Expired locks are treated as stale and can be replaced.
- Locks are released in the executor `finally` path.
- Lock and unlock events are audited.

## Execution Safety Guards

`JobExecutionService` enforces these checks before and during execution:

- job must be approved;
- job must not be cancelled;
- dry-run must exist;
- backup-before-apply must be enabled;
- device dry-run entry must have `apply_supported=true`;
- verification commands must exist;
- device lock must be acquired;
- backup must be created before config commands;
- save config runs only after verification succeeds.
- password jobs must run through canary rollout batches and cannot use the generic job run endpoint.
- inventory onboarding and discovery cannot run config commands, save commands, password changes, VLAN changes, ACL changes, or port changes.
- config backup jobs and restore plan previews cannot run config commands, save commands, password changes, VLAN changes, ACL changes, port changes, or restore apply.
- VLAN workflow hardening cannot run config commands, save commands, password changes, VLAN changes, ACL changes, port changes, or restore/apply actions.
- Change Execution Orchestrator simulation cannot open transports, send commands, save configs, collect backups, run password batches, or apply VLAN/ACL/port changes.
- Operator Console Backend cannot mutate state; it performs read-only aggregation and exposes no POST, PUT, PATCH, DELETE, apply, run, simulate, backup, or validation action endpoints.
- Observability reporting cannot mutate state; it performs read-only aggregation/export and exposes no POST, PUT, PATCH, DELETE, apply, run, simulate, backup, or validation action endpoints.
- Driver Runtime cannot mutate state; it performs read-only transport decisions and exposes no POST, PUT, PATCH, DELETE, apply, run, session-open, or command execution endpoints.
- Legacy CLI apply cannot bypass Driver Runtime decisions; destructive `netops apply` is blocked before SSH transport creation, while `--dry-run` and read-only backup remain available.

Tasks that violate a safety gate are marked `failed` or `skipped` with a sanitized reason.

## Why Real Apply Is Disabled By Default

Real network apply is disabled by default through `NCP_ALLOW_REAL_DEVICE_APPLY=false`. This protects production devices while driver templates are still being validated against real firmware.

The second-stage executor runs only through `DummyTransport`. If a dry-run device entry requests `scrapli` or `netmiko` transport while real apply is disabled, execution is blocked with a clear safety error.

## Lab Validation Gate

Lab validation is a database-backed approval record for a specific vendor, optional model pattern, driver, and capability. It is a future real-apply precondition, not a real-apply implementation.

The lab validation service allows operators to:

- create validation requests;
- attach sanitized command transcripts;
- maintain checklist items;
- approve, reject, or expire validations;
- enforce a gate before future destructive real transport execution.

When a future real-transport path is attempted, the gate requires:

- `NCP_ALLOW_REAL_DEVICE_APPLY=true`;
- an approved validation with matching vendor, driver, capability, and model pattern;
- a validation that is not expired.

If any condition fails, execution raises `SafetyError`. Even when the gate passes, the existing controls still apply: dry-run, approval, backup, verification, locks, audit, and save-after-verification. Current production execution still uses `DummyTransport`; this framework does not enable real Scrapli or Netmiko apply.

Lab validation endpoints:

- `POST /api/v1/lab-validations`
- `GET /api/v1/lab-validations`
- `GET /api/v1/lab-validations/{validation_id}`
- `POST /api/v1/lab-validations/{validation_id}/transcript`
- `POST /api/v1/lab-validations/{validation_id}/approve`
- `POST /api/v1/lab-validations/{validation_id}/reject`
- `POST /api/v1/lab-validations/{validation_id}/expire`
- `GET /api/v1/lab-validations/{validation_id}/checklist`
- `PATCH /api/v1/lab-validations/{validation_id}/checklist/{item_id}`

## Runnable Lab Prototype

The runnable lab prototype provides `scripts/lab_prototype.py` for local operator testing against 3-4 lab devices. It imports lab devices, creates encrypted credential refs, checks runtime decisions, collects sanitized read-only backups, renders dry-run command hashes, evaluates safety gates, and can execute lab-only Netmiko/Paramiko command plans after the Apply Safety Kernel allows the request.

This is not production apply. There is no generic `/apply`, no destructive `/run`, and production apply remains denied.

## How To Enable Lab-Only Apply Safely

`NCP_ALLOW_REAL_DEVICE_APPLY=true` should be treated as a lab-only gate, not as production enablement. Real lab execution also requires `NCP_LAB_REAL_APPLY_ENABLED=true`, `NCP_PRODUCTION_REAL_APPLY_ENABLED=false`, a lab-tagged allowlisted device, fresh backup, lab validation, approval metadata, matching command hash, rollback preview, device lock, credential ref, and RBAC permissions.

For a closed lab readiness exercise:

1. Use a dedicated inventory with non-production devices.
2. Confirm backup and verification commands manually for each firmware family.
3. Set `NCP_SECRET_KEY` to a lab-only random secret.
4. Set `NCP_ALLOW_REAL_DEVICE_APPLY=true`.
5. Set `NCP_LAB_REAL_APPLY_ENABLED=true`.
6. Keep `NCP_PRODUCTION_REAL_APPLY_ENABLED=false`.
7. Keep batch size at 1 until each driver template has a golden transcript.
8. Store all command transcripts with secrets removed.

Do not enable this setting in production until approval, rollback, and device-family golden tests are complete.

## Driver Strategy

Driver mapping:

- Huawei S57xx/S67xx/CE68xx/S17xx/S23xx/S24xx: `HuaweiVRPDriver`
- HPE 1910/1920/5130 and 3Com S4210/S5500: `HPComwareDriver`
- HPE 2510/2530: `HPEProCurveDriver`
- Eltex MES: `EltexMESDriver`, dry-run only until lab confirmation
- Bulat BS2500/BS6300: `BulatBSDriver`, dry-run only until lab confirmation
- Cisco Catalyst/Cat2960: `CiscoIOSDriver`
- Dell PowerConnect: `DellPowerConnectDriver`
- Unknown SNMP/Huawei Unknown: `GenericSSHDriver`
- ICMP-only: `ReadOnlyICMPDriver`

## Rollout Strategy

- VLAN/port/ACL changes require dry-run, approval, backup, verification, and save only after verification.
- Password changes must use canary rollout: 1 device, then 5, then 20, then the remainder.
- Batch size defaults to 10 or lower.
- Device locks prevent concurrent changes on the same switch.
- Drivers with unconfirmed templates return `apply_supported=false`.

## Testing Strategy

Current tests cover:

- driver resolver;
- secret masking;
- VLAN range parser;
- Huawei, Cisco, and HP Comware command rendering;
- dry-run planning;
- FastAPI VLAN endpoint;
- encrypted credentials;
- approval workflow;
- audit filters and masking;
- encrypted backups and masked diffs;
- device locks and stale lock replacement;
- execution safety gates;
- job status transitions;
- RBAC header permissions;
- existing CLI transport/backup tests.
- database repository and persistence tests for credentials, jobs, tasks, audit, backups, locks, and execution flow.
- observability sanitization, repository aggregation, JSON/CSV export, RBAC, empty state, and safety tests.
- driver runtime matrix decisions, adapter safety, API GET-only behavior, RBAC, and integration with inventory devices.

Real devices are not required for unit tests. Lab validation should add sanitized golden outputs and command transcripts by vendor/model/firmware.

## CLI Workflow Versus Enterprise API Workflow

The CLI workflow in `src/netops_orchestrator` remains file-driven and is intentionally not coupled to the enterprise database. It reads inventory files, renders command plans, dry-runs legacy apply previews, and can run read-only backups where the runtime matrix allows a safe CLI transport. Destructive legacy apply is blocked before credentials or SSH transport creation.

The Enterprise API workflow is stateful and database-backed. It stores devices, jobs, dry-runs, tasks, encrypted credentials, encrypted backups, audit events, and device locks. It keeps real network apply disabled by default and requires approval, backup, verification, lock acquisition, and audit before the safe executor path can run.
