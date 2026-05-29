from __future__ import annotations

from app.core.rbac import Actor, Permission, require_permission


class ApprovalService:
    def approve(self, actor: Actor, job_id: str) -> dict[str, str]:
        require_permission(actor, Permission.approve_job)
        return {"job_id": job_id, "approval_status": "approved", "approved_by": actor.username}

