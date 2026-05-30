from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models.lab_validation import LabValidationChecklistItem
from app.repositories import coerce_uuid


class LabValidationChecklistRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_items(
        self,
        validation_id: str | uuid.UUID,
        items: list[tuple[str, str]],
    ) -> list[LabValidationChecklistItem]:
        parsed_id = coerce_uuid(validation_id, object_name="Lab validation")
        created: list[LabValidationChecklistItem] = []
        for item_key, description in items:
            item = LabValidationChecklistItem(
                validation_id=parsed_id,
                item_key=item_key,
                description=description,
                status="pending",
            )
            self.session.add(item)
            self.session.flush()
            created.append(item)
        self.session.flush()
        return created

    def get(self, item_id: str | uuid.UUID) -> LabValidationChecklistItem:
        parsed_id = coerce_uuid(item_id, object_name="Lab validation checklist item")
        item = self.session.get(LabValidationChecklistItem, parsed_id)
        if item is None:
            raise NotFoundError(f"Lab validation checklist item {item_id} not found")
        return item

    def list_for_validation(self, validation_id: str | uuid.UUID) -> list[LabValidationChecklistItem]:
        parsed_id = coerce_uuid(validation_id, object_name="Lab validation")
        return list(
            self.session.scalars(
                select(LabValidationChecklistItem)
                .where(LabValidationChecklistItem.validation_id == parsed_id)
                .order_by(LabValidationChecklistItem.created_at, LabValidationChecklistItem.id)
            ).all()
        )

    def update_item_status(
        self,
        item_id: str | uuid.UUID,
        status: str,
        notes: str | None = None,
    ) -> LabValidationChecklistItem:
        item = self.get(item_id)
        item.status = status
        if notes is not None:
            item.notes = notes
        self.session.flush()
        return item
