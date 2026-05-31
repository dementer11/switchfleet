from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models.config_backup import ConfigBackupJob, ConfigBackupJobItem, ConfigBackupSchedule
from app.repositories import coerce_uuid


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ConfigBackupRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_job(
        self,
        name: str,
        scope_type: str,
        scope_filter: dict[str, Any] | None = None,
        description: str | None = None,
        requested_by: str | None = None,
    ) -> ConfigBackupJob:
        job = ConfigBackupJob(
            name=name,
            description=description,
            scope_type=scope_type,
            scope_filter=scope_filter,
            status="pending",
            requested_by=requested_by,
            total_devices=0,
            successful_devices=0,
            failed_devices=0,
            skipped_devices=0,
        )
        self.session.add(job)
        self.session.flush()
        return job

    def get_job(self, job_id: str | uuid.UUID) -> ConfigBackupJob:
        parsed_id = coerce_uuid(job_id, object_name="Config backup job")
        job = self.session.get(ConfigBackupJob, parsed_id)
        if job is None:
            raise NotFoundError(f"Config backup job {job_id} not found")
        return job

    def list_jobs(self, status: str | None = None) -> list[ConfigBackupJob]:
        statement = select(ConfigBackupJob)
        if status is not None:
            statement = statement.where(ConfigBackupJob.status == status)
        return list(self.session.scalars(statement.order_by(ConfigBackupJob.created_at.desc())).all())

    def create_job_items(self, job_id: str | uuid.UUID, device_ids: list[str | uuid.UUID]) -> list[ConfigBackupJobItem]:
        parsed_job_id = coerce_uuid(job_id, object_name="Config backup job")
        items: list[ConfigBackupJobItem] = []
        for device_id in device_ids:
            item = ConfigBackupJobItem(
                job_id=parsed_job_id,
                device_id=coerce_uuid(device_id, object_name="Device"),
                status="pending",
            )
            self.session.add(item)
            items.append(item)
        job = self.get_job(parsed_job_id)
        job.total_devices = len(items)
        self.session.flush()
        return items

    def get_job_item(self, item_id: str | uuid.UUID) -> ConfigBackupJobItem:
        parsed_id = coerce_uuid(item_id, object_name="Config backup job item")
        item = self.session.get(ConfigBackupJobItem, parsed_id)
        if item is None:
            raise NotFoundError(f"Config backup job item {item_id} not found")
        return item

    def list_job_items(self, job_id: str | uuid.UUID) -> list[ConfigBackupJobItem]:
        parsed_id = coerce_uuid(job_id, object_name="Config backup job")
        return list(
            self.session.scalars(
                select(ConfigBackupJobItem).where(ConfigBackupJobItem.job_id == parsed_id).order_by(ConfigBackupJobItem.created_at)
            ).all()
        )

    def update_job_status(
        self,
        job_id: str | uuid.UUID,
        status: str,
        error_summary: str | None = None,
    ) -> ConfigBackupJob:
        job = self.get_job(job_id)
        job.status = status
        job.updated_at = utcnow()
        if status == "running" and job.started_at is None:
            job.started_at = utcnow()
        if status in {"completed", "completed_with_errors", "failed", "cancelled"}:
            job.finished_at = utcnow()
        if error_summary is not None:
            job.error_summary = error_summary
        self.session.flush()
        return job

    def update_job_counters(self, job_id: str | uuid.UUID) -> ConfigBackupJob:
        job = self.get_job(job_id)
        items = self.list_job_items(job.id)
        job.total_devices = len(items)
        job.successful_devices = sum(1 for item in items if item.status == "success")
        job.failed_devices = sum(1 for item in items if item.status == "failed")
        job.skipped_devices = sum(1 for item in items if item.status in {"skipped", "unsupported"})
        job.updated_at = utcnow()
        self.session.flush()
        return job

    def mark_item_running(self, item_id: str | uuid.UUID) -> ConfigBackupJobItem:
        item = self.get_job_item(item_id)
        item.status = "running"
        item.started_at = utcnow()
        self.session.flush()
        return item

    def mark_item_success(self, item_id: str | uuid.UUID, snapshot_id: str | uuid.UUID) -> ConfigBackupJobItem:
        item = self.get_job_item(item_id)
        item.status = "success"
        item.snapshot_id = coerce_uuid(snapshot_id, object_name="Config snapshot")
        item.finished_at = utcnow()
        item.error_message = None
        self.session.flush()
        return item

    def mark_item_failed(self, item_id: str | uuid.UUID, error_message: str) -> ConfigBackupJobItem:
        item = self.get_job_item(item_id)
        item.status = "failed"
        item.error_message = error_message
        item.finished_at = utcnow()
        self.session.flush()
        return item

    def mark_item_skipped(self, item_id: str | uuid.UUID, reason: str, status: str = "skipped") -> ConfigBackupJobItem:
        item = self.get_job_item(item_id)
        item.status = status
        item.error_message = reason
        item.finished_at = utcnow()
        self.session.flush()
        return item

    def create_schedule(
        self,
        name: str,
        scope_type: str,
        cron_expression: str,
        timezone_name: str = "UTC",
        retention_days: int = 90,
        scope_filter: dict[str, Any] | None = None,
        description: str | None = None,
        max_snapshots_per_device: int | None = None,
        next_run_at: datetime | None = None,
        created_by: str | None = None,
    ) -> ConfigBackupSchedule:
        schedule = ConfigBackupSchedule(
            name=name,
            description=description,
            enabled=True,
            scope_type=scope_type,
            scope_filter=scope_filter,
            cron_expression=cron_expression,
            timezone=timezone_name,
            retention_days=retention_days,
            max_snapshots_per_device=max_snapshots_per_device,
            next_run_at=next_run_at,
            created_by=created_by,
        )
        self.session.add(schedule)
        self.session.flush()
        return schedule

    def get_schedule(self, schedule_id: str | uuid.UUID) -> ConfigBackupSchedule:
        parsed_id = coerce_uuid(schedule_id, object_name="Config backup schedule")
        schedule = self.session.get(ConfigBackupSchedule, parsed_id)
        if schedule is None:
            raise NotFoundError(f"Config backup schedule {schedule_id} not found")
        return schedule

    def list_schedules(self, enabled: bool | None = None) -> list[ConfigBackupSchedule]:
        statement = select(ConfigBackupSchedule)
        if enabled is not None:
            statement = statement.where(ConfigBackupSchedule.enabled == enabled)
        return list(self.session.scalars(statement.order_by(ConfigBackupSchedule.created_at.desc())).all())

    def update_schedule(
        self,
        schedule_id: str | uuid.UUID,
        **changes: Any,
    ) -> ConfigBackupSchedule:
        schedule = self.get_schedule(schedule_id)
        for field in (
            "name",
            "description",
            "scope_type",
            "scope_filter",
            "cron_expression",
            "timezone",
            "retention_days",
            "max_snapshots_per_device",
            "next_run_at",
        ):
            if field in changes and changes[field] is not None:
                setattr(schedule, field, changes[field])
        schedule.updated_at = utcnow()
        self.session.flush()
        return schedule

    def disable_schedule(self, schedule_id: str | uuid.UUID) -> ConfigBackupSchedule:
        schedule = self.get_schedule(schedule_id)
        schedule.enabled = False
        schedule.updated_at = utcnow()
        self.session.flush()
        return schedule

    def enable_schedule(self, schedule_id: str | uuid.UUID, next_run_at: datetime | None = None) -> ConfigBackupSchedule:
        schedule = self.get_schedule(schedule_id)
        schedule.enabled = True
        if next_run_at is not None:
            schedule.next_run_at = next_run_at
        schedule.updated_at = utcnow()
        self.session.flush()
        return schedule

    def delete_schedule(self, schedule_id: str | uuid.UUID) -> None:
        schedule = self.get_schedule(schedule_id)
        self.session.delete(schedule)
        self.session.flush()
