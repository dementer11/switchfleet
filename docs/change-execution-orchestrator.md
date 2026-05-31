# Change Execution Orchestrator

The Change Execution Orchestrator is a simulation-only enterprise workflow for connecting existing preparation workflows into one controlled timeline.

It does not apply changes to devices. It does not expose `/apply`. It does not expose a destructive `/run`. It never opens SSH, Scrapli, Netmiko, or any transport to execute commands.

## Supported Sources

- `password_rollout`: existing password-change jobs and rollout tasks.
- `vlan_workflow`: existing VLAN workflow requests and per-device dry-run plans.
- `config_backup_job`: existing config backup jobs as dependency checks.
- `manual` and `composite`: metadata-only simulation placeholders.

## Workflow States

The intended simulation path is:

1. `draft`
2. `validated`
3. `pending_approval`
4. `approved`
5. `ready`
6. `simulating`
7. `simulated`

Blocked sources move to `blocked`. Rejected approvals move to `rejected`. Operator cancellation moves to `cancelled` and releases orchestration locks.

## Validation Dependencies

Validation checks:

- mode is exactly `simulation`;
- source object exists;
- source workflow is in an acceptable ready/approved state;
- fresh config snapshot exists for each target device when required;
- approved lab validation exists for each target device when required;
- no conflicting active orchestration lock exists.

The orchestrator reads existing source workflows. It does not collect backups, create lab validations, run password rollout batches, or build VLAN commands on devices.

## Planning

Planning creates a deterministic dry-run execution graph:

- validate source;
- check backup dependency;
- check lab validation dependency;
- check locks;
- build source plan;
- build rollback summary for VLAN sources;
- approval gate;
- per-device simulation steps;
- finalize.

VLAN steps include dry-run command text and rollback command text from the VLAN workflow. Password steps include operation metadata and masked command text. Backup steps state that collection is not started by the orchestrator.

## Simulation

Simulation is database-only:

- execution moves `ready -> simulating -> simulated`;
- each step moves `pending -> running -> simulated`;
- `dry_run_output` records what would happen;
- no commands are sent to devices;
- no credentials or raw configs are returned;
- repeated simulation is blocked after `simulated`.

GET report endpoints are read-only and do not create duplicate audit events or steps.

## Locks

Locks are orchestration-level database reservations only. They do not block external systems and do not open network connections.

Lock types:

- `device`;
- `workflow`;
- `credential`;
- `site`;
- `vlan`.

Current reservation uses device and source workflow locks for simulation readiness. Cancellation releases reserved locks.

## Approval

Approval is required by default:

- submit moves `validated -> pending_approval`;
- approve is allowed only from `pending_approval`;
- mark-ready requires validation success, planned steps, reserved locks, and approval if enabled.

Security administrators approve. Network administrators manage and cancel. Operators can plan and simulate but cannot approve.

## RBAC

- `viewer`: read change executions.
- `network_operator`: read, plan, and simulate.
- `network_admin`: read, manage, plan, simulate, and cancel.
- `security_admin`: read and approve.
- `admin` and `super_admin`: all permissions.

There is no apply permission because no apply endpoint exists.

## Safety Guarantees

- Real apply remains disabled by default.
- `NCP_ALLOW_REAL_DEVICE_APPLY=false` remains the default safety gate.
- No `/apply` endpoint exists.
- No destructive `/run` endpoint exists.
- No transport open, `send_config`, `save_config`, `write memory`, `commit`, or `copy running-config startup-config` is called by this workflow.
- Lab Validation, backup requirements, approval, existing password rollout, VLAN workflow, config backup, and inventory safety gates are not bypassed.

Future live apply is out of scope and must remain gated by dry-run, approval, fresh backup, lab validation, locks, verification, audit, and explicit real-apply controls.
