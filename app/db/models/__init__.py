from app.db.models.acl import AclObject, AclRuleModel
from app.db.models.audit import AuditLog
from app.db.models.backup import ConfigBackupModel
from app.db.models.config_backup import (
    ConfigBackupJob,
    ConfigBackupJobItem,
    ConfigBackupSchedule,
    ConfigRestorePlan,
    ConfigSnapshot,
    ConfigSnapshotDiff,
)
from app.db.models.credential import Credential, CredentialAssignment
from app.db.models.device import Device
from app.db.models.inventory import InventoryImportBatch, InventoryImportRow
from app.db.models.job import Job, JobTask
from app.db.models.lab_validation import LabDriverValidation, LabValidationChecklistItem, LabValidationTranscript
from app.db.models.lock import DeviceLock
from app.db.models.password import PasswordChangeSecret, PasswordRolloutBatch, PasswordRolloutBatchTask
from app.db.models.port import Port
from app.db.models.vlan import Vlan
from app.db.models.vlan_workflow import (
    VlanChangeApproval,
    VlanChangeAuditEvent,
    VlanChangeDevice,
    VlanChangeRequest,
)

__all__ = [
    "AclObject",
    "AclRuleModel",
    "AuditLog",
    "ConfigBackupModel",
    "ConfigBackupJob",
    "ConfigBackupJobItem",
    "ConfigBackupSchedule",
    "ConfigRestorePlan",
    "ConfigSnapshot",
    "ConfigSnapshotDiff",
    "Credential",
    "CredentialAssignment",
    "Device",
    "DeviceLock",
    "InventoryImportBatch",
    "InventoryImportRow",
    "Job",
    "JobTask",
    "LabDriverValidation",
    "LabValidationChecklistItem",
    "LabValidationTranscript",
    "PasswordChangeSecret",
    "PasswordRolloutBatch",
    "PasswordRolloutBatchTask",
    "Port",
    "Vlan",
    "VlanChangeApproval",
    "VlanChangeAuditEvent",
    "VlanChangeDevice",
    "VlanChangeRequest",
]
