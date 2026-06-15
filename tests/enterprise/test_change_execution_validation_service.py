from __future__ import annotations

from app.db.session import SessionLocal
from app.repositories.change_executions import ChangeExecutionRepository
from app.repositories.vlan_workflows import VlanWorkflowRepository, utcnow
from app.services.change_execution_validation_service import ChangeExecutionValidationService
from tests.enterprise.change_execution_helpers import create_device, create_ready_vlan_source


def test_change_execution_validation_accepts_simulation_ready_vlan_source() -> None:
    session = SessionLocal()
    source_id, device_id = create_ready_vlan_source(session)
    execution = ChangeExecutionRepository(session).create_execution(
        "simulate vlan",
        "vlan_change",
        "vlan_workflow",
        source_id=source_id,
    )
    session.commit()

    report = ChangeExecutionValidationService(SessionLocal()).validate_execution(str(execution.id))

    assert report.errors == []
    assert report.target_device_ids == [device_id]
    assert report.execution.status == "validated"


def test_change_execution_validation_blocks_non_simulation_mode_missing_source_and_blocked_source() -> None:
    session = SessionLocal()
    repo = ChangeExecutionRepository(session)
    bad_mode = repo.create_execution("bad mode", "vlan_change", "manual", mode="apply")
    missing = repo.create_execution("missing", "vlan_change", "vlan_workflow")
    device = create_device(session, ip="192.0.2.40")
    source_id, _device_id = create_ready_vlan_source(session, device=device, status="blocked")
    blocked = repo.create_execution("blocked", "vlan_change", "vlan_workflow", source_id=source_id)
    session.commit()
    service = ChangeExecutionValidationService(SessionLocal())

    assert service.validate_mode(str(bad_mode.id))
    assert service.validate_source_exists(str(missing.id))
    assert service.validate_source_ready(str(blocked.id))


def test_change_execution_validation_blocks_missing_stale_backup_missing_lab_and_conflicting_lock() -> None:
    session = SessionLocal()
    device = create_device(session, ip="192.0.2.41")
    source_id, _device_id = create_ready_vlan_source(session, device=device)
    execution = ChangeExecutionRepository(session).create_execution("exec", "vlan_change", "vlan_workflow", source_id=source_id)
    conflict = ChangeExecutionRepository(session).create_execution("conflict", "vlan_change", "manual")
    ChangeExecutionRepository(session).create_locks(
        conflict.id,
        [{"lock_type": "device", "target_type": "device", "target_id": device.id, "device_id": device.id}],
    )
    session.commit()

    assert ChangeExecutionValidationService(SessionLocal()).validate_locks(str(execution.id))

    session = SessionLocal()
    device2 = create_device(session, ip="192.0.2.42")
    source_id2, _device_id2 = create_ready_vlan_source(session, device=device2)
    latest = ChangeExecutionValidationService(session).snapshots.get_latest_snapshot_for_device(device2.id)
    latest.collected_at = utcnow().replace(year=2000)
    stale = ChangeExecutionRepository(session).create_execution("stale", "vlan_change", "vlan_workflow", source_id=source_id2)
    session.commit()

    assert ChangeExecutionValidationService(SessionLocal()).validate_fresh_backups(str(stale.id))

    session = SessionLocal()
    device3 = create_device(session, ip="192.0.2.44")
    source_id3, _device_id3 = create_ready_vlan_source(session, device=device3)
    lab_repo = ChangeExecutionValidationService(session).lab_validations
    for validation in lab_repo.list(status="approved"):
        validation.status = "expired"
    missing_lab = ChangeExecutionRepository(session).create_execution("missing lab", "vlan_change", "vlan_workflow", source_id=source_id3)
    session.commit()

    assert ChangeExecutionValidationService(SessionLocal()).validate_lab_validations(str(missing_lab.id))


def test_change_execution_validation_blocks_unready_vlan_source() -> None:
    session = SessionLocal()
    device = create_device(session, ip="192.0.2.43")
    source_id, _device_id = create_ready_vlan_source(session, device=device)
    VlanWorkflowRepository(session).update_request_status(source_id, "pending_approval")
    execution = ChangeExecutionRepository(session).create_execution("unready", "vlan_change", "vlan_workflow", source_id=source_id)
    session.commit()

    report = ChangeExecutionValidationService(SessionLocal()).build_validation_report(str(execution.id))

    assert any("must be ready or approved" in error for error in report.errors)
