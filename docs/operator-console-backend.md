# Operator Console Backend

The Operator Console Backend is a read-only API layer for a future UI. It aggregates the enterprise runtime state that already exists in the platform and returns stable summaries for operators.

This stage does not add a frontend. It does not execute workflows, open transports, run backups, run lab validations, simulate changes, or apply device configuration.

## API

All endpoints are `GET` only under `/api/v1/operator-console`:

- `/dashboard`
- `/health`
- `/safety`
- `/workflows`
- `/pending-approvals`
- `/recent-activity`
- `/risk-summary`
- `/device-health`
- `/change-executions`

The endpoints require explicit `X-Actor` and `X-Roles` headers and the `read_operator_console` permission.

## Dashboard Sections

The dashboard response contains:

- health summary;
- safety posture;
- inventory summary;
- config backup summary;
- lab validation summary;
- workflow summaries;
- pending approvals;
- recent activity;
- risk summary;
- change execution summary.

The API returns counts, statuses, timestamps, workflow IDs, and sanitized metadata. It never returns passwords, encrypted credential material, raw config text, private keys, or raw command transcripts.

## Safety Posture

The safety section reports:

- `real_apply_enabled`;
- `real_apply_env_value`;
- whether apply endpoints are present;
- whether run endpoints are present;
- whether destructive run endpoints are present;
- whether lab validation, backup, and approval gates are required;
- whether unsupported destructive apply remains blocked.

`NCP_ALLOW_REAL_DEVICE_APPLY=false` remains the default. Existing safe workflow-specific run endpoints may exist, but the console reports destructive generic run/apply posture separately.

## Workflow Summaries

The console summarizes:

- password rollout jobs;
- VLAN workflow requests;
- config backup jobs;
- change execution simulations;
- lab validations.

Each summary includes totals and status buckets for draft, pending approval, approved, ready, running or simulating, completed or simulated, blocked, failed, cancelled, and recent records.

## Pending Approvals

Pending approvals are aggregated from:

- password rollout jobs;
- VLAN workflow approvals;
- change execution approvals.

Approval rows include only metadata: approval ID, workflow type, workflow ID, title, status, requester, created time, risk level, risk summary, and target count.

## Recent Activity

Recent activity is a unified, sanitized timeline from audit and workflow metadata:

- generic audit logs;
- VLAN workflow audit events;
- change execution audit events;
- config backup job activity;
- lab validation activity.

Metadata is summarized and secret-bearing keys are redacted before returning the response.

## Device Health

Device health rows include:

- device identity and driver metadata;
- status and credential assignment status;
- latest backup timestamp;
- latest matching approved lab validation timestamp;
- active workflow count;
- blocked reasons;
- risk level.

The backend uses existing database records only. It does not run discovery or credential checks from the console endpoints.

## RBAC

The `read_operator_console` permission is granted to:

- `viewer`;
- `network_operator`;
- `network_admin`;
- `security_admin`;
- `admin`;
- `super_admin`.

This permission is read-only. It does not grant workflow management, approval, simulation, backup execution, restore plan approval, or device apply permissions.

## Future Frontend Integration

A future frontend can call `/dashboard` for the initial operator landing page and use the narrower endpoints for paginated grids, filters, and drill-downs. The backend is intentionally read-only so the UI can be introduced without increasing the destructive-operation surface.
