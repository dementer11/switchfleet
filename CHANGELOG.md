# Changelog

## v0.3.0 - SwitchFleet Local Excel-first MVP

### Highlights

* Excel-first local workflow for switch administration.
* Local state under `.switchfleet_lab/`.
* Encrypted credentials.
* Sanitized backups and local records.
* Read-only backup and dry-run remain mandatory before apply.
* Evaluate/certify/execute gates hardened and runtime-bound.
* Generic interactive CLI pager handling for backups.
* Generic cleanup of terminal artifacts from backup output.
* Cross-platform CLI smoke coverage for Windows and macOS.

### Safety

* Main workflow remains DB-independent.
* Dry-run/evaluate do not decrypt credentials or open SSH.
* Real execute revalidates allowlist, runtime, credential, backup, dry-run hashes, certification, forbidden commands, and locks before decrypt/transport.
* Unknown/GenericSSH/ICMP/non-switch devices fail closed for config apply.
* Production apply remains disabled by default.
* No unsafe generic `/apply` or destructive `/run`.

### Known limits

* Real firmware-specific behavior, prompts, paging, save behavior, and transport timing must still be validated in controlled lab conditions.
* Excel-first mode is the primary supported local workflow for this release.
