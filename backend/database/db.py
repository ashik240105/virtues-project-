"""
Database management for Field-to-Record.
Offline SQLite storage for clinical documentation, audit history, and medicine catalogue.
"""

import sqlite3
import json
import os
import uuid
from datetime import datetime, timezone

DATABASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "db"))
DATABASE_PATH = os.path.join(DATABASE_DIR, "field_to_record.db")

def get_db_path():
    return os.environ.get("FIELD_RECORD_DB_PATH", DATABASE_PATH)

def get_db_connection():
    db_path = get_db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    """Initialize database tables and seed medicine catalogue if empty."""
    db_path = get_db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = get_db_connection()
    cursor = conn.cursor()

    # Records table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id TEXT PRIMARY KEY,
            call_number TEXT,
            responder_id TEXT DEFAULT 'Paramedic-101',
            status TEXT NOT NULL DEFAULT 'Draft',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            recording_time TEXT,
            transcription_time TEXT,
            reviewed_at TEXT,
            approved_at TEXT,
            audio_filename TEXT,
            audio_mimetype TEXT,
            audio_duration_seconds REAL DEFAULT 0.0,
            machine_transcript TEXT DEFAULT '',
            corrected_transcript TEXT DEFAULT '',
            transcription_metadata TEXT DEFAULT '{}',
            clinical_data TEXT DEFAULT '{}',
            validation_warnings TEXT DEFAULT '[]',
            review_decisions TEXT DEFAULT '{}',
            patient_summary TEXT DEFAULT '{}',
            version INTEGER DEFAULT 1
        );
    """)

    # Audit logs table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id TEXT NOT NULL,
            action TEXT NOT NULL,
            actor TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            details TEXT DEFAULT '{}',
            FOREIGN KEY (record_id) REFERENCES records (id) ON DELETE CASCADE
        );
    """)

    # Medicine catalogue table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS medicine_catalogue (
            id TEXT PRIMARY KEY,
            canonical_name TEXT NOT NULL UNIQUE,
            aliases TEXT NOT NULL,
            category TEXT NOT NULL,
            standard_routes TEXT NOT NULL,
            standard_units TEXT NOT NULL,
            typical_doses TEXT NOT NULL,
            pediatric_warning INTEGER DEFAULT 0,
            contraindications_notes TEXT,
            provenance TEXT NOT NULL,
            version TEXT NOT NULL
        );
    """)

    # Indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_records_status ON records(status);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_records_created ON records(created_at);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_record_id ON audit_logs(record_id);")

    # Safe additive schema migration for records table
    cursor.execute("PRAGMA table_info(records);")
    existing_cols = {row["name"] for row in cursor.fetchall()}
    additive_cols = [
        ("patient_id", "TEXT"),
        ("event_at", "TEXT"),
        ("exported_at", "TEXT"),
        ("evidence_passport", "TEXT DEFAULT '[]'"),
        ("uncertainty_ledger", "TEXT DEFAULT '[]'"),
        ("change_impact_radar", "TEXT DEFAULT '{}'"),
        ("sync_status", "TEXT DEFAULT 'SYNCHRONIZED'"),
        ("client_updated_at", "TEXT"),
        ("device_id", "TEXT")
    ]
    for col_name, col_type in additive_cols:
        if col_name not in existing_cols:
            cursor.execute(f"ALTER TABLE records ADD COLUMN {col_name} {col_type};")

    # Additive Table: Patients (Patient Continuity Engine)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            id TEXT PRIMARY KEY,
            patient_id_display TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            dob TEXT NOT NULL,
            gender TEXT NOT NULL,
            phone TEXT DEFAULT '',
            blood_type TEXT DEFAULT 'Unknown',
            allergies TEXT DEFAULT '[]',
            medical_history TEXT DEFAULT '[]',
            emergency_contact TEXT DEFAULT '{}',
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)

    # Additive Table: Patient Encounters
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patient_encounters (
            id TEXT PRIMARY KEY,
            patient_id TEXT NOT NULL,
            record_id TEXT NOT NULL,
            encounter_type TEXT NOT NULL DEFAULT 'NEW_ENCOUNTER',
            created_at TEXT NOT NULL,
            FOREIGN KEY (patient_id) REFERENCES patients (id) ON DELETE CASCADE,
            FOREIGN KEY (record_id) REFERENCES records (id) ON DELETE CASCADE
        );
    """)

    # Additive Table: Evidence Passports
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS evidence_passports (
            id TEXT PRIMARY KEY,
            record_id TEXT NOT NULL,
            field_id TEXT NOT NULL,
            field_category TEXT NOT NULL,
            field_name TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_location TEXT,
            char_start INTEGER,
            char_end INTEGER,
            audio_timestamp_start REAL,
            audio_timestamp_end REAL,
            extracted_value TEXT,
            corrected_value TEXT,
            verification_status TEXT NOT NULL,
            reviewer_decision TEXT,
            decision_timestamp TEXT,
            reviewer_id TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (record_id) REFERENCES records (id) ON DELETE CASCADE
        );
    """)

    # Additive Table: Record Version History
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS record_versions (
            id TEXT PRIMARY KEY,
            record_id TEXT NOT NULL,
            version_number INTEGER NOT NULL,
            snapshot_json TEXT NOT NULL,
            approved_at TEXT,
            approved_by TEXT,
            amendment_reason TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (record_id) REFERENCES records (id) ON DELETE CASCADE
        );
    """)

    # Additive Table: Accuracy Evaluation Logs
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS accuracy_eval_logs (
            id TEXT PRIMARY KEY,
            test_suite_name TEXT NOT NULL,
            model_version TEXT NOT NULL,
            exact_match_accuracy REAL,
            wer_score REAL,
            precision_score REAL,
            recall_score REAL,
            f1_score REAL,
            sample_count INTEGER,
            details_json TEXT DEFAULT '{}',
            evaluated_at TEXT NOT NULL
        );
    """)

    # Additive Table: Unknown Medication Reviews (Feature 3)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS unknown_medication_reviews (
            id TEXT PRIMARY KEY,
            record_id TEXT,
            original_text TEXT NOT NULL,
            suspected_entity_name TEXT,
            char_start INTEGER,
            char_end INTEGER,
            audio_offset REAL,
            language TEXT DEFAULT 'en',
            review_status TEXT NOT NULL DEFAULT 'PENDING',
            reviewer_decision TEXT,
            corrected_canonical_name TEXT,
            reviewer_id TEXT,
            decision_timestamp TEXT,
            notes TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (record_id) REFERENCES records (id) ON DELETE CASCADE
        );
    """)

    # Additive Table: Allergy Safety Warnings & Decision Log (Feature 4)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS allergy_safety_warnings (
            id TEXT PRIMARY KEY,
            record_id TEXT NOT NULL,
            patient_id TEXT,
            warning_type TEXT NOT NULL,
            medication_name TEXT NOT NULL,
            recorded_allergy TEXT,
            allergy_source TEXT,
            severity TEXT NOT NULL,
            explanation TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            reviewer_id TEXT,
            reviewer_decision TEXT,
            decision_timestamp TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (record_id) REFERENCES records (id) ON DELETE CASCADE
        );
    """)

    # Additive Indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_patients_name ON patients(full_name);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_patients_dob ON patients(dob);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_encounters_patient_id ON patient_encounters(patient_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_encounters_record_id ON patient_encounters(record_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_evidence_record_id ON evidence_passports(record_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_versions_record_id ON record_versions(record_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_unknown_reviews_status ON unknown_medication_reviews(review_status);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_unknown_reviews_record ON unknown_medication_reviews(record_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_allergy_warnings_record ON allergy_safety_warnings(record_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_allergy_warnings_status ON allergy_safety_warnings(status);")

    conn.commit()
    seed_medicine_catalogue(conn)
    seed_patients(conn)
    conn.close()

def seed_patients(conn):
    """Seed synthetic pre-hospital patients for Patient Continuity Engine."""
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM patients;")
    if cursor.fetchone()[0] > 0:
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    synthetic_patients = [
        {
            "id": "PAT-1001",
            "patient_id_display": "MED-PAT-001",
            "full_name": "Sarah Connor",
            "dob": "1984-05-12",
            "gender": "Female",
            "phone": "+1-555-0192",
            "blood_type": "O+",
            "allergies": ["Penicillin", "Sulfa drugs"],
            "medical_history": ["Asthma", "Mild Hypertension"],
            "emergency_contact": {"name": "John Connor", "relation": "Son", "phone": "+1-555-0193"},
            "notes": "Known allergy to penicillin; severe bronchial spasms documented in 2023."
        },
        {
            "id": "PAT-1002",
            "patient_id_display": "MED-PAT-002",
            "full_name": "John Doe",
            "dob": "1975-11-23",
            "gender": "Male",
            "phone": "+1-555-0144",
            "blood_type": "A+",
            "allergies": ["Aspirin"],
            "medical_history": ["Coronary Artery Disease", "Type 2 Diabetes"],
            "emergency_contact": {"name": "Jane Doe", "relation": "Spouse", "phone": "+1-555-0145"},
            "notes": "Cardiac stent placed in 2021; takes daily anticoagulants."
        },
        {
            "id": "PAT-1003",
            "patient_id_display": "MED-PAT-003",
            "full_name": "Priya Sharma",
            "dob": "1992-08-30",
            "gender": "Female",
            "phone": "+1-555-0188",
            "blood_type": "B+",
            "allergies": ["Latex"],
            "medical_history": ["None documented"],
            "emergency_contact": {"name": "Raj Sharma", "relation": "Brother", "phone": "+1-555-0189"},
            "notes": "No chronic conditions."
        },
        {
            "id": "PAT-1004",
            "patient_id_display": "MED-PAT-004",
            "full_name": "John Doe",
            "dob": "1999-03-15",
            "gender": "Male",
            "phone": "+1-555-0177",
            "blood_type": "AB-",
            "allergies": [],
            "medical_history": ["Childhood epilepsy (resolved)"],
            "emergency_contact": {"name": "Mary Doe", "relation": "Mother", "phone": "+1-555-0178"},
            "notes": "Fictional duplicate name test case with different DOB/phone."
        }
    ]

    for p in synthetic_patients:
        cursor.execute("""
            INSERT OR REPLACE INTO patients (
                id, patient_id_display, full_name, dob, gender, phone, blood_type,
                allergies, medical_history, emergency_contact, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            p["id"],
            p["patient_id_display"],
            p["full_name"],
            p["dob"],
            p["gender"],
            p["phone"],
            p["blood_type"],
            json.dumps(p["allergies"]),
            json.dumps(p["medical_history"]),
            json.dumps(p["emergency_contact"]),
            p["notes"],
            now_iso,
            now_iso
        ))
    conn.commit()

def seed_medicine_catalogue(conn):
    """Seed verified local medicine catalogue with provenance, multilingual aliases, and ambulance formulary."""
    cursor = conn.cursor()

    # Verified EMS & First Responder Essential Medicines Catalogue (WHO Model List 2023 / EMS Formulary v1.2)
    catalog = [
        {
            "id": "MED-001",
            "canonical_name": "Paracetamol",
            "aliases": [
                "Acetaminophen", "Tylenol", "Panadol", "Calpol", "APAP", "Paramol", "Crocin", "Dolo", "Dolo 650",
                "பாராசிட்டமால்", "பேராசிட்டமால்", "காய்ச்சல் மாத்திரை",
                "पैरासिटामोल", "क्रोसीन", "डोलो", "बुखार की गोली"
            ],
            "category": "Analgesic / Antipyretic",
            "standard_routes": ["Oral", "IV", "PR"],
            "standard_units": ["mg", "g"],
            "typical_doses": ["500mg", "1000mg", "1g", "15mg/kg"],
            "pediatric_warning": 0,
            "contraindications_notes": "Severe hepatic impairment or active liver disease.",
            "provenance": "WHO Model List of Essential Medicines (23rd list, 2023) / Resuscitation Guidelines v1.2",
            "version": "1.3.0"
        },
        {
            "id": "MED-002",
            "canonical_name": "Ibuprofen",
            "aliases": [
                "Advil", "Motrin", "Nurofen", "Brufen", "Combiflam",
                "ஐபுப்ரூஃபன்", "ப்ரூஃபென்",
                "इबुप्रोफेन", "ब्रुफेन", "कॉम्बीफ्लाम"
            ],
            "category": "NSAID",
            "standard_routes": ["Oral"],
            "standard_units": ["mg"],
            "typical_doses": ["200mg", "400mg", "600mg"],
            "pediatric_warning": 0,
            "contraindications_notes": "Active GI bleeding, third-trimester pregnancy, severe renal failure.",
            "provenance": "WHO Model List of Essential Medicines (2023) / JRCALC EMS Guidelines",
            "version": "1.3.0"
        },
        {
            "id": "MED-003",
            "canonical_name": "Aspirin",
            "aliases": [
                "Acetylsalicylic Acid", "ASA", "Disprin", "Bayer", "Ecosprin",
                "ஆஸ்பிரின்", "அஸ்பிரின்", "டிஸ்ப்ரின்",
                "एस्पिरिन", "डिस्प्रिन", "इकोस्प्रिन"
            ],
            "category": "Antiplatelet / Analgesic",
            "standard_routes": ["Oral", "Chewable"],
            "standard_units": ["mg"],
            "typical_doses": ["75mg", "150mg", "300mg", "324mg"],
            "pediatric_warning": 1,
            "contraindications_notes": "Reye's syndrome risk in pediatric patients under 16; active gastrointestinal ulcer.",
            "provenance": "American Heart Association ACLS / WHO EML 2023",
            "version": "1.3.0"
        },
        {
            "id": "MED-004",
            "canonical_name": "Morphine",
            "aliases": [
                "Morphine Sulfate", "MS Contin", "Duramorph", "Roxanol",
                "மார்ஃபின்", "மார்பின்",
                "मॉर्फिन", "मॉर्फीन"
            ],
            "category": "Opioid Analgesic",
            "standard_routes": ["IV", "IM", "SC", "Oral"],
            "standard_units": ["mg"],
            "typical_doses": ["2mg", "2.5mg", "5mg", "10mg"],
            "pediatric_warning": 1,
            "contraindications_notes": "Severe respiratory depression, hypotension (systolic < 90), altered consciousness.",
            "provenance": "JRCALC Clinical Practice Guidelines / WHO EML 2023",
            "version": "1.3.0"
        },
        {
            "id": "MED-005",
            "canonical_name": "Naloxone",
            "aliases": [
                "Narcan", "Evzio",
                "நலாக்சோன்", "நார்கன்",
                "नेलोक्सोन", "नारकान"
            ],
            "category": "Opioid Antagonist",
            "standard_routes": ["IN", "IM", "IV", "SC"],
            "standard_units": ["mg", "mcg"],
            "typical_doses": ["0.4mg", "0.8mg", "2mg", "4mg"],
            "pediatric_warning": 0,
            "contraindications_notes": "Known hypersensitivity; may precipitate acute opioid withdrawal.",
            "provenance": "WHO Guidelines on Community Management of Opioid Overdose / ACLS 2023",
            "version": "1.3.0"
        },
        {
            "id": "MED-006",
            "canonical_name": "Salbutamol",
            "aliases": [
                "Albuterol", "Ventolin", "Proventil", "Accuneb", "Asthalin",
                "சல்பியூட்டமால்", "சால்புடமால்", "ஆஸ்தாலின்",
                "सालबुटामोल", "अस्थालिन"
            ],
            "category": "Short-acting Beta-2 Agonist (Bronchodilator)",
            "standard_routes": ["Inhaled", "Nebulized"],
            "standard_units": ["mg", "mcg", "puffs"],
            "typical_doses": ["2.5mg", "5mg", "2 puffs", "4 puffs", "100mcg"],
            "pediatric_warning": 0,
            "contraindications_notes": "Severe tachycardia, caution in severe cardiac disease.",
            "provenance": "British National Formulary / WHO EML 2023",
            "version": "1.3.0"
        },
        {
            "id": "MED-007",
            "canonical_name": "Nitroglycerin",
            "aliases": [
                "Glyceryl Trinitrate", "GTN", "Nitrostat", "Nitrolingual", "Nitro", "Sorbitrate",
                "நைட்ரோகிளிசரின்", "ஜிடிஎன்", "சார்பிட்ரேட்",
                "नाइट्रोग्लिसरीन", "जीटीएन", "सॉर्बिट्रेट"
            ],
            "category": "Vasodilator / Nitrate",
            "standard_routes": ["Sublingual", "Transdermal", "IV"],
            "standard_units": ["mcg", "mg", "tablets", "sprays"],
            "typical_doses": ["400mcg", "0.4mg", "1 spray", "1 tablet"],
            "pediatric_warning": 1,
            "contraindications_notes": "Hypotension (SBP < 90 mmHg), phosphodiesterase-5 inhibitor use within 24-48h.",
            "provenance": "American Heart Association ACS Guidelines / WHO EML 2023",
            "version": "1.3.0"
        },
        {
            "id": "MED-008",
            "canonical_name": "Epinephrine",
            "aliases": [
                "Adrenaline", "EpiPen", "Auvi-Q", "Adrenaclick",
                "எபினெப்ரின்", "அட்ரினலின்", "எபிபென்",
                "एपिनेफ्रीन", "एड्रेनालाईन"
            ],
            "category": "Sympathomimetic / Vasopressor / Anaphylaxis Agent",
            "standard_routes": ["IM", "IV", "IO", "SC", "Nebulized"],
            "standard_units": ["mg", "mcg", "ml"],
            "typical_doses": ["0.15mg", "0.3mg", "0.5mg", "1mg", "1:1000", "1:10000"],
            "pediatric_warning": 0,
            "contraindications_notes": "No absolute contraindications in life-threatening anaphylaxis or cardiac arrest.",
            "provenance": "ILCOR Resuscitation Guidelines / WHO EML 2023",
            "version": "1.3.0"
        },
        {
            "id": "MED-009",
            "canonical_name": "Fentanyl",
            "aliases": [
                "Sublimaze", "Actiq", "Duragesic",
                "ஃபெண்டானில்", "பெண்டானில்",
                "फेन्टानिल"
            ],
            "category": "Synthetic Opioid Analgesic",
            "standard_routes": ["IV", "IN", "IM", "IO"],
            "standard_units": ["mcg"],
            "typical_doses": ["25mcg", "50mcg", "100mcg"],
            "pediatric_warning": 1,
            "contraindications_notes": "Severe respiratory depression, MAO inhibitor use.",
            "provenance": "Prehospital Trauma Life Support (PHTLS) / JRCALC 2023",
            "version": "1.3.0"
        },
        {
            "id": "MED-010",
            "canonical_name": "Ondansetron",
            "aliases": [
                "Zofran", "Zuplenz", "Emeset", "Vomikind",
                "ஒன்டான்செட்ரான்", "எமிசெட்",
                "ओन्डान्सेट्रोन", "एमीसेट"
            ],
            "category": "Antiemetic (5-HT3 Antagonist)",
            "standard_routes": ["IV", "Oral", "IM", "ODT"],
            "standard_units": ["mg"],
            "typical_doses": ["4mg", "8mg"],
            "pediatric_warning": 0,
            "contraindications_notes": "Prolonged QT interval, concurrent apomorphine use.",
            "provenance": "WHO EML 2023 / EMS Antiemetic Protocols",
            "version": "1.3.0"
        },
        {
            "id": "MED-011",
            "canonical_name": "Midazolam",
            "aliases": [
                "Versed", "Hypnovel", "Mezolam",
                "மிடசோலாம்", "மெசோலாம்",
                "मिडाज़ोलम"
            ],
            "category": "Benzodiazepine / Anticonvulsant / Sedative",
            "standard_routes": ["IN", "IV", "IM", "Buccal"],
            "standard_units": ["mg"],
            "typical_doses": ["2.5mg", "5mg", "10mg"],
            "pediatric_warning": 1,
            "contraindications_notes": "Severe respiratory depression, acute narrow-angle glaucoma.",
            "provenance": "American Epilepsy Society / JRCALC 2023",
            "version": "1.3.0"
        },
        {
            "id": "MED-012",
            "canonical_name": "Oxygen",
            "aliases": [
                "O2", "Supplemental Oxygen",
                "ஆக்ஸிஜன்", "ஆக்சிஜன்", "பிராணவாயு",
                "ऑक्सीजन", "प्राणवायु"
            ],
            "category": "Medical Gas",
            "standard_routes": ["Inhaled", "Nasal Cannula", "Non-rebreather Mask", "BVM"],
            "standard_units": ["L/min", "%"],
            "typical_doses": ["2 L/min", "4 L/min", "10 L/min", "15 L/min"],
            "pediatric_warning": 0,
            "contraindications_notes": "Target 94-98% SpO2 in most acute conditions; 88-92% in patients at risk of hypercapnic respiratory failure (COPD).",
            "provenance": "British Thoracic Society Emergency Oxygen Guidelines / WHO EML 2023",
            "version": "1.3.0"
        },
        {
            "id": "MED-013",
            "canonical_name": "Atropine",
            "aliases": [
                "Atropine Sulfate",
                "அட்ரோபின்",
                "एट्रोपिन", "एट्रोपाइन"
            ],
            "category": "Anticholinergic / Parasympatholytic",
            "standard_routes": ["IV", "IO", "IM"],
            "standard_units": ["mg", "mcg"],
            "typical_doses": ["0.5mg", "1mg", "3mg"],
            "pediatric_warning": 1,
            "contraindications_notes": "Tachycardia, hypothermic bradycardia.",
            "provenance": "AHA ACLS Bradycardia Guidelines / WHO EML 2023",
            "version": "1.3.0"
        },
        {
            "id": "MED-014",
            "canonical_name": "Amiodarone",
            "aliases": [
                "Cordarone", "Pacerone",
                "அமியோடரோன்",
                "एमियोडेरोन"
            ],
            "category": "Antiarrhythmic (Class III)",
            "standard_routes": ["IV", "IO"],
            "standard_units": ["mg"],
            "typical_doses": ["150mg", "300mg"],
            "pediatric_warning": 1,
            "contraindications_notes": "Severe sinus node dysfunction, 2nd or 3rd degree AV block without pacemaker, cardiogenic shock.",
            "provenance": "AHA ACLS Cardiac Arrest & Tachycardia Guidelines / WHO EML 2023",
            "version": "1.3.0"
        },
        {
            "id": "MED-015",
            "canonical_name": "Glucagon",
            "aliases": [
                "GlucaGen",
                "குளூக்ககான்", "குளுக்கோகான்",
                "ग्लूकागन"
            ],
            "category": "Glucose-Elevating Agent / Pancreatic Hormone",
            "standard_routes": ["IM", "SC", "IN"],
            "standard_units": ["mg"],
            "typical_doses": ["1mg", "0.5mg"],
            "pediatric_warning": 0,
            "contraindications_notes": "Pheochromocytoma, insulinoma.",
            "provenance": "EMS Hypoglycemia Protocol / WHO EML 2023",
            "version": "1.3.0"
        },
        {
            "id": "MED-016",
            "canonical_name": "Dextrose",
            "aliases": [
                "Glucose", "D50", "D10", "D50W", "D10W", "Oral Glucose", "Dextrose 10%", "Dextrose 50%",
                "டெக்ஸ்ட்ரோஸ்", "குளுக்கோஸ்",
                "डेक्सट्रोज", "ग्लूकोज"
            ],
            "category": "Carbohydrate / Hypoglycemia Reversal",
            "standard_routes": ["IV", "IO", "Oral"],
            "standard_units": ["g", "ml", "%"],
            "typical_doses": ["10g", "25g", "100ml", "250ml"],
            "pediatric_warning": 1,
            "contraindications_notes": "Extravasation causes tissue necrosis (D50). D10 preferred in prehospital care.",
            "provenance": "NAEMSP Prehospital Hypoglycemia Guidelines",
            "version": "1.3.0"
        },
        {
            "id": "MED-017",
            "canonical_name": "Diazepam",
            "aliases": [
                "Valium", "Calmpose", "Diastat",
                "டயஸெபம்", "டயாசிபம்",
                "डायजेपाम", "वैल्शियम"
            ],
            "category": "Benzodiazepine / Anticonvulsant",
            "standard_routes": ["IV", "IO", "PR", "IM"],
            "standard_units": ["mg"],
            "typical_doses": ["5mg", "10mg", "2.5mg"],
            "pediatric_warning": 1,
            "contraindications_notes": "Severe respiratory depression, myasthenia gravis.",
            "provenance": "WHO EML 2023 / Emergency Seizure Protocols",
            "version": "1.3.0"
        },
        {
            "id": "MED-018",
            "canonical_name": "Ketamine",
            "aliases": [
                "Ketalar", "Ketanest",
                "கீட்டமைன்", "கெட்டமைன்",
                "केटामाइन"
            ],
            "category": "Dissociative Anesthetic / Analgesic",
            "standard_routes": ["IV", "IM", "IN", "IO"],
            "standard_units": ["mg", "mg/kg"],
            "typical_doses": ["20mg", "50mg", "100mg", "1mg/kg", "2mg/kg"],
            "pediatric_warning": 1,
            "contraindications_notes": "Uncontrolled severe hypertension, conditions where elevation of blood pressure would be hazardous.",
            "provenance": "PHTLS / WHO EML 2023",
            "version": "1.3.0"
        },
        {
            "id": "MED-019",
            "canonical_name": "Tranexamic Acid",
            "aliases": [
                "TXA", "Cyklokapron", "Lysteda", "Trapic",
                "ட்ரெனெக்ஸாமிக் அமிலம்", "டிஎக்ஸ்ஏ",
                "ट्रानेक्सामिक एसिड", "टीएक्सए"
            ],
            "category": "Antifibrinolytic / Hemostatic Agent",
            "standard_routes": ["IV", "IO"],
            "standard_units": ["g", "mg"],
            "typical_doses": ["1g", "1000mg"],
            "pediatric_warning": 1,
            "contraindications_notes": "Active thromboembolic disease, subarachnoid hemorrhage, injury > 3 hours prior.",
            "provenance": "CRASH-2 Trial / JRCALC Trauma Guidelines 2023",
            "version": "1.3.0"
        },
        {
            "id": "MED-020",
            "canonical_name": "Normal Saline",
            "aliases": [
                "0.9% NaCl", "0.9% Sodium Chloride", "Saline", "IV Saline", "Physiological Saline",
                "நார்மல் சலைன்", "சலைன்",
                "नॉर्मल सलाइन", "सलाइन"
            ],
            "category": "Isotonic Crystalloid IV Fluid",
            "standard_routes": ["IV", "IO"],
            "standard_units": ["ml", "L"],
            "typical_doses": ["250ml", "500ml", "1000ml", "1L"],
            "pediatric_warning": 0,
            "contraindications_notes": "Fluid overload, severe congestive heart failure, hypernatremia.",
            "provenance": "WHO Model List 2023 / EMS Resuscitation Fluid Protocols",
            "version": "1.3.0"
        },
        {
            "id": "MED-021",
            "canonical_name": "Ringer's Lactate",
            "aliases": [
                "Lactated Ringer's", "Hartmann's Solution", "RL", "Compound Sodium Lactate",
                "ரிங்கர்ஸ் லாக்டேட்", "ஆர்எல்",
                "रिंगर्स लैक्टेट", "आरएल"
            ],
            "category": "Balanced Crystalloid IV Fluid",
            "standard_routes": ["IV", "IO"],
            "standard_units": ["ml", "L"],
            "typical_doses": ["250ml", "500ml", "1000ml", "1L"],
            "pediatric_warning": 0,
            "contraindications_notes": "Severe liver disease, co-administration with ceftriaxone or blood products through same line.",
            "provenance": "WHO Model List 2023 / Advanced Trauma Life Support (ATLS)",
            "version": "1.3.0"
        }
    ]

    for item in catalog:
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
            item["id"],
            item["canonical_name"],
            json.dumps(item["aliases"]),
            item["category"],
            json.dumps(item["standard_routes"]),
            json.dumps(item["standard_units"]),
            json.dumps(item["typical_doses"]),
            item["pediatric_warning"],
            item["contraindications_notes"],
            item["provenance"],
            item["version"]
        ))
    conn.commit()

def log_audit_event(record_id, action, actor, details=None):
    """Log an immutable audit trail entry."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO audit_logs (record_id, action, actor, timestamp, details)
            VALUES (?, ?, ?, ?, ?);
        """, (
            record_id,
            action,
            actor,
            datetime.now(timezone.utc).isoformat(),
            json.dumps(details or {})
        ))
        conn.commit()
    finally:
        conn.close()

def get_record(record_id):
    """Retrieve a single record with parsed JSON structures."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM records WHERE id = ?;", (record_id,))
        row = cursor.fetchone()
        if not row:
            return None
        rec = dict(row)
        rec["transcription_metadata"] = json.loads(rec.get("transcription_metadata") or "{}")
        rec["clinical_data"] = json.loads(rec.get("clinical_data") or "{}")
        rec["validation_warnings"] = json.loads(rec.get("validation_warnings") or "[]")
        rec["review_decisions"] = json.loads(rec.get("review_decisions") or "{}")
        rec["patient_summary"] = json.loads(rec.get("patient_summary") or "{}")
        rec["evidence_passport"] = json.loads(rec.get("evidence_passport") or "[]")
        rec["uncertainty_ledger"] = json.loads(rec.get("uncertainty_ledger") or "[]")
        rec["change_impact_radar"] = json.loads(rec.get("change_impact_radar") or "{}")

        cursor.execute("SELECT * FROM allergy_safety_warnings WHERE record_id = ? ORDER BY created_at ASC;", (record_id,))
        rec["allergy_warnings"] = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT * FROM unknown_medication_reviews WHERE record_id = ? ORDER BY created_at ASC;", (record_id,))
        rec["unknown_medication_reviews"] = [dict(r) for r in cursor.fetchall()]

        return rec
    finally:
        conn.close()

def list_records(limit=100, offset=0, status_filter=None, patient_id=None):
    """List records with summary information and optional status/patient filter."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        query_parts = []
        params = []
        if status_filter:
            query_parts.append("status = ?")
            params.append(status_filter)
        if patient_id:
            query_parts.append("patient_id = ?")
            params.append(patient_id)

        where_clause = f"WHERE {' AND '.join(query_parts)}" if query_parts else ""
        query = f"""
            SELECT id, call_number, responder_id, status, created_at, updated_at,
                   patient_id, event_at, exported_at,
                   audio_duration_seconds, machine_transcript, corrected_transcript,
                   patient_summary, version
            FROM records
            {where_clause}
            ORDER BY created_at DESC LIMIT ? OFFSET ?;
        """
        params.extend([limit, offset])
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["patient_summary"] = json.loads(d["patient_summary"] or "{}")
            result.append(d)
        return result
    finally:
        conn.close()

def get_record_audit_logs(record_id):
    """Retrieve full audit log history for a record."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, record_id, action, actor, timestamp, details
            FROM audit_logs
            WHERE record_id = ?
            ORDER BY timestamp ASC;
        """, (record_id,))
        rows = cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["details"] = json.loads(d["details"] or "{}")
            result.append(d)
        return result
    finally:
        conn.close()

# ==========================================================
# Patient Continuity Engine Database Helpers
# ==========================================================
def get_patient(patient_id):
    """Retrieve full patient profile by UUID or display ID."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM patients WHERE id = ? OR patient_id_display = ?;", (patient_id, patient_id))
        row = cursor.fetchone()
        if not row:
            return None
        return _parse_patient_row(row)
    finally:
        conn.close()

def list_patients(limit=100, offset=0, search_term=None):
    """List patients with optional search filter."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        if search_term:
            term = f"%{search_term.strip()}%"
            cursor.execute("""
                SELECT * FROM patients
                WHERE full_name LIKE ? OR patient_id_display LIKE ? OR phone LIKE ? OR dob LIKE ?
                ORDER BY full_name ASC LIMIT ? OFFSET ?;
            """, (term, term, term, term, limit, offset))
        else:
            cursor.execute("SELECT * FROM patients ORDER BY full_name ASC LIMIT ? OFFSET ?;", (limit, offset))
        rows = cursor.fetchall()
        return [_parse_patient_row(r) for r in rows]
    finally:
        conn.close()

def search_patients_multifield(name=None, dob=None, phone=None, patient_id_display=None):
    """
    Search patients using multi-field matching.
    Crucial Rule: NEVER identify a patient by name alone.
    Flags 'ambiguous' if multiple patients match name without DOB/phone confirmation.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # Direct ID match
        if patient_id_display:
            cursor.execute("SELECT * FROM patients WHERE patient_id_display = ? OR id = ?;", (patient_id_display, patient_id_display))
            rows = cursor.fetchall()
            return [_parse_patient_row(r) for r in rows], False

        # Multi-factor queries
        conditions = []
        params = []
        if name:
            clean_name = name.strip()
            conditions.append("(LOWER(full_name) = LOWER(?) OR LOWER(full_name) LIKE LOWER(?))")
            params.extend([clean_name, f"%{clean_name}%"])
        if dob:
            conditions.append("dob = ?")
            params.append(dob.strip())
        if phone:
            conditions.append("phone = ?")
            params.append(phone.strip())

        if not conditions:
            return [], False

        query = f"SELECT * FROM patients WHERE {' AND '.join(conditions)};"
        cursor.execute(query, tuple(params))
        exact_matches = [_parse_patient_row(r) for r in cursor.fetchall()]

        # Check for ambiguity: if name given without DOB and multiple patients share the name
        is_ambiguous = False
        if name and not dob and len(exact_matches) > 1:
            is_ambiguous = True

        return exact_matches, is_ambiguous
    finally:
        conn.close()

def _parse_patient_row(row):
    p = dict(row)
    p["allergies"] = json.loads(p["allergies"] or "[]")
    p["medical_history"] = json.loads(p["medical_history"] or "[]")
    p["emergency_contact"] = json.loads(p["emergency_contact"] or "{}")
    p["date_of_birth"] = p.get("dob") or ""
    return p

def create_patient(data):
    """Create a new persistent patient profile."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        now_iso = datetime.now(timezone.utc).isoformat()
        patient_id = f"PAT-{uuid.uuid4().hex[:8].upper()}"
        display_id = data.get("patient_id_display") or f"PT-{str(uuid.uuid4().int)[:5]}"

        cursor.execute("""
            INSERT INTO patients (
                id, patient_id_display, full_name, dob, gender, phone, blood_type,
                allergies, medical_history, emergency_contact, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            patient_id,
            display_id,
            data.get("full_name", "").strip(),
            (data.get("dob") or data.get("date_of_birth") or "").strip(),
            data.get("gender", "Unspecified"),
            data.get("phone", ""),
            data.get("blood_type", "Unknown"),
            json.dumps(data.get("allergies", [])),
            json.dumps(data.get("medical_history", [])),
            json.dumps(data.get("emergency_contact", {})),
            data.get("notes", ""),
            now_iso,
            now_iso
        ))
        conn.commit()
        return get_patient(patient_id)
    finally:
        conn.close()

def link_encounter(patient_id, record_id, encounter_type="NEW_ENCOUNTER"):
    """Link an encounter record to a patient history (idempotent)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        now_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute("SELECT id FROM patient_encounters WHERE patient_id = ? AND record_id = ?;", (patient_id, record_id))
        row = cursor.fetchone()
        if row:
            cursor.execute("UPDATE patient_encounters SET encounter_type = ? WHERE id = ?;", (encounter_type, row["id"]))
            conn.commit()
            return row["id"]

        enc_id = f"ENC-{uuid.uuid4().hex[:8].upper()}"
        cursor.execute("""
            INSERT OR REPLACE INTO patient_encounters (id, patient_id, record_id, encounter_type, created_at)
            VALUES (?, ?, ?, ?, ?);
        """, (enc_id, patient_id, record_id, encounter_type, now_iso))

        # Also update patient_id on the record table
        cursor.execute("UPDATE records SET patient_id = ? WHERE id = ?;", (patient_id, record_id))
        conn.commit()
        return enc_id
    finally:
        conn.close()

def get_patient_encounters(patient_id):
    """Retrieve full chronological encounter history for a patient."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT pe.id as encounter_link_id, pe.encounter_type, pe.created_at as linked_at,
                   r.*
            FROM patient_encounters pe
            JOIN records r ON pe.record_id = r.id
            WHERE pe.patient_id = ?
            ORDER BY r.created_at DESC;
        """, (patient_id,))
        rows = cursor.fetchall()
        encounters = []
        for r in rows:
            d = dict(r)
            d["transcription_metadata"] = json.loads(d.get("transcription_metadata") or "{}")
            d["clinical_data"] = json.loads(d.get("clinical_data") or "{}")
            d["validation_warnings"] = json.loads(d.get("validation_warnings") or "[]")
            d["review_decisions"] = json.loads(d.get("review_decisions") or "{}")
            d["patient_summary"] = json.loads(d.get("patient_summary") or "{}")
            d["record_id"] = d.get("id")
            encounters.append(d)
        return encounters
    finally:
        conn.close()

# ==========================================================
# Version History Snapshot Database Helpers
# ==========================================================
def save_record_version_snapshot(record_id, version_num, snapshot_dict, approved_by="Supervisor", amendment_reason=None):
    """Save an immutable snapshot of an approved or amended record version."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        v_id = f"VER-{record_id}-v{version_num}"
        now_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
            INSERT OR REPLACE INTO record_versions (
                id, record_id, version_number, snapshot_json, approved_at,
                approved_by, amendment_reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            v_id,
            record_id,
            version_num,
            json.dumps(snapshot_dict),
            now_iso if not amendment_reason else snapshot_dict.get("approved_at"),
            approved_by,
            amendment_reason,
            now_iso
        ))
        conn.commit()
        return v_id
    finally:
        conn.close()

def get_record_versions(record_id):
    """Retrieve list of all preserved historical versions for a record."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, record_id, version_number, approved_at, approved_by, amendment_reason, created_at
            FROM record_versions
            WHERE record_id = ?
            ORDER BY version_number ASC;
        """, (record_id,))
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_record_version_snapshot(record_id, version_num):
    """Retrieve full snapshot payload for a specific version."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM record_versions
            WHERE record_id = ? AND version_number = ?;
        """, (record_id, version_num))
        row = cursor.fetchone()
        if not row:
            return None
        res = dict(row)
        parsed_snap = json.loads(res["snapshot_json"])
        res["snapshot_json"] = parsed_snap
        res["snapshot_data"] = parsed_snap
        return res
    finally:
        conn.close()

# ==========================================================
# Accuracy Evaluation Logging Helpers
# ==========================================================
def save_accuracy_eval_log(eval_data):
    """Record an internal evaluation run."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        log_id = f"EVAL-{uuid.uuid4().hex[:8].upper()}"
        now_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
            INSERT INTO accuracy_eval_logs (
                id, test_suite_name, model_version, exact_match_accuracy,
                wer_score, precision_score, recall_score, f1_score,
                sample_count, details_json, evaluated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            log_id,
            eval_data.get("test_suite_name", "Clinical Benchmark v1"),
            eval_data.get("model_version", "faster-whisper-base"),
            eval_data.get("exact_match_accuracy", 0.0),
            eval_data.get("wer_score", 0.0),
            eval_data.get("precision_score", 0.0),
            eval_data.get("recall_score", 0.0),
            eval_data.get("f1_score", 0.0),
            eval_data.get("sample_count", 0),
            json.dumps(eval_data.get("details", {})),
            now_iso
        ))
        conn.commit()
        return log_id
    finally:
        conn.close()

def get_latest_accuracy_eval_logs(limit=20):
    """Fetch latest internal benchmark evaluation runs."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM accuracy_eval_logs ORDER BY evaluated_at DESC LIMIT ?;", (limit,))
        rows = cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["details_json"] = json.loads(d["details_json"] or "{}")
            results.append(d)
        return results
    finally:
        conn.close()
