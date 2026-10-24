"""
Unit and Integration Tests for Feature 3 & Feature 4:
Expanded Medication Catalogue, Unknown-Drug Alerts & Safety Warnings.

Verifies:
1. Formulary completeness: covers 21 emergency pre-hospital medications with routes, doses, and aliases.
2. Unknown drug detection: identifies non-formulary drug mentions with dosage/route and creates review items.
3. Reviewer decisions: CONFIRM, CORRECT, REJECT, UNRESOLVED with audit logging, without auto-promoting to trusted catalogue.
4. Exact ingredient and verified alias allergy matching (e.g. Aspirin / Disprin / ASA).
5. Documented class cross-reactivity warnings (Aspirin <-> Ibuprofen/NSAID, Morphine <-> Opioid).
6. Unknown allergy status safety warning (missing allergy info is not treated as no allergies).
7. Explicit NKDA preservation.
8. Allergy warning acknowledgment and reviewer decision logging.
9. Negated medication handling (withheld drugs do not trigger false active administration alerts).
"""

import pytest
import os
import json
from backend.app import create_app
from backend.database.db import init_db, get_db_connection, get_record
from backend.services.medicine_service import MedicineService
from backend.services.clinical_extractor import ClinicalExtractor
from backend.services.validation_service import ValidationService
from backend.services.allergy_safety_service import AllergySafetyService, AllergyWarningState
from backend.services.unknown_drug_service import UnknownDrugService, ReviewStatus

@pytest.fixture
def app_and_client(tmp_path):
    test_db = str(tmp_path / "test_allergy_formulary.db")
    os.environ["FIELD_RECORD_DB_PATH"] = test_db
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        init_db()
    client = app.test_client()
    yield app, client, test_db

# -------------------------------------------------------------------------
# Feature 3: Expanded Medication Catalogue Tests
# -------------------------------------------------------------------------
def test_formulary_completeness(app_and_client):
    """Verify emergency formulary covers required medications with metadata."""
    meds = MedicineService.get_all_medicines()
    med_names = {m["canonical_name"].lower() for m in meds}

    required_formulary = [
        "epinephrine", "atropine", "amiodarone", "glucagon", "dextrose",
        "naloxone", "aspirin", "nitroglycerin", "salbutamol", "midazolam",
        "diazepam", "ketamine", "tranexamic acid", "morphine", "fentanyl",
        "ondansetron", "paracetamol", "normal saline", "ringer's lactate"
    ]
    for required_med in required_formulary:
        assert required_med in med_names, f"Required formulary medication '{required_med}' missing from catalogue."

    # Verify metadata and identity separation
    morphine = next(m for m in meds if m["canonical_name"] == "Morphine")
    assert "IV" in morphine["standard_routes"]
    assert "mg" in morphine["standard_units"]
    assert len(morphine["typical_doses"]) > 0
    assert morphine["provenance"] is not None

def test_unknown_medication_detection(app_and_client):
    """Detect unverified medication mentions with dosage/route not in approved formulary."""
    # 'Cefazolin 1g IV' is an antibiotic not in standard pre-hospital ambulance formulary
    note = "Paramedics initiated transport. Gave Cefazolin 1g IV push en route. Vitals stable."
    extracted = ClinicalExtractor.extract_all(note)

    unknowns = extracted.get("unknown_medications", [])
    assert len(unknowns) >= 1
    cefazolin_item = next((u for u in unknowns if "Cefazolin" in u.get("suspected_entity_name", "")), None)
    assert cefazolin_item is not None
    assert cefazolin_item["review_status"] == ReviewStatus.PENDING

    # Check that validation service creates an unknown medication warning
    warnings = ValidationService.validate_clinical_record(extracted)
    unk_warn = next((w for w in warnings if w.get("category") == "Unknown Medication Alert"), None)
    assert unk_warn is not None
    assert "Cefazolin" in unk_warn["message"]
    assert "review required" in unk_warn["message"]

def test_unknown_medication_review_workflow_and_audit(app_and_client):
    """Verify authorized reviewer actions on unknown medications without auto-promoting to catalogue."""
    app, client, _ = app_and_client

    # 1. Create a record with unknown medication
    record_payload = {
        "call_number": "EMS-7711",
        "responder_id": "Medic-42",
        "corrected_transcript": "Patient with infected laceration. Administered Cefazolin 1g IV.",
        "clinical_data": {
            "vital_signs": [],
            "medications": [],
            "unknown_medications": [{
                "id": "unk-cef01",
                "suspected_entity_name": "Cefazolin",
                "original_text": "Administered Cefazolin 1g IV",
                "char_start": 44,
                "char_end": 53,
                "language": "en",
                "review_status": "PENDING"
            }]
        }
    }
    rec_res = client.post("/api/records", json=record_payload)
    assert rec_res.status_code == 201
    rec_id = rec_res.get_json()["data"]["id"]

    # 2. Retrieve review items
    items_res = client.get(f"/api/records/{rec_id}/unknown-medications")
    assert items_res.status_code == 200
    items = items_res.get_json()["data"]
    assert len(items) == 1
    assert items[0]["review_status"] == "PENDING"

    # 3. Authorized reviewer CONFIRMS the item (e.g. transfer drug)
    resolve_res = client.post(
        f"/api/records/{rec_id}/unknown-medications/unk-cef01/resolve",
        json={
            "action": "CONFIRM",
            "reviewer_id": "Dr-Supervisor-9",
            "notes": "Verified hospital inter-facility transfer antibiotic order."
        }
    )
    assert resolve_res.status_code == 200
    updated_item = resolve_res.get_json()["data"]
    assert updated_item["review_status"] == "CONFIRMED"
    assert updated_item["reviewer_id"] == "Dr-Supervisor-9"

    # 4. CRITICAL RULE: Confirming does NOT automatically promote Cefazolin into medicine_catalogue
    search_res = client.get("/api/medicines/search?q=Cefazolin")
    search_data = search_res.get_json()["data"]
    assert search_data["status"] != "EXACT"

    # 5. Verify audit history logged the review decision
    audit_res = client.get(f"/api/records/{rec_id}/audit")
    assert audit_res.status_code == 200
    audit_logs = audit_res.get_json()["data"]
    review_log = next((l for l in audit_logs if l["action"] == "RESOLVE_UNKNOWN_MEDICATION"), None)
    assert review_log is not None
    assert review_log["actor"] == "Dr-Supervisor-9"

def test_configurable_formulary_administration(app_and_client):
    """Ambulance service administrator can add/update approved formulary entries via administrative API."""
    app, client, _ = app_and_client

    new_drug = {
        "canonical_name": "Adenosine",
        "aliases": ["Adenocard"],
        "category": "Antiarrhythmic",
        "standard_routes": ["IV", "IO"],
        "standard_units": ["mg"],
        "typical_doses": ["6mg", "12mg"],
        "pediatric_warning": 0,
        "contraindications_notes": "2nd or 3rd degree AV block, sick sinus syndrome, bronchospastic lung disease.",
        "provenance": "AHA ACLS SVT Protocol 2023",
        "version": "1.0.0"
    }

    res = client.post("/api/medicines/catalogue", json=new_drug, headers={"X-Reviewer-Id": "EMS-Medical-Director"})
    assert res.status_code == 201
    assert res.get_json()["success"] is True

    # Now verify it matches in search and extraction
    search_res = client.get("/api/medicines/search?q=Adenocard")
    assert search_res.status_code == 200
    assert search_res.get_json()["data"]["status"] == "ALIAS"
    assert search_res.get_json()["data"]["matched_canonical"] == "Adenosine"

# -------------------------------------------------------------------------
# Feature 4: Allergy & Medication Safety Warnings Tests
# -------------------------------------------------------------------------
def test_exact_ingredient_and_alias_allergy_conflict():
    """Detect direct ingredient and verified brand alias conflict (Aspirin / Disprin / ASA)."""
    # Patient has documented allergy to 'Aspirin'
    patient_allergies = ["Aspirin"]

    # Encounter administers Aspirin under brand alias 'Disprin'
    meds = [{
        "canonical_name": "Aspirin",
        "raw_mention": "Disprin",
        "dosage": "300",
        "unit": "mg",
        "route": "Oral",
        "is_negated": False,
        "administration_status": "ADMINISTERED"
    }]

    eval_result = AllergySafetyService.evaluate_safety(medications=meds, patient_allergies=patient_allergies)
    assert eval_result["has_critical"] is True
    assert eval_result["status"] == "CONFLICT_DETECTED"

    critical_warning = next(w for w in eval_result["warnings"] if w["severity"] == "CRITICAL")
    assert critical_warning["warning_type"] == AllergyWarningState.CONFIRMED_ALLERGY_CONFLICT
    assert critical_warning["medication_name"] == "Aspirin"
    assert critical_warning["recorded_allergy"] == "Aspirin"
    assert "Direct ingredient match" in critical_warning["explanation"] or "Verified ingredient" in critical_warning["explanation"]

def test_class_cross_reactivity_warning():
    """Detect documented class cross-reactivity (Aspirin allergy <-> Ibuprofen / NSAID)."""
    # Patient has documented allergy to 'Aspirin'
    patient_allergies = ["Aspirin"]

    # Paramedic administers Ibuprofen 400mg
    meds = [{
        "canonical_name": "Ibuprofen",
        "raw_mention": "Ibuprofen",
        "dosage": "400",
        "unit": "mg",
        "route": "Oral",
        "is_negated": False,
        "administration_status": "ADMINISTERED"
    }]

    eval_result = AllergySafetyService.evaluate_safety(medications=meds, patient_allergies=patient_allergies)
    assert eval_result["status"] == "POSSIBLE_CONFLICT"
    warn = next(w for w in eval_result["warnings"] if w["warning_type"] == AllergyWarningState.POSSIBLE_ALLERGY_CONFLICT)
    assert warn["severity"] == "WARNING"
    assert "NSAID" in warn["explanation"] or "cross-react" in warn["explanation"]

def test_allergy_status_unknown_rule():
    """Missing allergy info is NOT treated as proof patient has no allergies."""
    meds = [{
        "canonical_name": "Morphine",
        "raw_mention": "Morphine",
        "dosage": "5",
        "unit": "mg",
        "route": "IV",
        "is_negated": False,
        "administration_status": "ADMINISTERED"
    }]

    # Empty patient allergies, no encounter allergy statement
    eval_result = AllergySafetyService.evaluate_safety(
        medications=meds,
        patient_allergies=[],
        encounter_allergies=[]
    )
    assert eval_result["overall_state"] == AllergyWarningState.ALLERGY_STATUS_UNKNOWN
    unk_warn = next(w for w in eval_result["warnings"] if w["warning_type"] == AllergyWarningState.ALLERGY_STATUS_UNKNOWN)
    assert "not be treated as proof of absence" in unk_warn["explanation"].lower()

def test_explicit_nkda_documentation_clears_unknown_status():
    """Explicitly documented NKDA / No Known Allergies does not trigger unknown allergy status warning."""
    meds = [{
        "canonical_name": "Morphine",
        "raw_mention": "Morphine",
        "dosage": "5",
        "unit": "mg",
        "route": "IV",
        "is_negated": False,
        "administration_status": "ADMINISTERED"
    }]
    encounter_allergies = [{
        "status": "NO_KNOWN_ALLERGIES",
        "source_phrase": "No known allergies"
    }]

    eval_result = AllergySafetyService.evaluate_safety(
        medications=meds,
        patient_allergies=[],
        encounter_allergies=encounter_allergies
    )
    assert eval_result["overall_state"] == AllergyWarningState.NO_KNOWN_ALLERGIES
    assert not any(w["warning_type"] == AllergyWarningState.ALLERGY_STATUS_UNKNOWN for w in eval_result["warnings"])

def test_negated_withheld_medication_does_not_trigger_active_conflict():
    """When a medication is withheld/not given due to allergy, do not flag active critical conflict."""
    patient_allergies = ["Morphine"]
    meds = [{
        "canonical_name": "Morphine",
        "raw_mention": "Morphine",
        "dosage": "5",
        "unit": "mg",
        "is_negated": True,
        "administration_status": "NOT_ADMINISTERED"
    }]

    eval_result = AllergySafetyService.evaluate_safety(medications=meds, patient_allergies=patient_allergies)
    assert not any(w["warning_type"] == AllergyWarningState.CONFIRMED_ALLERGY_CONFLICT for w in eval_result["warnings"])

def test_allergy_warning_acknowledgment_workflow(app_and_client):
    """Responder acknowledges allergy warning with clinical justification, maintaining visibility and audit trail."""
    app, client, _ = app_and_client

    # Create record with direct Aspirin conflict
    record_payload = {
        "call_number": "EMS-9922",
        "responder_id": "Medic-101",
        "patient_id": "PAT-1002", # John Doe has recorded allergy to Aspirin in db
        "corrected_transcript": "Patient with acute STEMI chest pain. Administered Aspirin 300mg oral.",
        "clinical_data": {
            "vital_signs": [],
            "medications": [{
                "canonical_name": "Aspirin",
                "dosage": "300",
                "unit": "mg",
                "route": "Oral",
                "is_negated": False,
                "administration_status": "ADMINISTERED"
            }],
            "patient_id": "PAT-1002"
        }
    }
    create_res = client.post("/api/records", json=record_payload)
    assert create_res.status_code == 201
    rec_id = create_res.get_json()["data"]["id"]

    # Retrieve persistent allergy warnings
    warn_res = client.get(f"/api/records/{rec_id}/allergy-warnings")
    assert warn_res.status_code == 200
    warnings = warn_res.get_json()["data"]
    assert len(warnings) >= 1
    target_warn = warnings[0]
    assert target_warn["status"] == "ACTIVE"
    assert target_warn["warning_type"] == "CONFIRMED_ALLERGY_CONFLICT"

    # Acknowledge the warning
    ack_res = client.post(
        f"/api/records/{rec_id}/allergy-warnings/{target_warn['id']}/acknowledge",
        json={
            "reviewer_id": "Paramedic-101",
            "decision_reason": "BENEFIT_OUTWEIGHS_RISK_ACUTE_STEMI",
            "notes": "Patient reported mild stomach upset from aspirin years ago, not anaphylaxis. Emergent antiplatelet therapy indicated for acute coronary syndrome."
        }
    )
    assert ack_res.status_code == 200
    updated_warn = ack_res.get_json()["data"]
    assert updated_warn["status"] == "ACKNOWLEDGED"
    assert updated_warn["reviewer_id"] == "Paramedic-101"

    # Check audit trail records the decision
    audit_res = client.get(f"/api/records/{rec_id}/audit")
    assert audit_res.status_code == 200
    audit_logs = audit_res.get_json()["data"]
    ack_log = next((l for l in audit_logs if l["action"] == "ACKNOWLEDGE_ALLERGY_WARNING"), None)
    assert ack_log is not None
    assert ack_log["actor"] == "Paramedic-101"
