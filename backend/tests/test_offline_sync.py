"""
Unit and Integration Tests for Offline-First Synchronization & Conflict Handling.
Verifies:
- Stable case and event IDs
- Idempotent record creation and synchronization retries
- Conflict detection (server version higher, approved record immutability)
- Timestamp and provenance preservation
- Safe handling of partial synchronization
"""

import os
import sys
import json
import pytest
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.app import create_app
from backend.database.db import init_db, get_record, get_record_audit_logs

@pytest.fixture
def client(tmp_path):
    test_db = os.path.join(tmp_path, "test_sync.db")
    os.environ["FIELD_RECORD_DB_PATH"] = test_db
    init_db()

    app = create_app({"TESTING": True})
    with app.test_client() as test_client:
        yield test_client

def test_stable_record_id_and_idempotent_creation(client):
    """Verify pre-generated client ID is preserved and retrying does not create duplicates."""
    stable_id = "REC-20261024-AMB001"
    payload = {
        "id": stable_id,
        "call_number": "EMS-7701",
        "responder_id": "Medic-101",
        "created_at": "2026-10-24T08:30:00+00:00",
        "corrected_transcript": "Patient BP 120/80, pulse 72. Gave 500mg paracetamol oral.",
    }

    # First creation
    res1 = client.post("/api/records", json=payload)
    assert res1.status_code == 201
    data1 = res1.get_json()["data"]
    assert data1["id"] == stable_id
    assert data1["call_number"] == "EMS-7701"
    assert data1["created_at"] == "2026-10-24T08:30:00+00:00"

    # Retry creation with the same stable ID (idempotent duplicate submission)
    res2 = client.post("/api/records", json=payload)
    assert res2.status_code == 200
    assert res2.get_json()["idempotent"] is True
    assert res2.get_json()["data"]["id"] == stable_id

def test_offline_batch_sync_idempotent(client):
    """Test batch sync of offline-created records and verify retry idempotency."""
    rec1_id = "REC-20261024-OFF001"
    rec2_id = "REC-20261024-OFF002"

    batch_payload = {
        "device_id": "Ambulance-Unit-9",
        "records": [
            {
                "id": rec1_id,
                "call_number": "EMS-8001",
                "responder_id": "Paramedic-John",
                "created_at": "2026-10-24T08:15:00+00:00",
                "client_updated_at": "2026-10-24T08:20:00+00:00",
                "corrected_transcript": "BP 130/85, pulse 80, SpO2 98 percent.",
                "status": "Needs Review"
            },
            {
                "id": rec2_id,
                "call_number": "EMS-8002",
                "responder_id": "Paramedic-John",
                "created_at": "2026-10-24T08:45:00+00:00",
                "client_updated_at": "2026-10-24T08:50:00+00:00",
                "corrected_transcript": "Administered 0.4mg Naloxone IN for suspected opioid overdose.",
                "status": "Needs Review"
            }
        ]
    }

    # Initial sync
    res = client.post("/api/records/sync", json=batch_payload)
    assert res.status_code == 200
    body = res.get_json()
    assert body["success"] is True
    assert body["data"]["synced_count"] == 2
    assert body["data"]["conflicts_count"] == 0

    # Verify records in database
    r1 = get_record(rec1_id)
    assert r1 is not None
    assert r1["id"] == rec1_id
    assert r1["created_at"] == "2026-10-24T08:15:00+00:00"

    r2 = get_record(rec2_id)
    assert r2 is not None
    assert r2["id"] == rec2_id

    # Check audit log for sync provenance
    audit = get_record_audit_logs(rec1_id)
    assert any(log["action"] == "OFFLINE_SYNC_CREATE" for log in audit)

    # Retry the exact same sync (e.g. intermittent connection retry)
    res_retry = client.post("/api/records/sync", json=batch_payload)
    assert res_retry.status_code == 200
    body_retry = res_retry.get_json()
    assert body_retry["success"] is True
    assert body_retry["data"]["synced_count"] == 2
    assert body_retry["data"]["conflicts_count"] == 0

def test_offline_sync_conflict_detection_server_version_higher(client):
    """Detect conflict when server record has moved to a higher version."""
    rec_id = "REC-20261024-CONF01"

    # 1. Create base record on server
    res_init = client.post("/api/records", json={
        "id": rec_id,
        "call_number": "EMS-9001",
        "corrected_transcript": "Initial base observation."
    })
    assert res_init.status_code == 201

    # 2. Server updates to Approved and then Amends (version becomes 2)
    client.post(f"/api/records/{rec_id}/approve", json={"reviewer_id": "Dr-Supervisor"})
    client.post(f"/api/records/{rec_id}/amend", json={"reason": "Hospital handover update", "responder_id": "Nurse-Alice"})

    server_rec = get_record(rec_id)
    assert server_rec["version"] == 2

    # 3. Client attempts to sync an offline edit that was branched from base version 1
    conflict_payload = {
        "device_id": "Ambulance-Unit-9",
        "records": [{
            "id": rec_id,
            "call_number": "EMS-9001",
            "base_version": 1,
            "version": 1,
            "client_updated_at": "2026-10-24T09:00:00+00:00",
            "corrected_transcript": "Offline paramedic edit without knowing server was amended."
        }]
    }

    res_sync = client.post("/api/records/sync", json=conflict_payload)
    assert res_sync.status_code == 409
    body = res_sync.get_json()
    assert body["success"] is False
    assert body["data"]["conflicts_count"] == 1
    conflict_item = body["data"]["conflicts"][0]
    assert conflict_item["id"] == rec_id
    assert "version 2" in conflict_item["reason"]

    # Verify server record was NOT overwritten
    persisted = get_record(rec_id)
    assert persisted["version"] == 2
    assert "Offline paramedic edit" not in persisted["corrected_transcript"]

def test_offline_sync_conflict_on_approved_record(client):
    """Syncing non-amendment offline changes over an Approved record must be flagged as conflict."""
    rec_id = "REC-20261024-APP01"

    client.post("/api/records", json={
        "id": rec_id,
        "call_number": "EMS-9002",
        "corrected_transcript": "Patient vital signs recorded."
    })
    client.post(f"/api/records/{rec_id}/approve", json={"reviewer_id": "Supervisor-Dr-Smith"})

    sync_payload = {
        "device_id": "Ambulance-Unit-9",
        "records": [{
            "id": rec_id,
            "call_number": "EMS-9002",
            "status": "Draft",
            "corrected_transcript": "Attempt to overwrite approved record directly."
        }]
    }

    res = client.post("/api/records/sync", json=sync_payload)
    assert res.status_code == 409
    assert res.get_json()["data"]["conflicts_count"] == 1
    assert "Approved (immutable)" in res.get_json()["data"]["conflicts"][0]["reason"]

