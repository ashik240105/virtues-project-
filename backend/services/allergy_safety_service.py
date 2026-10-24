"""
Allergy & Medication Safety Decision Support Service.
Implements evidence-based, transparent allergy conflict detection against verified ingredients
and documented cross-sensitivity classes.
Safety constraints:
- Purely clinical documentation and decision support; NEVER an autonomous prescribing engine.
- Does NOT recommend treatment or independently determine whether medicine should be administered.
- Does NOT treat missing allergy information as proof that the patient has no allergies.
- Distinguishes exact ingredient matches, verified aliases, unknown allergy status, and explicit NKDA.
- Records warning acknowledgment and reviewer decisions in immutable audit history.
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import uuid
import json
from datetime import datetime, timezone
from backend.database.db import get_db_connection, log_audit_event

# Documented evidence-based reference data (WHO Model List 2023 / AHFS / Martindale)
VERIFIED_INGREDIENT_MAP = {
    "aspirin": {
        "canonical": "Aspirin",
        "ingredients": ["aspirin", "acetylsalicylic acid", "asa", "disprin", "bayer", "ecosprin", "ஆஸ்பிரின்", "அஸ்பிரின்", "டிஸ்ப்ரின்", "एस्पिरिन", "डिस्प्रिन", "इकोस्प्रिन"],
        "class": "NSAID / Salicylate",
        "cross_reactive_classes": ["nsaid", "salicylate", "ibuprofen", "advil", "motrin"]
    },
    "paracetamol": {
        "canonical": "Paracetamol",
        "ingredients": ["paracetamol", "acetaminophen", "tylenol", "panadol", "calpol", "apap", "paramol", "crocin", "dolo", "dolo 650", "பாராசிட்டமால்", "பேராசிட்டமால்", "पैरासिटामोल", "क्रोसीन", "डोलो"],
        "class": "Analgesic / Antipyretic",
        "cross_reactive_classes": []
    },
    "ibuprofen": {
        "canonical": "Ibuprofen",
        "ingredients": ["ibuprofen", "advil", "motrin", "nurofen", "brufen", "combiflam", "ஐபுப்ரூஃபன்", "इबुप्रोफेन", "ब्रुफेन", "कॉम्बीफ्लाम"],
        "class": "NSAID",
        "cross_reactive_classes": ["nsaid", "salicylate", "aspirin", "asa", "disprin"]
    },
    "morphine": {
        "canonical": "Morphine",
        "ingredients": ["morphine", "morphine sulfate", "ms contin", "duramorph", "roxanol", "மார்ஃபின்", "மார்பின்", "मॉर्फिन", "मॉर्फीन"],
        "class": "Opioid Analgesic",
        "cross_reactive_classes": ["opioid", "opioids", "opiates", "codeine"]
    },
    "fentanyl": {
        "canonical": "Fentanyl",
        "ingredients": ["fentanyl", "sublimaze", "duragesic", "actiq", "ஃபெண்டானில்", "फेन्टानिल"],
        "class": "Synthetic Opioid",
        "cross_reactive_classes": ["opioid", "synthetic opioid"]
    },
    "naloxone": {
        "canonical": "Naloxone",
        "ingredients": ["naloxone", "narcan", "evzio", "நலாக்சோன்", "नेलोक्सोन"],
        "class": "Opioid Antagonist",
        "cross_reactive_classes": []
    },
    "salbutamol": {
        "canonical": "Salbutamol",
        "ingredients": ["salbutamol", "albuterol", "ventolin", "proventil", "accuneb", "asthalin", "சல்பியூட்டமால்", "सालबुटामोल"],
        "class": "Beta-2 Agonist",
        "cross_reactive_classes": []
    },
    "nitroglycerin": {
        "canonical": "Nitroglycerin",
        "ingredients": ["nitroglycerin", "glyceryl trinitrate", "gtn", "nitrostat", "nitrolingual", "nitro", "sorbitrate", "நைட்ரோகிளிசரின்", "नाइट्रोग्लिसरीन"],
        "class": "Nitrate",
        "cross_reactive_classes": ["nitrates"]
    },
    "epinephrine": {
        "canonical": "Epinephrine",
        "ingredients": ["epinephrine", "adrenaline", "epipen", "auvi-q", "adrenaclick", "எபினெப்ரின்", "एपिनेफ्रीन", "एड्रेनालाईन"],
        "class": "Sympathomimetic",
        "cross_reactive_classes": []
    },
    "atropine": {
        "canonical": "Atropine",
        "ingredients": ["atropine", "atropine sulfate", "belladonna", "அட்ரோபின்", "एट्रोपिन"],
        "class": "Anticholinergic",
        "cross_reactive_classes": []
    },
    "amiodarone": {
        "canonical": "Amiodarone",
        "ingredients": ["amiodarone", "cordarone", "pacerone", "அமியோடரோன்", "एमियोडेरोन"],
        "class": "Antiarrhythmic",
        "cross_reactive_classes": ["iodine", "iodine contrast"]
    },
    "penicillin": {
        "canonical": "Penicillin",
        "ingredients": ["penicillin", "amoxicillin", "ampicillin", "augmentin", "piperacillin", "benzylpenicillin", "penicillins", "பெனிசிலின்", "पेनिसिलिन"],
        "class": "Beta-lactam Antibiotic",
        "cross_reactive_classes": ["beta-lactam", "cephalosporin"]
    },
    "sulfa": {
        "canonical": "Sulfa",
        "ingredients": ["sulfa", "sulfa drugs", "sulfamethoxazole", "bactrim", "septra", "sulfonamide", "sulfonamides", "சல்பா", "सल्फा"],
        "class": "Sulfonamide",
        "cross_reactive_classes": ["sulfonamides"]
    },
    "midazolam": {
        "canonical": "Midazolam",
        "ingredients": ["midazolam", "versed", "hypnovel", "mezolam", "மிடசோலாம்", "मिडाज़ोलम"],
        "class": "Benzodiazepine",
        "cross_reactive_classes": ["benzodiazepine", "benzodiazepines"]
    },
    "diazepam": {
        "canonical": "Diazepam",
        "ingredients": ["diazepam", "valium", "calmpose", "டயஸெபம்", "डायजेपाम"],
        "class": "Benzodiazepine",
        "cross_reactive_classes": ["benzodiazepine", "benzodiazepines"]
    },
    "ketamine": {
        "canonical": "Ketamine",
        "ingredients": ["ketamine", "ketalar", "ketanest", "கீட்டமைன்", "केटामाइन"],
        "class": "Dissociative Anesthetic",
        "cross_reactive_classes": []
    },
    "ondansetron": {
        "canonical": "Ondansetron",
        "ingredients": ["ondansetron", "zofran", "zuplenz", "emeset", "vomikind", "ஒன்டான்செட்ரான்", "ओन्डान्सेट्रोन"],
        "class": "5-HT3 Antagonist",
        "cross_reactive_classes": []
    },
    "tranexamic acid": {
        "canonical": "Tranexamic Acid",
        "ingredients": ["tranexamic acid", "txa", "cyklokapron", "lysteda", "trapic", "ட்ரெனெக்ஸாமிக் அமிலம்", "டிஎக்ஸ்ஏ", "ट्रानेक्सामिक एसिड"],
        "class": "Antifibrinolytic",
        "cross_reactive_classes": []
    }
}

class AllergyWarningState:
    CONFIRMED_ALLERGY_CONFLICT = "CONFIRMED_ALLERGY_CONFLICT"
    POSSIBLE_ALLERGY_CONFLICT = "POSSIBLE_ALLERGY_CONFLICT"
    ALLERGY_STATUS_UNKNOWN = "ALLERGY_STATUS_UNKNOWN"
    NO_KNOWN_ALLERGIES = "NO_KNOWN_ALLERGIES"
    ALLERGY_REQUIRES_REVIEW = "ALLERGY_REQUIRES_REVIEW"

class AllergySafetyService:

    @classmethod
    def normalize_substance(cls, text):
        """Clean and normalize substance string."""
        if not text:
            return ""
        return str(text).lower().strip().strip(".,;:?!'\"")

    @classmethod
    def match_ingredient(cls, med_name, allergen_name):
        """
        Check if a medication and recorded allergen match:
        Returns: (match_type: 'EXACT' | 'CLASS' | None, explanation: str, basis: str)
        """
        norm_med = cls.normalize_substance(med_name)
        norm_allr = cls.normalize_substance(allergen_name)

        if not norm_med or not norm_allr:
            return None, "", ""

        # 1. Exact string match or direct inclusion
        if norm_med == norm_allr or norm_allr in norm_med or norm_med in norm_allr:
            return "EXACT", f"Direct ingredient match between '{med_name}' and documented allergy '{allergen_name}'.", "Exact chemical/generic match"

        # 2. Check reference map for verified ingredients and aliases
        for ref_key, ref_info in VERIFIED_INGREDIENT_MAP.items():
            med_in_ref = any(ing in norm_med or norm_med in ing for ing in ref_info["ingredients"])
            allr_in_ref = any(ing in norm_allr or norm_allr in ing for ing in ref_info["ingredients"])

            # Both belong to the exact same ingredient entry
            if med_in_ref and allr_in_ref:
                return "EXACT", (
                    f"Verified ingredient equivalence: '{med_name}' shares the exact generic substance "
                    f"'{ref_info['canonical']}' with recorded allergy '{allergen_name}'."
                ), f"WHO Model List / AHFS Verified Synonym for {ref_info['canonical']}"

            # Class cross-reactivity check (e.g. Patient allergic to Aspirin or NSAIDs, medication is Ibuprofen)
            if med_in_ref:
                is_cross_reactive = any(cls_name in norm_allr for cls_name in ref_info["cross_reactive_classes"])
                if is_cross_reactive:
                    return "CLASS", (
                        f"Possible class cross-reactivity: Documented allergy to '{allergen_name}' "
                        f"belongs to or cross-reacts with {ref_info['class']} ('{med_name}')."
                    ), f"Documented {ref_info['class']} Cross-Sensitivity Rule"

            if allr_in_ref:
                is_cross_reactive = any(cls_name in norm_med for cls_name in ref_info["cross_reactive_classes"])
                if is_cross_reactive:
                    return "CLASS", (
                        f"Possible class cross-reactivity: Medication '{med_name}' "
                        f"shares cross-reactivity with recorded allergy class '{allergen_name}'."
                    ), f"Documented {ref_info['class']} Cross-Sensitivity Rule"

        return None, "", ""

    @classmethod
    def evaluate_safety(cls, medications, patient_allergies=None, encounter_allergies=None):
        """
        Evaluate administered or planned medications against patient and encounter allergies.
        Distinguishes:
          - CONFIRMED_ALLERGY_CONFLICT
          - POSSIBLE_ALLERGY_CONFLICT
          - ALLERGY_STATUS_UNKNOWN
          - NO_KNOWN_ALLERGIES
          - ALLERGY_REQUIRES_REVIEW
        """
        warnings = []
        patient_allergies = patient_allergies or []
        encounter_allergies = encounter_allergies or []

        # Check explicit NKDA documentation in encounter or patient record
        has_explicit_nkda = any(
            a.get("status") == "NO_KNOWN_ALLERGIES" for a in encounter_allergies
        ) or any(
            "no known" in str(pa).lower() or "nkda" in str(pa).lower() or "nka" in str(pa).lower()
            for pa in patient_allergies
        )

        # Check if allergy status is known
        has_allergy_history = bool(patient_allergies) or bool(encounter_allergies)

        # Build list of active confirmed/reported allergies with provenance
        active_allergies = []
        for pa in patient_allergies:
            norm_pa = cls.normalize_substance(pa)
            if norm_pa and norm_pa not in ("none", "nil", "unknown", "n/a", "no known allergies", "nkda"):
                active_allergies.append({
                    "allergen": pa,
                    "source": "Patient Medical History Profile",
                    "status": "CONFIRMED"
                })

        for ea in encounter_allergies:
            ea_status = ea.get("status")
            if ea_status == "CONFIRMED_ALLERGY":
                substance = ea.get("substance") or ea.get("source_phrase")
                active_allergies.append({
                    "allergen": substance,
                    "source": f"Current Encounter Narrative ('{ea.get('source_phrase', '')}')",
                    "status": "CONFIRMED"
                })
            elif ea_status == "ALLERGY_DENIED":
                # Specifically denied (e.g. "no morphine allergy") - NOT a conflict
                continue

        # RULE 1: If medications exist but allergy status is unknown and no NKDA documented
        if medications and not has_allergy_history and not has_explicit_nkda:
            warnings.append({
                "id": f"allrw-{uuid.uuid4().hex[:6]}",
                "warning_type": AllergyWarningState.ALLERGY_STATUS_UNKNOWN,
                "severity": "WARNING",
                "medication_name": "All Medications",
                "recorded_allergy": "None Documented",
                "allergy_source": "Encounter Assessment",
                "explanation": (
                    "Patient allergy status is completely unknown. No allergy history or NKDA statement documented. "
                    "Clinical Safety Rule: Missing allergy information must NOT be treated as proof of absence of allergies."
                ),
                "evidence_basis": "Pre-hospital Clinical Documentation & Safety Standard",
                "status": "ACTIVE",
                "acknowledged": False,
                "reviewer_decision": None
            })

        # RULE 2: Cross-check each medication against active allergies
        for med in medications:
            med_name = med.get("canonical_name") or med.get("raw_mention", "")
            is_negated = med.get("is_negated", False)
            admin_status = med.get("administration_status", "ADMINISTERED")

            # Only check administered or planned medications
            if is_negated or admin_status == "NOT_ADMINISTERED":
                continue

            for allr in active_allergies:
                match_type, explanation, basis = cls.match_ingredient(med_name, allr["allergen"])

                if match_type == "EXACT":
                    warnings.append({
                        "id": f"allrw-{uuid.uuid4().hex[:6]}",
                        "warning_type": AllergyWarningState.CONFIRMED_ALLERGY_CONFLICT,
                        "severity": "CRITICAL",
                        "medication_name": med_name,
                        "recorded_allergy": allr["allergen"],
                        "allergy_source": allr["source"],
                        "explanation": f"CRITICAL SAFETY WARNING: {explanation}",
                        "evidence_basis": basis,
                        "status": "ACTIVE",
                        "acknowledged": False,
                        "reviewer_decision": None
                    })
                elif match_type == "CLASS":
                    warnings.append({
                        "id": f"allrw-{uuid.uuid4().hex[:6]}",
                        "warning_type": AllergyWarningState.POSSIBLE_ALLERGY_CONFLICT,
                        "severity": "WARNING",
                        "medication_name": med_name,
                        "recorded_allergy": allr["allergen"],
                        "allergy_source": allr["source"],
                        "explanation": f"CAUTION: {explanation}",
                        "evidence_basis": basis,
                        "status": "ACTIVE",
                        "acknowledged": False,
                        "reviewer_decision": None
                    })

        # Determine overall safety state
        if any(w["warning_type"] == AllergyWarningState.CONFIRMED_ALLERGY_CONFLICT for w in warnings):
            overall_state = AllergyWarningState.CONFIRMED_ALLERGY_CONFLICT
            status_label = "CONFLICT_DETECTED"
        elif any(w["warning_type"] == AllergyWarningState.POSSIBLE_ALLERGY_CONFLICT for w in warnings):
            overall_state = AllergyWarningState.POSSIBLE_ALLERGY_CONFLICT
            status_label = "POSSIBLE_CONFLICT"
        elif any(w["warning_type"] == AllergyWarningState.ALLERGY_STATUS_UNKNOWN for w in warnings):
            overall_state = AllergyWarningState.ALLERGY_STATUS_UNKNOWN
            status_label = "ALLERGY_STATUS_UNKNOWN"
        elif has_explicit_nkda:
            overall_state = AllergyWarningState.NO_KNOWN_ALLERGIES
            status_label = "NO_KNOWN_ALLERGIES"
        else:
            overall_state = "ASSESSED_CLEAR"
            status_label = "NO_CONFLICTS_DOCUMENTED"

        return {
            "status": status_label,
            "overall_state": overall_state,
            "has_critical": any(w["severity"] == "CRITICAL" for w in warnings),
            "warnings_count": len(warnings),
            "warnings": warnings,
            "allergy_summary": {
                "active_allergies": active_allergies,
                "explicit_nkda_documented": has_explicit_nkda,
                "allergy_status_known": has_allergy_history or has_explicit_nkda
            }
        }

    @classmethod
    def persist_warnings_for_record(cls, record_id, patient_id, warnings):
        """Save active allergy safety warnings in the database."""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            now_iso = datetime.now(timezone.utc).isoformat()
            for w in warnings:
                explanation = w.get("explanation") or w.get("message") or ""
                severity = w.get("severity") or "WARNING"
                if hasattr(severity, "value"):
                    severity = severity.value
                warning_type = w.get("warning_type") or AllergyWarningState.POSSIBLE_ALLERGY_CONFLICT

                cursor.execute("""
                    INSERT OR REPLACE INTO allergy_safety_warnings (
                        id, record_id, patient_id, warning_type, medication_name,
                        recorded_allergy, allergy_source, severity, explanation,
                        status, reviewer_id, reviewer_decision, decision_timestamp, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    w["id"],
                    record_id,
                    patient_id,
                    warning_type,
                    w.get("medication_name", "Medication"),
                    w.get("recorded_allergy", ""),
                    w.get("allergy_source", ""),
                    str(severity),
                    explanation,
                    w.get("status", "ACTIVE"),
                    w.get("reviewer_id"),
                    w.get("reviewer_decision"),
                    w.get("decision_timestamp"),
                    now_iso
                ))
            conn.commit()
        finally:
            conn.close()

    @classmethod
    def get_warnings_for_record(cls, record_id):
        """Fetch all persistent allergy safety warnings and reviewer decisions for a record."""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM allergy_safety_warnings
                WHERE record_id = ?
                ORDER BY created_at ASC;
            """, (record_id,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @classmethod
    def acknowledge_warning(cls, warning_id, record_id, reviewer_id, decision_reason, notes=None):
        """
        Record authorized responder/reviewer acknowledgment or override in the audit log.
        Maintains visibility while recording the rationale.
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            now_iso = datetime.now(timezone.utc).isoformat()
            cursor.execute("""
                UPDATE allergy_safety_warnings
                SET status = 'ACKNOWLEDGED',
                    reviewer_id = ?,
                    reviewer_decision = ?,
                    decision_timestamp = ?
                WHERE id = ? AND record_id = ?;
            """, (reviewer_id, decision_reason, now_iso, warning_id, record_id))

            conn.commit()

            # Record in immutable audit trail
            log_audit_event(
                record_id=record_id,
                action="ACKNOWLEDGE_ALLERGY_WARNING",
                actor=reviewer_id,
                details={
                    "warning_id": warning_id,
                    "decision_reason": decision_reason,
                    "notes": notes,
                    "decision_timestamp": now_iso
                }
            )

            cursor.execute("SELECT * FROM allergy_safety_warnings WHERE id = ?;", (warning_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
