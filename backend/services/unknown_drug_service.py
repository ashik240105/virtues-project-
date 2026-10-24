"""
Unknown Drug Detection & Review Item Service.
Manages unverified medication mentions encountered in pre-hospital emergency notes.
Safety & Clinical Governance Constraints:
- Detects unverified drug entities with dosages/routes that are not in the approved ambulance catalogue.
- Creates structured review items: original text, suspected name, transcript span, language, timestamp/offset, status.
- Generates clear "Unknown medication — review required" warnings.
- Allows authorized reviewer actions: CONFIRM, CORRECT, REJECT, UNRESOLVED.
- Records all reviewer decisions in immutable audit history.
- CRITICAL: Never automatically promotes unverified drug names into the trusted catalogue without explicit authorized validation.
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import re
import uuid
import json
from datetime import datetime, timezone
from backend.database.db import get_db_connection, log_audit_event
from backend.services.medicine_service import MedicineService

# Stop-words to avoid false positive unknown drug flags on non-medication clinical words
EXCLUDED_NON_DRUG_WORDS = {
    "patient", "bp", "pulse", "hr", "rr", "spo2", "gcs", "temp", "blood", "pressure",
    "heart", "rate", "glucose", "sugar", "monitor", "oxygen", "normal", "sinus", "rhythm",
    "clear", "lungs", "sounds", "chest", "pain", "shortness", "breath", "trauma", "headache",
    "wound", "dressing", "tourniquet", "cpr", "iv", "im", "io", "po", "sl", "administered",
    "given", "gave", "started", "bolus", "push", "infusion", "taking", "took", "prescribed",
    "female", "male", "year", "years", "old", "alert", "oriented", "unresponsive", "denies",
    "allergies", "allergy", "history", "vital", "vitals", "signs", "stable", "critical"
}

class ReviewStatus:
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CORRECTED = "CORRECTED"
    REJECTED = "REJECTED"
    UNRESOLVED = "UNRESOLVED"

class UnknownDrugService:

    @classmethod
    def detect_unknown_medications(cls, text, extracted_medications=None, language="en"):
        """
        Scan clinical note for potential medication administrations or mentions that
        do not match any approved medicine in the ambulance formulary.
        """
        if not text:
            return []

        extracted_medications = extracted_medications or []
        verified_spans = [(m.get("char_start", 0), m.get("char_end", 0)) for m in extracted_medications]
        known_canonical_and_aliases = set()
        for km in MedicineService.get_all_medicines():
            known_canonical_and_aliases.add(km["canonical_name"].lower())
            for al in km["aliases"]:
                known_canonical_and_aliases.add(al.lower())

        unknown_items = []

        # Pattern 1: Administration verb followed by capitalized or clinical token with dose/route
        # e.g. "gave Cefazolin 1g IV", "administered Metoprolol 5mg", "pushed Adenosine 6mg"
        dose_route_pattern = r"(?i)\b([0-9]+(?:\.[0-9]+)?\s*(?:mg|mcg|g|ml|units?|puffs?)|iv|im|po|sl|pr|io)\b"
        admin_verbs = r"(?:gave|given|administered|pushed|bolus\s+of|infused|started|injected|taking|prescribed|diya|kuduthom)"

        # Search pattern: <admin_verb> <suspected_word> (surrounded by dose/route)
        pat1 = rf"(?i)\b({admin_verbs})\s+([A-Za-z\u0900-\u097F\u0B80-\u0BFF][a-zA-Z0-9\-_]{{2,30}})\b"
        for m in re.finditer(pat1, text):
            suspected = m.group(2).strip()
            word_start = m.start(2)
            word_end = m.end(2)

            if suspected.lower() in EXCLUDED_NON_DRUG_WORDS or suspected.isdigit():
                continue

            # If already matched in verified catalogue
            if suspected.lower() in known_canonical_and_aliases:
                continue

            # If already overlapping with verified medication span
            if any(max(word_start, vs) < min(word_end, ve) for vs, ve in verified_spans):
                continue

            match_res = MedicineService.match_medicine(suspected)
            if match_res["status"] in ("EXACT", "ALIAS"):
                continue

            # Check if surrounding text has dose or route
            window_s = max(0, word_start - 30)
            window_e = min(len(text), word_end + 35)
            surrounding = text[window_s:window_e]

            has_dose_or_route = bool(re.search(dose_route_pattern, surrounding))
            if has_dose_or_route:
                unknown_items.append({
                    "id": f"unk-{uuid.uuid4().hex[:6]}",
                    "suspected_entity_name": suspected,
                    "original_text": surrounding.strip(),
                    "char_start": word_start,
                    "char_end": word_end,
                    "language": language,
                    "review_status": ReviewStatus.PENDING,
                    "warning": "Unknown medication — review required",
                    "explanation": f"Suspected drug mention '{suspected}' is not recognized in approved ambulance formulary.",
                    "audio_offset": None,
                    "created_at": datetime.now(timezone.utc).isoformat()
                })

        # Pattern 2: <suspected_word> immediately preceding a dosage unit
        # e.g. "Cefazolin 1g IV", "Toradol 30mg"
        pat2 = r"(?i)\b([A-Za-z\u0900-\u097F\u0B80-\u0BFF][a-zA-Z0-9\-_]{2,30})\s+([0-9]+(?:\.[0-9]+)?\s*(?:mg|mcg|g|ml))\b"
        for m in re.finditer(pat2, text):
            suspected = m.group(1).strip()
            word_start = m.start(1)
            word_end = m.end(1)

            if suspected.lower() in EXCLUDED_NON_DRUG_WORDS or suspected.isdigit():
                continue

            if suspected.lower() in known_canonical_and_aliases:
                continue

            if any(max(word_start, vs) < min(word_end, ve) for vs, ve in verified_spans):
                continue

            if any(u["char_start"] == word_start for u in unknown_items):
                continue

            match_res = MedicineService.match_medicine(suspected)
            if match_res["status"] in ("EXACT", "ALIAS"):
                continue

            window_s = max(0, word_start - 20)
            window_e = min(len(text), m.end() + 25)
            unknown_items.append({
                "id": f"unk-{uuid.uuid4().hex[:6]}",
                "suspected_entity_name": suspected,
                "original_text": text[window_s:window_e].strip(),
                "char_start": word_start,
                "char_end": word_end,
                "language": language,
                "review_status": ReviewStatus.PENDING,
                "warning": "Unknown medication — review required",
                "explanation": f"Possible medication name '{suspected}' with dosage not found in ambulance formulary.",
                "audio_offset": None,
                "created_at": datetime.now(timezone.utc).isoformat()
            })

        return unknown_items

    @classmethod
    def persist_review_items(cls, record_id, review_items):
        """Save unknown medication review items in SQLite database."""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            now_iso = datetime.now(timezone.utc).isoformat()
            for item in review_items:
                cursor.execute("""
                    INSERT OR REPLACE INTO unknown_medication_reviews (
                        id, record_id, original_text, suspected_entity_name,
                        char_start, char_end, audio_offset, language,
                        review_status, reviewer_decision, corrected_canonical_name,
                        reviewer_id, decision_timestamp, notes, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    item["id"],
                    record_id,
                    item["original_text"],
                    item["suspected_entity_name"],
                    item.get("char_start"),
                    item.get("char_end"),
                    item.get("audio_offset"),
                    item.get("language", "en"),
                    item.get("review_status", ReviewStatus.PENDING),
                    item.get("reviewer_decision"),
                    item.get("corrected_canonical_name"),
                    item.get("reviewer_id"),
                    item.get("decision_timestamp"),
                    item.get("notes"),
                    now_iso
                ))
            conn.commit()
        finally:
            conn.close()

    @classmethod
    def get_review_items_for_record(cls, record_id):
        """Retrieve unknown medication review items for a record."""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM unknown_medication_reviews
                WHERE record_id = ?
                ORDER BY created_at ASC;
            """, (record_id,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @classmethod
    def resolve_review_item(cls, item_id, record_id, action, reviewer_id, corrected_name=None, notes=None):
        """
        Authorized clinical reviewer action on unknown medication item:
        - CONFIRM: Verified as administered (e.g. valid non-formulary hospital transfer drug)
        - CORRECT: Corrected to verified catalogue medication
        - REJECT: Spurious or non-medication text
        - UNRESOLVED: Kept as unresolved for further escalation
        CRITICAL: Never automatically updates the trusted medicine_catalogue.
        """
        raw_action = (action or "").upper().strip()
        ACTION_MAP = {
            "CONFIRM": ReviewStatus.CONFIRMED,
            "CONFIRMED": ReviewStatus.CONFIRMED,
            "CORRECT": ReviewStatus.CORRECTED,
            "CORRECTED": ReviewStatus.CORRECTED,
            "REJECT": ReviewStatus.REJECTED,
            "REJECTED": ReviewStatus.REJECTED,
            "UNRESOLVED": ReviewStatus.UNRESOLVED
        }
        if raw_action not in ACTION_MAP:
            raise ValueError(f"Invalid review action '{action}'. Must be CONFIRM, CORRECT, REJECT, or UNRESOLVED.")

        canonical_action = ACTION_MAP[raw_action]

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            now_iso = datetime.now(timezone.utc).isoformat()

            cursor.execute("""
                UPDATE unknown_medication_reviews
                SET review_status = ?,
                    reviewer_decision = ?,
                    corrected_canonical_name = ?,
                    reviewer_id = ?,
                    decision_timestamp = ?,
                    notes = ?
                WHERE id = ? AND record_id = ?;
            """, (canonical_action, canonical_action, corrected_name, reviewer_id, now_iso, notes, item_id, record_id))

            conn.commit()

            # Record in immutable audit trail
            log_audit_event(
                record_id=record_id,
                action="RESOLVE_UNKNOWN_MEDICATION",
                actor=reviewer_id,
                details={
                    "review_item_id": item_id,
                    "action": canonical_action,
                    "corrected_name": corrected_name,
                    "notes": notes,
                    "timestamp": now_iso
                }
            )

            cursor.execute("SELECT * FROM unknown_medication_reviews WHERE id = ?;", (item_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @classmethod
    def add_formulary_entry(cls, entry_dict, actor_id="FormularyAdministrator"):
        """
        Explicit administrative configuration to add or update an approved formulary entry.
        Only called via authorized formulary administration endpoints, NEVER automatically.
        """
        required_fields = ["canonical_name", "category", "standard_routes", "standard_units", "typical_doses"]
        for rf in required_fields:
            if rf not in entry_dict:
                raise ValueError(f"Missing required formulary field: '{rf}'")

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            med_id = entry_dict.get("id") or f"MED-{uuid.uuid4().hex[:6].upper()}"
            aliases = entry_dict.get("aliases", [])
            routes = entry_dict.get("standard_routes", [])
            units = entry_dict.get("standard_units", [])
            doses = entry_dict.get("typical_doses", [])
            ped_warn = int(bool(entry_dict.get("pediatric_warning", 0)))
            notes = entry_dict.get("contraindications_notes", "")
            provenance = entry_dict.get("provenance", "Configured Ambulance Formulary")
            version = entry_dict.get("version", "1.0.0")

            cursor.execute("""
                INSERT INTO medicine_catalogue (
                    id, canonical_name, aliases, category, standard_routes, standard_units,
                    typical_doses, pediatric_warning, contraindications_notes, provenance, version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(canonical_name) DO UPDATE SET
                    aliases = excluded.aliases,
                    category = excluded.category,
                    standard_routes = excluded.standard_routes,
                    standard_units = excluded.standard_units,
                    typical_doses = excluded.typical_doses,
                    pediatric_warning = excluded.pediatric_warning,
                    contraindications_notes = excluded.contraindications_notes,
                    provenance = excluded.provenance,
                    version = excluded.version;
            """, (
                med_id,
                entry_dict["canonical_name"].strip(),
                json.dumps(aliases),
                entry_dict["category"].strip(),
                json.dumps(routes),
                json.dumps(units),
                json.dumps(doses),
                ped_warn,
                notes,
                provenance,
                version
            ))
            conn.commit()

            cursor.execute("SELECT * FROM medicine_catalogue WHERE canonical_name = ?;", (entry_dict["canonical_name"].strip(),))
            row = cursor.fetchone()
            res = dict(row)
            res["aliases"] = json.loads(res["aliases"])
            res["standard_routes"] = json.loads(res["standard_routes"])
            res["standard_units"] = json.loads(res["standard_units"])
            res["typical_doses"] = json.loads(res["typical_doses"])
            return res
        finally:
            conn.close()
