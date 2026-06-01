# Observability, Audit Export, And Operational Reporting

The Observability layer is a read-only and export-only backend capability for audit, reporting, compliance, and future dashboards or SIEM integrations.

It does not add a frontend. It does not execute workflows. It does not open network transports.

## Scope

The layer aggregates existing database state from:

- audit logs;
- password rollout jobs;
- VLAN workflow requests and audit events;
- config backup jobs and snapshots;
- lab validation records;
- inventory import batches and device metadata;
- change execution simulations and audit events.

No new database tables are required. The repository performs SELECT-style aggregation only.

## Endpoints

All endpoints are under `/api/v1/observability` and are GET-only:

- `GET /audit-events`
- `GET /audit-export`
- `GET /operational-report`
- `GET /compliance-snapshot`
- `GET /safety-posture`
- `GET /workflow-activity`
- `GET /device-readiness`
- `GET /metrics-summary`

There is no `/apply`, `/run`, `/simulate`, `/backup`, `/validate`, POST, PUT, PATCH, or DELETE action in this router.

## Audit Export

`GET /api/v1/observability/audit-events` returns a JSON audit view for users with `read_observability`.

`GET /api/v1/observability/audit-export` returns JSON or CSV and requires `export_audit_reports`.

Supported filters:

- `from_datetime`
- `to_datetime`
- `workflow_type`
- `device_id`
- `severity`
- `status`
- `limit`
- `offset`

The default limit is 100 and the maximum export limit is 5000.

Unified audit records include:

- event id;
- event source;
- workflow type;
- workflow id;
- optional device id;
- actor;
- event type;
- severity;
- message;
- sanitized metadata;
- created timestamp.

## Operational Report

`GET /api/v1/observability/operational-report` returns a summary of:

- inventory status;
- credential status;
- config backup status;
- lab validation status;
- workflow counts;
- change execution counts;
- recent failures;
- pending approvals;
- blocked items;
- safety warnings.

CSV export is available with `format=csv` and requires `export_audit_reports`.

## Compliance Snapshot

`GET /api/v1/observability/compliance-snapshot` evaluates safe checks without executing commands:

- device has an inventory record;
- device has valid credentials;
- device has a recent backup;
- device has approved lab validation;
- device has no failed required workflow blockers;
- real apply is disabled;
- destructive reporting endpoints are absent;
- unsupported destructive apply remains blocked.

Evidence contains only sanitized IDs, statuses, counts, and timestamps.

## Safety Posture

`GET /api/v1/observability/safety-posture` reports safety findings such as:

- real apply enabled or disabled;
- apply endpoint exposure;
- destructive run endpoint exposure;
- backup/lab/approval requirement representation;
- unsupported vendor apply guard;
- secret exposure risk.

The default safe posture is:

- `real_apply_enabled=false`;
- no apply endpoint;
- no destructive generic run endpoint;
- metadata sanitizer enabled.

## Workflow Activity

`GET /api/v1/observability/workflow-activity` summarizes recent workflow state for:

- password rollouts;
- VLAN workflows;
- config backup jobs;
- lab validations;
- change execution simulations.

CSV export is available with `format=csv` and requires `export_audit_reports`.

## Device Readiness

`GET /api/v1/observability/device-readiness` reports:

- device id;
- hostname and management IP;
- vendor, model, and driver;
- credential status;
- latest backup status and timestamp;
- latest lab validation status and timestamp;
- readiness status;
- blocker reasons;
- risk level.

CSV export is available with `format=csv` and requires `export_audit_reports`.

## Metrics Summary

`GET /api/v1/observability/metrics-summary` returns counts and daily buckets for future dashboards:

- total devices;
- active devices;
- valid credentials;
- recent backups;
- recent lab validations;
- workflow counts by type and status;
- audit events by severity;
- blocked and failed item counts;
- daily audit/workflow time series.

## Sanitization

All report metadata is sanitized recursively before it is returned or exported.

Secret-like fields are masked, including:

- password and pass fields;
- secret fields;
- token and API key fields;
- private keys;
- credential secret material;
- auth tokens or auth secret material;
- raw config fields;
- running/startup/candidate config fields;
- command output;
- backup content.

The sanitizer is deterministic and does not mutate input dictionaries or lists.

Reports never return:

- raw config text;
- password values;
- encrypted credential material;
- private keys;
- raw command transcripts.

## RBAC

Permissions:

- `read_observability`
- `export_audit_reports`

Role mapping:

- `viewer`: read JSON reports only;
- `network_operator`: read JSON reports only;
- `network_admin`: read and export;
- `security_admin`: read and export;
- `admin` and `super_admin`: read and export.

`read_observability` grants no manage, approve, simulate, cancel, run, backup, validate, or apply permission.

## Safety Constraints

The Observability router is intentionally passive:

- no real device apply;
- no device commands;
- no SSH, Scrapli, Netmiko, or DummyTransport open;
- no workflow execution;
- no change simulation;
- no config backup collection;
- no lab validation execution;
- no credential validation execution;
- no destructive endpoint;
- no state mutation.

Existing workflow gates remain unchanged: approval, dry-run, backup, lab validation, verification, locks, audit, password canary rollout, VLAN preparation-only, config backup read-only, and change execution simulation-only.

## Future Integration

The JSON and CSV exports are intended for:

- SIEM ingestion;
- compliance archive snapshots;
- operations review packets;
- dashboards;
- monitoring and alerting adapters.

Any future streaming or scheduled export worker must keep the same read-only behavior and sanitization contract.
