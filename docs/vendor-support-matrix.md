# Vendor Support Matrix

SwitchFleet Local is the primary supported workflow for this release. Enterprise
FastAPI/PostgreSQL paths remain optional/prototype unless explicitly marked
otherwise below.

Config apply is not production-ready. Production apply remains disabled. Real
lab execution is eligible only through the Excel-first safety gates: allowlist,
fresh sanitized backup, stored dry-run hash, runtime-bound certification,
evaluation, lock, and credential-use checks.

| Vendor / Family | Detection Path | Backup Support | Dry-Run Support | Config Apply Support Level | Real Apply Eligibility | Execution Path | Tested Status | Notes / Limitations |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Huawei VRP | Excel vendor/model normalization, runtime matrix, vendor contracts | Supported for profiled switches | Supported for explicit templates | Lab candidate only | Excel-first lab gates only; no production | Excel-first, enterprise decision API, legacy read-only | Simulated plus controlled lab candidate | Firmware prompt and paging behavior still needs per-model validation. |
| HPE / 3Com Comware | HPE/3Com model normalization and Comware contract | Supported, including interactive pager handling | Supported for explicit templates | Lab candidate only | Excel-first lab gates only; no production | Excel-first, enterprise decision API, legacy read-only | Real-lab backup exercised; apply remains gated | Some legacy switches do not support paging-disable commands. |
| HPE ProCurve / ArubaOS-Switch | HPE model normalization and ProCurve contract | Supported where CLI is profiled | Supported for explicit templates | Lab candidate only | Excel-first lab gates only; no production | Excel-first, enterprise decision API, legacy read-only | Simulated | Syntax varies across firmware trains. |
| QTECH | QTECH model normalization and explicit QTECH profile | Supported for profiled read-only backup | Dry-run where explicit templates exist | Blocked until exact lab certification/policy | Not eligible by default | Excel-first, legacy read-only | Real-lab backup exercised | Config apply remains blocked by certification/runtime gates. |
| Eltex MES | Eltex MES normalization and explicit Eltex profile | Supported for profiled read-only backup | Dry-run where explicit templates exist | Blocked until exact lab certification/policy | Not eligible by default | Excel-first, legacy read-only | Real-lab backup exercised | Config apply remains blocked by certification/runtime gates. |
| Bulat | Bulat model normalization and Bulat profile | Limited read-only where profiled | Dry-run only where explicit templates exist | Blocked until exact lab certification/policy | Not eligible by default | Excel-first, enterprise decision API | Simulated | Destructive templates are intentionally not broadly enabled. |
| Dell PowerConnect | Dell model normalization and PowerConnect profile | Supported for profiled switches | Supported for explicit templates | Lab candidate only | Excel-first lab gates only; no production | Excel-first, enterprise decision API, legacy read-only | Simulated | Save/commit behavior requires controlled lab validation. |
| Cisco IOS | Cisco/Catalyst model normalization and IOS contract | Supported for profiled switches | Supported for explicit templates | Lab candidate only | Excel-first lab gates only; no production | Excel-first, enterprise decision API, legacy read-only | Simulated | Netmiko device type must match firmware. |
| D-Link unmanaged | D-Link unmanaged model normalization | Inventory/health only | Not supported for config | Unsupported | Not eligible | Excel-first inventory only | Blocked | Unmanaged devices are not CLI config targets. |
| SecurityCode Continent non-switch | Security appliance classification | Inventory only | Not supported for switch config | Unsupported | Not eligible | Excel-first inventory only | Blocked | Non-switch/security appliances are excluded from switch config apply. |
| ICMP / Unknown | ICMP-only and unknown/ambiguous normalization | Health/inventory only | Not supported for config | Unsupported | Not eligible | Excel-first inventory/readiness only | Blocked | Fail-closed by design. |
| GenericSSH | Explicit generic SSH profile only | Read-only only when explicitly profiled | Dry-run/read-only only | Unsupported for config apply | Not eligible | Excel-first read-only candidate, legacy read-only | Blocked for config | Generic SSH cannot perform destructive apply until a vendor profile is certified. |

Enterprise API notes:

- Driver-runtime endpoints are read-only decision endpoints.
- Change execution orchestration is simulation-only.
- The database-backed generic job `/run` path uses `DummyTransport` in this
  release and must be treated as simulated/non-production.
- No generic API `/apply` endpoint exists.
