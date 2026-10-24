"""
Clinical Extractor Service: Deterministic rule-based extraction of first responder clinical entities.
Extracts: Vital signs, Medicines, Dosages, Routes, Symptoms, Procedures, Negation, and Timestamps.
Preserves exact text spans, character offsets, source phrases, and verification states.
Purely a documentation assistant: NEVER diagnoses or recommends treatment.
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import re
import uuid
from backend.services.medicine_service import MedicineService
from backend.services.number_normalizer import SpokenNumberNormalizer
from backend.services.unknown_drug_service import UnknownDrugService

# Common clinical symptom keywords (English, Tamil, and Hindi)
SYMPTOMS_LIST = [
    # English
    "chest pain", "shortness of breath", "dyspnea", "wheezing", "stridor", "cough",
    "nausea", "vomiting", "dizziness", "lightheadedness", "headache", "confusion",
    "syncope", "loss of consciousness", "altered mental status", "diaphoresis",
    "palpitations", "abdominal pain", "flank pain", "back pain", "trauma", "laceration",
    "contusion", "hematoma", "bleeding", "hemorrhage", "deformity", "fracture",
    "burn", "rash", "fever", "chills", "numbness", "weakness", "facial droop", "slurred speech",
    # Tamil
    "நெஞ்சு வலி", "மார்பு வலி", "மூச்சுத்திணறல்", "மூச்சு திணறல்", "தலைச்சுற்றல்", "குமட்டல்", "வாந்தி",
    "மயக்கம்", "ரத்தப்போக்கு", "ரத்த கசிவு", "காய்ச்சல்", "தலைவலி",
    # Hindi
    "सीना दर्द", "छाती में दर्द", "सांस फूलना", "सांस लेने में तकलीफ", "चक्कर", "जी मिचलाना", "उल्टी",
    "बेहोश", "बेहोशी", "खून बहना", "बुखार", "सिरदर्द"
]

# Common prehospital procedures (English, Tamil, and Hindi)
PROCEDURES_LIST = [
    # English
    "bag-valve-mask", "bvm", "high-flow oxygen", "oxygen therapy", "nasal cannula",
    "non-rebreather mask", "nrb mask", "iv cannulation", "iv access", "cpr",
    "chest compressions", "defibrillation", "shock advised", "shock delivered",
    "wound dressing", "pressure dressing", "tourniquet applied", "splint application",
    "cervical collar", "c-collar", "spinal immobilization", "suctioning",
    "endotracheal intubation", "et tube", "supraglottic airway", "12-lead ecg", "cardiac monitor",
    # Tamil
    "சிபிஆர்", "நெஞ்சு அழுத்தம்", "ஆக்சிஜன் சிகிச்சை", "ஆக்ஸிஜன் சிகிச்சை", "ஐவி லைன்", "ஐவி அணுகல்",
    "டிஃபிப்ரிிலேஷன்", "ஷாக்", "கட்டு போடப்பட்டது", "கட்டு",
    # Hindi
    "सीपीआर", "छाती संपीड़न", "ऑक्सीजन थेरेपी", "आईवी लाइन", "शॉक दिया", "पट्टी बांधी", "पट्टी"
]

# Negation triggers
NEGATION_TRIGGERS = [
    r"\bno\b", r"\bnot\b", r"\bdenies\b", r"\bdenied\b", r"\bwithout\b",
    r"\bdid not\b", r"\bdidn't\b", r"\bnegative for\b", r"\bno signs of\b",
    r"\bfree of\b", r"\bno report of\b"
]

def make_word_pattern(word):
    """
    Build regex pattern that respects word boundaries for ASCII and Indic scripts (Tamil, Hindi).
    Standard \b fails on Indic combining marks (pulli/virama, matras).
    """
    esc = re.escape(word)
    if word.isascii() and word.replace("_", "").isalnum():
        return rf"(?i)\b{esc}\b"
    return rf"(?i)(?:^|(?<=[\s,.;:!?()/'\"]))({esc})(?=$|[\s,.;:!?()/'\划])".replace(r"\划", r"\"")

def detect_source_language(text):
    """Detect whether transcript contains Tamil, Hindi/Devanagari, or English."""
    if not text:
        return "en"
    has_tamil = bool(re.search(r"[\u0B80-\u0BFF]", text))
    has_hindi = bool(re.search(r"[\u0900-\u097F]", text))
    has_latin = bool(re.search(r"[A-Za-z]", text))

    if (has_tamil or has_hindi) and has_latin:
        return "mixed"
    if has_tamil:
        return "ta"
    if has_hindi:
        return "hi"
    return "en"

class ClinicalExtractor:

    @classmethod
    def extract_all(cls, transcript_text, language=None):
        """
        Extract all clinical entities from a transcript string.
        Normalizes spoken number forms and speech variations while retaining the raw transcript.
        Returns a dictionary of structured clinical findings with language awareness and provenance.
        """
        if not transcript_text:
            return {
                "vital_signs": [],
                "medications": [],
                "allergies": [],
                "symptoms": [],
                "procedures": [],
                "examinations": [],
                "timestamps": [],
                "raw_text": "",
                "normalized_text": "",
                "source_language": language or "en"
            }

        raw_text = transcript_text.strip()
        source_lang = language or detect_source_language(raw_text)

        # Apply spoken-number and speech normalizer
        normalized_text = SpokenNumberNormalizer.normalize_all(raw_text)

        # Extract allergies first to protect medication extraction from false positive triggers
        allergies, allergy_spans = cls.extract_allergies(normalized_text)

        vitals = cls.extract_vitals(normalized_text)
        meds = cls.extract_medications(normalized_text, allergy_spans=allergy_spans)
        unknown_meds = UnknownDrugService.detect_unknown_medications(
            normalized_text, extracted_medications=meds, language=source_lang
        )
        symptoms = cls.extract_symptoms(normalized_text)
        procedures = cls.extract_procedures(normalized_text)
        examinations = cls.extract_examinations(normalized_text)
        timestamps = cls.extract_timestamps(normalized_text)

        # Correlate closest preceding narrative clock timestamps to entities without inventing values
        vitals = cls._correlate_entity_timestamps(vitals, timestamps, normalized_text)
        meds = cls._correlate_entity_timestamps(meds, timestamps, normalized_text)
        procedures = cls._correlate_entity_timestamps(procedures, timestamps, normalized_text)

        return {
            "vital_signs": vitals,
            "medications": meds,
            "unknown_medications": unknown_meds,
            "allergies": allergies,
            "symptoms": symptoms,
            "procedures": procedures,
            "examinations": examinations,
            "timestamps": timestamps,
            "raw_text": raw_text,
            "normalized_text": normalized_text,
            "source_language": source_lang
        }

    @classmethod
    def extract_allergies(cls, text):
        """
        Extract patient allergies and adverse reaction statements.
        Separates general allergy denials (e.g. 'No allergies', 'NKDA')
        from specific drug allergies (e.g. 'allergic to penicillin') and
        specific drug allergy denials (e.g. 'no morphine allergy').
        """
        allergies = []
        allergy_spans = []

        # 1. General No Known Allergies (NKDA) in English, Tamil, and Hindi
        general_patterns = [
            r"(?i)\b(?:no\s+known\s+(?:drug\s+)?allergies|nkda|nka|no\s+allergies|denies\s+(?:all\s+)?allergies|nil\s+known\s+allergies|no\s+drug\s+allergies|free\s+of\s+allergies|without\s+known\s+allergies)\b",
            r"(?:^|(?<=[\s,.;:!?]))(?:எந்த\s+மருந்து\s+ஒவ்வாமையும்\s+இல்லை|மருந்து\s+ஒவ்வாமை\s+இல்லை|ஒவ்வாமை\s+இல்லை)(?=$|[\s,.;:!?])",
            r"(?:^|(?<=[\s,.;:!?]))(?:कोई\s+एलर्जी\s+नहीं(?:\s+है)?|एलर्जी\s+नहीं\s+है|दवा\s+से\s+एलर्जी\s+नहीं)(?=$|[\s,.;:!?])"
        ]
        for pat in general_patterns:
            for m in re.finditer(pat, text):
                start, end = m.start(), m.end()
                allergy_spans.append((start, end, "NO_KNOWN_ALLERGIES", "None Reported"))
                allergies.append({
                    "id": f"allr-{uuid.uuid4().hex[:6]}",
                    "allergy": "No Known Allergies (NKDA)",
                    "status": "NO_KNOWN_ALLERGIES",
                    "substance": "None Reported",
                    "source_phrase": m.group(0).strip(),
                    "char_start": start,
                    "char_end": end,
                    "verification_state": "Extracted"
                })

        # 2. Specific Drug Allergy Denials (e.g. 'no morphine allergy', 'denies penicillin allergy')
        denied_patterns = [
            r"(?i)\b(?:no|denies|denied)\s+([A-Za-z\u0900-\u097F\u0B80-\u0BFF]+)\s+allerg(?:y|ies)\b",
            r"(?i)\bnot\s+allergic\s+to\s+([A-Za-z\u0900-\u097F\u0B80-\u0BFF]+)\b"
        ]
        for pat in denied_patterns:
            for m in re.finditer(pat, text):
                start, end = m.start(), m.end()
                substance = m.group(1).strip()
                if substance.lower() in ("known", "drug", "reported", "food"):
                    continue
                allergy_spans.append((start, end, "ALLERGY_DENIED", substance))
                allergies.append({
                    "id": f"allr-{uuid.uuid4().hex[:6]}",
                    "allergy": f"No {substance.title()} Allergy",
                    "status": "ALLERGY_DENIED",
                    "substance": substance.title(),
                    "source_phrase": m.group(0).strip(),
                    "char_start": start,
                    "char_end": end,
                    "verification_state": "Extracted"
                })

        # 3. Confirmed / Documented Allergies (e.g. 'allergic to penicillin', 'penicillin allergy', 'allergy to aspirin')
        confirmed_patterns = [
            r"(?i)\b(?:allergic\s+to|allergy\s+to|reaction\s+to)\s+([A-Za-z\u0900-\u097F\u0B80-\u0BFF]+)\b",
            r"(?i)\b([A-Za-z\u0900-\u097F\u0B80-\u0BFF]+)\s+allerg(?:y|ies)\b",
            r"(?:^|(?<=[\s,.;:!?]))([A-Za-z\u0B80-\u0BFF]+)\s*(?:ஒவ்வாமை\s+உள்ளது|அலர்ஜி|ஒவ்வாமை)(?=$|[\s,.;:!?])",
            r"(?:^|(?<=[\s,.;:!?]))([A-Za-z\u0900-\u097F]+)\s*(?:से\s+एलर्जी\s+है|की\s+एलर्जी|एलर्जी)(?=$|[\s,.;:!?])"
        ]
        for pat in confirmed_patterns:
            for m in re.finditer(pat, text):
                start, end = m.start(), m.end()
                if any(max(start, s) < min(end, e) for s, e, _, _ in allergy_spans):
                    continue
                substance = m.group(1).strip()
                if substance.lower() in ("no", "nil", "denies", "none", "without", "unknown", "drug", "any"):
                    continue
                allergy_spans.append((start, end, "CONFIRMED_ALLERGY", substance))
                allergies.append({
                    "id": f"allr-{uuid.uuid4().hex[:6]}",
                    "allergy": f"Allergy: {substance.title()}",
                    "status": "CONFIRMED_ALLERGY",
                    "substance": substance.title(),
                    "source_phrase": m.group(0).strip(),
                    "char_start": start,
                    "char_end": end,
                    "verification_state": "Extracted"
                })

        return allergies, allergy_spans

    @classmethod
    def check_medication_status(cls, text, match_start, match_end):
        """
        Context-aware evaluation of medication administration status:
        Distinguishes:
          - ADMINISTERED: "gave morphine", "morphine 5mg IV", "paracetamol diya"
          - NOT_ADMINISTERED: "morphine was not given", "did not administer morphine", "withheld", "nahi diya"
          - PLANNED: "plan to give morphine", "prepare morphine", "order for morphine"
          - UNCERTAIN: ambiguous context

        Guarantees that an allergy statement (e.g. 'No allergies, gave morphine')
        does NOT incorrectly cancel the administered medication.
        """
        # 1. Post-entity negation check (up to 45 characters after match_end)
        post_window = text[match_end:min(len(text), match_end + 45)].lower()
        for break_char in [".", ";", "\n"]:
            b_idx = post_window.find(break_char)
            if b_idx != -1:
                post_window = post_window[:b_idx]

        post_neg_patterns = [
            r"\b(?:was\s+not\s+given|was\s+not\s+administered|not\s+given|not\s+administered|was\s+withheld|withheld|refused|avoided)\b",
            r"\b(?:nahi\s+diya(?:\s+gaya)?|nahi\s+di|mana\s+kiya)\b",
            r"(?:கொடுக்கப்படவில்லை|தரப்படவில்லை|கொடுக்கவில்லை)"
        ]
        for pat in post_neg_patterns:
            m = re.search(pat, post_window, re.IGNORECASE)
            if m:
                return "NOT_ADMINISTERED", True, m.group(0).strip()

        # 2. Preceding text check (up to 55 characters before match_start)
        pre_window_start = max(0, match_start - 55)
        preceding = text[pre_window_start:match_start]

        last_period = max(preceding.rfind("."), preceding.rfind(";"), preceding.rfind("\n"))
        if last_period != -1:
            preceding = preceding[last_period + 1:]

        # If preceding text has a comma followed by an affirmative administration verb:
        # e.g. "No allergies, gave morphine" -> the comma + affirmative verb resets the clause
        affirmative_split = re.search(r",\s*(?:gave|given|administered|pushed|bolus|injected|started|diya|kuduthom|kuduthathu)\s*", preceding, re.IGNORECASE)
        if affirmative_split:
            preceding = preceding[affirmative_split.start() + 1:]

        # Strip out explicit general allergy phrases from preceding text
        # so "no allergies" does NOT trigger negation on medications
        clean_preceding = re.sub(
            r"(?i)\b(?:no|denies|nil|without)\s+(?:known\s+)?(?:drug\s+)?allerg(?:y|ies)\b",
            "",
            preceding
        )
        clean_preceding = re.sub(r"(?:ஒவ்வாமை\s+இல்லை|எந்த\s+ஒவ்வாமையும்\s+இல்லை|कोई\s+एलर्जी\s+नहीं)", "", clean_preceding)

        # Preceding negation check
        pre_neg_patterns = [
            r"\b(?:did\s+not\s+(?:give|administer)|do\s+not\s+give|not\s+given|not\s+administered|withheld|avoided|contraindicated|never\s+gave)\b",
            r"\b(?:no\s+[a-z\u0900-\u097F\u0B80-\u0BFF\s\-]+?\s+(?:given|administered))\b",
            r"\b(?:nahi\s+dena|nahi\s+diya)\b",
            r"(?:கொடுக்க\s+வேண்டாம்|கொடுக்கப்படவில்லை)"
        ]
        for pat in pre_neg_patterns:
            m = re.search(pat, clean_preceding, re.IGNORECASE)
            if m:
                return "NOT_ADMINISTERED", True, m.group(0).strip()

        # Check general negation keywords only if not preceded by affirmative word
        has_affirmative = bool(re.search(r"\b(?:gave|given|administered|pushed|bolus|injected|taking|diya|kuduthom)\b", clean_preceding, re.IGNORECASE))
        if not has_affirmative:
            for pat in [r"\bno\b", r"\bnot\b", r"\bwithout\b", r"\bdenies\b"]:
                m = re.search(pat, clean_preceding, re.IGNORECASE)
                if m:
                    return "NOT_ADMINISTERED", True, m.group(0).strip()

        # Check planned
        planned_patterns = [
            r"\b(?:plan\s+to\s+give|to\s+be\s+given|prepare|order\s+for|standby\s+for)\b",
            r"\b(?:dena\s+hai|kudukka\s+vendum)\b"
        ]
        for pat in planned_patterns:
            m = re.search(pat, clean_preceding, re.IGNORECASE)
            if m:
                return "PLANNED", False, None

        return "ADMINISTERED", False, None

    @classmethod
    def check_negation(cls, text, match_start, window=45):
        """
        Check if an entity is preceded by a negation trigger within a character window.
        Respects sentence/clause boundaries and allergy triggers.
        Returns (is_negated: bool, trigger_phrase: str or None)
        """
        window_start = max(0, match_start - window)
        preceding_text = text[window_start:match_start].lower()

        # Check for sentence boundaries between trigger and entity
        last_period = preceding_text.rfind(".")
        if last_period != -1:
            preceding_text = preceding_text[last_period + 1:]

        # Strip allergy clauses so "no allergies, chest pain" does not negate chest pain
        preceding_text = re.sub(r"(?i)\b(?:no|denies)\s+allerg(?:y|ies)\b", "", preceding_text)

        for pattern in NEGATION_TRIGGERS:
            m = re.search(pattern, preceding_text, re.IGNORECASE)
            if m:
                return True, m.group(0).strip()
        return False, None

    @classmethod
    def extract_vitals(cls, text):
        """Extract physiological vital signs (English, Tamil, Hindi, and Spoken formats)."""
        vitals = []

        # 1. Blood Pressure: e.g. "BP 120/80", "120/80", "blood pressure 120/80", "systolic 120 diastolic 80"
        bp_patterns = [
            r"(?i)\b(?:bp|blood pressure|pressure|இரத்த அழுத்தம்|ரத்த அழுத்தம்|பிபி|ரத்தக் கொதிப்பு|रक्तचाप|ब्लड प्रेशर|बीपी)\s*(?:is|was|of|measured|அளவு|का)?\s*([0-9]{2,3})\s*(?:/|over|by|keezh|கீழ்|बटा)\s*([0-9]{2,3})\b",
            r"(?i)\bsystolic\s*([0-9]{2,3})\s*(?:and|,)?\s*diastolic\s*([0-9]{2,3})\b",
            r"\b([0-9]{2,3})\s*/\s*([0-9]{2,3})\s*(?:mm\s*hg)?\b"
        ]
        bp_spans = []
        for pat in bp_patterns:
            for m in re.finditer(pat, text):
                start, end = m.start(), m.end()
                if any(max(start, s) < min(end, e) for s, e in bp_spans):
                    continue
                sys_val = int(m.group(1))
                dia_val = int(m.group(2))
                # Sanity filter: realistic blood pressure ranges
                if 40 <= sys_val <= 300 and 20 <= dia_val <= 200:
                    bp_spans.append((start, end))
                    vitals.append({
                        "id": f"vit-{uuid.uuid4().hex[:6]}",
                        "type": "Blood Pressure",
                        "name": "Blood Pressure",
                        "systolic": sys_val,
                        "diastolic": dia_val,
                        "value": f"{sys_val}/{dia_val}",
                        "unit": "mmHg",
                        "source_phrase": m.group(0),
                        "char_start": start,
                        "char_end": end,
                        "verification_state": "Extracted"
                    })

        # 2. Heart Rate / Pulse: e.g. "pulse 78", "heart rate 88 bpm", "pulse of 92"
        hr_pattern = r"(?i)\b(?:pulse|heart rate|hr|நாடித்துடிப்பு|இதயத்துடிப்பு|பல்ஸ்|नाड़ी|हृदय गति|पल्स)\s*(?:is|was|of|at|அளவு)?\s*([0-9]{2,3})\s*(?:bpm|beats per min(?:ute)?)?\b"
        for m in re.finditer(hr_pattern, text):
            val = int(m.group(1))
            if 30 <= val <= 260:
                vitals.append({
                    "id": f"vit-{uuid.uuid4().hex[:6]}",
                    "type": "Heart Rate",
                    "name": "Heart Rate / Pulse",
                    "value": str(val),
                    "unit": "bpm",
                    "source_phrase": m.group(0),
                    "char_start": m.start(),
                    "char_end": m.end(),
                    "verification_state": "Extracted"
                })

        # 3. Respiratory Rate: e.g. "respiratory rate 16", "RR 18", "breathing 20", "18/min"
        rr_pattern = r"(?i)\b(?:respiratory rate|rr|breathing rate|respirations|சுவாச விகிதம்|மூச்சு|श्वसन दर|सांस)\s*(?:is|was|at|of)?\s*([0-9]{1,2})\s*(?:/min|per\s*min(?:ute)?|breaths\s*(?:per\s*min(?:ute)?)?|bpm)?(?=$|[\s,.;:!?])"
        for m in re.finditer(rr_pattern, text):
            val = int(m.group(1))
            if 4 <= val <= 60:
                vitals.append({
                    "id": f"vit-{uuid.uuid4().hex[:6]}",
                    "type": "Respiratory Rate",
                    "name": "Respiratory Rate",
                    "value": str(val),
                    "unit": "breaths/min",
                    "source_phrase": m.group(0),
                    "char_start": m.start(),
                    "char_end": m.end(),
                    "verification_state": "Extracted"
                })

        # 4. SpO2 / Oxygen Saturation: e.g. "SpO2 98%", "sats 95%", "oxygen saturation 98 percent"
        spo2_pattern = r"(?i)\b(?:spo2|sats|o2 sat(?:uration)?|oxygen sat(?:uration)?|ஆக்சிஜன் அளவு|ஆக்ஸிஜன் அளவு|ऑक्सीजन स्तर)\s*(?:is|was|at|of)?\s*([0-9]{2,3})\s*(?:%|percent|per\s*cent)?(?=$|[\s,.;:!?])"
        for m in re.finditer(spo2_pattern, text):
            val = int(m.group(1))
            if 40 <= val <= 100:
                vitals.append({
                    "id": f"vit-{uuid.uuid4().hex[:6]}",
                    "type": "Oxygen Saturation",
                    "name": "SpO2",
                    "value": str(val),
                    "unit": "%",
                    "source_phrase": m.group(0),
                    "char_start": m.start(),
                    "char_end": m.end(),
                    "verification_state": "Extracted"
                })

        # 5. Temperature: e.g. "temperature 37.2", "temp 38.5 C", "temp is 98.6 F"
        temp_pattern = r"(?i)\b(?:temp|temperature|வெப்பநிலை|காய்ச்சல்|तापमान|बुखार)\s*(?:is|was|of|at)?\s*([0-9]{2}(?:\.[0-9])?)\s*(?:degrees\s*)?(c|celsius|f|fahrenheit)?\b"
        for m in re.finditer(temp_pattern, text):
            val = float(m.group(1))
            raw_unit = (m.group(2) or "C").upper()
            unit = "°F" if "F" in raw_unit else "°C"
            vitals.append({
                "id": f"vit-{uuid.uuid4().hex[:6]}",
                "type": "Temperature",
                "name": "Body Temperature",
                "value": str(val),
                "unit": unit,
                "source_phrase": m.group(0),
                "char_start": m.start(),
                "char_end": m.end(),
                "verification_state": "Extracted"
            })

        # 6. Glasgow Coma Scale (GCS): e.g. "GCS 15", "GCS of 14"
        gcs_pattern = r"(?i)\b(?:gcs|glasgow coma scale|ஜிசிஎஸ்|जीसीएस)\s*(?:is|was|of)?\s*([3-9]|1[0-5])\b"
        for m in re.finditer(gcs_pattern, text):
            val = int(m.group(1))
            vitals.append({
                "id": f"vit-{uuid.uuid4().hex[:6]}",
                "type": "GCS",
                "name": "Glasgow Coma Scale",
                "value": str(val),
                "unit": "/15",
                "source_phrase": m.group(0),
                "char_start": m.start(),
                "char_end": m.end(),
                "verification_state": "Extracted"
            })

        # 7. Blood Glucose: e.g. "glucose 5.4", "blood sugar 110 mg/dl"
        bgl_pattern = r"(?i)\b(?:blood glucose|glucose|blood sugar|bgl|இரத்த சர்க்கரை|சுகர்|रक्त शर्करा|शुगर)\s*(?:is|was|of|at)?\s*([0-9]{1,3}(?:\.[0-9])?)\s*(mmol/l|mg/dl)?\b"
        for m in re.finditer(bgl_pattern, text):
            val = float(m.group(1))
            unit = m.group(2) or ("mmol/L" if val < 35.0 else "mg/dL")
            vitals.append({
                "id": f"vit-{uuid.uuid4().hex[:6]}",
                "type": "Blood Glucose",
                "name": "Blood Glucose Level",
                "value": str(val),
                "unit": unit,
                "source_phrase": m.group(0),
                "char_start": m.start(),
                "char_end": m.end(),
                "verification_state": "Extracted"
            })

        return vitals

    @classmethod
    def extract_medications(cls, text, allergy_spans=None):
        """Extract medications, dosages, routes, and link with medicine catalogue."""
        if allergy_spans is None:
            _, allergy_spans = cls.extract_allergies(text)

        medications = []
        all_known_meds = MedicineService.get_all_medicines()

        # Build search patterns for all canonical names and aliases
        candidates_to_search = []
        for med in all_known_meds:
            candidates_to_search.append((med["canonical_name"], med))
            for alias in med["aliases"]:
                candidates_to_search.append((alias, med))

        # Sort longer names first so "Morphine Sulfate" matches before "Morphine"
        candidates_to_search.sort(key=lambda x: len(x[0]), reverse=True)

        found_spans = []

        for name, med_meta in candidates_to_search:
            pattern = make_word_pattern(name)
            for m in re.finditer(pattern, text):
                start = m.start(1) if m.groups() and m.group(1) is not None else m.start()
                end = m.end(1) if m.groups() and m.group(1) is not None else m.end()

                # Avoid duplicate overlapping span
                if any(start >= s and end <= e for s, e in found_spans):
                    continue

                # CRITICAL: If this medication name falls inside an allergy statement (e.g. "no morphine allergy", "allergic to aspirin"),
                # do NOT record an administration event!
                if allergy_spans and any(max(start, s) < min(end, e) for s, e, _, _ in allergy_spans):
                    continue

                found_spans.append((start, end))

                # Check medication administration status with clause-aware negation
                admin_status, is_neg, neg_trigger = cls.check_medication_status(text, start, end)

                # Search surrounding window (+- 60 chars) for dosage and route, respecting sentence/clause boundaries
                prev_text = text[:start]
                next_text = text[end:]
                last_break = max(prev_text.rfind(". "), prev_text.rfind("; "), prev_text.rfind("\n"))
                clause_start = 0 if last_break == -1 else last_break + 2
                window_start = max(clause_start, start - 45)

                next_breaks = [p for p in [next_text.find(". "), next_text.find("; "), next_text.find("\n")] if p != -1]
                clause_end = len(text) if not next_breaks else end + min(next_breaks) + 1
                window_end = min(clause_end, end + 60)
                surrounding = text[window_start:window_end]

                med_offset_s = start - window_start
                med_offset_e = end - window_start

                def span_dist(m_s, m_e):
                    if m_e <= med_offset_s:
                        return med_offset_s - m_e
                    if m_s >= med_offset_e:
                        return m_s - med_offset_e
                    return 0

                # Dosage regex (supports standard and multilingual Indic unit words)
                dose_pattern = r"(?i)\b([0-9]+(?:\.[0-9]+)?)\s*(mg|mcg|micrograms?|milligrams?|g|grams?|ml|milliliters?|puffs?|sprays?|tablets?|tabs?|l/min|units?|மில்லிகிராம்|मिलीग्राम|மில்லி|मिलीलीटर)\b"
                dose_matches = list(re.finditer(dose_pattern, surrounding))
                dosage = None
                dose_unit = None
                if dose_matches:
                    best_dose = min(dose_matches, key=lambda dm: span_dist(dm.start(), dm.end()))
                    dosage = best_dose.group(1)
                    raw_u = best_dose.group(2).lower()
                    # Normalize unit
                    if "mcg" in raw_u or "micro" in raw_u:
                        dose_unit = "mcg"
                    elif "mg" in raw_u or "milli" in raw_u or raw_u in ("மில்லிகிராம்", "मिलीग्राम"):
                        dose_unit = "mg"
                    elif "g" in raw_u or "gram" in raw_u:
                        dose_unit = "g"
                    elif "ml" in raw_u or raw_u in ("மில்லி", "मिलीलीटर"):
                        dose_unit = "ml"
                    elif "puff" in raw_u:
                        dose_unit = "puffs"
                    elif "spray" in raw_u:
                        dose_unit = "sprays"
                    elif "tab" in raw_u:
                        dose_unit = "tablets"
                    else:
                        dose_unit = raw_u

                # Route regex covering English, Tamil, and Hindi administration phrases
                route_pattern = (
                    r"(?i)\b("
                    r"iv|i\.v\.|intravenous|intravenously|iv\s+push|iv\s+drip|iv\s+infusion|via\s+iv|"
                    r"im|i\.m\.|intramuscular|intramuscularly|"
                    r"oral|orally|po|p\.o\.|by\s+mouth|per\s+os|swallowed|"
                    r"chewable|chewed|"
                    r"sublingual|sublingually|sl|s\.l\.|under\s+the\s+tongue|"
                    r"in|i\.n\.|intranasal|intranasally|nasal\s+spray|nasal|"
                    r"nebulized|nebulizer|via\s+nebulizer|inhaled|inhalation|inhaler|puffs?|"
                    r"io|i\.o\.|intraosseous|intraosseously|"
                    r"sc|s\.c\.|sq|s\.q\.|sub-q|subq|subcutaneous|subcutaneously|"
                    r"pr|p\.r\.|per\s+rectum|rectal|rectally|"
                    r"topical|topically|transdermal|transdermally|patch|"
                    r"buccal|buccally|"
                    r"odt|orally\s+disintegrating|"
                    r"வாய்வழியாக|குடிக்க|முழுங்க|நரம்பு வழியாக|ஐவி|தசை வழியாக|நாக்கின் அடியில்|சுவாசம் வழியாக|இன்ஹேலர்|"
                    r"मुंह से|नस से|आईवी|मांसपेशी में|जीभ के नीचे|सांस द्वारा|इन्हेलर"
                    r")\b"
                )
                route_matches = list(re.finditer(route_pattern, surrounding))
                route = None
                if route_matches:
                    best_route = min(route_matches, key=lambda rm: span_dist(rm.start(), rm.end()))
                    raw_r = re.sub(r"[.\s]+", " ", best_route.group(1).lower().strip())
                    if raw_r in ["iv", "i v", "intravenous", "intravenously", "iv push", "iv drip", "iv infusion", "via iv", "நரம்பு வழியாக", "ஐவி", "नस से", "आईवी"]:
                        route = "IV"
                    elif raw_r in ["im", "i m", "intramuscular", "intramuscularly", "தசை வழியாக", "मांसपेशी में"]:
                        route = "IM"
                    elif raw_r in ["oral", "orally", "po", "p o", "by mouth", "per os", "swallowed", "வாய்வழியாக", "குடிக்க", "முழுங்க", "मुंह से"]:
                        route = "Oral"
                    elif raw_r in ["chewable", "chewed"]:
                        route = "Chewable"
                    elif raw_r in ["sublingual", "sublingually", "sl", "s l", "under the tongue", "நாக்கின் அடியில்", "जीभ के नीचे"]:
                        route = "Sublingual"
                    elif raw_r in ["in", "i n", "intranasal", "intranasally", "nasal", "nasal spray"]:
                        route = "Intranasal"
                    elif raw_r in ["nebulized", "nebulizer", "via nebulizer", "inhaled", "inhalation", "inhaler", "puff", "puffs", "சுவாசம் வழியாக", "இன்ஹேலர்", "सांस द्वारा", "इन्हेलर"]:
                        route = "Inhaled/Nebulized"
                    elif raw_r in ["io", "i o", "intraosseous", "intraosseously"]:
                        route = "IO"
                    elif raw_r in ["sc", "s c", "sq", "s q", "sub-q", "subq", "subcutaneous", "subcutaneously"]:
                        route = "SC"
                    elif raw_r in ["pr", "p r", "per rectum", "rectal", "rectally"]:
                        route = "PR"
                    elif raw_r in ["topical", "topically", "transdermal", "transdermally", "patch"]:
                        route = "Transdermal"
                    elif raw_r in ["buccal", "buccally"]:
                        route = "Buccal"
                    elif raw_r in ["odt", "orally disintegrating"]:
                        route = "ODT"
                    else:
                        route = best_route.group(1).title()

                raw_mention_text = text[start:end]

                # Match details from catalogue with strength and route check
                match_result = MedicineService.match_medicine(raw_mention_text, strength=dosage, route=route)

                # Verification state
                state = "Extracted"
                if match_result["status"] == "AMBIGUOUS":
                    state = "Uncertain"

                medications.append({
                    "id": f"med-{uuid.uuid4().hex[:6]}",
                    "raw_mention": raw_mention_text,
                    "canonical_name": med_meta["canonical_name"],
                    "category": med_meta["category"],
                    "dosage": dosage,
                    "unit": dose_unit,
                    "route": route,
                    "is_negated": is_neg,
                    "administration_status": admin_status,
                    "negation_trigger": neg_trigger,
                    "pediatric_warning": bool(med_meta["pediatric_warning"]),
                    "contraindications_notes": med_meta["contraindications_notes"],
                    "provenance": med_meta["provenance"],
                    "match_status": match_result["status"],
                    "candidates": match_result["candidates"],
                    "source_phrase": text[window_start:window_end].strip(),
                    "char_start": start,
                    "char_end": end,
                    "verification_state": state
                })

        return medications

    @classmethod
    def get_clean_source_phrase(cls, text, start, end, neg_trigger=None):
        """Extract a clean clause or sentence span without cutting mid-word."""
        if neg_trigger:
            return f"{neg_trigger} {text[start:end]}".strip()
        clause_start = max(text.rfind(".", 0, start), text.rfind(",", 0, start), text.rfind(";", 0, start))
        clause_start = 0 if clause_start == -1 else clause_start + 1
        clause_end = len(text)
        for p in [".", ",", ";"]:
            idx = text.find(p, end)
            if idx != -1 and idx < clause_end:
                clause_end = idx
        phrase = text[clause_start:clause_end].strip()
        return phrase if phrase else text[start:end]

    @classmethod
    def extract_symptoms(cls, text):
        """Extract clinical symptoms and patient complaints with negation status."""
        symptoms = []
        found_spans = []

        for sym in sorted(SYMPTOMS_LIST, key=len, reverse=True):
            pattern = make_word_pattern(sym)
            for m in re.finditer(pattern, text):
                start = m.start(1) if m.groups() and m.group(1) is not None else m.start()
                end = m.end(1) if m.groups() and m.group(1) is not None else m.end()
                if any(start >= s and end <= e for s, e in found_spans):
                    continue
                found_spans.append((start, end))

                is_neg, neg_trigger = cls.check_negation(text, start)

                symptoms.append({
                    "id": f"sym-{uuid.uuid4().hex[:6]}",
                    "symptom": sym.title(),
                    "is_negated": is_neg,
                    "negation_trigger": neg_trigger,
                    "source_phrase": cls.get_clean_source_phrase(text, start, end, neg_trigger),
                    "char_start": start,
                    "char_end": end,
                    "verification_state": "Extracted"
                })

        return symptoms

    @classmethod
    def extract_procedures(cls, text):
        """Extract first responder interventions and procedures."""
        procedures = []
        found_spans = []

        for proc in sorted(PROCEDURES_LIST, key=len, reverse=True):
            pattern = make_word_pattern(proc)
            for m in re.finditer(pattern, text):
                start = m.start(1) if m.groups() and m.group(1) is not None else m.start()
                end = m.end(1) if m.groups() and m.group(1) is not None else m.end()
                if any(start >= s and end <= e for s, e in found_spans):
                    continue
                found_spans.append((start, end))

                is_neg, neg_trigger = cls.check_negation(text, start)

                procedures.append({
                    "id": f"proc-{uuid.uuid4().hex[:6]}",
                    "procedure": proc.title(),
                    "is_negated": is_neg,
                    "negation_trigger": neg_trigger,
                    "source_phrase": cls.get_clean_source_phrase(text, start, end, neg_trigger),
                    "char_start": start,
                    "char_end": end,
                    "verification_state": "Extracted"
                })

        return procedures

    @classmethod
    def extract_examinations(cls, text):
        """
        Extract physical examination and clinical observation findings.
        Maps observations (e.g. cardiac rhythm, breath sounds, pupils, abdomen)
        into structured examination fields while marking them for explicit clinician verification.
        Never infers that a measurement is clinically normal merely because the transcript says so.
        """
        examinations = []
        exam_patterns = [
            (
                "Cardiovascular",
                "Heart Rhythm / Cardiac Examination",
                r"(?i)\b(?:heartbeat|heart rate|heart sounds|cardiac rhythm|pulse rhythm|heart rhythm)\s*(?:is|was|noted as|documented as|appears|found to be)?\s*(normal|regular|irregular|abnormal|rapid|slow|arrhythmic|weak|bounding|thready|palpable|absent)\b"
            ),
            (
                "Cardiovascular",
                "Cardiac Rhythm",
                r"(?i)\b(normal sinus rhythm|regular rate and rhythm|sinus tachycardia|sinus bradycardia|atrial fibrillation|asystole)\b"
            ),
            (
                "Respiratory",
                "Breath / Lung Sounds",
                r"(?i)\b(?:breath sounds|lung sounds|auscultation|lungs)\s*(?:are|were|noted as|documented as)?\s*(clear|clear bilaterally|wheezing|wheezes|crackles|rales|rhonchi|diminished|absent|stridor)\b"
            ),
            (
                "Neurological",
                "Pupillary Assessment",
                r"(?i)\b(?:pupils|pupillary response)\s*(?:are|were|noted as)?\s*(equal round and reactive|perrl|sluggish|fixed and dilated|pinpoint|constricted|dilated|reactive)\b"
            ),
            (
                "Abdomen",
                "Abdominal Examination",
                r"(?i)\b(?:abdomen|abdominal examination|belly)\s*(?:is|was|noted as)?\s*(soft non-tender|soft and non-tender|rigid|distended|tender|guarding|rebound)\b"
            ),
            (
                "Integumentary",
                "Skin Assessment",
                r"(?i)\b(?:skin)\s*(?:is|was|noted as)?\s*(warm and dry|pale and clammy|cool and diaphoretic|cyanotic|flushed|jaundiced|turgor normal)\b"
            )
        ]

        found_spans = []
        for system, exam_name, pat in exam_patterns:
            for m in re.finditer(pat, text):
                start, end = m.start(), m.end()
                if any(max(start, s) < min(end, e) for s, e in found_spans):
                    continue
                found_spans.append((start, end))

                finding_text = m.group(0).strip()
                val_text = m.group(1).strip() if m.groups() else finding_text

                examinations.append({
                    "id": f"exam-{uuid.uuid4().hex[:6]}",
                    "system": system,
                    "exam": exam_name,
                    "finding": finding_text,
                    "value": val_text,
                    "documented_value": val_text,
                    "source_phrase": finding_text,
                    "char_start": start,
                    "char_end": end,
                    "verification_state": "Extracted"  # Flagged for clinician verification; not assumed medically approved
                })

        return examinations

    @classmethod
    def extract_timestamps(cls, text):
        """
        Extract explicit time expressions from narrative text:
        Supports:
        - "10:05 AM IST", "10:15 AM IST", "10:25 AM IST"
        - "10:05 AM", "2:30 PM", "22:05 IST", "14:30 hrs"
        - Full date and time: "2026-10-24 10:05 AM IST", "24/10/2026 at 10:05 IST"
        - Relative elapsed times: "10 minutes ago"
        Preserves original text spans and source phrases without fabricating dates.
        """
        timestamps = []

        # Explicit Clock and Date-Time pattern
        clock_pattern = (
            r"(?ix)\b"
            r"(?:(?P<date>\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{4})\s*(?:at|,|T)?\s*)?"
            r"(?:at\s+)?"
            r"(?P<hours>[01]?[0-9]|2[0-3])"
            r":"
            r"(?P<minutes>[0-5][0-9])"
            r"(?::(?P<seconds>[0-5][0-9]))?"
            r"\s*"
            r"(?P<ampm>am|pm)?"
            r"\s*"
            r"(?P<tz>ist|utc|gmt|hrs|hours)?"
            r"\b"
        )

        for m in re.finditer(clock_pattern, text):
            hrs = int(m.group("hours"))
            mins = int(m.group("minutes"))
            ampm = (m.group("ampm") or "").lower()
            if ampm == "pm" and hrs < 12:
                hrs += 12
            elif ampm == "am" and hrs == 12:
                hrs = 0

            date_val = m.group("date")
            time_disp = f"{hrs:02d}:{mins:02d} IST"
            time_of_day = f"{hrs:02d}:{mins:02d}"

            timestamps.append({
                "id": f"time-{uuid.uuid4().hex[:6]}",
                "type": "Clock Time",
                "expression": m.group(0).strip(),
                "hours": hrs,
                "minutes": mins,
                "time_of_day": time_of_day,
                "formatted_time": time_disp,
                "timezone": "Asia/Kolkata",
                "date": date_val,
                "has_date": bool(date_val),
                "source_phrase": m.group(0).strip(),
                "char_start": m.start(),
                "char_end": m.end(),
                "verification_state": "Extracted"
            })

        # Relative elapsed time: e.g. "10 minutes ago", "onset 30 mins ago"
        rel_pattern = r"(?i)\b([0-9]{1,3})\s*(?:minutes?|mins|hours?|hrs)\s*ago\b"
        for m in re.finditer(rel_pattern, text):
            timestamps.append({
                "id": f"time-{uuid.uuid4().hex[:6]}",
                "type": "Relative Elapsed Time",
                "expression": m.group(0).strip(),
                "value": m.group(1),
                "source_phrase": m.group(0),
                "char_start": m.start(),
                "char_end": m.end(),
                "verification_state": "Extracted"
            })

        return timestamps

    @classmethod
    def _correlate_entity_timestamps(cls, entities, timestamps, text):
        """
        Associate each clinical entity with the appropriate explicit timestamp,
        respecting sentence boundaries, paragraph boundaries, and assessment blocks.
        
        Rules:
        1. Timestamps never cross unrelated paragraph boundaries (delimited by double newlines).
        2. Within a paragraph:
           - An entity in the same sentence as a timestamp is associated with that timestamp.
           - Otherwise, an entity is associated with the closest preceding timestamp within the paragraph.
        3. Observations lacking a timestamp remain explicitly timestamp: None.
        4. Date is preserved if explicit, otherwise left as None (never fabricated).
        """
        clock_times = [t for t in timestamps if t.get("type") == "Clock Time"]
        if not clock_times:
            for item in entities:
                if "timestamp" not in item:
                    item["timestamp"] = None
            return entities

        # Determine paragraph boundary spans
        para_spans = []
        last_end = 0
        for m in re.finditer(r"\n\s*\n", text):
            para_spans.append((last_end, m.start()))
            last_end = m.end()
        para_spans.append((last_end, len(text)))

        for item in entities:
            if item.get("timestamp") or (item.get("time") and str(item.get("time")).lower() in ("unknown", "n/a", "none", "encounter")):
                continue

            # If entity is not anchored in text (no char_start and no matching source phrase), keep None
            item_start = item.get("char_start")
            if item_start is None:
                sp = item.get("source_phrase")
                if sp and sp in text:
                    item_start = text.find(sp)
                else:
                    item["timestamp"] = None
                    continue

            item_end = item.get("char_end", item_start)

            # Locate enclosing paragraph
            curr_para = next((p for p in para_spans if p[0] <= item_start <= p[1]), (0, len(text)))
            p_start, p_end = curr_para

            # Collect clock timestamps within the same paragraph
            para_ts = [t for t in clock_times if p_start <= t.get("char_start", 0) <= p_end]
            if not para_ts:
                # No timestamp in this paragraph -> explicitly untimestamped
                item["timestamp"] = None
                continue

            # 1. Check if there is a timestamp within the exact same sentence
            same_sent_ts = None
            min_sent_dist = float("inf")
            for ts in para_ts:
                ts_start = ts.get("char_start", 0)
                ts_end = ts.get("char_end", 0)
                if ts_end <= item_start:
                    between = text[ts_end:item_start]
                    if not any(c in between for c in [".", "!", "?"]):
                        dist = item_start - ts_end
                        if dist < min_sent_dist:
                            min_sent_dist = dist
                            same_sent_ts = ts
                elif item_end <= ts_start:
                    between = text[item_end:ts_start]
                    if not any(c in between for c in [".", "!", "?"]):
                        dist = ts_start - item_end
                        if dist < min_sent_dist:
                            min_sent_dist = dist
                            same_sent_ts = ts

            if same_sent_ts:
                best_ts = same_sent_ts
            else:
                # 2. Check for preceding timestamp in the same paragraph (governs assessment block)
                preceding = [t for t in para_ts if t.get("char_end", 0) <= item_start]
                best_ts = max(preceding, key=lambda t: t.get("char_end", 0)) if preceding else None

            if best_ts:
                hrs = int(best_ts.get("hours", 0))
                mins = int(best_ts.get("minutes", 0))
                time_disp = f"{hrs:02d}:{mins:02d} IST"
                item["timestamp"] = time_disp
                item["time"] = time_disp
                item["time_of_day"] = f"{hrs:02d}:{mins:02d}"
                item["timezone"] = "Asia/Kolkata"
                item["timestamp_source"] = best_ts.get("source_phrase")
                item["timestamp_char_start"] = best_ts.get("char_start")
                item["timestamp_char_end"] = best_ts.get("char_end")
                item["date"] = best_ts.get("date")
                item["has_date"] = bool(best_ts.get("date"))
            else:
                item["timestamp"] = None

        return entities
