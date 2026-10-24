"""
Unit and Integration Tests for Feature 2:
Tamil, Hindi, Spoken Number Normalization, and Multilingual Clinical NLP.
Verifies:
1. Spoken numbers: "one twenty over eighty", "five milligrams of morphine", "zero point five milligrams".
2. Negation context: "No allergies, gave morphine" vs "Morphine was not given" vs "No morphine allergy".
3. Indic language extraction: Tamil & Hindi vitals, medications, symptoms, and procedures.
4. Code-switching: Hindi-English ("ek sau bees over assi") and Tamil-English ("nootru irubadhu over enbadhu").
5. Speech recognition model checks: Reports missing regional models without claiming Tamil/Hindi STT is available.
6. Provenance & raw text preservation: Retains raw text, normalized text, and detected source language.
"""

import pytest
import os
from backend.app import create_app
from backend.database.db import init_db
from backend.services.number_normalizer import SpokenNumberNormalizer
from backend.services.clinical_extractor import ClinicalExtractor
from backend.services.transcription_service import TranscriptionService, MissingModelError

@pytest.fixture
def app_client(tmp_path):
    test_db = str(tmp_path / "test_multilingual.db")
    os.environ["FIELD_RECORD_DB_PATH"] = test_db
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        init_db()
    client = app.test_client()
    yield app, client, test_db

# -------------------------------------------------------------------------
# 1. Spoken Number Normalization Tests
# -------------------------------------------------------------------------
def test_spoken_number_blood_pressure():
    # "one twenty over eighty" -> BP 120/80
    text1 = "patient blood pressure one twenty over eighty"
    norm1 = SpokenNumberNormalizer.normalize_all(text1)
    assert "120/80" in norm1

    # Extract vitals from spoken BP
    res = ClinicalExtractor.extract_all(text1)
    bp = next((v for v in res["vital_signs"] if v["type"] == "Blood Pressure"), None)
    assert bp is not None
    assert bp["systolic"] == 120
    assert bp["diastolic"] == 80
    assert bp["value"] == "120/80"

def test_spoken_number_systolic_diastolic():
    # "blood pressure systolic one twenty diastolic eighty" -> 120/80
    text = "blood pressure systolic one twenty diastolic eighty"
    res = ClinicalExtractor.extract_all(text)
    bp = next((v for v in res["vital_signs"] if v["type"] == "Blood Pressure"), None)
    assert bp is not None
    assert bp["systolic"] == 120
    assert bp["diastolic"] == 80

def test_spoken_number_dosages():
    # "five milligrams of morphine" -> dose 5 mg
    res1 = ClinicalExtractor.extract_all("administered five milligrams of morphine IV")
    med1 = next((m for m in res1["medications"] if m["canonical_name"] == "Morphine"), None)
    assert med1 is not None
    assert med1["dosage"] == "5"
    assert med1["unit"] == "mg"
    assert med1["route"] == "IV"
    assert med1["administration_status"] == "ADMINISTERED"

    # "zero point five milligrams" -> dose 0.5 mg
    res2 = ClinicalExtractor.extract_all("gave zero point five milligrams of atropine IV")
    med2 = next((m for m in res2["medications"] if m["canonical_name"] == "Atropine"), None)
    assert med2 is not None
    assert med2["dosage"] == "0.5"
    assert med2["unit"] == "mg"

def test_spoken_number_pulse_and_vitals():
    text = "pulse seventy five respiratory rate sixteen oxygen saturation ninety eight percent"
    res = ClinicalExtractor.extract_all(text)
    hr = next((v for v in res["vital_signs"] if v["type"] == "Heart Rate"), None)
    assert hr is not None
    assert hr["value"] == "75"

    rr = next((v for v in res["vital_signs"] if v["type"] == "Respiratory Rate"), None)
    assert rr is not None
    assert rr["value"] == "16"

    spo2 = next((v for v in res["vital_signs"] if v["type"] == "Oxygen Saturation"), None)
    assert spo2 is not None
    assert spo2["value"] == "98"

# -------------------------------------------------------------------------
# 2. Context-Aware Negation & Allergy Separation Tests
# -------------------------------------------------------------------------
def test_no_allergies_gave_morphine_distinction():
    # "No allergies, gave morphine" -> allergy statement and medication administration remain separate
    text = "No allergies, gave morphine 5 mg IV"
    res = ClinicalExtractor.extract_all(text)

    # 1. Allergies array must have the general allergy denial (NKDA)
    allergies = res["allergies"]
    assert len(allergies) >= 1
    assert allergies[0]["status"] == "NO_KNOWN_ALLERGIES"

    # 2. Medications array must have morphine, NOT negated!
    meds = res["medications"]
    assert len(meds) == 1
    morphine = meds[0]
    assert morphine["canonical_name"] == "Morphine"
    assert morphine["is_negated"] is False
    assert morphine["administration_status"] == "ADMINISTERED"
    assert morphine["dosage"] == "5"
    assert morphine["unit"] == "mg"

def test_morphine_was_not_given_negation():
    # "Morphine was not given" -> medication not administered
    text = "Patient was in severe pain, but morphine was not given due to low blood pressure"
    res = ClinicalExtractor.extract_all(text)
    meds = res["medications"]
    assert len(meds) == 1
    morphine = meds[0]
    assert morphine["canonical_name"] == "Morphine"
    assert morphine["is_negated"] is True
    assert morphine["administration_status"] == "NOT_ADMINISTERED"

def test_no_morphine_allergy_isolation():
    # "No morphine allergy" -> allergy statement, NOT medication administration!
    text = "Patient confirms no morphine allergy. Vitals are stable."
    res = ClinicalExtractor.extract_all(text)

    # Allergy recorded as denied
    allergies = res["allergies"]
    assert len(allergies) >= 1
    morphine_allergy = next((a for a in allergies if "Morphine" in a.get("substance", "")), None)
    assert morphine_allergy is not None
    assert morphine_allergy["status"] == "ALLERGY_DENIED"

    # Crucially, Morphine must NOT be in the medications list as an administered or negated drug
    assert len(res["medications"]) == 0

def test_penicillin_allergy_and_morphine_administered():
    text = "Patient has severe penicillin allergy. Administered morphine 10 mg IV push."
    res = ClinicalExtractor.extract_all(text)

    # Allergy extracted
    allergies = res["allergies"]
    assert len(allergies) >= 1
    assert any("Penicillin" in a.get("substance", "") for a in allergies)

    # Medication administered
    meds = res["medications"]
    assert len(meds) == 1
    assert meds[0]["canonical_name"] == "Morphine"
    assert meds[0]["is_negated"] is False
    assert meds[0]["administration_status"] == "ADMINISTERED"

# -------------------------------------------------------------------------
# 3. Multilingual Extraction (Tamil, Hindi, Code-Switching)
# -------------------------------------------------------------------------
def test_hindi_code_switching_blood_pressure():
    # "ek sau bees over assi" -> 120/80
    text = "patient ka bp ek sau bees over assi hai"
    res = ClinicalExtractor.extract_all(text)
    bp = next((v for v in res["vital_signs"] if v["type"] == "Blood Pressure"), None)
    assert bp is not None
    assert bp["value"] == "120/80"

def test_tamil_code_switching_blood_pressure():
    # "nootru irubadhu over enbadhu" -> 120/80
    text = "patient blood pressure nootru irubadhu over enbadhu"
    res = ClinicalExtractor.extract_all(text)
    bp = next((v for v in res["vital_signs"] if v["type"] == "Blood Pressure"), None)
    assert bp is not None
    assert bp["value"] == "120/80"

def test_hindi_clinical_note_extraction():
    # Hindi note with vitals, medication, symptom, procedure
    text = "रक्तचाप 120/80, 5 mg मॉर्फिन दिया, सीना दर्द कम हुआ"
    res = ClinicalExtractor.extract_all(text)

    # Vital
    bp = next((v for v in res["vital_signs"] if v["type"] == "Blood Pressure"), None)
    assert bp is not None
    assert bp["value"] == "120/80"

    # Medication
    med = next((m for m in res["medications"] if m["canonical_name"] == "Morphine"), None)
    assert med is not None
    assert med["dosage"] == "5"
    assert med["unit"] == "mg"
    assert med["administration_status"] == "ADMINISTERED"

    # Symptom
    sym = next((s for s in res["symptoms"] if "सीना दर्द" in s["source_phrase"]), None)
    assert sym is not None

def test_tamil_clinical_note_extraction():
    # Tamil note with vitals, medication, symptom
    text = "இரத்த அழுத்தம் 120/80, 5 mg மார்பின் கொடுத்தோம், நெஞ்சு வலி உள்ளது"
    res = ClinicalExtractor.extract_all(text)

    # Vital
    bp = next((v for v in res["vital_signs"] if v["type"] == "Blood Pressure"), None)
    assert bp is not None
    assert bp["value"] == "120/80"

    # Medication
    med = next((m for m in res["medications"] if m["canonical_name"] == "Morphine"), None)
    assert med is not None
    assert med["dosage"] == "5"
    assert med["unit"] == "mg"
    assert med["administration_status"] == "ADMINISTERED"

    # Symptom
    sym = next((s for s in res["symptoms"] if "நெஞ்சு வலி" in s["source_phrase"]), None)
    assert sym is not None

def test_raw_and_normalized_provenance_preservation():
    raw = "blood pressure one twenty over eighty, five milligrams of morphine given"
    res = ClinicalExtractor.extract_all(raw)
    assert res["raw_text"] == raw
    assert "120/80" in res["normalized_text"]
    assert "5 mg" in res["normalized_text"]
    assert res["source_language"] == "en"

# -------------------------------------------------------------------------
# 4. Regional Speech Recognition Model Availability Diagnostics
# -------------------------------------------------------------------------
def test_transcription_service_language_diagnostics():
    svc = TranscriptionService.get_instance()
    langs = svc.get_available_languages()
    lang_map = {l["language"]: l for l in langs}

    # English is available with downloaded Whisper base weights
    assert lang_map["en"]["available"] is True

    # Regional Tamil and Hindi models: do not claim available until weights are locally installed
    assert lang_map["ta"]["available"] is False
    assert lang_map["ta"]["status"] == "MODEL_MISSING"
    assert "English speech recognition remains active" in lang_map["ta"]["message"]

    assert lang_map["hi"]["available"] is False
    assert lang_map["hi"]["status"] == "MODEL_MISSING"
    assert "English speech recognition remains active" in lang_map["hi"]["message"]

def test_transcription_api_regional_missing_model_rejection(app_client):
    app, client, _ = app_client

    # Query languages diagnostic endpoint
    res = client.get("/api/transcription/languages")
    assert res.status_code == 200
    data = res.get_json()["data"]
    ta_entry = next(l for l in data if l["language"] == "ta")
    assert ta_entry["available"] is False
    assert "MODEL_MISSING" in ta_entry["status"]

    # Attempting to transcribe with language='ta' without weights returns 400 with clear message
    import io
    dummy_wav = io.BytesIO(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x44\xac\x00\x00\x88\x58\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00")
    tx_res = client.post(
        "/api/transcription/transcribe",
        data={"audio": (dummy_wav, "test.wav"), "language": "ta"},
        content_type="multipart/form-data"
    )
    assert tx_res.status_code == 400
    tx_data = tx_res.get_json()
    assert tx_data["error"] == "MODEL_MISSING"
    assert "Tamil" in tx_data["message"]
    assert tx_data["english_fallback_available"] is True

