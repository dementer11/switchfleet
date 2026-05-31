# Inventory Onboarding

Inventory onboarding is a read-only metadata workflow for adding and validating network devices before any change job is created.

It does not enable real device apply. It does not run configuration commands. It prepares device records, driver reports, credential assignment status, and reachability status so later change workflows can stay controlled.

## Import Modes

`POST /api/v1/inventory/import` accepts API/JSON-style inventory records:

```json
{
  "source_type": "api",
  "filename": "inventory.json",
  "dry_run": true,
  "strict": false,
  "items": [
    {
      "ip": "10.0.0.1",
      "hostname": "sw-core-1",
      "vendor": "Huawei",
      "model": "S5735",
      "site": "HQ",
      "tags": ["core"],
      "credential_name": "core-ssh"
    }
  ]
}
```

`dry_run=true` creates an import batch and row-level validation report, but it does not create or update device records.

`dry_run=false` idempotently creates or updates device metadata by management IP. Existing devices are updated instead of duplicated.

## Supported Columns

The parser accepts common aliases:

- `ip`, `ip_address`, `management_ip`
- `host`, `hostname`, `name`
- `vendor`, `manufacturer`
- `model`
- `platform`
- `site`
- `location`
- `rack`
- `role`
- `tags`
- `credential_name`

Tags can be a JSON list or a comma/semicolon separated string.

## Normalization

The normalizer validates management IP and derives:

- `normalized_vendor`
- `normalized_model`
- `platform`
- normalized tag labels

Known families include Huawei VRP, Cisco IOS, HP/HPE/3Com Comware, HPE ProCurve, Eltex MES, Bulat BS, Dell PowerConnect, QSW, D-Link, Continent, Unknown SNMP, and ICMP-only.

Unknown devices are not rejected only because a driver is not exact. They are reported with warnings and mapped to `GenericSSHDriver` or `ReadOnlyICMPDriver` where appropriate.

## Driver Resolution Report

`GET /api/v1/inventory/imports/{batch_id}/driver-resolution-report` returns:

- device or row id;
- hostname and management IP;
- original and normalized vendor/model;
- selected driver;
- driver resolution status;
- supported capabilities;
- whether destructive apply is supported by the confirmed driver template;
- warnings and unsupported reason.

Bulat, Eltex, GenericSSH, and ICMP-only targets remain blocked by existing `apply_supported=false` and driver capability guards. A report does not make those devices applyable.

## Credential Assignment

Inventory rows may include `credential_name`.

If the credential exists, the response returns only safe metadata:

- id;
- name;
- username;
- status.

Passwords and encrypted password fields are never returned. Missing credentials are warnings in non-strict mode and invalid rows in strict mode.

## Discovery

Discovery endpoints are read-only:

- `POST /api/v1/inventory/devices/{device_id}/check-reachability`
- `POST /api/v1/inventory/imports/{batch_id}/check-reachability`
- `GET /api/v1/inventory/imports/{batch_id}/discovery-report`

The implementation supports safe reachability status and safe fact updates such as hostname, serial number, OS version, platform, and last seen timestamp. Tests use `DummyTransport` and only call read-only command paths.

Discovery does not run config mode, save config, password changes, VLAN changes, ACL changes, or port changes.

## RBAC

- `viewer` and `network_operator`: read inventory.
- `network_admin`, `security_admin`, `admin`, `super_admin`: manage inventory.
- `network_operator`, `network_admin`, `security_admin`, `admin`, `super_admin`: run read-only discovery.

## Limitations

Inventory onboarding is not a substitute for lab validation. It prepares normalized records and reports so operators can understand driver coverage before creating change jobs.

Real Scrapli/Netmiko apply remains disabled by default. Lab validation approval, approval workflow, dry-run, backup, verification, locks, audit, and password canary rollout remain separate safety layers.
