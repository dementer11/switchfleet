from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.db.models.job import Job, JobTask
from app.db.session import SessionLocal
from app.repositories.devices import DeviceRepository
from app.repositories.job_tasks import JobTaskRepository
from app.repositories.jobs import JobRepository
from app.schemas.job import JobCreateResponse, JobDryRunResponse, JobRead, JobTaskRead, VlanChangeJobRequest
from app.services.audit_service import AuditService
from app.services.change_planner import ChangePlanner


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobService:
    def __init__(
        self,
        session: Session | None = None,
        planner: ChangePlanner | None = None,
        audit: AuditService | None = None,
    ):
        self.session = session or SessionLocal()
        self.jobs = JobRepository(self.session)
        self.tasks = JobTaskRepository(self.session)
        self.devices = DeviceRepository(self.session)
        self.planner = planner or ChangePlanner()
        self.audit = audit or AuditService(self.session)

    def create_vlan_change_job(self, payload: VlanChangeJobRequest, actor: str) -> JobCreateResponse:
        dry_run = self.planner.plan_vlan_change(payload)
        dry_run_dict = dry_run.model_dump()
        for index, device_result in enumerate(dry_run_dict["devices"]):
            device_input = payload.devices[index]
            stored_device = self.devices.create_or_update_from_input(
                device_input,
                driver_name=str(device_result.get("driver") or ""),
                capabilities=dict(device_result.get("capabilities") or {}),
            )
            device_result["device_id"] = str(stored_device.id)
        job = self.jobs.create(
            job_type="vlan_change",
            status="pending_approval",
            requested_by=actor,
            approval_status="pending",
            dry_run=dry_run_dict,
            input_payload=payload.model_dump(),
        )
        for device in dry_run_dict["devices"]:
            self.tasks.create(
                job_id=job.id,
                device_id=str(device["device_id"]),
                commands=list(device["commands"]),
                dry_run_device=device,
            )
        job.dry_run = dry_run_dict
        self.session.flush()
        self.audit.write(
            actor=actor,
            action="job.created",
            object_type="job",
            object_id=str(job.id),
            after={"job_type": job.job_type, "status": job.status, "approval_status": job.approval_status},
        )
        self.audit.write(
            actor=actor,
            action="job.dry_run_generated",
            object_type="job",
            object_id=str(job.id),
            after={"device_count": dry_run.device_count, "estimated_impact": dry_run.estimated_impact},
        )
        return JobCreateResponse(
            job_id=str(job.id),
            status=job.status,
            approval_status=job.approval_status,
            approval_required=True,
            apply_allowed=False,
            dry_run=JobDryRunResponse.model_validate(job.dry_run),
        )

    def list_jobs(self) -> list[JobRead]:
        return [self._read_job(job) for job in self.jobs.list()]

    def get_job(self, job_id: str) -> JobRead:
        return self._read_job(self._stored_job(job_id))

    def get_dry_run(self, job_id: str) -> JobDryRunResponse:
        return JobDryRunResponse.model_validate(self._stored_job(job_id).dry_run)

    def list_tasks(self, job_id: str) -> list[JobTaskRead]:
        self._stored_job(job_id)
        return [self._read_task(task) for task in self.tasks.list_by_job(job_id)]

    def approve(self, job_id: str, actor: str) -> JobRead:
        job = self._stored_job(job_id)
        if job.status == "cancelled":
            raise ConflictError("Cancelled job cannot be approved")
        if job.approval_status == "approved":
            return self._read_job(job)
        before = {"status": job.status, "approval_status": job.approval_status}
        job.status = "approved"
        job.approval_status = "approved"
        job.approved_by = actor
        job.approved_at = utcnow()
        self.session.flush()
        self.audit.write(
            actor=actor,
            action="job.approved",
            object_type="job",
            object_id=str(job.id),
            job_id=str(job.id),
            before=before,
            after={"status": job.status, "approval_status": job.approval_status, "approved_by": actor},
        )
        return self._read_job(job)

    def cancel(self, job_id: str, actor: str) -> JobRead:
        job = self._stored_job(job_id)
        if job.status == "cancelled":
            return self._read_job(job)
        if job.status in {"running", "succeeded"}:
            raise ConflictError(f"Cannot cancel job in status {job.status}")
        before = {"status": job.status, "approval_status": job.approval_status}
        job.status = "cancelled"
        job.approval_status = "cancelled"
        job.finished_at = utcnow()
        for task in self.tasks.list_by_job(job.id):
            if task.status == "pending":
                task.status = "skipped"
                task.error = "Job cancelled before execution"
        self.session.flush()
        self.audit.write(
            actor=actor,
            action="job.cancelled",
            object_type="job",
            object_id=str(job.id),
            job_id=str(job.id),
            before=before,
            after={"status": job.status, "approval_status": job.approval_status},
        )
        return self._read_job(job)

    def create_draft_from_dry_run(self, dry_run: JobDryRunResponse) -> dict[str, object]:
        return {"status": "pending_approval", "dry_run": dry_run.model_dump()}

    def _stored_job(self, job_id: str) -> Job:
        try:
            return self.jobs.get(job_id)
        except NotFoundError:
            raise

    def _read_job(self, job: Job) -> JobRead:
        return JobRead(
            id=str(job.id),
            job_type=job.job_type,
            status=job.status,
            requested_by=job.requested_by,
            approved_by=job.approved_by,
            approval_status=job.approval_status,
            created_at=job.created_at.isoformat(),
            approved_at=job.approved_at.isoformat() if job.approved_at else None,
            started_at=job.started_at.isoformat() if job.started_at else None,
            finished_at=job.finished_at.isoformat() if job.finished_at else None,
            task_ids=[str(task_id) for task_id in self.jobs.task_ids(job.id)],
        )

    def _read_task(self, task: JobTask) -> JobTaskRead:
        return JobTaskRead(
            id=str(task.id),
            job_id=str(task.job_id),
            device_id=str(task.device_id),
            status=task.status,
            attempt=task.attempt,
            commands=list(task.commands),
            sanitized_output=task.sanitized_output,
            error=task.error,
            backup_id=str(task.backup_id) if task.backup_id else None,
            started_at=task.started_at.isoformat() if task.started_at else None,
            finished_at=task.finished_at.isoformat() if task.finished_at else None,
        )
