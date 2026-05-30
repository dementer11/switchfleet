from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

import app.db.models  # noqa: F401
from app.api.deps import get_db
from app.db.base import Base
from app.db.session import SessionLocal, configure_database, get_engine
from app.main import app
from app.services.runtime_state import reset_runtime_state


@pytest.fixture(autouse=True)
def clean_enterprise_state(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("NCP_ENVIRONMENT", "test")
    monkeypatch.setenv("NCP_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    configure_database("sqlite+pysqlite:///:memory:")
    engine = get_engine()
    Base.metadata.create_all(engine)
    db = SessionLocal()

    def override_get_db() -> Generator[Session, None, None]:
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise

    app.dependency_overrides[get_db] = override_get_db
    reset_runtime_state()
    try:
        yield
    finally:
        db.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        reset_runtime_state()
