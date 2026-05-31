from __future__ import annotations

from app.utils.config_sanitizer import sanitize_config


def test_config_sanitizer_redacts_common_secret_forms() -> None:
    raw = """enable secret EnableSecret
username admin password 0 UserPassword
username ops secret UserSecret
snmp-server community public RO
snmp community private
tacacs-server key TacacsSecret
radius-server key RadiusSecret
ntp authentication-key 1 md5 NtpSecret
api-token=ApiSecret
Authorization: Bearer abc.def.ghi
-----BEGIN RSA PRIVATE KEY-----
super-secret-key
-----END RSA PRIVATE KEY-----
"""

    sanitized = sanitize_config(raw)

    assert "EnableSecret" not in sanitized.text
    assert "UserPassword" not in sanitized.text
    assert "UserSecret" not in sanitized.text
    assert "public" not in sanitized.text
    assert "private" not in sanitized.text
    assert "TacacsSecret" not in sanitized.text
    assert "RadiusSecret" not in sanitized.text
    assert "NtpSecret" not in sanitized.text
    assert "ApiSecret" not in sanitized.text
    assert "abc.def.ghi" not in sanitized.text
    assert "super-secret-key" not in sanitized.text
    assert "<redacted>" in sanitized.text
    assert sanitized.config_hash
    assert "private_key_block" in sanitized.redaction_types


def test_config_sanitizer_hashes_sanitized_config() -> None:
    first = sanitize_config("username admin secret One\n")
    second = sanitize_config("username admin secret Two\n")

    assert first.text == second.text
    assert first.config_hash == second.config_hash
