from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models.config_backup import ConfigSnapshot, ConfigSnapshotDiff
from app.repositories import coerce_uuid, optional_uuid


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ConfigSnapshotRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_snapshot(
        self,
        device_id: str | uuid.UUID,
        config_text: str,
        config_hash: str,
        source: str,
        config_type: str,
        collection_method: str,
        backup_job_id: str | uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
        collected_at: datetime | None = None,
        sanitized: bool = True,
    ) -> ConfigSnapshot:
        timestamp = collected_at or utcnow()
        snapshot = ConfigSnapshot(
            device_id=coerce_uuid(device_id, object_name="Device"),
            backup_job_id=optional_uuid(backup_job_id, object_name="Config backup job"),
            source=source,
            config_type=config_type,
            config_text=config_text,
            config_hash=config_hash,
            sanitized=sanitized,
            collection_method=collection_method,
            collected_at=timestamp,
            created_at=timestamp,
            metadata_=metadata,
        )
        self.session.add(snapshot)
        self.session.flush()
        return snapshot

    def get_snapshot(self, snapshot_id: str | uuid.UUID) -> ConfigSnapshot:
        parsed_id = coerce_uuid(snapshot_id, object_name="Config snapshot")
        snapshot = self.session.get(ConfigSnapshot, parsed_id)
        if snapshot is None:
            raise NotFoundError(f"Config snapshot {snapshot_id} not found")
        return snapshot

    def list_snapshots_for_device(self, device_id: str | uuid.UUID) -> list[ConfigSnapshot]:
        parsed_id = coerce_uuid(device_id, object_name="Device")
        return list(
            self.session.scalars(
                select(ConfigSnapshot)
                .where(ConfigSnapshot.device_id == parsed_id)
                .order_by(ConfigSnapshot.collected_at.desc(), ConfigSnapshot.created_at.desc(), ConfigSnapshot.id.desc())
            ).all()
        )

    def get_latest_snapshot_for_device(
        self,
        device_id: str | uuid.UUID,
        exclude_snapshot_id: str | uuid.UUID | None = None,
    ) -> ConfigSnapshot | None:
        snapshots = self.list_snapshots_for_device(device_id)
        excluded = optional_uuid(exclude_snapshot_id, object_name="Config snapshot")
        for snapshot in snapshots:
            if excluded is None or snapshot.id != excluded:
                return snapshot
        return None

    def find_snapshot_by_hash(self, device_id: str | uuid.UUID, config_hash: str) -> ConfigSnapshot | None:
        parsed_id = coerce_uuid(device_id, object_name="Device")
        return self.session.scalar(
            select(ConfigSnapshot).where(ConfigSnapshot.device_id == parsed_id, ConfigSnapshot.config_hash == config_hash)
        )

    def create_diff(
        self,
        device_id: str | uuid.UUID,
        from_snapshot_id: str | uuid.UUID,
        to_snapshot_id: str | uuid.UUID,
        diff_text: str,
        diff_hash: str,
        change_summary: dict[str, Any] | None = None,
    ) -> ConfigSnapshotDiff:
        diff = ConfigSnapshotDiff(
            device_id=coerce_uuid(device_id, object_name="Device"),
            from_snapshot_id=coerce_uuid(from_snapshot_id, object_name="Config snapshot"),
            to_snapshot_id=coerce_uuid(to_snapshot_id, object_name="Config snapshot"),
            diff_text=diff_text,
            diff_hash=diff_hash,
            change_summary=change_summary,
        )
        self.session.add(diff)
        self.session.flush()
        return diff

    def get_diff(self, diff_id: str | uuid.UUID) -> ConfigSnapshotDiff:
        parsed_id = coerce_uuid(diff_id, object_name="Config snapshot diff")
        diff = self.session.get(ConfigSnapshotDiff, parsed_id)
        if diff is None:
            raise NotFoundError(f"Config snapshot diff {diff_id} not found")
        return diff

    def list_diffs_for_device(self, device_id: str | uuid.UUID) -> list[ConfigSnapshotDiff]:
        parsed_id = coerce_uuid(device_id, object_name="Device")
        return list(
            self.session.scalars(
                select(ConfigSnapshotDiff).where(ConfigSnapshotDiff.device_id == parsed_id).order_by(ConfigSnapshotDiff.created_at.desc())
            ).all()
        )

    def find_diff_between_snapshots(
        self,
        from_snapshot_id: str | uuid.UUID,
        to_snapshot_id: str | uuid.UUID,
    ) -> ConfigSnapshotDiff | None:
        parsed_from_id = coerce_uuid(from_snapshot_id, object_name="Config snapshot")
        parsed_to_id = coerce_uuid(to_snapshot_id, object_name="Config snapshot")
        return self.session.scalar(
            select(ConfigSnapshotDiff).where(
                ConfigSnapshotDiff.from_snapshot_id == parsed_from_id,
                ConfigSnapshotDiff.to_snapshot_id == parsed_to_id,
            )
        )

    def delete_old_snapshots(
        self,
        retention_days: int,
        max_snapshots_per_device: int | None = None,
    ) -> int:
        cutoff = utcnow() - timedelta(days=retention_days)
        to_delete: dict[uuid.UUID, ConfigSnapshot] = {}
        for snapshot in self.session.scalars(select(ConfigSnapshot).where(ConfigSnapshot.collected_at < cutoff)).all():
            to_delete[snapshot.id] = snapshot
        if max_snapshots_per_device is not None:
            device_ids = {snapshot.device_id for snapshot in self.session.scalars(select(ConfigSnapshot)).all()}
            for device_id in device_ids:
                snapshots = self.list_snapshots_for_device(device_id)
                for snapshot in snapshots[max_snapshots_per_device:]:
                    to_delete[snapshot.id] = snapshot
        if not to_delete:
            return 0
        snapshot_ids = set(to_delete)
        for diff in self.session.scalars(
            select(ConfigSnapshotDiff).where(
                or_(
                    ConfigSnapshotDiff.from_snapshot_id.in_(snapshot_ids),
                    ConfigSnapshotDiff.to_snapshot_id.in_(snapshot_ids),
                )
            )
        ).all():
            self.session.delete(diff)
        for snapshot in to_delete.values():
            self.session.delete(snapshot)
        self.session.flush()
        return len(to_delete)
