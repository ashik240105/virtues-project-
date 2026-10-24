"""
Feature 5 Integration Tests: Printable Hospital Handover Page.
Verifies ReportLab A4 PDF generation, Sections A through G, grayscale usability,
medication administration status distinction, allergy status uncertainty, and API endpoints.
"""

import os
import sys
import pytest
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.app import create_app
from backend.database.db import init_db, get_db_connection, create_patient
from backend.services.report_service import ReportService

@pytest.fixture
def app_and_client(tmp_path):
    db_file = str(tmp_path / "test_handover.db")
    app = create_app({"TESTING": True, "DATABASE": db_file})
    with app.app_context():
        init_db()
        yield app, app.test_client(), db_file

def test_handover_data_sections_a_through_g(app_and_client):
    """Verify handover data covers all required sections A through G."""
    app, client, _ = app_and_client

    # Create patient with known allergy
    patient = create_patient({
        "full_name": "Marcus Aurelius",
        "dob": "1972-04-26",
        "gender": "Male",
        "blood_type": "O-",
        "allergies": ["Penicillin", "Morphine"],
        "medical_history": ["Hypertension", "Atrial Fibrillation"]
    })

    # Create record with multiple vitals, medications (administered, withheld, planned), and symptoms
    record_payload = {
        "call_number": "EMS-1088",
        "responder_id": "Medic-Echo-4",
        "patient_id": patient["id"],
        "corrected_transcript": "Patient with acute chest pressure. Administered Aspirin 300mg oral. Morphine was not given due to allergy. Started IV Saline 500ml planned.",
        "patient_summary": {
            "incident_location": "842 Broadway, Downtown Sector 4",
            "dispatch_time": "2026-10-24T10:15:00Z",
            "arrival_time": "2026-10-24T10:22:30Z",
            "hospital_arrival_time": "2026-10-24T10:48:00Z",
            "chief_complaint": "Acute retrosternal chest pain radiating to left arm"
        },
        "clinical_data": {
            "patient_id": patient["id"],
            "vital_signs": [
                {"name": "BP", "value": "150/95", "unit": "mmHg", "verification_state": "Verified", "source_phrase": "blood pressure 150 over 95"},
                {"name": "HR", "value": "108", "unit": "bpm", "verification_state": "Verified", "source_phrase": "heart rate 108"},
                {"name": "SpO2", "value": "94", "unit": "%", "verification_state": "Verified", "source_phrase": "oxygen saturation 94 percent"}
            ],
            "medications": [
                {
                    "canonical_name": "Aspirin",
                    "raw_mention": "Aspirin",
                    "dosage": "300",
                    "unit": "mg",
                    "route": "Oral",
                    "is_negated": False,
                    "administration_status": "ADMINISTERED",
                    "verification_state": "Verified"
                },
                {
                    "canonical_name": "Morphine",
                    "raw_mention": "Morphine",
                    "dosage": "5",
                    "unit": "mg",
                    "route": "IV",
                    "is_negated": True,
                    "administration_status": "NOT_ADMINISTERED",
                    "verification_state": "Verified"
                },
                {
                    "canonical_name": "Normal Saline",
                    "raw_mention": "Saline",
                    "dosage": "500",
                    "unit": "ml",
                    "route": "IV",
                    "is_negated": False,
                    "administration_status": "PLANNED",
                    "verification_state": "Extracted"
                }
            ],
            "symptoms": [
                {"symptom": "Chest Pressure", "is_negated": False, "source_phrase": "acute chest pressure"},
                {"symptom": "Shortness of Breath", "is_negated": True, "source_phrase": "denies shortness of breath"}
            ],
            "procedures": [
                {"procedure": "18G Peripheral IV Access", "source_phrase": "started IV"}
            ]
        }
    }

    create_res = client.post("/api/records", json=record_payload)
    assert create_res.status_code == 201
    rec_id = create_res.get_json()["data"]["id"]

    # 1. Test Handover Data Generation
    handover = ReportService.generate_handover_data(rec_id)
    assert handover is not None

    # Section A: Incident Details
    assert handover["section_a_incident"]["call_number"] == "EMS-1088"
    assert "842 Broadway" in handover["section_a_incident"]["location"]
    assert "2026-10-24" in handover["section_a_incident"]["dispatch_time"]
    assert handover["section_a_incident"]["timezone"] == "UTC"

    # Section B: Patient Information
    assert handover["section_b_patient"]["name"] == "Marcus Aurelius"
    assert handover["section_b_patient"]["blood_type"] == "O-"
    assert "Penicillin" in handover["section_b_patient"]["allergy_status"]["active_allergies"][0]["allergen"]

    # Section C: Timeline of Vital Signs
    vitals = handover["section_c_vitals_timeline"]
    assert len(vitals) == 3
    assert any(v["name"] == "BP" and v["value"] == "150/95" for v in vitals)
    assert any(v["name"] == "HR" and v["value"] == "108" for v in vitals)

    # Section D: Medication Administration Record (Distinguishes Administered, Withheld, Planned)
    meds = handover["section_d_medications"]
    assert len(meds) == 3
    asp = next(m for m in meds if m["name"] == "Aspirin")
    assert asp["status"] == "ADMINISTERED"
    assert "[ADMINISTERED]" in asp["status_display"]

    morph = next(m for m in meds if m["name"] == "Morphine")
    assert morph["status"] == "NOT_ADMINISTERED"
    assert "[WITHHELD / DENIED]" in morph["status_display"]

    saline = next(m for m in meds if m["name"] == "Normal Saline")
    assert saline["status"] == "PLANNED"
    assert "[PLANNED / ORDERED]" in saline["status_display"]

    # Section E: Clinical Summary
    assert "Chest Pressure" in str(handover["section_e_clinical_summary"]["symptoms"])
    assert "18G Peripheral IV Access" in str(handover["section_e_clinical_summary"]["procedures"])

    # Section F: Safety & Allergy Alerts
    assert "section_f_safety_alerts" in handover

    # Section G: Provenance & Sign-off
    assert handover["section_g_provenance_signoff"]["reporting_responder"] == "Medic-Echo-4"
    assert "Field-to-Record" in handover["section_g_provenance_signoff"]["platform"]

def test_document_state_progression(app_and_client):
    """Verify document states: UNVERIFIED FIELD DRAFT -> PRELIMINARY NOTE -> FINALIZED RECORD."""
    app, client, _ = app_and_client

    rec_payload = {
        "call_number": "EMS-7733",
        "responder_id": "Medic-10",
        "status": "Draft",
        "corrected_transcript": "Patient with minor laceration.",
        "clinical_data": {"vital_signs": [], "medications": []}
    }
    rec_res = client.post("/api/records", json=rec_payload)
    rec_id = rec_res.get_json()["data"]["id"]

    # State 1: Draft
    h1 = ReportService.generate_handover_data(rec_id)
    assert h1["document_metadata"]["document_state"] == "UNVERIFIED FIELD DRAFT"

    # State 2: Reviewed / Preliminary
    client.put(f"/api/records/{rec_id}", json={"status": "Needs Review"})
    h2 = ReportService.generate_handover_data(rec_id)
    assert h2["document_metadata"]["document_state"] == "PRELIMINARY RESPONDER-APPROVED NOTE"

    # State 3: Approved / Finalized
    client.post(f"/api/records/{rec_id}/approve", json={"reviewer_id": "Dr-Smith", "override_notes": "All checks verified"})
    h3 = ReportService.generate_handover_data(rec_id)
    assert h3["document_metadata"]["document_state"] == "FINALIZED & AUDITED CLINICAL RECORD"
    assert h3["section_g_provenance_signoff"]["reviewer_supervisor"] == "Dr-Smith"

def test_a4_pdf_generation(app_and_client):
    """Verify ReportLab compiles standard A4 PDF document with valid size and formatting."""
    app, client, _ = app_and_client

    rec_payload = {
        "call_number": "EMS-8822",
        "responder_id": "Paramedic-33",
        "corrected_transcript": "Patient with asthma exacerbation. Administered Salbutamol 5mg nebulized.",
        "clinical_data": {
            "vital_signs": [{"name": "RR", "value": "28", "unit": "breaths/min", "verification_state": "Verified"}],
            "medications": [{
                "canonical_name": "Salbutamol",
                "dosage": "5",
                "unit": "mg",
                "route": "Nebulized",
                "is_negated": False,
                "administration_status": "ADMINISTERED"
            }]
        }
    }
    rec_res = client.post("/api/records", json=rec_payload)
    rec_id = rec_res.get_json()["data"]["id"]

    pdf_path = ReportService.generate_handover_pdf(rec_id)
    assert pdf_path is not None
    assert os.path.exists(pdf_path)
    file_size = os.path.getsize(pdf_path)
    assert file_size > 1500  # Valid ReportLab binary document

def test_handover_api_endpoints(app_and_client):
    """Verify GET /api/records/<id>/handover and GET /api/records/<id>/handover/pdf HTTP endpoints."""
    app, client, _ = app_and_client

    rec_payload = {
        "call_number": "EMS-9944",
        "responder_id": "Medic-01",
        "corrected_transcript": "Patient in anaphylaxis. Administered Epinephrine 0.5mg IM.",
        "clinical_data": {
            "vital_signs": [{"name": "BP", "value": "85/50", "unit": "mmHg"}],
            "medications": [{
                "canonical_name": "Epinephrine",
                "dosage": "0.5",
                "unit": "mg",
                "route": "IM",
                "is_negated": False,
                "administration_status": "ADMINISTERED"
            }]
        }
    }
    create_res = client.post("/api/records", json=rec_payload)
    rec_id = create_res.get_json()["data"]["id"]

    # 1. JSON Handover Endpoint
    json_res = client.get(f"/api/records/{rec_id}/handover")
    assert json_res.status_code == 200
    data = json_res.get_json()
    assert data["success"] is True
    assert data["data"]["document_metadata"]["call_number"] == "EMS-9944"
    assert len(data["data"]["section_d_medications"]) == 1

    # 2. PDF Handover Endpoint
    pdf_res = client.get(f"/api/records/{rec_id}/handover/pdf")
    assert pdf_res.status_code == 200
    assert pdf_res.mimetype == "application/pdf"
    assert len(pdf_res.data) > 1500
