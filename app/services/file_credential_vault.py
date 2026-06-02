from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.exceptions import SecretHandlingError
from app.core.secret_crypto import SecretCrypto
from app.services.file_lab_state import FileLabState


class FileCredentialVaultError(ValueError):
    """Raised when a file credential cannot be stored or used safely."""


@dataclass(frozen=True)
class FileCredentialMetadata:
    id: str
    name: str
    username: str
    purpose: str
    status: str
    has_secret: bool = True

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "username": self.username,
            "purpose": self.purpose,
            "status": self.status,
            "has_secret": self.has_secret,
        }


class FileCredentialVault:
    def __init__(self, state: FileLabState, crypto: SecretCrypto | None = None):
        self.state = state
        try:
            self.crypto = crypto or SecretCrypto()
        except SecretHandlingError as exc:
            raise FileCredentialVaultError(
                "NCP_SECRET_KEY is required for Excel lab credential storage. "
                "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
            ) from exc

    def create_or_update(self, *, name: str, username: str, secret: str, purpose: str = "lab_apply") -> FileCredentialMetadata:
        if not secret:
            raise FileCredentialVaultError("Credential secret cannot be empty")
        credentials = [item for item in self.state.read_credentials() if item.get("name") != name]
        existing = next((item for item in self.state.read_credentials() if item.get("name") == name), None)
        record = {
            "id": (existing or {}).get("id") or f"cred-{name}",
            "name": name,
            "username": username,
            "purpose": purpose,
            "status": "active",
            "encrypted_payload": self.crypto.encrypt_payload(secret),
        }
        credentials.append(record)
        self.state.write_credentials(sorted(credentials, key=lambda item: item.get("name", "")))
        self.state.append_audit(
            action="file_credential.upserted",
            actor="excel-lab",
            object_type="credential",
            object_id=record["id"],
            metadata={"name": name, "username": username, "purpose": purpose},
        )
        return self._metadata(record)

    def list_metadata(self, active: bool = True) -> list[FileCredentialMetadata]:
        credentials = self.state.read_credentials()
        if active:
            credentials = [item for item in credentials if item.get("status") == "active"]
        return [self._metadata(item) for item in credentials]

    def get_metadata(self, ref: str) -> FileCredentialMetadata:
        return self._metadata(self._get_record(ref))

    def check_usable(self, ref: str) -> tuple[bool, list[str]]:
        try:
            record = self._get_record(ref)
        except FileCredentialVaultError as exc:
            return False, [str(exc)]
        reasons: list[str] = []
        if record.get("status") != "active":
            reasons.append("Credential is not active")
        if not record.get("encrypted_payload"):
            reasons.append("Credential has no encrypted payload")
        return not reasons, reasons

    def decrypt_for_execution_after_safety(self, ref: str) -> str:
        record = self._get_record(ref)
        if record.get("status") != "active":
            raise FileCredentialVaultError("Credential is not active")
        encrypted = str(record.get("encrypted_payload") or "")
        if not encrypted:
            raise FileCredentialVaultError("Credential has no encrypted payload")
        return self.crypto.decrypt_payload(encrypted)

    def _get_record(self, ref: str) -> dict[str, Any]:
        for record in self.state.read_credentials():
            if record.get("id") == ref or record.get("name") == ref:
                return record
        raise FileCredentialVaultError(f"Credential {ref!r} was not found")

    def _metadata(self, record: dict[str, Any]) -> FileCredentialMetadata:
        return FileCredentialMetadata(
            id=str(record.get("id") or ""),
            name=str(record.get("name") or ""),
            username=str(record.get("username") or ""),
            purpose=str(record.get("purpose") or ""),
            status=str(record.get("status") or "unknown"),
            has_secret=bool(record.get("encrypted_payload")),
        )
