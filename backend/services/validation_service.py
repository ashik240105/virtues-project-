"""
Validation Service: Implements safety and consistency rules on extracted clinical records.
Detects:
- Ambiguous medicines requiring human verification
- Missing required fields (dosage, route, units)
- Physiological contradictions (systolic <= diastolic, pulse out of limits)
- Missing timestamps for interventions
- Unsupported assumptions or missing source evidence
"""

import uuid
from backend.services.medicine_service import MedicineService
from backend.services.allergy_safety_service import AllergySafetyService, AllergyWarningState

class ValidationSeverity:
    CRITICAL = "CRITICAL"    # Blocks record approval until acknowledged or resolved
    WARNING = "WARNING"      # Requires human clinical attention
    INFO = "INFO"            # Advisory note

class ValidationService:

    @classmethod
    def validate_clinical_record(cls, clinical_data):
        """
        Evaluate extracted clinical entities against clinical consistency & completeness rules.
        Returns a list of structured warning objects.
        """
        warnings = []

        vitals = clinical_data.get("vital_signs", [])
        meds = clinical_data.get("medications", [])
        symptoms = clinical_data.get("symptoms", [])
        procedures = clinical_data.get("procedures", [])
        timestamps = clinical_data.get("timestamps", [])

        # 1. Validate Blood Pressure Consistency
        for v in vitals:
            if v.get("type") == "Blood Pressure":
                sys = v.get("systolic")
                dia = v.get("diastolic")
                if sys and dia:
                    if sys <= dia:
                        warnings.append({
                            "id": f"warn-{uuid.uuid4().hex[:6]}",
                            "severity": ValidationSeverity.CRITICAL,
                            "category": "Physiological Contradiction",
                            "item_id": v.get("id"),
                            "field": "Blood Pressure",
                            "message": f"Systolic pressure ({sys} mmHg) cannot be less than or equal to diastolic pressure ({dia} mmHg).",
                            "recommendation": "Review audio or re-enter accurate cuff readings.",
                            "resolved": False
                        })
                    elif sys < 60 or sys > 260:
                        warnings.append({
                            "id": f"warn-{uuid.uuid4().hex[:6]}",
                            "severity": ValidationSeverity.WARNING,
                            "category": "Extreme Vital Reading",
                            "item_id": v.get("id"),
                            "field": "Blood Pressure",
                            "message": f"Systolic pressure ({sys} mmHg) is critically abnormal.",
                            "recommendation": "Verify reading and confirm immediate clinical attention.",
                            "resolved": False
                        })

            # Pulse extreme check
            if v.get("type") == "Heart Rate":
                hr = int(v.get("value", 0))
                if hr < 40 or hr > 180:
                    warnings.append({
                        "id": f"warn-{uuid.uuid4().hex[:6]}",
                        "severity": ValidationSeverity.WARNING,
                        "category": "Extreme Vital Reading",
                        "item_id": v.get("id"),
                        "field": "Heart Rate",
                        "message": f"Heart rate ({hr} bpm) is outside normal emergency physiological bounds.",
                        "recommendation": "Verify pulse reading against cardiac monitor/palpation.",
                        "resolved": False
                    })

            # SpO2 bounds check
            if v.get("type") == "Oxygen Saturation":
                sat = int(v.get("value", 0))
                if sat > 100:
                    warnings.append({
                        "id": f"warn-{uuid.uuid4().hex[:6]}",
                        "severity": ValidationSeverity.CRITICAL,
                        "category": "Physiological Contradiction",
                        "item_id": v.get("id"),
                        "field": "SpO2",
                        "message": f"Oxygen saturation ({sat}%) cannot exceed 100%.",
                        "recommendation": "Correct sensor value.",
                        "resolved": False
                    })
                elif sat < 85:
                    warnings.append({
                        "id": f"warn-{uuid.uuid4().hex[:6]}",
                        "severity": ValidationSeverity.WARNING,
                        "category": "Critical Desaturation",
                        "item_id": v.get("id"),
                        "field": "SpO2",
                        "message": f"Severe hypoxemia detected ({sat}%).",
                        "recommendation": "Ensure supplemental oxygen administration is documented.",
                        "resolved": False
                    })

        # 2. Validate Medications: Ambiguity, Dosage, Route, Pediatric alerts
        all_meds_cat = {m["canonical_name"]: m for m in MedicineService.get_all_medicines()}

        for med in meds:
            cname = med.get("canonical_name")
            med_id = med.get("id")
            is_negated = med.get("is_negated", False)
            match_status = med.get("match_status")

            # Check Ambiguity
            if match_status == "AMBIGUOUS":
                warnings.append({
                    "id": f"warn-{uuid.uuid4().hex[:6]}",
                    "severity": ValidationSeverity.CRITICAL,
                    "category": "Ambiguous Medicine Mention",
                    "item_id": med_id,
                    "field": "Medication",
                    "message": f"Mention '{med.get('raw_mention')}' is ambiguous between candidate medications. Explicit human confirmation required.",
                    "recommendation": "Select the exact intended medication from the verified catalogue.",
                    "resolved": False
                })

            # If medication was given (not negated)
            if not is_negated:
                # Missing dosage
                if not med.get("dosage"):
                    warnings.append({
                        "id": f"warn-{uuid.uuid4().hex[:6]}",
                        "severity": ValidationSeverity.WARNING,
                        "category": "Missing Required Field",
                        "item_id": med_id,
                        "field": "Dosage",
                        "message": f"Medication '{cname}' was mentioned without a numeric dosage.",
                        "recommendation": "Specify the administered dose or mark as unknown.",
                        "resolved": False
                    })

                # Missing route
                if not med.get("route"):
                    warnings.append({
                        "id": f"warn-{uuid.uuid4().hex[:6]}",
                        "severity": ValidationSeverity.WARNING,
                        "category": "Missing Required Field",
                        "item_id": med_id,
                        "field": "Administration Route",
                        "message": f"Administration route (e.g. IV, Oral, IM) not documented for '{cname}'.",
                        "recommendation": "Select administration route.",
                        "resolved": False
                    })

                # Unit validation against catalogue
                if cname in all_meds_cat:
                    valid_units = all_meds_cat[cname].get("standard_units", [])
                    u = med.get("unit")
                    if u and valid_units and u.lower() not in [vu.lower() for vu in valid_units]:
                        warnings.append({
                            "id": f"warn-{uuid.uuid4().hex[:6]}",
                            "severity": ValidationSeverity.WARNING,
                            "category": "Unusual Unit",
                            "item_id": med_id,
                            "field": "Dose Unit",
                            "message": f"Unit '{u}' is non-standard for {cname}. Standard units: {', '.join(valid_units)}.",
                            "recommendation": "Confirm unit of measure.",
                            "resolved": False
                        })

                # Pediatric warning alert
                if med.get("pediatric_warning"):
                    warnings.append({
                        "id": f"warn-{uuid.uuid4().hex[:6]}",
                        "severity": ValidationSeverity.INFO,
                        "category": "Pediatric Safety Warning",
                        "item_id": med_id,
                        "field": "Medication Safety",
                        "message": f"{cname} carries specific pediatric warnings or contraindications.",
                        "recommendation": "Verify patient age and contraindications.",
                        "resolved": False
                    })

        # 3. Missing Timestamps for Interventions
        if meds or procedures:
            if not timestamps:
                warnings.append({
                    "id": f"warn-{uuid.uuid4().hex[:6]}",
                    "severity": ValidationSeverity.INFO,
                    "category": "Missing Event Timing",
                    "item_id": None,
                    "field": "Timeline",
                    "message": "Clinical interventions or medications were recorded without explicit timestamps in the transcript.",
                    "recommendation": "Add approximate time of administration in the review step.",
                    "resolved": False
                })

        # 4. Source Evidence Check
        for v in vitals:
            if not v.get("source_phrase"):
                warnings.append({
                    "id": f"warn-{uuid.uuid4().hex[:6]}",
                    "severity": ValidationSeverity.WARNING,
                    "category": "Missing Source Evidence",
                    "item_id": v.get("id"),
                    "field": v.get("name"),
                    "message": "Vital sign lacks direct textual evidence span.",
                    "recommendation": "Link or verify against original note.",
                    "resolved": False
                })

        # 5. Unknown Medication Warnings (Feature 3)
        unknown_meds = clinical_data.get("unknown_medications", [])
        for unk in unknown_meds:
            s_name = unk.get("suspected_entity_name", "Unknown Drug")
            warnings.append({
                "id": f"warn-{uuid.uuid4().hex[:6]}",
                "severity": ValidationSeverity.WARNING,
                "category": "Unknown Medication Alert",
                "item_id": unk.get("id"),
                "field": "Medication",
                "message": f"Unknown medication — review required: Suspected entity '{s_name}' was documented with dosage/route but is not recognized in approved ambulance formulary.",
                "recommendation": "An authorized reviewer must confirm, correct, or reject this unverified entry.",
                "resolved": False,
                "review_status": unk.get("review_status", "PENDING")
            })

        # 6. Allergy & Medication Safety Evaluation (Feature 4)
        patient_allergies = clinical_data.get("patient_allergies") or []
        encounter_allergies = clinical_data.get("allergies") or []

        # If patient_id is present in clinical_data but patient_allergies not yet populated, lookup patient
        patient_id = clinical_data.get("patient_id")
        if patient_id and not patient_allergies:
            from backend.database.db import get_patient
            pt = get_patient(patient_id)
            if pt and pt.get("allergies"):
                patient_allergies = pt["allergies"]

        safety_eval = AllergySafetyService.evaluate_safety(
            medications=meds,
            patient_allergies=patient_allergies,
            encounter_allergies=encounter_allergies
        )

        for aw in safety_eval["warnings"]:
            sev = ValidationSeverity.CRITICAL if aw["severity"] == "CRITICAL" else ValidationSeverity.WARNING
            warnings.append({
                "id": aw["id"],
                "severity": sev,
                "category": "Allergy & Medication Safety Warning",
                "item_id": aw.get("medication_name"),
                "field": "Medication Safety",
                "message": aw["explanation"],
                "explanation": aw["explanation"],
                "warning_type": aw["warning_type"],
                "medication_name": aw["medication_name"],
                "recorded_allergy": aw.get("recorded_allergy"),
                "allergy_source": aw.get("allergy_source"),
                "evidence_basis": aw.get("evidence_basis"),
                "recommendation": "Verify clinical appropriateness and record explicit acknowledgment if justified.",
                "resolved": aw.get("acknowledged", False)
            })

        return warnings
