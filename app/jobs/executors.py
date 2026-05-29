from __future__ import annotations

from app.drivers.base import BaseNetworkDriver, CommandResult
from app.core.config import Settings, get_settings
from app.core.exceptions import SafetyError
from app.schemas.job import JobRunResponse
from app.services.audit_service import AuditService
from app.services.backup_service import BackupService
from app.services.lock_service import LockService
from app.services.runtime_state import RuntimeState, StoredJob, StoredJobTask, get_runtime_state, utcnow
from app.transports.base import Transport
from app.transports.dummy_transport import DummyTransport
from app.utils.masking import mask_secrets


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
        state: RuntimeState | None = None,
        settings: Settings | None = None,
        audit: AuditService | None = None,
        backup_service: BackupService | None = None,
        lock_service: LockService | None = None,
    ):
        self.state = state or get_runtime_state()
        self.settings = settings or get_settings()
        self.audit = audit or AuditService(self.state)
        self.backup_service = backup_service or BackupService(self.state, audit=self.audit)
        self.lock_service = lock_service or LockService(self.state, audit=self.audit)

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
        task_statuses: dict[str, str] = {}
        for task_id in job.task_ids:
            task_statuses[task_id] = self.execute_job_task(task_id, actor=actor)
        final_statuses = set(task_statuses.values())
        if final_statuses <= {"succeeded"}:
            job.status = "succeeded"
        elif "succeeded" in final_statuses:
            job.status = "partially_failed"
        else:
            job.status = "failed"
        job.finished_at = utcnow()
        return JobRunResponse(job_id=job.id, status=job.status, task_statuses=task_statuses)

    def execute_job_task(self, job_task_id: str, actor: str) -> str:
        task = self._task(job_task_id)
        job = self._job(task.job_id)
        task.started_at = utcnow()
        task.attempt += 1
        self.audit.write(
            actor=actor,
            action="task.started",
            object_type="job_task",
            object_id=task.id,
            device_id=task.device_id,
            job_id=job.id,
        )
        try:
            self.execute_vlan_change_task(job, task, actor=actor)
            task.status = "succeeded"
            self.audit.write(
                actor=actor,
                action="task.succeeded",
                object_type="job_task",
                object_id=task.id,
                device_id=task.device_id,
                job_id=job.id,
            )
        except SafetyError as exc:
            if task.status != "skipped":
                task.status = "failed"
            task.error = mask_secrets(str(exc))
            self.audit.write(
                actor=actor,
                action="task.skipped" if task.status == "skipped" else "task.failed",
                object_type="job_task",
                object_id=task.id,
                device_id=task.device_id,
                job_id=job.id,
                metadata={"error": task.error},
            )
        except Exception as exc:
            task.status = "failed"
            task.error = mask_secrets(str(exc))
            self.audit.write(
                actor=actor,
                action="task.failed",
                object_type="job_task",
                object_id=task.id,
                device_id=task.device_id,
                job_id=job.id,
                metadata={"error": task.error},
            )
        finally:
            task.finished_at = utcnow()
            if task.dry_run_device.pop("_lock_acquired", False):
                self.lock_service.release(task.device_id, actor=actor)
        return task.status

    def execute_vlan_change_task(self, job: StoredJob, task: StoredJobTask, actor: str) -> None:
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

        self.lock_service.acquire(task.device_id, job.id, actor=actor)
        task.dry_run_device["_lock_acquired"] = True
        task.status = "locked"

        task.status = "backing_up"
        backup = self.backup_service.create_backup(
            device_id=task.device_id,
            actor=actor,
            job_task_id=task.id,
            job_id=job.id,
            config_text=f"! pre-change backup for {task.device_id}\n",
        )
        task.backup_id = backup.id

        transport = DummyTransport()
        task.status = "applying"
        transport.open()
        try:
            config_results = transport.send_config(list(dry_run.get("config_commands", [])))
            if not all(result.success for result in config_results):
                raise SafetyError("One or more config commands failed")
            task.status = "verifying"
            verify_results = [
                transport.send_command(command)
                for command in list(dry_run.get("verification_commands", []))
            ]
            if not all(result.success for result in verify_results):
                raise SafetyError("Verification failed")
            task.status = "saving"
            save_results = transport.send_config(list(dry_run.get("save_commands", [])))
            if not all(result.success for result in save_results):
                raise SafetyError("Save config failed")
            task.sanitized_output = mask_secrets(
                "\n".join(result.output for result in [*config_results, *verify_results, *save_results])
            )
        finally:
            transport.close()

    def _job(self, job_id: str) -> StoredJob:
        job = self.state.jobs.get(job_id)
        if job is None:
            raise SafetyError(f"Job {job_id} not found")
        return job

    def _task(self, task_id: str) -> StoredJobTask:
        task = self.state.job_tasks.get(task_id)
        if task is None:
            raise SafetyError(f"Job task {task_id} not found")
        return task
