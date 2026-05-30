# Password Change Rollout

This procedure is mandatory for local user password changes on network devices.

Password changes are high-risk because a failed credential can lock automation and operators out of a device. Do not run a broad password job until each canary stage has passed backup, apply, verification, audit review, and operator sign-off.

## Preconditions

1. Inventory is current and grouped by vendor, model, site, and role.
2. Current credentials are known and tested.
3. New credentials are stored through the encrypted credential API or supplied through a secret environment variable for CLI use.
4. Dry-run output has no unmasked password material.
5. Approval is recorded before apply.
6. Backup before apply is enabled.
7. Verification reconnects with the new credential.
8. Old credentials remain available until the rollout is complete.
9. A rollback or manual recovery plan exists for every device family.

## Canary Stages

### Stage 1: One Device

Select one low-risk device from the target driver family.

Required checks:

- backup captured and readable;
- command template matches the exact platform syntax;
- password command output contains no error;
- reconnect with the new credential succeeds;
- audit log contains create, approve, backup, task, and verification events;
- old credential handling is documented for recovery.

Stop if any check fails.

### Stage 2: Five Devices

Select five devices across different access stacks or closets, but keep the same vendor/model family where possible.

Required checks:

- no concurrent lock conflicts;
- every task has its own backup id;
- failed tasks do not continue into save;
- verification succeeds on all five devices;
- operators can still log in manually to at least one sampled device.

Stop if more than zero devices fail verification.

### Stage 3: Twenty Devices

Select twenty devices across at least two sites or roles when the inventory allows it.

Required checks:

- batch size stays within the approved limit;
- job status is `succeeded` or any failure has a documented manual resolution;
- audit events can be filtered by job id and device id;
- backup hashes are unique where configs differ;
- no password appears in API responses, logs, or artifacts.

Stop if failures repeat on the same model, firmware, or site.

### Stage 4: Remainder

Proceed only after stages 1, 2, and 3 are accepted.

Required checks:

- split remaining devices into bounded batches;
- keep one operator watching job progress and one operator available for manual device access;
- review failed tasks before launching the next batch;
- keep old credentials until the whole rollout has passed verification;
- record final audit and backup references in the change ticket.

## Failure Handling

- If reconnect with the new credential fails, mark the device failed and do not retry blindly.
- If backup fails, do not apply.
- If verification fails, do not save config.
- If a device lock is active, skip or reschedule that device.
- If a driver template is not confirmed, keep the device in dry-run only mode.

## Completion Criteria

A password rollout is complete only when:

- every targeted device has a successful verification result;
- failed devices have documented manual remediation;
- audit logs are reviewed;
- old credentials are retired according to local policy;
- updated credentials are stored encrypted and assigned to the correct scope.
