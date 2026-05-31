from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.core.exceptions import CapabilityError, ConflictError
from app.db.models.config_backup import ConfigBackupJob, ConfigBackupJobItem, ConfigBackupSchedule, ConfigSnapshot, ConfigSnapshotDiff
from app.db.models.device import Device
from app.db.session import SessionLocal
from app.repositories.config_backups import ConfigBackupRepository
from app.repositories.config_snapshots import ConfigSnapshotRepository
from app.repositories.device_inventory import DeviceInventoryRepository
from app.schemas.config_backup import (
    ConfigBackupJobCreate,
    ConfigBackupJobRead,
    ConfigBackupJobItemRead,
    ConfigBackupReport,
    ConfigBackupScheduleCreate,
    ConfigBackupScheduleRead,
    ConfigBackupScheduleUpdate,
    ConfigSnapshotDiffRead,
    ConfigSnapshotImportRequest,
    ConfigSnapshotRead,
)
from app.services.config_diff_service import ConfigDiffService
from app.utils.config_sanitizer import sanitize_config


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ConfigBackupService:
    def __init__(self, session: Session | None = None):
        self.session = session or SessionLocal()
        self.backups = ConfigBackupRepository(self.session)
        self.snapshots = ConfigSnapshotRepository(self.session)
        self.devices = DeviceInventoryRepository(self.session)
        self.diff_service = ConfigDiffService(self.session)

    def create_backup_job(self, payload: ConfigBackupJobCreate, actor: str) -> ConfigBackupReport:
        devices = self._devices_for_scope(payload.scope_type, payload.scope_filter or {})
        job = self.backups.create_job(
            name=payload.name,
            description=payload.description,
            scope_type=payload.scope_type,
            scope_filter=payload.scope_filter,
            requested_by=actor,
        )
        self.backups.create_job_items(job.id, [device.id for device in devices])
        self.backups.update_job_counters(job.id)
        return self.build_backup_report(str(job.id))

    def run_backup_job(self, job_id: str, actor: str) -> ConfigBackupReport:
        job = self.backups.get_job(job_id)
        if job.status == "cancelled":
            raise ConflictError("Cancelled backup job cannot be run")
        self.backups.update_job_status(job.id, "running")
        for item in self.backups.list_job_items(job.id):
            if item.status == "success":
                continue
            self.backups.mark_item_running(item.id)
            try:
                snapshot, _diff = self.backup_device_config(
                    str(item.device_id),
                    actor=actor,
                    backup_job_id=str(job.id),
                    source="api",
                    config_type="running",
                )
            except CapabilityError as exc:
                self.backups.mark_item_skipped(item.id, str(exc), status="unsupported")
            except Exception as exc:
                self.backups.mark_item_failed(item.id, str(exc))
            else:
                self.backups.mark_item_success(item.id, snapshot.id)
        job = self.backups.update_job_counters(job.id)
        if job.failed_devices:
            final_status = "failed" if job.successful_devices == 0 else "completed_with_errors"
        elif job.skipped_devices:
            final_status = "completed_with_errors"
        else:
            final_status = "completed"
        self.backups.update_job_status(job.id, final_status)
        return self.build_backup_report(str(job.id))

    def backup_device_config(
        self,
        device_id: str,
        actor: str,
        backup_job_id: str | None = None,
        source: str = "api",
        config_type: str = "running",
        config_text: str | None = None,
    ) -> tuple[ConfigSnapshot, ConfigSnapshotDiff | None]:
        device = self.devices.get(device_id)
        if self._is_unsupported_for_readonly_backup(device):
            raise CapabilityError("Device does not support read-only configuration backup")
        previous = self.snapshots.get_latest_snapshot_for_device(device.id)
        raw_config = config_text if config_text is not None else self._read_only_config(device)
        sanitized = sanitize_config(raw_config)
        collection_method = "manual_upload" if config_text is not None else "dummy_transport"
        if source == "imported":
            collection_method = "imported"
        snapshot = self.snapshots.create_snapshot(
            device_id=device.id,
            backup_job_id=backup_job_id,
            source=source,
            config_type=config_type,
            config_text=sanitized.text,
            config_hash=sanitized.config_hash,
            sanitized=True,
            collection_method=collection_method,
            metadata={"redaction_types": sanitized.redaction_types, "created_by": actor},
        )
        diff = self.diff_service.create_diff_if_changed(previous, snapshot)
        return snapshot, diff

    def import_snapshot(self, device_id: str, payload: ConfigSnapshotImportRequest, actor: str) -> ConfigSnapshotRead:
        snapshot, _diff = self.backup_device_config(
            device_id,
            actor=actor,
            source=payload.source,
            config_type=payload.config_type,
            config_text=payload.config_text,
        )
        return read_snapshot(snapshot)

    def build_backup_report(self, job_id: str) -> ConfigBackupReport:
        job = self.backups.get_job(job_id)
        return ConfigBackupReport(
            job=read_job(job),
            items=[read_item(item) for item in self.backups.list_job_items(job.id)],
        )

    def create_schedule(self, payload: ConfigBackupScheduleCreate, actor: str) -> ConfigBackupScheduleRead:
        next_run = self.calculate_next_run(payload.cron_expression, payload.timezone)
        schedule = self.backups.create_schedule(
            name=payload.name,
            description=payload.description,
            scope_type=payload.scope_type,
            scope_filter=payload.scope_filter,
            cron_expression=payload.cron_expression,
            timezone_name=payload.timezone,
            retention_days=payload.retention_days,
            max_snapshots_per_device=payload.max_snapshots_per_device,
            next_run_at=next_run,
            created_by=actor,
        )
        return read_schedule(schedule)

    def calculate_next_run(self, cron_expression: str, timezone_name: str = "UTC", now: datetime | None = None) -> datetime:
        try:
            zone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unsupported timezone: {timezone_name}") from exc
        local_now = (now or utcnow()).astimezone(zone)
        if cron_expression == "@hourly":
            return (local_now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).astimezone(timezone.utc)
        if cron_expression == "@daily":
            return (local_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).astimezone(timezone.utc)
        parts = cron_expression.split()
        if len(parts) != 5:
            raise ValueError("cron_expression must be @hourly, @daily, or a five-field cron expression")
        minute_expr, hour_expr = parts[0], parts[1]
        minute = self._cron_number(minute_expr, local_now.minute)
        hour = self._cron_number(hour_expr, local_now.hour)
        candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= local_now:
            candidate += timedelta(days=1 if hour_expr != "*" else 0, hours=1 if hour_expr == "*" else 0)
        return candidate.astimezone(timezone.utc)

    def apply_retention_policy(self, retention_days: int, max_snapshots_per_device: int | None = None) -> int:
        return self.snapshots.delete_old_snapshots(retention_days, max_snapshots_per_device)

    def list_jobs(self) -> list[ConfigBackupJobRead]:
        return [read_job(job) for job in self.backups.list_jobs()]

    def get_job(self, job_id: str) -> ConfigBackupJobRead:
        return read_job(self.backups.get_job(job_id))

    def list_schedules(self) -> list[ConfigBackupScheduleRead]:
        return [read_schedule(schedule) for schedule in self.backups.list_schedules()]

    def get_schedule(self, schedule_id: str) -> ConfigBackupScheduleRead:
        return read_schedule(self.backups.get_schedule(schedule_id))

    def update_schedule(self, schedule_id: str, payload: ConfigBackupScheduleUpdate) -> ConfigBackupScheduleRead:
        changes = payload.model_dump(exclude_unset=True)
        if "cron_expression" in changes or "timezone" in changes:
            cron = str(changes.get("cron_expression") or self.backups.get_schedule(schedule_id).cron_expression)
            timezone_name = str(changes.get("timezone") or self.backups.get_schedule(schedule_id).timezone)
            changes["next_run_at"] = self.calculate_next_run(cron, timezone_name)
        return read_schedule(self.backups.update_schedule(schedule_id, **changes))

    def enable_schedule(self, schedule_id: str) -> ConfigBackupScheduleRead:
        schedule = self.backups.get_schedule(schedule_id)
        return read_schedule(self.backups.enable_schedule(schedule.id, self.calculate_next_run(schedule.cron_expression, schedule.timezone)))

    def disable_schedule(self, schedule_id: str) -> ConfigBackupScheduleRead:
        return read_schedule(self.backups.disable_schedule(schedule_id))

    def delete_schedule(self, schedule_id: str) -> None:
        self.backups.delete_schedule(schedule_id)

    def list_snapshots_for_device(self, device_id: str) -> list[ConfigSnapshotRead]:
        self.devices.get(device_id)
        return [read_snapshot(snapshot) for snapshot in self.snapshots.list_snapshots_for_device(device_id)]

    def get_snapshot(self, snapshot_id: str) -> ConfigSnapshotRead:
        return read_snapshot(self.snapshots.get_snapshot(snapshot_id))

    def list_diffs_for_device(self, device_id: str) -> list[ConfigSnapshotDiffRead]:
        self.devices.get(device_id)
        return [read_diff(diff) for diff in self.snapshots.list_diffs_for_device(device_id)]

    def get_diff(self, diff_id: str) -> ConfigSnapshotDiffRead:
        return read_diff(self.snapshots.get_diff(diff_id))

    def _devices_for_scope(self, scope_type: str, scope_filter: dict[str, Any]) -> list[Device]:
        if scope_type == "all":
            return self.devices.list_devices()
        if scope_type == "site":
            return self.devices.list_by_site(str(scope_filter.get("site") or ""))
        if scope_type == "tag":
            return self.devices.list_by_tag(str(scope_filter.get("tag") or ""))
        if scope_type == "device_ids":
            return [self.devices.get(device_id) for device_id in scope_filter.get("device_ids", [])]
        if scope_type == "query":
            devices = self.devices.list_devices()
            for field in ("vendor", "model", "driver_name", "status", "role"):
                value = scope_filter.get(field)
                if value:
                    devices = [device for device in devices if str(getattr(device, field, "")) == str(value)]
            return devices
        return []

    def _is_unsupported_for_readonly_backup(self, device: Device) -> bool:
        return device.driver_name == "ReadOnlyICMPDriver" or device.platform == "icmp-only" or device.vendor == "ICMP"

    def _read_only_config(self, device: Device) -> str:
        hostname = device.hostname or str(device.management_ip or device.ip_address)
        return (
            f"! read-only simulated running-config for {hostname}\n"
            f"! collection method: driver_readonly\n"
            f"hostname {hostname}\n"
            "interface Loopback0\n"
            " description backup-safe\n"
        )

    def _cron_number(self, expression: str, current: int) -> int:
        if expression == "*":
            return current
        value = int(expression)
        if value < 0:
            raise ValueError("cron field cannot be negative")
        return value


def read_job(job: ConfigBackupJob) -> ConfigBackupJobRead:
    return ConfigBackupJobRead(
        id=str(job.id),
        name=job.name,
        description=job.description,
        scope_type=job.scope_type,
        scope_filter=job.scope_filter,
        status=job.status,
        requested_by=job.requested_by,
        started_at=job.started_at.isoformat() if job.started_at else None,
        finished_at=job.finished_at.isoformat() if job.finished_at else None,
        total_devices=job.total_devices,
        successful_devices=job.successful_devices,
        failed_devices=job.failed_devices,
        skipped_devices=job.skipped_devices,
        error_summary=job.error_summary,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
    )


def read_item(item: ConfigBackupJobItem) -> ConfigBackupJobItemRead:
    return ConfigBackupJobItemRead(
        id=str(item.id),
        job_id=str(item.job_id),
        device_id=str(item.device_id),
        status=item.status,
        snapshot_id=str(item.snapshot_id) if item.snapshot_id else None,
        error_message=item.error_message,
        started_at=item.started_at.isoformat() if item.started_at else None,
        finished_at=item.finished_at.isoformat() if item.finished_at else None,
        created_at=item.created_at.isoformat(),
    )


def read_schedule(schedule: ConfigBackupSchedule) -> ConfigBackupScheduleRead:
    return ConfigBackupScheduleRead(
        id=str(schedule.id),
        name=schedule.name,
        description=schedule.description,
        enabled=schedule.enabled,
        scope_type=schedule.scope_type,
        scope_filter=schedule.scope_filter,
        cron_expression=schedule.cron_expression,
        timezone=schedule.timezone,
        retention_days=schedule.retention_days,
        max_snapshots_per_device=schedule.max_snapshots_per_device,
        last_run_at=schedule.last_run_at.isoformat() if schedule.last_run_at else None,
        next_run_at=schedule.next_run_at.isoformat() if schedule.next_run_at else None,
        created_by=schedule.created_by,
        created_at=schedule.created_at.isoformat(),
        updated_at=schedule.updated_at.isoformat(),
    )


def read_snapshot(snapshot: ConfigSnapshot) -> ConfigSnapshotRead:
    return ConfigSnapshotRead(
        id=str(snapshot.id),
        device_id=str(snapshot.device_id),
        backup_job_id=str(snapshot.backup_job_id) if snapshot.backup_job_id else None,
        source=snapshot.source,
        config_type=snapshot.config_type,
        config_text=snapshot.config_text,
        config_hash=snapshot.config_hash,
        sanitized=snapshot.sanitized,
        collection_method=snapshot.collection_method,
        collected_at=snapshot.collected_at.isoformat(),
        created_at=snapshot.created_at.isoformat(),
        metadata=dict(snapshot.metadata_ or {}),
    )


def read_diff(diff: ConfigSnapshotDiff) -> ConfigSnapshotDiffRead:
    return ConfigSnapshotDiffRead(
        id=str(diff.id),
        device_id=str(diff.device_id),
        from_snapshot_id=str(diff.from_snapshot_id),
        to_snapshot_id=str(diff.to_snapshot_id),
        diff_text=diff.diff_text,
        diff_hash=diff.diff_hash,
        change_summary=dict(diff.change_summary or {}),
        created_at=diff.created_at.isoformat(),
    )
