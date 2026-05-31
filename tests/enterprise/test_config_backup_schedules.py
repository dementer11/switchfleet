from __future__ import annotations

from datetime import datetime, timezone

from app.db.session import SessionLocal
from app.schemas.config_backup import ConfigBackupScheduleCreate, ConfigBackupScheduleUpdate
from app.services.config_backup_service import ConfigBackupService


def test_config_backup_schedule_next_run_enable_disable_and_update() -> None:
    service = ConfigBackupService(SessionLocal())
    next_run = service.calculate_next_run("15 2 * * *", "UTC", now=datetime(2026, 5, 31, 1, 0, tzinfo=timezone.utc))
    created = service.create_schedule(
        ConfigBackupScheduleCreate(name="nightly", scope_type="all", cron_expression="15 2 * * *"),
        actor="netadmin",
    )
    disabled = service.disable_schedule(created.id)
    enabled = service.enable_schedule(created.id)
    updated = service.update_schedule(created.id, ConfigBackupScheduleUpdate(retention_days=30, cron_expression="@daily"))

    assert next_run.hour == 2
    assert next_run.minute == 15
    assert created.enabled is True
    assert disabled.enabled is False
    assert enabled.enabled is True
    assert updated.retention_days == 30
    assert updated.next_run_at is not None
