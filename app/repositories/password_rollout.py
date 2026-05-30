from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models.password import PasswordRolloutBatch, PasswordRolloutBatchTask
from app.repositories import coerce_uuid


class PasswordRolloutRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_batches(
        self,
        job_id: str | uuid.UUID,
        job_task_ids: Sequence[str | uuid.UUID],
        canary_plan: Sequence[int],
    ) -> list[PasswordRolloutBatch]:
        parsed_job_id = coerce_uuid(job_id, object_name="Job")
        parsed_task_ids = [coerce_uuid(task_id, object_name="Job task") for task_id in job_task_ids]
        batches: list[PasswordRolloutBatch] = []
        offset = 0
        for batch_index, batch_size in enumerate(canary_plan):
            batch_task_ids = parsed_task_ids[offset : offset + batch_size]
            offset += batch_size
            batch = PasswordRolloutBatch(
                job_id=parsed_job_id,
                batch_index=batch_index,
                batch_size=len(batch_task_ids),
                status="pending",
            )
            self.session.add(batch)
            self.session.flush()
            for task_id in batch_task_ids:
                self.session.add(
                    PasswordRolloutBatchTask(
                        batch_id=batch.id,
                        job_task_id=task_id,
                        status="pending",
                    )
                )
            batches.append(batch)
        self.session.flush()
        return batches

    def list_batches(self, job_id: str | uuid.UUID) -> list[PasswordRolloutBatch]:
        parsed_job_id = coerce_uuid(job_id, object_name="Job")
        return [
            batch
            for batch in self.session.scalars(
                select(PasswordRolloutBatch)
                .where(PasswordRolloutBatch.job_id == parsed_job_id)
                .order_by(PasswordRolloutBatch.batch_index)
            ).all()
        ]

    def get_next_pending_batch(self, job_id: str | uuid.UUID) -> PasswordRolloutBatch | None:
        parsed_job_id = coerce_uuid(job_id, object_name="Job")
        return self.session.scalar(
            select(PasswordRolloutBatch)
            .where(PasswordRolloutBatch.job_id == parsed_job_id, PasswordRolloutBatch.status == "pending")
            .order_by(PasswordRolloutBatch.batch_index)
            .limit(1)
        )

    def get_batch(self, batch_id: str | uuid.UUID) -> PasswordRolloutBatch:
        parsed_id = coerce_uuid(batch_id, object_name="Password rollout batch")
        batch = self.session.get(PasswordRolloutBatch, parsed_id)
        if batch is None:
            raise NotFoundError(f"Password rollout batch {batch_id} not found")
        return batch

    def update_batch_status(
        self,
        batch_id: str | uuid.UUID,
        status: str,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> PasswordRolloutBatch:
        batch = self.get_batch(batch_id)
        batch.status = status
        if started_at is not None:
            batch.started_at = started_at
        if finished_at is not None:
            batch.finished_at = finished_at
        self.session.flush()
        return batch

    def list_batch_tasks(self, batch_id: str | uuid.UUID) -> list[PasswordRolloutBatchTask]:
        parsed_id = coerce_uuid(batch_id, object_name="Password rollout batch")
        return [
            task
            for task in self.session.scalars(
                select(PasswordRolloutBatchTask)
                .where(PasswordRolloutBatchTask.batch_id == parsed_id)
                .order_by(PasswordRolloutBatchTask.created_at, PasswordRolloutBatchTask.id)
            ).all()
        ]

    def update_batch_task_status(
        self,
        batch_task_id: str | uuid.UUID,
        status: str,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> PasswordRolloutBatchTask:
        parsed_id = coerce_uuid(batch_task_id, object_name="Password rollout batch task")
        batch_task = self.session.get(PasswordRolloutBatchTask, parsed_id)
        if batch_task is None:
            raise NotFoundError(f"Password rollout batch task {batch_task_id} not found")
        batch_task.status = status
        if started_at is not None:
            batch_task.started_at = started_at
        if finished_at is not None:
            batch_task.finished_at = finished_at
        self.session.flush()
        return batch_task
