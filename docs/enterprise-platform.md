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

Repositories live under `app/repositories/` and are the only layer that performs SQLAlchemy queries for enterprise runtime objects. Routers do not contain SQLAlchemy queries.

Alembic revision `20260530_0001` creates the enterprise tables and includes a downgrade path. The migration uses PostgreSQL-native UUID, JSONB, and INET types on PostgreSQL and portable UUID string, JSON, and string IP columns on SQLite test databases.

## Change Workflow

The intended production flow is:

1. User submits intent.
2. API validates payload.
3. Driver resolver maps each device to the safest available driver.
4. Planner generates dry-run commands, warnings, risks, capabilities, and rollback flags.
5. API returns masked dry-run and marks approval required.
6. Approved job creates per-device tasks.
7. Current executor locks each device, creates a pre-change backup, applies commands through the safe dummy transport, verifies state, saves only after verification, writes audit, and releases lock.
8. Failures are stored per task without secrets.

`POST /api/v1/jobs/vlan-change` now creates a database-backed job in `pending_approval`, stores the dry-run payload, creates or updates device rows, and creates per-device tasks. `POST /api/v1/jobs/{job_id}/run` executes only approved jobs and still uses the safe `DummyTransport` path. Dry-run entries marked for Scrapli or Netmiko execution are rejected while `NCP_ALLOW_REAL_DEVICE_APPLY=false`.

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

Tasks that violate a safety gate are marked `failed` or `skipped` with a sanitized reason.

## Why Real Apply Is Disabled By Default

Real network apply is disabled by default through `NCP_ALLOW_REAL_DEVICE_APPLY=false`. This protects production devices while driver templates are still being validated against real firmware.

The second-stage executor runs only through `DummyTransport`. If a dry-run device entry requests `scrapli` or `netmiko` transport while real apply is disabled, execution is blocked with a clear safety error.

## How To Enable Lab-Only Apply Safely

The current release does not connect the enterprise executor to real Scrapli or Netmiko apply. `NCP_ALLOW_REAL_DEVICE_APPLY=true` should be treated as a lab-readiness gate for future real transport execution, not as production enablement.

For a closed lab readiness exercise:

1. Use a dedicated inventory with non-production devices.
2. Confirm backup and verification commands manually for each firmware family.
3. Set `NCP_SECRET_KEY` to a lab-only random secret.
4. Set `NCP_ALLOW_REAL_DEVICE_APPLY=true`.
5. Keep batch size at 1 until each driver template has a golden transcript.
6. Store all command transcripts with secrets removed.

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

Real devices are not required for unit tests. Lab validation should add sanitized golden outputs and command transcripts by vendor/model/firmware.

## CLI Workflow Versus Enterprise API Workflow

The CLI workflow in `src/netops_orchestrator` remains file-driven and is intentionally not coupled to the enterprise database. It reads inventory files, renders command plans, and can execute explicit CLI operations with operator-provided credentials.

The Enterprise API workflow is stateful and database-backed. It stores devices, jobs, dry-runs, tasks, encrypted credentials, encrypted backups, audit events, and device locks. It keeps real network apply disabled by default and requires approval, backup, verification, lock acquisition, and audit before the safe executor path can run.
