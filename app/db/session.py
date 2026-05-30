from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def create_configured_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        if database_url.endswith(":memory:") or database_url.endswith("/memory"):
            return create_engine(
                database_url,
                connect_args=connect_args,
                poolclass=StaticPool,
            )
        return create_engine(database_url, connect_args=connect_args)
    return create_engine(database_url, pool_pre_ping=True)


def configure_database(database_url: str | None = None) -> None:
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    url = database_url or get_settings().database_url
    _engine = create_configured_engine(url)
    _session_factory = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


def get_engine() -> Engine:
    if _engine is None:
        configure_database()
    if _engine is None:
        raise RuntimeError("Database engine is not configured")
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    if _session_factory is None:
        configure_database()
    if _session_factory is None:
        raise RuntimeError("Database session factory is not configured")
    return _session_factory


class _SessionLocalProxy:
    def __call__(self) -> Session:
        return get_session_factory()()


SessionLocal = _SessionLocalProxy()
