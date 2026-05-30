from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, SafetyError
from app.db.models.password import PasswordRolloutBatch, PasswordRolloutBatchTask
from app.db.session import SessionLocal
from app.jobs.executors import JobExecutionService
from app.repositories.job_tasks import JobTaskRepository
from app.repositories.jobs import JobRepository
from app.repositories.password_change_secrets import PasswordChangeSecretRepository
from app.repositories.password_rollout import PasswordRolloutRepository
from app.schemas.job import PasswordBatchRunResponse, RolloutBatchRead, RolloutBatchTaskRead, RolloutPlanResponse
from app.services.audit_service import AuditService


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_canary_plan(device_count: int, canary_plan: list[int] | None = None) -> list[int]:
    if device_count <= 0:
        return []
    requested = list(canary_plan or [1, 5, 20])
    normalized: list[int] = []
    remaining = device_count
    for size in requested:
        if remaining <= 0:
            break
        batch_size = min(size, remaining)
        if batch_size > 0:
            normalized.append(batch_size)
            remaining -= batch_size
    if remaining > 0:
        normalized.append(remaining)
    return normalized


class PasswordRolloutService:
    def __init__(
        self,
        session: Session | None = None,
        audit: AuditService | None = None,
        executor: JobExecutionService | None = None,
    ):
        self.session = session or SessionLocal()
        self.rollout = PasswordRolloutRepository(self.session)
        self.jobs = JobRepository(self.session)
        self.tasks = JobTaskRepository(self.session)
        self.secrets = PasswordChangeSecretRepository(self.session)
        self.audit = audit or AuditService(self.session)
        self.executor = executor or JobExecutionService(self.session, audit=self.audit)

    def create_rollout_plan(self, job_id: str, job_task_ids: list[str], canary_plan: list[int]) -> RolloutPlanResponse:
        batches = self.rollout.create_batches(job_id, job_task_ids, canary_plan)
        for batch in batches:
            self.audit.write(
                actor="system",
                action="password_rollout_batch_created",
                object_type="password_rollout_batch",
                object_id=str(batch.id),
                job_id=job_id,
                after={"batch_index": batch.batch_index, "batch_size": batch.batch_size},
            )
        return self.get_rollout_plan(job_id)

    def get_rollout_plan(self, job_id: str) -> RolloutPlanResponse:
        self.jobs.get(job_id)
        return RolloutPlanResponse(
            job_id=job_id,
            batches=[self._read_batch(batch) for batch in self.rollout.list_batches(job_id)],
        )

    def run_next_batch(self, job_id: str, actor: str) -> PasswordBatchRunResponse:
        job = self.jobs.get(job_id)
        if job.job_type != "password_change":
            raise SafetyError(f"Unsupported job type for password rollout: {job.job_type}")
        if job.status == "cancelled":
            raise SafetyError("Cancelled job cannot be run")
        if job.status == "paused":
            raise SafetyError("Password rollout is paused")
        if job.status in {"succeeded", "failed"}:
            raise SafetyError(f"Password rollout cannot run in status {job.status}")
        if job.approval_status != "approved":
            raise SafetyError("Job must be approved before execution")
        if not job.dry_run:
            raise SafetyError("Job has no dry-run payload")
        if not bool(job.input_payload.get("backup_before_apply", True)):
            raise SafetyError("backup_before_apply must be enabled")
        if not bool(job.input_payload.get("verify_new_credential", True)):
            raise SafetyError("verify_new_credential must be enabled")

        batch = self.rollout.get_next_pending_batch(job_id)
        if batch is None:
            return self._complete_if_done(job_id)

        batch.started_at = utcnow()
        batch.status = "running"
        job.status = "running"
        self.session.flush()
        self.audit.write(
            actor=actor,
            action="password_rollout_batch_started",
            object_type="password_rollout_batch",
            object_id=str(batch.id),
            job_id=job_id,
            after={"batch_index": batch.batch_index, "batch_size": batch.batch_size},
        )

        task_statuses: dict[str, str] = {}
        failed = False
        for batch_task in self.rollout.list_batch_tasks(batch.id):
            batch_task.started_at = utcnow()
            batch_task.status = "running"
            self.session.flush()
            status = self.executor.execute_password_change_task(str(batch_task.job_task_id), actor=actor)
            batch_task.finished_at = utcnow()
            batch_task.status = "succeeded" if status == "succeeded" else "failed"
            self.session.flush()
            task_statuses[str(batch_task.job_task_id)] = batch_task.status
            if batch_task.status != "succeeded":
                failed = True

        batch.finished_at = utcnow()
        batch.status = "failed" if failed else "succeeded"
        if failed:
            job.status = "failed" if bool(job.input_payload.get("stop_on_first_failure", True)) else "partially_failed"
            action = "password_rollout_batch_failed"
        else:
            pending = self.rollout.get_next_pending_batch(job_id)
            job.status = "approved" if pending is not None else "succeeded"
            action = "password_rollout_batch_succeeded"
            if pending is None:
                self._cleanup_secret(job_id)
        self.session.flush()
        self.audit.write(
            actor=actor,
            action=action,
            object_type="password_rollout_batch",
            object_id=str(batch.id),
            job_id=job_id,
            after={"status": batch.status, "job_status": job.status},
        )
        return PasswordBatchRunResponse(
            job_id=job_id,
            status=job.status,
            message="batch completed",
            batch_id=str(batch.id),
            batch_status=batch.status,
            task_statuses=task_statuses,
            remaining_batches=len([item for item in self.rollout.list_batches(job_id) if item.status == "pending"]),
        )

    def pause_rollout(self, job_id: str, actor: str) -> RolloutPlanResponse:
        job = self.jobs.get(job_id)
        if job.job_type != "password_change":
            raise SafetyError(f"Unsupported job type for password rollout: {job.job_type}")
        if job.status in {"succeeded", "failed", "cancelled"}:
            raise ConflictError(f"Cannot pause password rollout in status {job.status}")
        job.status = "paused"
        self.session.flush()
        self.audit.write(
            actor=actor,
            action="password_rollout_paused",
            object_type="job",
            object_id=str(job.id),
            job_id=str(job.id),
            after={"status": job.status},
        )
        return self.get_rollout_plan(job_id)

    def resume_rollout(self, job_id: str, actor: str) -> RolloutPlanResponse:
        job = self.jobs.get(job_id)
        if job.job_type != "password_change":
            raise SafetyError(f"Unsupported job type for password rollout: {job.job_type}")
        if job.status != "paused":
            raise ConflictError(f"Cannot resume password rollout in status {job.status}")
        job.status = "approved"
        self.session.flush()
        self.audit.write(
            actor=actor,
            action="password_rollout_resumed",
            object_type="job",
            object_id=str(job.id),
            job_id=str(job.id),
            after={"status": job.status},
        )
        return self.get_rollout_plan(job_id)

    def stop_rollout_on_failure(self, job_id: str, actor: str) -> None:
        job = self.jobs.get(job_id)
        job.status = "failed"
        self.session.flush()
        self.audit.write(
            actor=actor,
            action="password_rollout_stopped_on_failure",
            object_type="job",
            object_id=str(job.id),
            job_id=str(job.id),
            after={"status": job.status},
        )

    def _complete_if_done(self, job_id: str) -> PasswordBatchRunResponse:
        job = self.jobs.get(job_id)
        batches = self.rollout.list_batches(job_id)
        if batches and all(batch.status == "succeeded" for batch in batches):
            job.status = "succeeded"
            self._cleanup_secret(job_id)
            self.session.flush()
            return PasswordBatchRunResponse(job_id=job_id, status=job.status, message="rollout completed")
        return PasswordBatchRunResponse(job_id=job_id, status=job.status, message="no pending rollout batch")

    def _cleanup_secret(self, job_id: str) -> None:
        try:
            self.secrets.delete_for_job(job_id)
        except NotFoundError:
            return

    def _read_batch(self, batch: PasswordRolloutBatch) -> RolloutBatchRead:
        return RolloutBatchRead(
            id=str(batch.id),
            job_id=str(batch.job_id),
            batch_index=batch.batch_index,
            batch_size=batch.batch_size,
            status=batch.status,
            created_at=batch.created_at.isoformat(),
            started_at=batch.started_at.isoformat() if batch.started_at else None,
            finished_at=batch.finished_at.isoformat() if batch.finished_at else None,
            tasks=[self._read_batch_task(task) for task in self.rollout.list_batch_tasks(batch.id)],
        )

    def _read_batch_task(self, task: PasswordRolloutBatchTask) -> RolloutBatchTaskRead:
        return RolloutBatchTaskRead(
            id=str(task.id),
            batch_id=str(task.batch_id),
            job_task_id=str(task.job_task_id),
            status=task.status,
            created_at=task.created_at.isoformat(),
            started_at=task.started_at.isoformat() if task.started_at else None,
            finished_at=task.finished_at.isoformat() if task.finished_at else None,
        )
