# Security Policy

## Supported Versions

Security fixes are applied to the current `main` branch and the latest published release.

## Reporting A Vulnerability

Do not open public issues with passwords, configs, IP plans, customer names, SNMP communities, private inventory exports, SSH transcripts, or other sensitive data.

Report vulnerabilities privately to the repository owner. Include:

- affected version or commit;
- component name, such as API, CLI, driver, transport, backup, credentials, or release packaging;
- sanitized reproduction steps;
- expected and observed behavior;
- security impact;
- sanitized logs or command transcripts when needed.

## Secret Handling Rules

- API credential read endpoints must never return password material.
- Credentials must be encrypted at rest through `NCP_SECRET_KEY`.
- Audit events must sanitize nested `password`, `enable_password`, `encrypted_password`, `encrypted_enable_password`, `secret`, and `token` fields.
- Command output and backup diffs must pass through secret masking before leaving service boundaries.
- Password-change jobs must store the new password only in encrypted temporary execution records.
- Password-change dry-runs, job payloads, task commands, audit events, and logs must contain only masked password material.
- Temporary password-change execution secrets must be removed after a successful rollout.
- Test fixtures and lab transcripts must be sanitized before commit.

## Destructive Operation Rules

Destructive network apply is guarded by default:

- dry-run must exist;
- job must be approved;
- backup before apply must be enabled;
- verification commands must exist;
- a per-device lock must be acquired;
- save commands run only after verification succeeds;
- real Scrapli/Netmiko apply is blocked while `NCP_ALLOW_REAL_DEVICE_APPLY=false`;
- Bulat, Eltex, and Generic SSH drivers must not run destructive apply until templates are confirmed in a lab.
- Password-change jobs must run through canary rollout batches and must not use the generic job run endpoint.

## Production Guidance

- Set a long random `NCP_SECRET_KEY` before production use.
- Keep `NCP_ALLOW_REAL_DEVICE_APPLY=false` outside an isolated lab until real-device execution is implemented and validated for every target platform.
- Use canary rollout for password changes: 1 device, 5 devices, 20 devices, then the remainder.
- Keep release artifacts and `.sha256` files together.
- Review audit logs after every approved change.
