from __future__ import annotations

from app.core.exceptions import CapabilityError
from app.drivers.base import ExpectedState, VlanIntent
from app.schemas.job import DryRunDeviceResult, JobDryRunResponse, VlanChangeJobRequest
from app.services.driver_resolver import DriverResolverService
from app.utils.masking import mask_command_list


class ChangePlanner:
    def __init__(self, resolver: DriverResolverService | None = None):
        self.resolver = resolver or DriverResolverService()

    def plan_vlan_change(self, request: VlanChangeJobRequest) -> JobDryRunResponse:
        results: list[DryRunDeviceResult] = []
        intent = VlanIntent(
            vlan_id=request.intent.vlan_id,
            name=request.intent.name,
            state=request.intent.state,
            force=request.intent.force,
        )
        for device in request.devices:
            match = self.resolver.resolve(device)
            driver = match.driver_class(host=device.ip_address)
            capabilities = driver.detect_capabilities()
            warnings = [match.reason]
            risks: list[str] = []
            commands: list[str] = []
            config_commands: list[str] = []
            verification_commands: list[str] = []
            save_commands: list[str] = []
            apply_supported = capabilities.destructive_apply_confirmed
            try:
                plan = driver.plan_vlan_intent(intent)
                verify = driver.verify_change(ExpectedState(vlan=intent))
                save_commands = driver.save_commands()
                config_commands = plan.commands
                verification_commands = verify.checks
                commands = mask_command_list(plan.commands + verify.checks + save_commands)
                warnings.extend(plan.warnings)
                if not capabilities.destructive_apply_confirmed:
                    warning = "Driver template is not confirmed for destructive apply"
                    warnings.append(warning)
                    risks.append(warning)
            except CapabilityError as exc:
                apply_supported = False
                risks.append(str(exc))
            results.append(
                DryRunDeviceResult(
                    ip_address=device.ip_address,
                    vendor=device.vendor,
                    model=device.model,
                    driver=driver.name,
                    capabilities=capabilities.__dict__,
                    commands=commands,
                    config_commands=mask_command_list(config_commands),
                    verification_commands=mask_command_list(verification_commands),
                    save_commands=mask_command_list(save_commands),
                    warnings=warnings,
                    risks=risks,
                    manual_confirmation_required=True,
                    rollback_supported=capabilities.supports_rollback,
                    apply_supported=apply_supported,
                )
            )
        return JobDryRunResponse(
            job_type="vlan_change",
            device_count=len(results),
            approval_required=True,
            apply_allowed=False,
            batch_size=request.batch_size,
            estimated_impact=f"{len(results)} device(s), VLAN {intent.vlan_id} state={intent.state}",
            devices=results,
        )
