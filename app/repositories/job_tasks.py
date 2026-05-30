from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models.job import JobTask
from app.repositories import coerce_uuid


class JobTaskRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        job_id: str | uuid.UUID,
        device_id: str | uuid.UUID,
        commands: list[str],
        dry_run_device: dict[str, Any],
        status: str = "pending",
    ) -> JobTask:
        task = JobTask(
            job_id=coerce_uuid(job_id, object_name="Job"),
            device_id=coerce_uuid(device_id, object_name="Device"),
            status=status,
            attempt=0,
            commands=list(commands),
            dry_run_device=dict(dry_run_device),
        )
        self.session.add(task)
        self.session.flush()
        return task

    def get(self, job_task_id: str | uuid.UUID) -> JobTask:
        parsed_id = coerce_uuid(job_task_id, object_name="Job task")
        task = self.session.get(JobTask, parsed_id)
        if task is None:
            raise NotFoundError(f"Job task {job_task_id} not found")
        return task

    def list_by_job(self, job_id: str | uuid.UUID) -> list[JobTask]:
        parsed_id = coerce_uuid(job_id, object_name="Job")
        return list(self.session.scalars(select(JobTask).where(JobTask.job_id == parsed_id)).all())

    def flush(self) -> None:
        self.session.flush()
