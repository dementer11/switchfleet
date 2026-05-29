# Lab Validation

Before batch execution, validate each driver family on one access, one aggregation, and one core device where available.

## Required Capture

For every vendor/model/firmware profile, save sanitized transcripts for:

- login banner and initial prompt;
- privilege escalation if required;
- pager disable command;
- backup command;
- config mode enter/exit;
- one password change on a temporary user;
- one ACL create/update;
- one VLAN create/update;
- one port description/admin-state change;
- save command and any confirmation prompts;
- invalid command output.

## Acceptance Criteria

- `netops inventory` selects the expected driver and transport.
- `netops plan-backup` produces read-only commands only.
- `netops backup` captures the full config without pager artifacts.
- `netops apply --dry-run` redacts secrets unless `--show-secrets` is used.
- `netops apply --pre-backup --post-backup` creates both backups and a JSONL audit log.
- A failed command stops the current device unless `--continue-on-error` is set.
- Unknown vendors remain `unsupported_cli`.

## Golden Test Inputs

Add one sanitized transcript fixture per profile under `tests/fixtures/<driver>/<model>/`:

- `login.txt`
- `backup.txt`
- `config_success.txt`
- `config_error.txt`
- `save_prompt.txt`

Each fixture must remove real IP addresses, hostnames, usernames, passwords, SNMP communities, and internal network names.
