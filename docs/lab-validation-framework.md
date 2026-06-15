# Lab Validation Framework

Lab validation records prove that a specific vendor, model pattern, driver, and capability has been tested in an isolated lab before any future destructive real-device apply is allowed.

This framework does not enable real apply automatically. The enterprise executor still uses `DummyTransport` for safe execution, and `NCP_ALLOW_REAL_DEVICE_APPLY=false` remains the default.

## Why It Exists

Network CLIs differ by firmware, platform family, privilege mode, and prompt behavior. A command template that is safe on one model can be unsafe on another. Lab validation creates an explicit evidence trail before a future real transport path can pass its safety gate.

## Data Captured

The platform stores:

- validation records in `lab_driver_validations`;
- sanitized transcripts in `lab_validation_transcripts`;
- checklist items in `lab_validation_checklists`.

Each validation is scoped to:

- vendor;
- optional platform;
- optional model pattern;
- driver name;
- capability, such as `vlan_change`, `password_change`, `acl_change`, `port_change`, or `config_backup`.

## API Workflow

Create a validation request:

```powershell
$body = @{
  vendor = "Cisco"
  model_pattern = "Cat2960*"
  driver_name = "CiscoIOSDriver"
  capability = "password_change"
  lab_environment = "isolated lab rack"
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri "http://localhost:8000/api/v1/lab-validations" `
  -Headers @{ "X-Actor" = "sec"; "X-Roles" = "security_admin" } `
  -ContentType "application/json" `
  -Body $body
```

Attach a sanitized transcript:

```powershell
$body = @{
  filename = "cat2960-password-change.txt"
  content_type = "text/plain"
  raw_text = $env:SANITIZED_LAB_TRANSCRIPT_SOURCE
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri "http://localhost:8000/api/v1/lab-validations/<validation_id>/transcript" `
  -Headers @{ "X-Actor" = "sec"; "X-Roles" = "security_admin" } `
  -ContentType "application/json" `
  -Body $body
```

The API never stores `raw_text`. It stores only `sanitized_text`, a SHA-256 hash of the sanitized text, and metadata.

Approve, reject, or expire:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://localhost:8000/api/v1/lab-validations/<validation_id>/approve" `
  -Headers @{ "X-Actor" = "sec"; "X-Roles" = "security_admin" } `
  -ContentType "application/json" `
  -Body '{"evidence_summary":"lab transcript reviewed"}'
```

Use `/reject` when evidence shows the template is unsafe. Use `/expire` when firmware, templates, or device behavior changed.

## Checklist Expectations

Password change validations include:

- connect to lab device;
- verify current credential works;
- render masked command plan;
- apply password change in isolated lab;
- verify new credential works;
- verify old credential no longer works, if safe;
- save config only after verification;
- reboot/reconnect check, if lab permits;
- confirm transcript sanitized;
- confirm rollback procedure documented.

VLAN change validations include:

- connect to lab device;
- create VLAN;
- assign VLAN to test port;
- verify running config;
- verify idempotent re-run;
- rollback VLAN;
- confirm transcript sanitized.

Generic destructive capabilities include:

- connect;
- dry-run;
- apply in lab;
- verify;
- rollback;
- sanitize transcript.

## Safety Gate

`LabValidationService.assert_real_apply_allowed(...)` passes only when all conditions are true:

- `NCP_ALLOW_REAL_DEVICE_APPLY=true`;
- a validation is approved;
- the validation is not expired;
- vendor matches;
- driver name matches;
- capability matches;
- model matches `model_pattern` when a pattern is set.

If any condition fails, the service raises `SafetyError` with a reason such as real apply disabled, no approved validation, expired validation, capability mismatch, driver mismatch, or model mismatch.

Even when this gate passes, it does not bypass the existing controls:

- dry-run;
- approval;
- backup before apply;
- verification before save;
- per-device locks;
- audit logging;
- secret masking.

## Vendor Caution

Bulat, Eltex, GenericSSH, and ICMP-only devices remain non-applyable through the existing `apply_supported=false` guard until their destructive templates are separately confirmed and the driver capability is intentionally changed. A lab validation record alone does not override that driver safety setting.

## Transcript Handling

Do not commit raw lab transcripts. Raw transcripts can include passwords, tokens, SNMP communities, private keys, and internal topology details.

The sanitizer masks common secret forms, including password commands, SNMP communities, bearer tokens, and private key blocks. Sanitization is a safety net, not a replacement for manual transcript review.

