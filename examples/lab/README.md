# Runnable Lab Prototype Example

This example file is for lab-only device onboarding. It does not enable production apply.

Import the example devices:

```powershell
python scripts/lab_prototype.py import-devices examples/lab/devices.example.yaml
```

Then set the lab allowlist to device IDs, hostnames, or management IPs returned by the import:

```powershell
$env:NCP_LAB_DEVICE_ALLOWLIST = "sw1-lab,sw2-lab,192.168.88.11,192.168.88.12"
```

Keep production apply disabled:

```powershell
$env:NCP_PRODUCTION_REAL_APPLY_ENABLED = "false"
```
