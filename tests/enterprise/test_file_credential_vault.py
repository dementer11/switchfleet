from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings
from app.services.file_credential_vault import FileCredentialVault, FileCredentialVaultError
from app.services.file_lab_state import FileLabState


def test_file_credential_vault_encrypts_and_never_returns_plaintext(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NCP_SECRET_KEY", "excel-lab-secret-key")
    get_settings.cache_clear()
    state = FileLabState(tmp_path / ".switchfleet_lab")
    vault = FileCredentialVault(state)

    created = vault.create_or_update(name="lab-admin", username="admin", secret="PlainSecret")

    rendered = state.paths.credentials.read_text(encoding="utf-8")
    assert "PlainSecret" not in rendered
    assert created.to_safe_dict()["has_secret"] is True
    assert "encrypted_payload" not in created.to_safe_dict()
    assert vault.decrypt_for_execution_after_safety("lab-admin") == "PlainSecret"


def test_file_credential_vault_metadata_checks_do_not_require_secret_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NCP_SECRET_KEY", "excel-lab-secret-key")
    get_settings.cache_clear()
    state = FileLabState(tmp_path / ".switchfleet_lab")
    FileCredentialVault(state).create_or_update(name="lab-admin", username="admin", secret="PlainSecret")

    monkeypatch.delenv("NCP_SECRET_KEY", raising=False)
    get_settings.cache_clear()
    vault = FileCredentialVault(state)

    usable, reasons = vault.check_usable("lab-admin")
    assert usable is True
    assert reasons == []
    try:
        vault.decrypt_for_execution_after_safety("lab-admin")
    except FileCredentialVaultError as exc:
        assert "NCP_SECRET_KEY" in str(exc)
    else:
        raise AssertionError("File credential vault decrypted without NCP_SECRET_KEY")


def test_file_credential_vault_create_requires_secret_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("NCP_SECRET_KEY", raising=False)
    get_settings.cache_clear()
    vault = FileCredentialVault(FileLabState(tmp_path / ".switchfleet_lab"))

    try:
        vault.create_or_update(name="lab-admin", username="admin", secret="PlainSecret")
    except FileCredentialVaultError as exc:
        assert "NCP_SECRET_KEY" in str(exc)
    else:
        raise AssertionError("File credential vault stored a secret without NCP_SECRET_KEY")
