from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models.inventory import InventoryImportBatch, InventoryImportRow
from app.repositories import coerce_uuid


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InventoryImportRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_batch(
        self,
        source_type: str,
        filename: str | None = None,
        requested_by: str | None = None,
    ) -> InventoryImportBatch:
        batch = InventoryImportBatch(
            filename=filename,
            source_type=source_type,
            status="pending",
            requested_by=requested_by,
            total_rows=0,
            valid_rows=0,
            invalid_rows=0,
            created_devices=0,
            updated_devices=0,
            skipped_rows=0,
        )
        self.session.add(batch)
        self.session.flush()
        return batch

    def add_rows(self, batch_id: str | uuid.UUID, rows: list[dict[str, Any]]) -> list[InventoryImportRow]:
        parsed_batch_id = coerce_uuid(batch_id, object_name="Inventory import batch")
        created: list[InventoryImportRow] = []
        for index, raw_data in enumerate(rows, start=1):
            row = InventoryImportRow(
                batch_id=parsed_batch_id,
                row_index=index,
                raw_data=raw_data,
                normalized_data=None,
                status="valid",
            )
            self.session.add(row)
            created.append(row)
        self.session.flush()
        batch = self.get_batch(parsed_batch_id)
        batch.total_rows = len(created)
        self.session.flush()
        return created

    def get_batch(self, batch_id: str | uuid.UUID) -> InventoryImportBatch:
        parsed_id = coerce_uuid(batch_id, object_name="Inventory import batch")
        batch = self.session.get(InventoryImportBatch, parsed_id)
        if batch is None:
            raise NotFoundError(f"Inventory import batch {batch_id} not found")
        return batch

    def list_batches(self, status: str | None = None) -> list[InventoryImportBatch]:
        statement = select(InventoryImportBatch)
        if status is not None:
            statement = statement.where(InventoryImportBatch.status == status)
        return list(self.session.scalars(statement.order_by(InventoryImportBatch.created_at.desc())).all())

    def get_row(self, row_id: str | uuid.UUID) -> InventoryImportRow:
        parsed_id = coerce_uuid(row_id, object_name="Inventory import row")
        row = self.session.get(InventoryImportRow, parsed_id)
        if row is None:
            raise NotFoundError(f"Inventory import row {row_id} not found")
        return row

    def list_rows(self, batch_id: str | uuid.UUID) -> list[InventoryImportRow]:
        parsed_id = coerce_uuid(batch_id, object_name="Inventory import batch")
        return list(
            self.session.scalars(
                select(InventoryImportRow)
                .where(InventoryImportRow.batch_id == parsed_id)
                .order_by(InventoryImportRow.row_index)
            ).all()
        )

    def update_batch_status(self, batch_id: str | uuid.UUID, status: str, error_summary: str | None = None) -> InventoryImportBatch:
        batch = self.get_batch(batch_id)
        batch.status = status
        if error_summary is not None:
            batch.error_summary = error_summary
        self.session.flush()
        return batch

    def mark_row_valid(self, row_id: str | uuid.UUID, normalized_data: dict[str, Any]) -> InventoryImportRow:
        return self._mark_row(row_id, status="valid", normalized_data=normalized_data)

    def mark_row_invalid(self, row_id: str | uuid.UUID, error_message: str, normalized_data: dict[str, Any] | None = None) -> InventoryImportRow:
        return self._mark_row(row_id, status="invalid", normalized_data=normalized_data, error_message=error_message)

    def mark_row_created(self, row_id: str | uuid.UUID, device_id: str | uuid.UUID) -> InventoryImportRow:
        return self._mark_row(row_id, status="created", device_id=device_id)

    def mark_row_updated(self, row_id: str | uuid.UUID, device_id: str | uuid.UUID) -> InventoryImportRow:
        return self._mark_row(row_id, status="updated", device_id=device_id)

    def mark_row_skipped(self, row_id: str | uuid.UUID, reason: str | None = None) -> InventoryImportRow:
        return self._mark_row(row_id, status="skipped", error_message=reason)

    def mark_row_failed(self, row_id: str | uuid.UUID, reason: str) -> InventoryImportRow:
        return self._mark_row(row_id, status="failed", error_message=reason)

    def finish_batch(
        self,
        batch_id: str | uuid.UUID,
        status: str,
        error_summary: str | None = None,
    ) -> InventoryImportBatch:
        batch = self.get_batch(batch_id)
        rows = self.list_rows(batch_id)
        batch.status = status
        batch.total_rows = len(rows)
        batch.valid_rows = sum(1 for row in rows if row.status in {"valid", "created", "updated", "skipped"})
        batch.invalid_rows = sum(1 for row in rows if row.status in {"invalid", "failed"})
        batch.created_devices = sum(1 for row in rows if row.status == "created")
        batch.updated_devices = sum(1 for row in rows if row.status == "updated")
        batch.skipped_rows = sum(1 for row in rows if row.status == "skipped")
        batch.error_summary = error_summary
        batch.finished_at = utcnow()
        self.session.flush()
        return batch

    def _mark_row(
        self,
        row_id: str | uuid.UUID,
        status: str,
        normalized_data: dict[str, Any] | None = None,
        error_message: str | None = None,
        device_id: str | uuid.UUID | None = None,
    ) -> InventoryImportRow:
        row = self.get_row(row_id)
        row.status = status
        if normalized_data is not None:
            row.normalized_data = normalized_data
        row.error_message = error_message
        if device_id is not None:
            row.device_id = coerce_uuid(device_id, object_name="Device")
        self.session.flush()
        return row
