from __future__ import annotations

import builtins
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models.job import Job, JobTask
from app.repositories import coerce_uuid


class JobRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        job_type: str,
        status: str,
        requested_by: str,
        approval_status: str,
        dry_run: dict[str, Any],
        input_payload: dict[str, Any],
    ) -> Job:
        job = Job(
            job_type=job_type,
            status=status,
            requested_by=requested_by,
            approval_status=approval_status,
            dry_run=dry_run,
            input_payload=input_payload,
        )
        self.session.add(job)
        self.session.flush()
        return job

    def list(self) -> builtins.list[Job]:
        return [job for job in self.session.scalars(select(Job).order_by(Job.created_at.desc())).all()]

    def get(self, job_id: str | uuid.UUID) -> Job:
        parsed_id = coerce_uuid(job_id, object_name="Job")
        job = self.session.get(Job, parsed_id)
        if job is None:
            raise NotFoundError(f"Job {job_id} not found")
        return job

    def task_ids(self, job_id: str | uuid.UUID) -> builtins.list[uuid.UUID]:
        parsed_id = coerce_uuid(job_id, object_name="Job")
        return [task_id for task_id in self.session.scalars(select(JobTask.id).where(JobTask.job_id == parsed_id)).all()]

    def flush(self) -> None:
        self.session.flush()
