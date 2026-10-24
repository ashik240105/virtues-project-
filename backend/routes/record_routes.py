"""
Record Management Routes: Full lifecycle support for clinical field documentation records.
Status flow: Draft -> Needs Review -> Reviewed -> Approved -> Amended.
Audit logging on all lifecycle transitions.
"""

import os
import json
import uuid
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, send_file
from backend.database.db import (
    get_db_connection, get_record, list_records, log_audit_event, get_record_audit_logs,
    link_encounter, save_record_version_snapshot, get_record_versions, get_record_version_snapshot,
    get_patient
)
from backend.services.clinical_extractor import ClinicalExtractor
from backend.services.validation_service import ValidationService, ValidationSeverity
from backend.services.report_service import ReportService
from backend.services.evidence_service import EvidencePassportService
from backend.services.uncertainty_service import UncertaintyService

record_bp = Blueprint("records", __name__)

@record_bp.route("/api/records", methods=["POST"])
def create_record():
    """Create a new clinical documentation record with idempotent retry support."""
    body = request.get_json(silent=True) or {}

    record_id = body.get("id") or f"REC-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    # Idempotent deduplication check: if record already exists, return cleanly
    existing_record = get_record(record_id)
    if existing_record:
        return jsonify({
            "success": True,
            "message": "Record already synchronized (idempotent).",
            "data": existing_record,
            "idempotent": True
        }), 200

    call_number = body.get("call_number", f"EMS-{uuid.uuid4().hex[:5].upper()}")
    responder_id = body.get("responder_id", "Paramedic-101")
    patient_id = body.get("patient_id")
    event_at = body.get("event_at")
    created_at = body.get("created_at") or datetime.now(timezone.utc).isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()
    client_updated_at = body.get("client_updated_at", now_iso)
    device_id = body.get("device_id", "Unknown-Device")

    machine_transcript = body.get("machine_transcript", "").strip()
    corrected_transcript = body.get("corrected_transcript", machine_transcript).strip()
    audio_filename = body.get("audio_filename", "")
    audio_mimetype = body.get("audio_mimetype", "audio/webm")
    audio_duration = float(body.get("audio_duration_seconds", 0.0))
    transcription_meta = body.get("transcription_metadata", {})
    patient_summary = body.get("patient_summary", {})

    # If transcript is provided, extract clinical entities automatically
    clinical_data = body.get("clinical_data")
    if not clinical_data and corrected_transcript:
        clinical_data = ClinicalExtractor.extract_all(corrected_transcript)
    elif not clinical_data:
        clinical_data = {"vital_signs": [], "medications": [], "symptoms": [], "procedures": [], "timestamps": []}
    elif clinical_data and corrected_transcript:
        vitals = clinical_data.get("vital_signs") or []
        if any(v.get("timestamp") is None for v in vitals):
            ts_list = ClinicalExtractor.extract_timestamps(corrected_transcript)
            if ts_list:
                clinical_data["vital_signs"] = ClinicalExtractor._correlate_entity_timestamps(vitals, ts_list, corrected_transcript)
                clinical_data["medications"] = ClinicalExtractor._correlate_entity_timestamps(clinical_data.get("medications", []), ts_list, corrected_transcript)
                clinical_data["procedures"] = ClinicalExtractor._correlate_entity_timestamps(clinical_data.get("procedures", []), ts_list, corrected_transcript)

    # Validate clinical entities
    validation_warnings = ValidationService.validate_clinical_record(clinical_data)

    # Compile Evidence Passport and Uncertainty Ledger
    evidence_passport = body.get("evidence_passport")
    if not evidence_passport:
        evidence_passport = EvidencePassportService.compile_evidence_passport(
            record_id=record_id,
            clinical_data=clinical_data,
            transcript_text=corrected_transcript,
            transcription_meta=transcription_meta,
            reviewer_decisions=body.get("review_decisions", {})
        )

    uncertainty_ledger = UncertaintyService.compile_uncertainty_ledger(
        clinical_data=clinical_data,
        warnings=validation_warnings
    )

    initial_status = body.get("status") or ("Needs Review" if (clinical_data.get("vital_signs") or clinical_data.get("medications")) else "Draft")

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO records (
                id, call_number, responder_id, status, created_at, updated_at,
                recording_time, transcription_time, audio_filename, audio_mimetype,
                audio_duration_seconds, machine_transcript, corrected_transcript,
                transcription_metadata, clinical_data, validation_warnings,
                review_decisions, patient_summary, version, patient_id, event_at,
                evidence_passport, uncertainty_ledger, change_impact_radar,
                sync_status, client_updated_at, device_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, 'SYNCHRONIZED', ?, ?);
        """, (
            record_id,
            call_number,
            responder_id,
            initial_status,
            created_at,
            now_iso,
            body.get("recording_time", created_at),
            body.get("transcription_time", now_iso if machine_transcript else None),
            audio_filename,
            audio_mimetype,
            audio_duration,
            machine_transcript,
            corrected_transcript,
            json.dumps(transcription_meta),
            json.dumps(clinical_data),
            json.dumps(validation_warnings),
            json.dumps(body.get("review_decisions", {})),
            json.dumps(patient_summary),
            patient_id,
            event_at,
            json.dumps(evidence_passport),
            json.dumps(uncertainty_ledger),
            json.dumps({}),
            client_updated_at,
            device_id
        ))
        conn.commit()

        # Link to patient if provided
        if patient_id:
            link_encounter(patient_id, record_id, body.get("encounter_type", "NEW_ENCOUNTER"))

        # Persist unknown drug review items if detected (Feature 3)
        if clinical_data.get("unknown_medications"):
            from backend.services.unknown_drug_service import UnknownDrugService
            UnknownDrugService.persist_review_items(record_id, clinical_data["unknown_medications"])

        # Persist allergy safety warnings if detected (Feature 4)
        allergy_warnings = [w for w in validation_warnings if w.get("category") == "Allergy & Medication Safety Warning"]
        if allergy_warnings:
            from backend.services.allergy_safety_service import AllergySafetyService
            AllergySafetyService.persist_warnings_for_record(record_id, patient_id, allergy_warnings)

        log_audit_event(
            record_id=record_id,
            action="CREATE",
            actor=responder_id,
            details={
                "call_number": call_number,
                "status": initial_status,
                "patient_id": patient_id,
                "has_audio": bool(audio_filename),
                "warnings_count": len(validation_warnings),
                "evidence_passport_items": len(evidence_passport),
                "device_id": device_id
            }
        )

        created_record = get_record(record_id)
        return jsonify({
            "success": True,
            "data": created_record
        }), 201

    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Failed to create record: {str(e)}"
        }), 500
    finally:
        conn.close()

@record_bp.route("/api/records/sync", methods=["POST"])
def sync_records():
    """
    Idempotent offline synchronization endpoint for emergency responders.
    Accepts a batch of offline-created or offline-updated records.
    Detects conflicts without silently overwriting newer server data.
    Preserves stable client-generated record IDs and original timestamps.
    """
    body = request.get_json(silent=True) or {}
    device_id = body.get("device_id", "Unknown-Device")
    incoming_records = body.get("records", [])
    if isinstance(body, list):
        incoming_records = body

    synced = []
    conflicts = []
    failed = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for item in incoming_records:
        rec_id = item.get("id")
        if not rec_id:
            failed.append({"item": item, "error": "Missing record id"})
            continue

        try:
            existing = get_record(rec_id)
            if not existing:
                # 1. New record created offline: Insert with stable ID
                call_number = item.get("call_number", f"EMS-{uuid.uuid4().hex[:5].upper()}")
                responder_id = item.get("responder_id", "Paramedic-101")
                created_at = item.get("created_at") or now_iso
                updated_at = item.get("updated_at") or created_at
                client_updated_at = item.get("client_updated_at") or updated_at
                machine_transcript = item.get("machine_transcript", "").strip()
                corrected_transcript = item.get("corrected_transcript", machine_transcript).strip()
                clinical_data = item.get("clinical_data")
                if not clinical_data and corrected_transcript:
                    clinical_data = ClinicalExtractor.extract_all(corrected_transcript)
                elif not clinical_data:
                    clinical_data = {"vital_signs": [], "medications": [], "symptoms": [], "procedures": [], "timestamps": []}

                validation_warnings = ValidationService.validate_clinical_record(clinical_data)
                initial_status = item.get("status") or ("Needs Review" if (clinical_data.get("vital_signs") or clinical_data.get("medications")) else "Draft")

                conn = get_db_connection()
                try:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO records (
                            id, call_number, responder_id, status, created_at, updated_at,
                            recording_time, transcription_time, audio_filename, audio_mimetype,
                            audio_duration_seconds, machine_transcript, corrected_transcript,
                            transcription_metadata, clinical_data, validation_warnings,
                            review_decisions, patient_summary, version, patient_id, event_at,
                            evidence_passport, uncertainty_ledger, change_impact_radar,
                            sync_status, client_updated_at, device_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, 'SYNCHRONIZED', ?, ?);
                    """, (
                        rec_id, call_number, responder_id, initial_status, created_at, updated_at,
                        item.get("recording_time", created_at),
                        item.get("transcription_time"),
                        item.get("audio_filename", ""),
                        item.get("audio_mimetype", "audio/webm"),
                        float(item.get("audio_duration_seconds", 0.0)),
                        machine_transcript, corrected_transcript,
                        json.dumps(item.get("transcription_metadata", {})),
                        json.dumps(clinical_data),
                        json.dumps(validation_warnings),
                        json.dumps(item.get("review_decisions", {})),
                        json.dumps(item.get("patient_summary", {})),
                        item.get("patient_id"),
                        item.get("event_at"),
                        json.dumps([]),
                        json.dumps([]),
                        json.dumps({}),
                        client_updated_at,
                        device_id
                    ))
                    conn.commit()

                    if item.get("patient_id"):
                        link_encounter(item["patient_id"], rec_id, item.get("encounter_type", "NEW_ENCOUNTER"))

                    if clinical_data.get("unknown_medications"):
                        from backend.services.unknown_drug_service import UnknownDrugService
                        UnknownDrugService.persist_review_items(rec_id, clinical_data["unknown_medications"])

                    sync_allergy_warnings = [w for w in validation_warnings if w.get("category") == "Allergy & Medication Safety Warning"]
                    if sync_allergy_warnings:
                        from backend.services.allergy_safety_service import AllergySafetyService
                        AllergySafetyService.persist_warnings_for_record(rec_id, item.get("patient_id"), sync_allergy_warnings)

                    log_audit_event(
                        record_id=rec_id,
                        action="OFFLINE_SYNC_CREATE",
                        actor=responder_id,
                        details={"device_id": device_id, "synced_at": now_iso, "original_created_at": created_at}
                    )
                    synced.append(get_record(rec_id))
                finally:
                    conn.close()

            else:
                # 2. Existing record on server: Check for conflict
                client_base_version = item.get("base_version", item.get("version", 1))
                server_version = existing.get("version", 1)

                # If server is Approved and client is trying to modify without amendment
                if existing.get("status") == "Approved" and item.get("status") != "Approved":
                    conflicts.append({
                        "id": rec_id,
                        "reason": "Server record is already Approved (immutable). Submit via /amend instead.",
                        "server_record": existing,
                        "client_record": item
                    })
                    continue

                # If server version > client's base version, conflict detected
                if server_version > client_base_version:
                    conflicts.append({
                        "id": rec_id,
                        "reason": f"Conflict: Server record is at version {server_version}, but offline edit was based on version {client_base_version}.",
                        "server_record": existing,
                        "client_record": item
                    })
                    continue

                # If client edit timestamp is older than server's last updated_at and data differs
                server_updated = existing.get("updated_at", "")
                client_updated = item.get("client_updated_at") or item.get("updated_at", "")
                if server_updated and client_updated and server_updated > client_updated:
                    if existing.get("corrected_transcript") != item.get("corrected_transcript"):
                        conflicts.append({
                            "id": rec_id,
                            "reason": f"Conflict: Server record has newer update ({server_updated}) than client offline draft ({client_updated}).",
                            "server_record": existing,
                            "client_record": item
                        })
                        continue

                # Safe update or idempotent repeat
                corrected_transcript = item.get("corrected_transcript", existing.get("corrected_transcript", ""))
                clinical_data = item.get("clinical_data", existing.get("clinical_data", {}))
                review_decisions = item.get("review_decisions", existing.get("review_decisions", {}))
                patient_summary = item.get("patient_summary", existing.get("patient_summary", {}))
                status = item.get("status", existing.get("status", "Draft"))
                responder_id = item.get("responder_id", existing.get("responder_id", "Paramedic-101"))

                validation_warnings = ValidationService.validate_clinical_record(clinical_data)

                conn = get_db_connection()
                try:
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE records SET
                            responder_id = ?,
                            status = ?,
                            updated_at = ?,
                            corrected_transcript = ?,
                            clinical_data = ?,
                            validation_warnings = ?,
                            review_decisions = ?,
                            patient_summary = ?,
                            client_updated_at = ?,
                            device_id = ?,
                            sync_status = 'SYNCHRONIZED'
                        WHERE id = ?;
                    """, (
                        responder_id, status, now_iso, corrected_transcript,
                        json.dumps(clinical_data), json.dumps(validation_warnings),
                        json.dumps(review_decisions), json.dumps(patient_summary),
                        client_updated, device_id, rec_id
                    ))
                    conn.commit()

                    log_audit_event(
                        record_id=rec_id,
                        action="OFFLINE_SYNC_UPDATE",
                        actor=responder_id,
                        details={"device_id": device_id, "synced_at": now_iso, "client_updated_at": client_updated}
                    )
                    synced.append(get_record(rec_id))
                finally:
                    conn.close()

        except Exception as e:
            failed.append({"id": rec_id, "error": str(e)})

    has_conflicts = len(conflicts) > 0
    all_ok = len(failed) == 0 and not has_conflicts
    status_code = 200 if all_ok else (409 if has_conflicts else 207)

    return jsonify({
        "success": all_ok,
        "data": {
            "synced_count": len(synced),
            "conflicts_count": len(conflicts),
            "failed_count": len(failed),
            "synced": synced,
            "conflicts": conflicts,
            "failed": failed,
            "server_time": now_iso
        }
    }), status_code

@record_bp.route("/api/records", methods=["GET"])
def get_records_list():
    """List all records with optional status filter."""
    status_filter = request.args.get("status")
    limit = int(request.args.get("limit", 100))
    offset = int(request.args.get("offset", 0))

    records = list_records(limit=limit, offset=offset, status_filter=status_filter)
    return jsonify({
        "success": True,
        "count": len(records),
        "data": records
    }), 200

@record_bp.route("/api/records/<record_id>", methods=["GET"])
def get_single_record(record_id):
    """Retrieve complete record details."""
    rec = get_record(record_id)
    if not rec:
        return jsonify({
            "success": False,
            "error": f"Record '{record_id}' not found."
        }), 404

    audit_logs = get_record_audit_logs(record_id)
    rec["audit_trail"] = audit_logs

    from backend.services.confidence_service import ReportConfidenceService
    rec["report_confidence"] = ReportConfidenceService.evaluate_record_quality(rec)

    return jsonify({
        "success": True,
        "data": rec
    }), 200

@record_bp.route("/api/records/<record_id>", methods=["PUT"])
def update_record(record_id):
    """Update record fields (transcript, clinical data, review decisions)."""
    rec = get_record(record_id)
    if not rec:
        return jsonify({
            "success": False,
            "error": f"Record '{record_id}' not found."
        }), 404

    # Approved records cannot be edited directly via PUT; must use /amend
    if rec["status"] == "Approved":
        return jsonify({
            "success": False,
            "error": "Approved records are immutable. Use the /api/records/<id>/amend endpoint to submit a traceable amendment."
        }), 409

    body = request.get_json(silent=True) or {}
    now_iso = datetime.now(timezone.utc).isoformat()
    responder_id = body.get("responder_id", rec["responder_id"])

    corrected_transcript = body.get("corrected_transcript", rec["corrected_transcript"])
    clinical_data = body.get("clinical_data", rec["clinical_data"])
    if clinical_data and corrected_transcript:
        vitals = clinical_data.get("vital_signs") or []
        if any(v.get("timestamp") is None for v in vitals):
            ts_list = ClinicalExtractor.extract_timestamps(corrected_transcript)
            if ts_list:
                clinical_data["vital_signs"] = ClinicalExtractor._correlate_entity_timestamps(vitals, ts_list, corrected_transcript)
                clinical_data["medications"] = ClinicalExtractor._correlate_entity_timestamps(clinical_data.get("medications", []), ts_list, corrected_transcript)
                clinical_data["procedures"] = ClinicalExtractor._correlate_entity_timestamps(clinical_data.get("procedures", []), ts_list, corrected_transcript)
    review_decisions = body.get("review_decisions", rec["review_decisions"])
    patient_summary = body.get("patient_summary", rec["patient_summary"])
    status = body.get("status", rec["status"])
    call_number = body.get("call_number", rec["call_number"])

    # Re-run validation rules
    validation_warnings = ValidationService.validate_clinical_record(clinical_data)

    # If any warnings were marked resolved in review_decisions, update their state
    resolved_ids = set(review_decisions.get("resolved_warning_ids", []))
    for w in validation_warnings:
        if w["id"] in resolved_ids:
            w["resolved"] = True

    # Change Impact Radar: analyze ripple effects of edits
    change_impact = UncertaintyService.analyze_change_impact(
        old_record=rec,
        new_clinical_data=clinical_data,
        new_transcript=corrected_transcript
    )

    # Recompile Evidence Passport & Uncertainty Ledger
    evidence_passport = EvidencePassportService.compile_evidence_passport(
        record_id=record_id,
        clinical_data=clinical_data,
        transcript_text=corrected_transcript,
        transcription_meta=rec.get("transcription_metadata", {}),
        reviewer_decisions=review_decisions
    )

    uncertainty_ledger = UncertaintyService.compile_uncertainty_ledger(
        clinical_data=clinical_data,
        warnings=validation_warnings
    )

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE records SET
                call_number = ?,
                responder_id = ?,
                status = ?,
                updated_at = ?,
                corrected_transcript = ?,
                clinical_data = ?,
                validation_warnings = ?,
                review_decisions = ?,
                patient_summary = ?,
                evidence_passport = ?,
                uncertainty_ledger = ?,
                change_impact_radar = ?
            WHERE id = ?;
        """, (
            call_number,
            responder_id,
            status,
            now_iso,
            corrected_transcript,
            json.dumps(clinical_data),
            json.dumps(validation_warnings),
            json.dumps(review_decisions),
            json.dumps(patient_summary),
            json.dumps(evidence_passport),
            json.dumps(uncertainty_ledger),
            json.dumps(change_impact),
            record_id
        ))
        conn.commit()

        log_audit_event(
            record_id=record_id,
            action="UPDATE_RECORD",
            actor=responder_id,
            details={
                "new_status": status,
                "transcript_length": len(corrected_transcript),
                "warnings_count": len(validation_warnings),
                "impact_items_count": change_impact.get("impact_count", 0)
            }
        )

        updated = get_record(record_id)
        return jsonify({
            "success": True,
            "data": updated,
            "change_impact": change_impact
        }), 200

    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Failed to update record: {str(e)}"
        }), 500
    finally:
        conn.close()

@record_bp.route("/api/records/<record_id>/approve", methods=["POST"])
def approve_record(record_id):
    """
    Approve record. Requires human verification.
    Blocks if critical unresolved validation warnings exist.
    Snapshots approved version in record_versions.
    """
    rec = get_record(record_id)
    if not rec:
        return jsonify({"success": False, "error": "Record not found."}), 404

    body = request.get_json(silent=True) or {}
    actor = body.get("reviewer_id") or rec.get("responder_id") or "First Responder"
    override_notes = body.get("override_notes", "")

    warnings = rec.get("validation_warnings", [])
    critical_unresolved = [
        w for w in warnings
        if w.get("severity") == ValidationSeverity.CRITICAL and not w.get("resolved")
    ]

    if critical_unresolved and not override_notes:
        return jsonify({
            "success": False,
            "error": "Cannot approve record with unresolved CRITICAL warnings without explicit clinician override notes.",
            "critical_warnings": critical_unresolved
        }), 422

    now_iso = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE records SET
                status = 'Approved',
                updated_at = ?,
                approved_at = ?,
                reviewed_at = ?
            WHERE id = ?;
        """, (now_iso, now_iso, now_iso, record_id))
        conn.commit()

        log_audit_event(
            record_id=record_id,
            action="APPROVE",
            actor=actor,
            details={
                "previous_status": rec["status"],
                "approved_at": now_iso,
                "override_notes": override_notes
            }
        )

        approved_record = get_record(record_id)

        # Snapshot version 1 (or current version) into record_versions table
        save_record_version_snapshot(
            record_id=record_id,
            version_num=approved_record.get("version", 1),
            snapshot_dict=approved_record,
            approved_by=actor,
            amendment_reason=None
        )

        return jsonify({
            "success": True,
            "message": "Record successfully approved and finalized.",
            "data": approved_record
        }), 200
    finally:
        conn.close()

@record_bp.route("/api/records/<record_id>/amend", methods=["POST"])
def amend_record(record_id):
    """
    Amend an approved record. Requires amendment reason and logs traceability.
    Snapshots amended version in record_versions.
    """
    rec = get_record(record_id)
    if not rec:
        return jsonify({"success": False, "error": "Record not found."}), 404

    body = request.get_json(silent=True) or {}
    amendment_reason = body.get("reason", "").strip()
    if not amendment_reason:
        return jsonify({
            "success": False,
            "error": "A clear amendment reason is mandatory to modify an approved record."
        }), 400

    actor = body.get("responder_id") or rec.get("responder_id")
    now_iso = datetime.now(timezone.utc).isoformat()
    current_ver = rec.get("version", 1)
    new_version = current_ver + 1

    # 1. Ensure the previous approved version (e.g. V1) is preserved as an immutable snapshot
    existing_snap = get_record_version_snapshot(record_id, current_ver)
    if not existing_snap:
        save_record_version_snapshot(
            record_id=record_id,
            version_num=current_ver,
            snapshot_dict=rec,
            approved_by=rec.get("responder_id", "First Responder"),
            amendment_reason=None
        )

    corrected_transcript = body.get("corrected_transcript", rec["corrected_transcript"])

    # 2. Re-extract clinical entities from amended transcript so newly added findings are captured
    extracted = ClinicalExtractor.extract_all(corrected_transcript)
    incoming_clinical = body.get("clinical_data")
    if incoming_clinical and isinstance(incoming_clinical, dict):
        clinical_data = extracted
        # Retain any user verification states from previous reviews where IDs or canonical names match
        for cat in ("vital_signs", "medications", "symptoms", "procedures", "examinations"):
            incoming_items = incoming_clinical.get(cat, [])
            incoming_map = {item.get("id"): item for item in incoming_items if item.get("id")}
            for item in clinical_data.get(cat, []):
                if item.get("id") in incoming_map:
                    item["verification_state"] = incoming_map[item["id"]].get("verification_state", item["verification_state"])
    else:
        clinical_data = extracted

    validation_warnings = ValidationService.validate_clinical_record(clinical_data)

    evidence_passport = EvidencePassportService.compile_evidence_passport(
        record_id=record_id,
        clinical_data=clinical_data,
        transcript_text=corrected_transcript,
        transcription_meta=rec.get("transcription_metadata", {}),
        reviewer_decisions={"amendment_reason": amendment_reason}
    )

    uncertainty_ledger = UncertaintyService.compile_uncertainty_ledger(
        clinical_data=clinical_data,
        warnings=validation_warnings
    )

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # Requirement 8 & 9: Approval applies to a specific version.
        # An amended version resets to 'Needs Review' with approved_at = NULL until approved.
        cursor.execute("""
            UPDATE records SET
                status = 'Needs Review',
                version = ?,
                updated_at = ?,
                approved_at = NULL,
                corrected_transcript = ?,
                clinical_data = ?,
                validation_warnings = ?,
                evidence_passport = ?,
                uncertainty_ledger = ?
            WHERE id = ?;
        """, (
            new_version,
            now_iso,
            corrected_transcript,
            json.dumps(clinical_data),
            json.dumps(validation_warnings),
            json.dumps(evidence_passport),
            json.dumps(uncertainty_ledger),
            record_id
        ))
        conn.commit()

        log_audit_event(
            record_id=record_id,
            action="AMEND",
            actor=actor,
            details={
                "previous_version": current_ver,
                "new_version": new_version,
                "reason": amendment_reason,
                "amended_at": now_iso
            }
        )

        amended = get_record(record_id)

        # Snapshot newly amended version linked to the amendment reason
        save_record_version_snapshot(
            record_id=record_id,
            version_num=new_version,
            snapshot_dict=amended,
            approved_by=actor,
            amendment_reason=amendment_reason
        )

        return jsonify({
            "success": True,
            "message": f"Record amended to version {new_version}. Review and approval required for the new version.",
            "data": amended
        }), 200
    finally:
        conn.close()

@record_bp.route("/api/records/<record_id>/versions", methods=["GET"])
def get_record_version_list(record_id):
    """Retrieve list of preserved versions for a record."""
    rec = get_record(record_id)
    if not rec:
        return jsonify({"success": False, "error": "Record not found."}), 404
    versions = get_record_versions(record_id)
    return jsonify({
        "success": True,
        "record_id": record_id,
        "count": len(versions),
        "data": versions,
        "versions": versions
    }), 200

@record_bp.route("/api/records/<record_id>/versions/<int:version_num>", methods=["GET"])
def get_version_snapshot(record_id, version_num):
    """Retrieve exact snapshot of a historical approved or amended version."""
    snapshot = get_record_version_snapshot(record_id, version_num)
    if not snapshot:
        return jsonify({"success": False, "error": f"Version {version_num} for record '{record_id}' not found."}), 404
    return jsonify({
        "success": True,
        "data": snapshot
    }), 200

@record_bp.route("/api/records/<record_id>/export/fhir", methods=["GET"])
def export_fhir(record_id):
    """Export standards-compatible HL7 FHIR R4 Document Bundle."""
    bundle = ReportService.generate_fhir_bundle(record_id)
    if not bundle:
        return jsonify({"success": False, "error": "Record not found."}), 404
    return jsonify(bundle), 200

@record_bp.route("/api/records/<record_id>/export/json", methods=["GET"])
def export_json(record_id):
    """Export complete structured JSON report. Supports ?version=N for specific historical version."""
    version_num = request.args.get("version", type=int)
    report = ReportService.generate_json_report(record_id, version_num=version_num)
    if not report:
        return jsonify({"success": False, "error": "Record or version not found."}), 404
    return jsonify(report), 200

@record_bp.route("/api/records/<record_id>/export/pdf", methods=["GET"])
def export_pdf(record_id):
    """Generate and serve clinical PDF report. Supports ?version=N for specific historical version."""
    rec = get_record(record_id)
    if not rec:
        return jsonify({"success": False, "error": "Record not found."}), 404

    version_num = request.args.get("version", type=int)
    pdf_path = ReportService.generate_pdf_report(record_id, version_num=version_num)
    if not pdf_path or not os.path.exists(pdf_path):
        return jsonify({"success": False, "error": "Failed to compile PDF report."}), 500

    ver_suffix = f"_v{version_num}" if version_num is not None else f"_v{rec.get('version', 1)}"
    filename = f"field_to_record_{record_id}{ver_suffix}.pdf"
    return send_file(
        pdf_path,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename
    )

@record_bp.route("/api/records/<record_id>/handover", methods=["GET"])
def get_hospital_handover_data(record_id):
    """
    Feature 5: Hospital Handover Document Payload.
    Provides structured clinical handover data covering Sections A through G.
    Supports ?version=N for historical snapshot audit.
    """
    rec = get_record(record_id)
    if not rec:
        return jsonify({"success": False, "error": "Record not found."}), 404

    version_num = request.args.get("version", type=int)
    handover_data = ReportService.generate_handover_data(record_id, version_num=version_num)
    if not handover_data:
        return jsonify({"success": False, "error": "Failed to generate hospital handover data."}), 500

    return jsonify({
        "success": True,
        "record_id": record_id,
        "data": handover_data
    }), 200

@record_bp.route("/api/records/<record_id>/handover/pdf", methods=["GET"])
def export_hospital_handover_pdf(record_id):
    """
    Feature 5: Printable Hospital Handover Page PDF.
    Generates and serves professional A4 PDF using ReportLab with Sections A through G,
    grayscale contrast optimization, and document status banners.
    Supports ?version=N.
    """
    rec = get_record(record_id)
    if not rec:
        return jsonify({"success": False, "error": "Record not found."}), 404

    version_num = request.args.get("version", type=int)
    pdf_path = ReportService.generate_handover_pdf(record_id, version_num=version_num)
    if not pdf_path or not os.path.exists(pdf_path):
        return jsonify({"success": False, "error": "Failed to compile hospital handover PDF."}), 500

    ver_suffix = f"_v{version_num}" if version_num is not None else f"_v{rec.get('version', 1)}"
    filename = f"hospital_handover_{record_id}{ver_suffix}.pdf"
    return send_file(
        pdf_path,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename
    )

@record_bp.route("/api/records/<record_id>/timeline", methods=["GET"])
def get_case_timeline(record_id):
    """
    Ongoing Case Timeline and Vitals Chart API (Features A, B, C, D, E).
    Aggregates chronological vital signs, medication administration events,
    procedures, review milestones, and plottable chart series with source evidence.
    """
    from backend.services.timeline_service import TimelineService
    timeline_data = TimelineService.build_case_timeline(record_id)
    if not timeline_data:
        return jsonify({"success": False, "error": "Record not found."}), 404

    return jsonify({
        "success": True,
        "record_id": record_id,
        "data": timeline_data
    }), 200

@record_bp.route("/api/records/<record_id>/audit", methods=["GET"])
def get_audit_trail(record_id):
    """Retrieve full audit log trail for a record."""
    rec = get_record(record_id)
    if not rec:
        return jsonify({"success": False, "error": "Record not found."}), 404

    logs = get_record_audit_logs(record_id)
    return jsonify({
        "success": True,
        "record_id": record_id,
        "count": len(logs),
        "data": logs
    }), 200
