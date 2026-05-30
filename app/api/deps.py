from __future__ import annotations

from collections.abc import Generator

from fastapi import Header
from sqlalchemy.orm import Session

from app.core.rbac import Actor, Role
from app.db.session import SessionLocal


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_current_actor(
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    x_roles: str | None = Header(default=None, alias="X-Roles"),
) -> Actor:
    username = x_actor or "system"
    if not x_roles:
        return Actor(username=username, roles=frozenset({Role.super_admin}))
    roles: set[Role] = set()
    for raw_role in x_roles.split(","):
        role = raw_role.strip()
        if role:
            roles.add(Role(role))
    return Actor(username=username, roles=frozenset(roles or {Role.viewer}))
