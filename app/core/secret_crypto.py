from __future__ import annotations

from app.core.config import Settings, get_settings
from app.core.crypto import FernetCredentialCipher
from app.core.exceptions import SecretHandlingError


class SecretCrypto:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        if not self.settings.secret_key:
            raise SecretHandlingError("NCP_SECRET_KEY is required for credential vault secret storage")
        self.cipher = FernetCredentialCipher(self.settings.secret_key)

    def encrypt_payload(self, value: str) -> str:
        return self.cipher.encrypt(value)

    def decrypt_payload(self, value: str) -> str:
        return self.cipher.decrypt(value)

