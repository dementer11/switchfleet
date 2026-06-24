# Runnable Lab Prototype Example

This directory contains lab-only examples. They do not enable production apply.

## Excel-first local mode

Use `inventory.example.xlsx` with the primary local CLI:

```powershell
switchfleet examples/lab/inventory.example.xlsx doctor
switchfleet examples/lab/inventory.example.xlsx summary
switchfleet examples/lab/inventory.example.xlsx list
switchfleet examples/lab/inventory.example.xlsx check-runtime --device 192.0.2.10
```

The Excel example uses only documentation-range lab IP addresses and includes supported, candidate, and blocked classifications:

- Huawei VRP
- HPE Comware
- HPE ProCurve
- QTECH
- Eltex MES
- Bulat
- Dell PowerConnect
- Cisco IOS
- D-Link unmanaged
- SecurityCode Continent as non-switch
- Unknown SNMP inventory-only
- ICMP health-only

Set the lab allowlist to device IP addresses before backup or apply evaluation:

```powershell
$env:NCP_LAB_DEVICE_ALLOWLIST = "192.0.2.10"
```

Keep production apply disabled:

```powershell
$env:NCP_PRODUCTION_REAL_APPLY_ENABLED = "false"
```

## Optional DB-backed prototype mode

`devices.example.yaml` is for the older DB-backed enterprise prototype path. Use it only when you intentionally run the SQLAlchemy/PostgreSQL-backed helper:

```powershell
python scripts/lab_prototype.py import-devices examples/lab/devices.example.yaml
```

Then set the lab allowlist to management IPs returned by the DB import:

```powershell
$env:NCP_LAB_DEVICE_ALLOWLIST = "198.51.100.11,198.51.100.12"
```
