from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


SECURITY_HEADERS = {"X-Actor": "sec", "X-Roles": "security_admin"}
READ_HEADERS = {"X-Actor": "netop", "X-Roles": "network_operator"}
VIEWER_HEADERS = {"X-Actor": "viewer", "X-Roles": "viewer"}
OPERATOR_HEADERS = {"X-Actor": "operator", "X-Roles": "operator"}


def _payload() -> dict[str, object]:
    return {
        "vendor": "Cisco",
        "model_pattern": "Cat2960*",
        "driver_name": "CiscoIOSDriver",
        "capability": "password_change",
        "lab_environment": "isolated lab rack",
    }


def _secret() -> str:
    return f"runtime-secret-{uuid4().hex}"


def test_lab_validation_api_lifecycle_and_sanitized_transcript() -> None:
    client = TestClient(app)
    secret = _secret()

    created = client.post("/api/v1/lab-validations", headers=SECURITY_HEADERS, json=_payload())
    assert created.status_code == 201
    validation_id = created.json()["id"]
    assert created.json()["status"] == "pending"
    assert len(created.json()["checklist"]) == 10

    listed = client.get("/api/v1/lab-validations?vendor=Cisco", headers=READ_HEADERS)
    fetched = client.get(f"/api/v1/lab-validations/{validation_id}", headers=READ_HEADERS)
    checklist = client.get(f"/api/v1/lab-validations/{validation_id}/checklist", headers=READ_HEADERS)
    assert listed.status_code == 200
    assert fetched.status_code == 200
    assert checklist.status_code == 200

    transcript = client.post(
        f"/api/v1/lab-validations/{validation_id}/transcript",
        headers=SECURITY_HEADERS,
        json={
            "filename": "session.txt",
            "content_type": "text/plain",
            "raw_text": f"username admin password {secret}\nshow version\n",
        },
    )
    assert transcript.status_code == 201
    assert secret not in transcript.text
    assert transcript.json()["sha256"]
    assert "<redacted>" in transcript.json()["sanitized_preview"]

    item_id = checklist.json()[0]["id"]
    updated_item = client.patch(
        f"/api/v1/lab-validations/{validation_id}/checklist/{item_id}",
        headers=SECURITY_HEADERS,
        json={"status": "passed", "notes": "validated"},
    )
    assert updated_item.status_code == 200
    assert updated_item.json()["status"] == "passed"

    approved = client.post(
        f"/api/v1/lab-validations/{validation_id}/approve",
        headers=SECURITY_HEADERS,
        json={"evidence_summary": "lab transcript reviewed"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    expired = client.post(f"/api/v1/lab-validations/{validation_id}/expire", headers=SECURITY_HEADERS)
    assert expired.status_code == 200
    assert expired.json()["status"] == "expired"


def test_lab_validation_api_rejects_unauthorized_writes() -> None:
    client = TestClient(app)

    denied = client.post("/api/v1/lab-validations", headers=VIEWER_HEADERS, json=_payload())

    assert denied.status_code == 403


def test_lab_validation_api_allows_network_operator_read_but_not_operator_role() -> None:
    client = TestClient(app)
    validation_id = client.post("/api/v1/lab-validations", headers=SECURITY_HEADERS, json=_payload()).json()["id"]

    allowed = client.get(f"/api/v1/lab-validations/{validation_id}", headers=READ_HEADERS)
    denied = client.get(f"/api/v1/lab-validations/{validation_id}", headers=OPERATOR_HEADERS)

    assert allowed.status_code == 200
    assert denied.status_code == 403


def test_lab_validation_api_reject_flow() -> None:
    client = TestClient(app)
    validation_id = client.post("/api/v1/lab-validations", headers=SECURITY_HEADERS, json=_payload()).json()["id"]

    rejected = client.post(
        f"/api/v1/lab-validations/{validation_id}/reject",
        headers=SECURITY_HEADERS,
        json={"evidence_summary": "prompt handling mismatch"},
    )

    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
