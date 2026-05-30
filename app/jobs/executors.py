from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models.job import Job, JobTask
from app.db.session import SessionLocal
from app.drivers.base import BaseNetworkDriver, CommandResult
from app.core.config import Settings, get_settings
from app.core.exceptions import SafetyError
from app.repositories.job_tasks import JobTaskRepository
from app.repositories.jobs import JobRepository
from app.schemas.job import JobRunResponse
from app.services.audit_service import AuditService
from app.services.backup_service import BackupService
from app.services.lock_service import LockService
from app.transports.base import Transport
from app.transports.dummy_transport import DummyTransport
from app.utils.masking import mask_secrets


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DeviceJobExecutor:
    def __init__(self, driver: BaseNetworkDriver, transport: Transport):
        self.driver = driver
        self.transport = transport

    def execute_commands(self, commands: list[str], timeout_seconds: int = 60) -> list[CommandResult]:
        self.transport.open()
        try:
            results = self.transport.send_config(commands, timeout_seconds=timeout_seconds)
            return [
                CommandResult(
                    commands=[result.command],
                    output=result.output,
                    success=result.success,
                    changed=result.success,
                    error=result.error,
                )
                for result in results
            ]
        finally:
            self.transport.close()


class JobExecutionService:
    def __init__(
        self,
        session: Session | None = None,
        settings: Settings | None = None,
        audit: AuditService | None = None,
        backup_service: BackupService | None = None,
        lock_service: LockService | None = None,
    ):
        self.session = session or SessionLocal()
        self.jobs = JobRepository(self.session)
        self.tasks = JobTaskRepository(self.session)
        self.settings = settings or get_settings()
        self.audit = audit or AuditService(self.session)
        self.backup_service = backup_service or BackupService(self.session, audit=self.audit)
        self.lock_service = lock_service or LockService(self.session, audit=self.audit)
        self._acquired_locks: set[str] = set()

    def execute_job(self, job_id: str, actor: str) -> JobRunResponse:
        job = self._job(job_id)
        if job.status == "cancelled":
            raise SafetyError("Cancelled job cannot be run")
        if job.approval_status != "approved":
            raise SafetyError("Job must be approved before execution")
        if not job.dry_run:
            raise SafetyError("Job has no dry-run payload")
        if not self.settings.backup_before_apply:
            raise SafetyError("backup_before_apply must be enabled")

        job.status = "running"
        job.started_at = utcnow()
        self.session.flush()
        task_statuses: dict[str, str] = {}
        for task_id in self.jobs.task_ids(job.id):
            task_statuses[str(task_id)] = self.execute_job_task(str(task_id), actor=actor)
        final_statuses = set(task_statuses.values())
        if final_statuses <= {"succeeded"}:
            job.status = "succeeded"
        elif "succeeded" in final_statuses:
            job.status = "partially_failed"
        else:
            job.status = "failed"
        job.finished_at = utcnow()
        self.session.flush()
        return JobRunResponse(job_id=str(job.id), status=job.status, task_statuses=task_statuses)

    def execute_job_task(self, job_task_id: str, actor: str) -> str:
        task = self._task(job_task_id)
        job = self._job(str(task.job_id))
        task.started_at = utcnow()
        task.attempt += 1
        self.session.flush()
        self.audit.write(
            actor=actor,
            action="task.started",
            object_type="job_task",
            object_id=str(task.id),
            device_id=str(task.device_id),
            job_id=str(job.id),
        )
        try:
            self.execute_vlan_change_task(job, task, actor=actor)
            task.status = "succeeded"
            self.session.flush()
            self.audit.write(
                actor=actor,
                action="task.succeeded",
                object_type="job_task",
                object_id=str(task.id),
                device_id=str(task.device_id),
                job_id=str(job.id),
            )
        except SafetyError as exc:
            if task.status != "skipped":
                task.status = "failed"
            task.error = mask_secrets(str(exc))
            self.session.flush()
            self.audit.write(
                actor=actor,
                action="task.skipped" if task.status == "skipped" else "task.failed",
                object_type="job_task",
                object_id=str(task.id),
                device_id=str(task.device_id),
                job_id=str(job.id),
                metadata={"error": task.error},
            )
        except Exception as exc:
            task.status = "failed"
            task.error = mask_secrets(str(exc))
            self.session.flush()
            self.audit.write(
                actor=actor,
                action="task.failed",
                object_type="job_task",
                object_id=str(task.id),
                device_id=str(task.device_id),
                job_id=str(job.id),
                metadata={"error": task.error},
            )
        finally:
            task.finished_at = utcnow()
            self.session.flush()
            device_id = str(task.device_id)
            if device_id in self._acquired_locks:
                self.lock_service.release(device_id, actor=actor)
                self._acquired_locks.remove(device_id)
        return task.status

    def execute_vlan_change_task(self, job: Job, task: JobTask, actor: str) -> None:
        dry_run = task.dry_run_device
        if job.job_type != "vlan_change":
            raise SafetyError(f"Unsupported job type: {job.job_type}")
        if job.status == "cancelled":
            raise SafetyError("Job was cancelled")
        if not dry_run.get("apply_supported", False):
            task.status = "skipped"
            raise SafetyError("Driver is not confirmed for destructive apply")
        if not dry_run.get("verification_commands"):
            raise SafetyError("Verification commands are required before apply")
        if not self.settings.allow_real_device_apply and dry_run.get("transport") in {"scrapli", "netmiko"}:
            raise SafetyError("Real device apply is disabled by NCP_ALLOW_REAL_DEVICE_APPLY=false")

        self.lock_service.acquire(str(task.device_id), str(job.id), actor=actor)
        self._acquired_locks.add(str(task.device_id))
        task.status = "locked"
        self.session.flush()

        task.status = "backing_up"
        self.session.flush()
        backup = self.backup_service.create_backup(
            device_id=str(task.device_id),
            actor=actor,
            job_task_id=str(task.id),
            job_id=str(job.id),
            config_text=f"! pre-change backup for {task.device_id}\n",
        )
        task.backup_id = uuid.UUID(backup.id)
        self.session.flush()

        transport = DummyTransport()
        task.status = "applying"
        self.session.flush()
        transport.open()
        try:
            config_results = transport.send_config(list(dry_run.get("config_commands", [])))
            if not all(result.success for result in config_results):
                raise SafetyError("One or more config commands failed")
            task.status = "verifying"
            self.session.flush()
            verify_results = [
                transport.send_command(command)
                for command in list(dry_run.get("verification_commands", []))
            ]
            if not all(result.success for result in verify_results):
                raise SafetyError("Verification failed")
            task.status = "saving"
            self.session.flush()
            save_results = transport.send_config(list(dry_run.get("save_commands", [])))
            if not all(result.success for result in save_results):
                raise SafetyError("Save config failed")
            task.sanitized_output = mask_secrets(
                "\n".join(result.output for result in [*config_results, *verify_results, *save_results])
            )
            self.session.flush()
        finally:
            transport.close()

    def _job(self, job_id: str) -> Job:
        try:
            return self.jobs.get(job_id)
        except Exception as exc:
            raise SafetyError(f"Job {job_id} not found") from exc

    def _task(self, task_id: str) -> JobTask:
        try:
            return self.tasks.get(task_id)
        except Exception as exc:
            raise SafetyError(f"Job task {task_id} not found") from exc
