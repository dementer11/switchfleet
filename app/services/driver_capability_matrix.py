from __future__ import annotations

import re
from collections.abc import Iterable

from app.core.transport_strategy import DeviceFamily, DriverCapability, DriverRuntimeProfile, TransportDecision, TransportKind

READ_ONLY = frozenset({DriverCapability.read_only, DriverCapability.supports_dry_run})
CLI_PLANNING = frozenset(
    {
        DriverCapability.read_only,
        DriverCapability.prompt_detection,
        DriverCapability.privilege_mode,
        DriverCapability.config_mode,
        DriverCapability.config_staging,
        DriverCapability.commit_or_save,
        DriverCapability.rollback_prepare,
        DriverCapability.supports_dry_run,
        DriverCapability.requires_lab_certification,
    }
)
CUSTOM_CLI_PLANNING = frozenset(
    {
        DriverCapability.read_only,
        DriverCapability.prompt_detection,
        DriverCapability.privilege_mode,
        DriverCapability.config_staging,
        DriverCapability.supports_dry_run,
        DriverCapability.requires_lab_certification,
    }
)


RUNTIME_PROFILES: tuple[DriverRuntimeProfile, ...] = (
    DriverRuntimeProfile(
        vendor="Cisco",
        family=DeviceFamily.cisco_ios,
        model_pattern=r"(catalyst|cat2960|37xx|ios)",
        platform_pattern=r"(ios|cisco_ios)",
        preferred_transport=TransportKind.netmiko,
        fallback_transport=TransportKind.paramiko,
        capabilities=CLI_PLANNING,
        driver_name="CiscoIOSDriver",
        config_apply_supported=True,
        notes="Cisco IOS has a mature Netmiko profile; real apply still requires lab certification and global enablement.",
    ),
    DriverRuntimeProfile(
        vendor="Cisco",
        family=DeviceFamily.cisco_nxos,
        model_pattern=r"(nx-os|nxos|nexus)",
        platform_pattern=r"(nx-os|nxos|cisco_nxos)",
        preferred_transport=TransportKind.netmiko,
        fallback_transport=TransportKind.paramiko,
        capabilities=CLI_PLANNING,
        driver_name="CiscoNXOSDriver",
        config_apply_supported=True,
        notes="NX-OS is represented for strategy decisions; no first-party write driver is enabled in this stage.",
    ),
    DriverRuntimeProfile(
        vendor="Cisco",
        family=DeviceFamily.cisco_asa,
        model_pattern=r"(asa|adaptive security appliance)",
        platform_pattern=r"(asa|cisco_asa)",
        preferred_transport=TransportKind.netmiko,
        fallback_transport=TransportKind.custom_cli,
        capabilities=CLI_PLANNING,
        driver_name="CiscoASADriver",
        config_apply_supported=True,
        notes="ASA may require profile-specific CLI handling; real apply remains uncertified.",
    ),
    DriverRuntimeProfile(
        vendor="Huawei",
        family=DeviceFamily.huawei_vrp,
        model_pattern=r"((^|\s)(s17|s23|s24|s57|s67)\d*|ce68|vrp)",
        platform_pattern=r"(vrp|huawei_vrp)",
        preferred_transport=TransportKind.netmiko,
        fallback_transport=TransportKind.paramiko,
        capabilities=CLI_PLANNING,
        driver_name="HuaweiVRPDriver",
        config_apply_supported=True,
        notes="Huawei VRP prefers Netmiko when the model is profiled; Paramiko/custom CLI remains the fallback path.",
    ),
    DriverRuntimeProfile(
        vendor="HPE",
        family=DeviceFamily.limited_web,
        model_pattern=r"(hpe\s*)?(1620|1820|1905)|des[-\s]?1100|limited web|unmanaged",
        platform_pattern=r"(limited_web|unmanaged)",
        preferred_transport=TransportKind.unsupported,
        fallback_transport=None,
        capabilities=frozenset(),
        driver_name="LimitedWebInventoryDriver",
        config_apply_supported=False,
        read_only_supported=False,
        unsupported_reason="Limited web-managed or unmanaged devices are inventory-only in Excel lab mode.",
        notes="No CLI backup or config apply is attempted for limited web/unmanaged devices.",
    ),
    DriverRuntimeProfile(
        vendor="HPE",
        family=DeviceFamily.hpe_comware,
        model_pattern=r"(1910|1920|1950|5130|s4210|s5500|3com s4210|3com s5500|comware)",
        platform_pattern=r"(comware|hp_comware)",
        preferred_transport=TransportKind.netmiko,
        fallback_transport=TransportKind.custom_cli,
        capabilities=CLI_PLANNING,
        driver_name="HPComwareDriver",
        config_apply_supported=True,
        notes="Comware-like HPE/3Com devices can use Netmiko where profiled; legacy prompt behavior may need custom CLI.",
    ),
    DriverRuntimeProfile(
        vendor="HPE",
        family=DeviceFamily.hpe_procurve,
        model_pattern=r"(2510|2530|procurve)",
        platform_pattern=r"(procurve|hp_procurve)",
        preferred_transport=TransportKind.netmiko,
        fallback_transport=TransportKind.custom_cli,
        capabilities=CLI_PLANNING,
        driver_name="HPEProCurveDriver",
        config_apply_supported=True,
        notes="ProCurve/ArubaOS-Switch strategy prefers Netmiko with custom CLI fallback for legacy prompts.",
    ),
    DriverRuntimeProfile(
        vendor="Aruba",
        family=DeviceFamily.aruba_os_switch,
        model_pattern=r"(aruba|arubaos|aruba os-switch)",
        platform_pattern=r"(aruba_os_switch|arubaos_switch)",
        preferred_transport=TransportKind.netmiko,
        fallback_transport=TransportKind.custom_cli,
        capabilities=CLI_PLANNING,
        driver_name="HPEProCurveDriver",
        config_apply_supported=True,
        notes="ArubaOS-Switch is aligned with the ProCurve-style runtime strategy.",
    ),
    DriverRuntimeProfile(
        vendor="QTECH",
        family=DeviceFamily.qtech,
        model_pattern=r"(qsw[-\s]?(4610|3750))",
        platform_pattern=r"(qtech|qsw)",
        preferred_transport=TransportKind.custom_cli,
        fallback_transport=TransportKind.paramiko,
        capabilities=READ_ONLY,
        driver_name="QtechQswDriver",
        config_apply_supported=False,
        unsupported_reason="QTECH config apply is blocked until templates are explicitly certified.",
        notes="QTECH inventory/runtime classification is explicit; only read-only backup/dry-run metadata is allowed now.",
    ),
    DriverRuntimeProfile(
        vendor="Dell",
        family=DeviceFamily.dell_os,
        model_pattern=r"(powerconnect)",
        platform_pattern=r"(dell|powerconnect)",
        preferred_transport=TransportKind.netmiko,
        fallback_transport=TransportKind.custom_cli,
        capabilities=CLI_PLANNING,
        driver_name="DellPowerConnectDriver",
        config_apply_supported=True,
        notes="Dell PowerConnect can use Netmiko where supported, with custom CLI fallback.",
    ),
    DriverRuntimeProfile(
        vendor="Eltex",
        family=DeviceFamily.eltex,
        model_pattern=r"(mes2324|mes2348|mes2448)",
        platform_pattern=r"(eltex|mes)",
        preferred_transport=TransportKind.custom_cli,
        fallback_transport=TransportKind.paramiko,
        capabilities=CUSTOM_CLI_PLANNING,
        driver_name="EltexMESDriver",
        config_apply_supported=False,
        unsupported_reason="Eltex destructive apply requires confirmed device templates and lab certification.",
        notes="Eltex is intentionally custom-cli/Paramiko first, not generic Netmiko by default.",
    ),
    DriverRuntimeProfile(
        vendor="Bulat",
        family=DeviceFamily.bulat,
        model_pattern=r"(bs2500|bs6300|bk[-\s]?a837)",
        platform_pattern=r"(bulat|bs)",
        preferred_transport=TransportKind.custom_cli,
        fallback_transport=TransportKind.paramiko,
        capabilities=CUSTOM_CLI_PLANNING,
        driver_name="BulatBSDriver",
        config_apply_supported=False,
        unsupported_reason="Bulat destructive apply requires confirmed custom CLI templates and lab certification.",
        notes="Bulat uses first-party custom CLI strategy until certified templates exist.",
    ),
    DriverRuntimeProfile(
        vendor="SecurityCode",
        family=DeviceFamily.non_switch,
        model_pattern=r"(securitycode|continent[-\s]?500|security appliance|non[-\s]?switch)",
        platform_pattern=r"(non_switch|security_appliance)",
        preferred_transport=TransportKind.unsupported,
        fallback_transport=None,
        capabilities=frozenset(),
        driver_name="NonSwitchInventoryDriver",
        config_apply_supported=False,
        read_only_supported=False,
        unsupported_reason="Non-switch/security appliance inventory records are not CLI switch targets.",
        notes="Security appliances are retained for inventory context but never receive backup or config commands.",
    ),
    DriverRuntimeProfile(
        vendor="Generic",
        family=DeviceFamily.generic_ssh,
        model_pattern=r"(unknown product|unknown snmp product|generic|genericssh)",
        platform_pattern=r"(generic|ssh)",
        preferred_transport=TransportKind.paramiko,
        fallback_transport=TransportKind.custom_cli,
        capabilities=READ_ONLY,
        driver_name="GenericSSHDriver",
        config_apply_supported=False,
        unsupported_reason="Generic SSH cannot perform destructive apply until a vendor/model profile is explicitly certified.",
        notes="Generic SSH is discovery/read-only or dry-run only.",
    ),
    DriverRuntimeProfile(
        vendor="ICMP",
        family=DeviceFamily.icmp,
        model_pattern=r"(icmp|icmp-only)",
        platform_pattern=r"(icmp|icmp-only)",
        preferred_transport=TransportKind.icmp_only,
        fallback_transport=None,
        capabilities=frozenset({DriverCapability.read_only}),
        driver_name="ReadOnlyICMPDriver",
        config_apply_supported=False,
        unsupported_reason="ICMP-only devices support health/readiness checks only; config operations are unsupported.",
        notes="ICMP devices never receive CLI sessions.",
    ),
)

UNSUPPORTED_PROFILE = DriverRuntimeProfile(
    vendor="Unknown",
    family=DeviceFamily.unknown,
    preferred_transport=TransportKind.unsupported,
    fallback_transport=None,
    capabilities=frozenset(),
    driver_name="UnsupportedDriver",
    config_apply_supported=False,
    read_only_supported=False,
    unsupported_reason="No safe vendor/model/platform runtime profile matched this device.",
    notes="Unknown devices fail closed until inventory is normalized and certified.",
)

DRIVER_NAME_TO_FAMILY: dict[str, DeviceFamily] = {
    "CiscoIOSDriver": DeviceFamily.cisco_ios,
    "HuaweiVRPDriver": DeviceFamily.huawei_vrp,
    "HPComwareDriver": DeviceFamily.hpe_comware,
    "HPEProCurveDriver": DeviceFamily.hpe_procurve,
    "DellPowerConnectDriver": DeviceFamily.dell_os,
    "QtechQswDriver": DeviceFamily.qtech,
    "EltexMESDriver": DeviceFamily.eltex,
    "BulatBSDriver": DeviceFamily.bulat,
    "LimitedWebInventoryDriver": DeviceFamily.limited_web,
    "NonSwitchInventoryDriver": DeviceFamily.non_switch,
    "GenericSSHDriver": DeviceFamily.generic_ssh,
    "ReadOnlyICMPDriver": DeviceFamily.icmp,
}


def normalize(value: str | None) -> str:
    return (value or "").strip().casefold()


def matches_pattern(pattern: str | None, *values: str | None) -> bool:
    if not pattern:
        return False
    text = " ".join(normalize(value) for value in values if value)
    return bool(text and re.search(pattern, text, re.IGNORECASE))


class DriverCapabilityMatrix:
    def __init__(self, profiles: Iterable[DriverRuntimeProfile] = RUNTIME_PROFILES):
        self.profiles = tuple(profiles)

    def list_profiles(self) -> tuple[DriverRuntimeProfile, ...]:
        return self.profiles + (UNSUPPORTED_PROFILE,)

    def get_profile(self, family: DeviceFamily | str) -> DriverRuntimeProfile | None:
        family_value = family.value if isinstance(family, DeviceFamily) else str(family)
        for profile in self.list_profiles():
            if profile.family.value == family_value:
                return profile
        return None

    def decide(
        self,
        *,
        vendor: str,
        model: str | None = None,
        platform: str | None = None,
        driver_name: str | None = None,
        family: str | DeviceFamily | None = None,
        device_id: str | None = None,
        hostname: str | None = None,
    ) -> TransportDecision:
        profile = self._match_profile(vendor=vendor, model=model, platform=platform, driver_name=driver_name, family=family)
        warnings = self._warnings_for(profile)
        return TransportDecision(
            device_id=device_id,
            hostname=hostname,
            vendor=vendor or profile.vendor,
            model=model,
            platform=platform,
            family=profile.family,
            selected_transport=profile.preferred_transport,
            fallback_transport=profile.fallback_transport,
            driver_name=driver_name or profile.driver_name,
            capabilities=profile.capabilities,
            config_apply_allowed=False,
            real_apply_certified=False,
            read_only_allowed=profile.read_only_supported,
            unsupported_reason=profile.unsupported_reason,
            safety_warnings=tuple(warnings),
        )

    def _match_profile(
        self,
        *,
        vendor: str,
        model: str | None,
        platform: str | None,
        driver_name: str | None,
        family: str | DeviceFamily | None,
    ) -> DriverRuntimeProfile:
        text = f"{vendor} {model or ''} {platform or ''}"
        normalized_text = normalize(text)
        normalized_vendor = normalize(vendor)
        normalized_model = normalize(model)
        if "icmp" in normalized_text:
            return self.get_profile(DeviceFamily.icmp) or UNSUPPORTED_PROFILE
        if (
            normalized_vendor in {"unknown", "n/a", "na", "not known", "unidentified"}
            or normalized_vendor.startswith("unknown ")
            or normalized_vendor.startswith("snmp unknown")
            or normalized_model in {"unknown", "unknown product", "unknown snmp product"}
        ):
            return UNSUPPORTED_PROFILE
        if "unknown product" in normalized_text or "unknown snmp product" in normalized_text:
            return UNSUPPORTED_PROFILE
        if "securitycode" in normalized_text or "continent" in normalized_text:
            return self.get_profile(DeviceFamily.non_switch) or UNSUPPORTED_PROFILE
        if "des1100" in normalized_text or "des-1100" in normalized_text:
            return self.get_profile(DeviceFamily.limited_web) or UNSUPPORTED_PROFILE
        if "generic" in normalized_text:
            generic = self.get_profile(DeviceFamily.generic_ssh)
            return generic if generic is not None else UNSUPPORTED_PROFILE
        if family is not None:
            profile = self.get_profile(family)
            if profile is not None:
                return profile
        if driver_name in DRIVER_NAME_TO_FAMILY:
            profile = self.get_profile(DRIVER_NAME_TO_FAMILY[driver_name or ""])
            if profile is not None:
                return profile
        for profile in self.profiles:
            if matches_pattern(profile.model_pattern, vendor, model) or matches_pattern(profile.platform_pattern, platform):
                return profile
        return UNSUPPORTED_PROFILE

    def _warnings_for(self, profile: DriverRuntimeProfile) -> list[str]:
        warnings = ["Real device apply is disabled globally; this stage is decision/read-only only."]
        if profile.family == DeviceFamily.generic_ssh:
            warnings.append("Generic SSH cannot perform destructive apply until explicitly certified.")
        if profile.family in {DeviceFamily.bulat, DeviceFamily.eltex}:
            warnings.append(f"{profile.family.value} config apply is blocked until confirmed templates and lab certification exist.")
        if profile.family == DeviceFamily.qtech:
            warnings.append("QTECH config apply is blocked until explicit templates and lab certification exist.")
        if profile.family == DeviceFamily.limited_web:
            warnings.append("Limited web/unmanaged devices are inventory-only and cannot run CLI backup or config operations.")
        if profile.family == DeviceFamily.non_switch:
            warnings.append("Non-switch/security appliance records are inventory-only and cannot run switch CLI operations.")
        if profile.family == DeviceFamily.icmp:
            warnings.append("ICMP-only devices are health/readiness only and cannot run config operations.")
        if profile.family == DeviceFamily.unknown:
            warnings.append("Unknown devices fail closed until a supported runtime profile is selected.")
        if profile.config_apply_supported and not profile.real_apply_certified:
            warnings.append("Profile can model config staging, but real apply is not certified.")
        return warnings
