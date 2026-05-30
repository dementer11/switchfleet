from __future__ import annotations

from app.core.config import Settings, get_settings
from app.core.exceptions import SafetyError
from app.db.models.device import Device


class CredentialVerificationService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def verify_new_credential(
        self,
        device: Device,
        username: str,
        new_password: str,
        transport_type: str = "dummy",
        simulate_failure: bool = False,
    ) -> bool:
        if transport_type in {"scrapli", "netmiko"} and not self.settings.allow_real_device_apply:
            raise SafetyError("Real credential verification is disabled by NCP_ALLOW_REAL_DEVICE_APPLY=false")
        if simulate_failure:
            return False
        if not username or not new_password:
            return False
        return True
