import pytest

from app.services.runtime_state import reset_runtime_state


@pytest.fixture(autouse=True)
def clean_runtime_state() -> None:
    reset_runtime_state()

