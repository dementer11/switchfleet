from app.core.logging import redact_log_event


def test_redact_log_event_masks_common_secret_fields_and_text() -> None:
    event = redact_log_event(
        None,
        "info",
        {
            "event": "login password ShouldNotLeak token TokenValue",
            "password": "ShouldNotLeak",
            "NCP_SECRET_KEY": "SecretKeyValue",
            "nested": {
                "authorization": "Bearer TokenValue",
                "metadata": {"private_key": "PrivateKeyValue"},
            },
            "rendered_commands": ["username admin secret ShouldNotLeak"],
        },
    )

    rendered = str(event)
    assert "ShouldNotLeak" not in rendered
    assert "TokenValue" not in rendered
    assert "SecretKeyValue" not in rendered
    assert "PrivateKeyValue" not in rendered
    assert "<redacted>" in rendered
