# Lab Validation

Use this procedure before any real device execution is connected to the enterprise executor or before broad CLI execution against production-like equipment.

Validate every vendor/model/firmware profile independently. Similar model names can have different privilege modes, save prompts, ACL syntax, VLAN semantics, and pager behavior.

## Scope Selection

For each driver family, select:

1. One access switch.
2. One aggregation switch where available.
3. One core switch where available.
4. One device with an older firmware train if the fleet contains mixed firmware.

Do not validate Bulat, Eltex, or Generic SSH write operations against production devices until the exact command template is confirmed and reviewed.

## Preparation

1. Create a lab inventory containing only test devices.
2. Confirm console or out-of-band recovery access.
3. Create a temporary local user for password-change testing.
4. Pick a temporary VLAN id that is not used by live ports.
5. Pick one unused or lab-connected interface for port tests.
6. Prepare a non-production ACL name or number.
7. Set `NCP_SECRET_KEY` to a lab-only value.
8. Keep `NCP_ALLOW_REAL_DEVICE_APPLY=false` for API tests in this release.

## Required Capture

For every vendor/model/firmware profile, save sanitized transcripts for:

- login banner and initial prompt;
- privilege escalation if required;
- pager disable command;
- backup command;
- config mode enter and exit;
- one password change on a temporary user;
- one ACL create or update;
- one VLAN create, rename, and delete;
- one access-port change;
- one trunk-port change if the platform supports trunks;
- one port description and admin-state change;
- save command and every confirmation prompt;
- invalid command output;
- failed authentication output without real usernames or addresses.

## Step-By-Step Validation

Use the Excel-first `switchfleet` command for runnable local validation. The older legacy apply command path is
intentionally blocked for destructive execution and should be used only for legacy dry-run/plan inspection.

1. Run inventory recognition:

   ```powershell
   switchfleet inventory.xlsx check-runtime --device 192.0.2.67
   ```

   Confirm the selected driver and transport match the device family.

2. Run the local readiness summary:

   ```powershell
   switchfleet inventory.xlsx doctor
   switchfleet inventory.xlsx summary
   ```

   Confirm the Excel file is readable, DB setup is not required, and unsupported/non-switch/ICMP rows fail closed.

3. Store a credential reference:

   ```powershell
   $env:NCP_SECRET_KEY = "replace-with-long-random-lab-secret"
   switchfleet inventory.xlsx add-credential --name lab-admin --username labadmin --password-prompt
   ```

   Confirm `.switchfleet_lab/credentials.json` contains only encrypted payloads and no plaintext password.

4. Capture a read-only backup:

   ```powershell
   $env:NCP_LAB_DEVICE_ALLOWLIST = "192.0.2.67"
   switchfleet inventory.xlsx backup --device 192.0.2.67 --credential lab-admin
   ```

   Confirm the backup is sanitized, complete, and has no pager artifacts.

5. Render dry-runs:

   ```powershell
   switchfleet inventory.xlsx dry-run --device 192.0.2.67 --operation vlan_create --vlan-id 3999 --name LAB_CANARY
   $env:NEW_SWITCH_PASS = "lab-new-password"
   switchfleet inventory.xlsx dry-run --device 192.0.2.67 --operation password_change --username lab-temp --new-password-env NEW_SWITCH_PASS
   ```

   Confirm commands match the exact CLI syntax for the platform and secret commands are redacted in output and state.

6. Evaluate gates:

   ```powershell
   switchfleet inventory.xlsx evaluate-apply --device 192.0.2.67 --credential lab-admin --operation vlan_create --vlan-id 3999 --name LAB_CANARY --simulation-hash <hash-from-dry-run>
   ```

   Confirm evaluation does not decrypt credentials or open SSH and denies until backup, certification, hash, allowlist,
   and lock gates are satisfied.

7. Record lab-only certification evidence:

   ```powershell
   switchfleet inventory.xlsx certify --device 192.0.2.67 --capability vlan_create --credential lab-admin
   switchfleet inventory.xlsx certification-report
   ```

   Confirm certification remains lab-only and does not mark the device production-certified.

8. Execute a single-device Excel lab apply only when console recovery is available:

   ```powershell
   $env:NCP_ALLOW_REAL_DEVICE_APPLY = "true"
   $env:NCP_LAB_REAL_APPLY_ENABLED = "true"
   $env:NCP_PRODUCTION_REAL_APPLY_ENABLED = "false"
   switchfleet inventory.xlsx execute-apply --device 192.0.2.67 --credential lab-admin --operation vlan_create --vlan-id 3999 --name LAB_CANARY --simulation-hash <hash-from-dry-run> --real-lab
   ```

   Confirm the safety decision is allowed before credential decrypt or SSH transport creation.

9. Verify manually on the switch with show/display commands.

10. Remove temporary VLANs, ACLs, users, and descriptions after validation.

## Acceptance Criteria

- Inventory selects the expected driver and transport.
- Backup captures the full config without pager artifacts.
- Dry-run redacts secrets unless `--show-secrets` is intentionally used.
- The command template matches the exact firmware syntax.
- Save prompts are handled or explicitly documented as unsupported.
- Failed commands stop the current device unless `--continue-on-error` is intentionally used.
- Pre-change and post-change backups are written.
- Audit JSONL records contain no passwords, SNMP communities, tokens, or internal secrets.
- Unknown vendors remain read-only or unsupported.
- Bulat, Eltex, and Generic SSH remain dry-run only until templates are confirmed.

## Golden Test Inputs

Add one sanitized transcript fixture per profile under `tests/fixtures/<driver>/<model>/`:

- `login.txt`
- `backup.txt`
- `config_success.txt`
- `config_error.txt`
- `save_prompt.txt`
- `verification_success.txt`
- `verification_failed.txt`

Each fixture must remove real IP addresses, hostnames, usernames, passwords, SNMP communities, internal network names, ticket numbers, and organization identifiers.

## Promotion Checklist

A driver template can be marked confirmed only after:

1. Backup, VLAN, port, ACL, password, verification, and save behavior are validated for the target firmware.
2. Golden transcripts are reviewed and sanitized.
3. Unit tests cover generated commands and failure handling.
4. A canary run on one lab device completes successfully.
5. Rollback or manual recovery steps are documented.
