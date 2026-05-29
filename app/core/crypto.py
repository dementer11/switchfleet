from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet

from app.core.exceptions import SecretHandlingError


class FernetCredentialCipher:
    def __init__(self, secret_key: str):
        if len(secret_key) < 16:
            raise SecretHandlingError("Encryption key must be at least 16 characters")
        digest = hashlib.sha256(secret_key.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    def encrypt(self, value: str) -> str:
        if not value:
            raise SecretHandlingError("Refusing to encrypt an empty credential")
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        if not value:
            raise SecretHandlingError("Refusing to decrypt an empty credential")
        return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
