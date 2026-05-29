from app.utils.masking import mask_command_list, mask_secrets


def test_masks_password_command_secret() -> None:
    assert mask_secrets("username admin password 0 VerySecret") == "username admin password 0 <redacted>"


def test_masks_secret_command_secret() -> None:
    assert mask_secrets("username admin secret VerySecret") == "username admin secret <redacted>"


def test_masks_explicit_secret_in_output() -> None:
    output = "authentication failed for password VerySecret"

    assert mask_secrets(output, explicit_secrets=["VerySecret"]) == "authentication failed for password <redacted>"


def test_masks_command_list() -> None:
    commands = mask_command_list(["local-user admin password irreversible-cipher VerySecret"])

    assert commands == ["local-user admin password irreversible-cipher <redacted>"]

