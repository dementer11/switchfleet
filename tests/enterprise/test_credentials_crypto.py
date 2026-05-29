import pytest

from app.core.config import Settings
from app.core.crypto import FernetCredentialCipher


def test_fernet_cipher_encrypts_and_decrypts() -> None:
    cipher = FernetCredentialCipher("test-encryption-key-material")

    encrypted = cipher.encrypt("VerySecret")

    assert encrypted != "VerySecret"
    assert cipher.decrypt(encrypted) == "VerySecret"


def test_production_requires_explicit_secret_key() -> None:
    with pytest.raises(ValueError):
        Settings(environment="production", secret_key=None)


def test_local_environment_can_use_test_key() -> None:
    settings = Settings(environment="test", secret_key=None)

    assert settings.encryption_key()

