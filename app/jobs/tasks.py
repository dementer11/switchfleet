from __future__ import annotations

from app.jobs.celery_app import celery_app


@celery_app.task(name="network_control_platform.noop")  # type: ignore[untyped-decorator]
def noop() -> str:
    return "ok"
