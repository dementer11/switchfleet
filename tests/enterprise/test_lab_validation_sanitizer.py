from __future__ import annotations

import hashlib
from uuid import uuid4

from app.utils.transcript_sanitizer import sanitize_transcript


def test_transcript_sanitizer_masks_secret_material_and_hashes_sanitized_text() -> None:
    secrets = [f"runtime-secret-{uuid4().hex}" for _ in range(9)]
    raw = "\n".join(
        [
            f"username admin password {secrets[0]}",
            f"username admin secret {secrets[1]}",
            f"set authentication password {secrets[2]}",
            f"snmp-server community {secrets[3]} ro",
            f"authorization bearer {secrets[4]}",
            f"enable password {secrets[5]}",
            f"passwd {secrets[6]}",
            f"token {secrets[7]}",
            "-----BEGIN PRIVATE KEY-----",
            secrets[8],
            "-----END PRIVATE KEY-----",
        ]
    )

    result = sanitize_transcript(raw)

    for secret in secrets:
        assert secret not in result.sanitized_text
    assert "<redacted>" in result.sanitized_text
    assert result.sha256 == hashlib.sha256(result.sanitized_text.encode("utf-8")).hexdigest()
