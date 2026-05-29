from __future__ import annotations

from app.core.exceptions import ConflictError, NotFoundError
from app.schemas.job import JobCreateResponse, JobDryRunResponse, JobRead, JobTaskRead, VlanChangeJobRequest
from app.services.audit_service import AuditService
from app.services.change_planner import ChangePlanner
from app.services.runtime_state import RuntimeState, StoredJob, StoredJobTask, get_runtime_state, new_id, utcnow


class JobService:
    def __init__(
        self,
        state: RuntimeState | None = None,
        planner: ChangePlanner | None = None,
        audit: AuditService | None = None,
    ):
        self.state = state or get_runtime_state()
        self.planner = planner or ChangePlanner()
        self.audit = audit or AuditService(self.state)

    def create_vlan_change_job(self, payload: VlanChangeJobRequest, actor: str) -> JobCreateResponse:
        dry_run = self.planner.plan_vlan_change(payload)
        job_id = new_id()
        dry_run_dict = dry_run.model_dump()
        job = StoredJob(
            id=job_id,
            job_type="vlan_change",
            status="pending_approval",
            requested_by=actor,
            approved_by=None,
            approval_status="pending",
            dry_run=dry_run_dict,
            input_payload=payload.model_dump(),
            created_at=utcnow(),
        )
        for index, device in enumerate(dry_run_dict["devices"]):
            device_id = device.get("device_id") or f"{job_id}:device:{index}"
            device["device_id"] = device_id
            task = StoredJobTask(
                id=new_id(),
                job_id=job_id,
                device_id=device_id,
                status="pending",
                attempt=0,
                commands=list(device["commands"]),
                dry_run_device=device,
            )
            self.state.job_tasks[task.id] = task
            job.task_ids.append(task.id)
        job.dry_run = dry_run_dict
        self.state.jobs[job.id] = job
        self.audit.write(
            actor=actor,
            action="job.created",
            object_type="job",
            object_id=job.id,
            after={"job_type": job.job_type, "status": job.status, "approval_status": job.approval_status},
        )
        self.audit.write(
            actor=actor,
            action="job.dry_run_generated",
            object_type="job",
            object_id=job.id,
            after={"device_count": dry_run.device_count, "estimated_impact": dry_run.estimated_impact},
        )
        return JobCreateResponse(
            job_id=job.id,
            status=job.status,
            approval_status=job.approval_status,
            approval_required=True,
            apply_allowed=False,
            dry_run=JobDryRunResponse.model_validate(job.dry_run),
        )

    def list_jobs(self) -> list[JobRead]:
        return [self._read_job(job) for job in self.state.jobs.values()]

    def get_job(self, job_id: str) -> JobRead:
        return self._read_job(self._stored_job(job_id))

    def get_dry_run(self, job_id: str) -> JobDryRunResponse:
        return JobDryRunResponse.model_validate(self._stored_job(job_id).dry_run)

    def list_tasks(self, job_id: str) -> list[JobTaskRead]:
        job = self._stored_job(job_id)
        return [self._read_task(self.state.job_tasks[task_id]) for task_id in job.task_ids]

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
        self.audit.write(
            actor=actor,
            action="job.approved",
            object_type="job",
            object_id=job.id,
            job_id=job.id,
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
        for task_id in job.task_ids:
            task = self.state.job_tasks[task_id]
            if task.status == "pending":
                task.status = "skipped"
                task.error = "Job cancelled before execution"
        self.audit.write(
            actor=actor,
            action="job.cancelled",
            object_type="job",
            object_id=job.id,
            job_id=job.id,
            before=before,
            after={"status": job.status, "approval_status": job.approval_status},
        )
        return self._read_job(job)

    def create_draft_from_dry_run(self, dry_run: JobDryRunResponse) -> dict[str, object]:
        return {"status": "pending_approval", "dry_run": dry_run.model_dump()}

    def _stored_job(self, job_id: str) -> StoredJob:
        job = self.state.jobs.get(job_id)
        if job is None:
            raise NotFoundError(f"Job {job_id} not found")
        return job

    def _read_job(self, job: StoredJob) -> JobRead:
        return JobRead(
            id=job.id,
            job_type=job.job_type,
            status=job.status,
            requested_by=job.requested_by,
            approved_by=job.approved_by,
            approval_status=job.approval_status,
            created_at=job.created_at.isoformat(),
            approved_at=job.approved_at.isoformat() if job.approved_at else None,
            started_at=job.started_at.isoformat() if job.started_at else None,
            finished_at=job.finished_at.isoformat() if job.finished_at else None,
            task_ids=list(job.task_ids),
        )

    def _read_task(self, task: StoredJobTask) -> JobTaskRead:
        return JobTaskRead(
            id=task.id,
            job_id=task.job_id,
            device_id=task.device_id,
            status=task.status,
            attempt=task.attempt,
            commands=list(task.commands),
            sanitized_output=task.sanitized_output,
            error=task.error,
            backup_id=task.backup_id,
            started_at=task.started_at.isoformat() if task.started_at else None,
            finished_at=task.finished_at.isoformat() if task.finished_at else None,
        )
