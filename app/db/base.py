from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


from app.db.models.acl import AclObject, AclRuleModel  # noqa: E402,F401
from app.db.models.audit import AuditLog  # noqa: E402,F401
from app.db.models.backup import ConfigBackupModel  # noqa: E402,F401
from app.db.models.credential import Credential, CredentialAssignment  # noqa: E402,F401
from app.db.models.device import Device  # noqa: E402,F401
from app.db.models.job import Job, JobTask  # noqa: E402,F401
from app.db.models.lock import DeviceLock  # noqa: E402,F401
from app.db.models.port import Port  # noqa: E402,F401
from app.db.models.vlan import Vlan  # noqa: E402,F401

