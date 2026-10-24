"""
Clinical Processing Routes: Text extraction, validation rules, and medicine catalogue search.
"""

from flask import Blueprint, request, jsonify
from backend.services.clinical_extractor import ClinicalExtractor
from backend.services.validation_service import ValidationService
from backend.services.medicine_service import MedicineService
from backend.services.allergy_safety_service import AllergySafetyService
from backend.services.unknown_drug_service import UnknownDrugService

clinical_bp = Blueprint("clinical", __name__)

@clinical_bp.route("/api/clinical/extract", methods=["POST"])
def extract_clinical_entities():
    """
    Extract structured clinical events from raw or edited transcript text.
    Preserves exact source phrases, character spans, and initial verification states.
    Evaluates allergy conflicts against patient profile if patient_id is supplied.
    """
    body = request.get_json(silent=True) or {}
    text = body.get("text", "").strip()

    if not text:
        return jsonify({
            "success": False,
            "error": "Input text is required for clinical entity extraction."
        }), 400

    extracted = ClinicalExtractor.extract_all(text)

    # Attach patient context if available
    patient_id = body.get("patient_id")
    if patient_id:
        extracted["patient_id"] = patient_id
    if body.get("patient_allergies"):
        extracted["patient_allergies"] = body.get("patient_allergies")

    warnings = ValidationService.validate_clinical_record(extracted)

    return jsonify({
        "success": True,
        "data": {
            "entities": extracted,
            "validation_warnings": warnings
        }
    }), 200

@clinical_bp.route("/api/clinical/validate", methods=["POST"])
def validate_entities():
    """Run validation rules against a structured clinical entity bundle."""
    body = request.get_json(silent=True) or {}
    clinical_data = body.get("clinical_data", {})
    warnings = ValidationService.validate_clinical_record(clinical_data)

    return jsonify({
        "success": True,
        "data": {
            "warnings": warnings,
            "has_critical": any(w.get("severity") == "CRITICAL" for w in warnings),
            "warnings_count": len(warnings)
        }
    }), 200

@clinical_bp.route("/api/medicines/search", methods=["GET"])
def search_medicines():
    """
    Search verified local medicine catalogue using exact and RapidFuzz ranking.
    Distinguishes exact match, alias match, and ambiguous candidate ranking.
    """
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({
            "success": False,
            "error": "Query parameter 'q' is required."
        }), 400

    match_result = MedicineService.match_medicine(query)
    return jsonify({
        "success": True,
        "data": match_result
    }), 200

@clinical_bp.route("/api/medicines/catalogue", methods=["GET"])
def get_catalogue():
    """Retrieve complete local verified medicine catalogue with provenance."""
    medicines = MedicineService.get_all_medicines()
    return jsonify({
        "success": True,
        "count": len(medicines),
        "data": medicines
    }), 200

@clinical_bp.route("/api/medicines/catalogue", methods=["POST"])
def add_or_update_formulary_item():
    """
    Explicit administrative configuration endpoint for ambulance service to add
    or update approved medications in the local formulary catalogue.
    CRITICAL: Never called automatically from unknown speech mentions.
    """
    body = request.get_json(silent=True) or {}
    if not body.get("canonical_name"):
        return jsonify({
            "success": False,
            "error": "Field 'canonical_name' is required for formulary configuration."
        }), 400

    try:
        actor = request.headers.get("X-Reviewer-Id", "FormularyAdmin")
        saved_entry = UnknownDrugService.add_formulary_entry(body, actor_id=actor)
        return jsonify({
            "success": True,
            "message": f"Successfully configured formulary entry '{saved_entry['canonical_name']}'.",
            "data": saved_entry
        }), 201
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": f"Failed to save formulary entry: {str(e)}"}), 500

# -------------------------------------------------------------------------
# Feature 3 & 4: Review Items & Allergy Warning Acknowledgments
# -------------------------------------------------------------------------
@clinical_bp.route("/api/records/<record_id>/allergy-warnings", methods=["GET"])
def get_record_allergy_warnings(record_id):
    """Retrieve persistent allergy safety warnings and reviewer decisions for a record."""
    warnings = AllergySafetyService.get_warnings_for_record(record_id)
    return jsonify({
        "success": True,
        "count": len(warnings),
        "data": warnings
    }), 200

@clinical_bp.route("/api/records/<record_id>/allergy-warnings/<warning_id>/acknowledge", methods=["POST"])
def acknowledge_allergy_warning(record_id, warning_id):
    """
    Record authorized responder decision/acknowledgment for an allergy safety warning.
    Keeps warning visible in audit history while marking as acknowledged.
    """
    body = request.get_json(silent=True) or {}
    reviewer_id = body.get("reviewer_id") or request.headers.get("X-Reviewer-Id") or "Paramedic-101"
    decision = body.get("decision_reason") or body.get("decision") or "CLINICALLY_JUSTIFIED"
    notes = body.get("notes", "")

    updated = AllergySafetyService.acknowledge_warning(
        warning_id=warning_id,
        record_id=record_id,
        reviewer_id=reviewer_id,
        decision_reason=decision,
        notes=notes
    )

    if not updated:
        return jsonify({
            "success": False,
            "error": "Warning not found or failed to acknowledge."
        }), 404

    return jsonify({
        "success": True,
        "message": "Allergy warning successfully acknowledged and recorded in audit log.",
        "data": updated
    }), 200

@clinical_bp.route("/api/records/<record_id>/unknown-medications", methods=["GET"])
def get_record_unknown_medications(record_id):
    """Retrieve unknown medication review items for a record."""
    items = UnknownDrugService.get_review_items_for_record(record_id)
    return jsonify({
        "success": True,
        "count": len(items),
        "data": items
    }), 200

@clinical_bp.route("/api/records/<record_id>/unknown-medications/<item_id>/resolve", methods=["POST"])
def resolve_unknown_medication(record_id, item_id):
    """
    Authorized reviewer resolution for an unknown medication mention:
    Actions: CONFIRM | CORRECT | REJECT | UNRESOLVED.
    Does NOT automatically promote unverified names into the trusted catalogue.
    """
    body = request.get_json(silent=True) or {}
    action = body.get("action", "").upper().strip()
    reviewer_id = body.get("reviewer_id") or request.headers.get("X-Reviewer-Id") or "Paramedic-101"
    corrected_name = body.get("corrected_name")
    notes = body.get("notes", "")

    if not action:
        return jsonify({
            "success": False,
            "error": "Field 'action' is required (CONFIRM, CORRECT, REJECT, or UNRESOLVED)."
        }), 400

    try:
        resolved = UnknownDrugService.resolve_review_item(
            item_id=item_id,
            record_id=record_id,
            action=action,
            reviewer_id=reviewer_id,
            corrected_name=corrected_name,
            notes=notes
        )
        if not resolved:
            return jsonify({
                "success": False,
                "error": "Review item not found."
            }), 404

        return jsonify({
            "success": True,
            "message": f"Unknown medication successfully resolved as '{action}'.",
            "data": resolved
        }), 200
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": f"Failed to resolve review item: {str(e)}"}), 500
