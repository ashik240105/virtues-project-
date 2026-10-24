"""
Feature: Ongoing Case Timeline and Vitals Chart Integration Tests.
Verifies:
1. 3 BP readings (10:05, 10:15, 10:25) appear in correct chronological order.
2. Systolic & diastolic values displayed as separate series.
3. Heart rate with correct "bpm" unit and numeric values.
4. Missing measurements do not produce fabricated/interpolated values.
5. Events with missing timestamps remain accessible in unspecified_time_events without fabricated ordering.
6. Reported medication administration is distinguished from clinician-confirmed administration.
7. Planned/considered medication is not displayed as administered.
8. Not-administered (withheld/denied) medication is explicitly distinguished.
9. Selecting an event displays its source transcript text, char offsets, and item ID.
10. Audio playback uses correct stored start and end offsets.
11. Missing audio or audio offsets does not break the timeline.
12. Reviewer corrections preserve original extracted values alongside corrected values.
13. Duplicate events do not appear after sync retries.
14. Chart data structure is clean and formatted for mobile rendering.
15. Full GET /api/records/<record_id>/timeline endpoint contract and regression integrity.
"""

import os
import sys
import json
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.app import create_app
from backend.database.db import init_db, create_patient, get_db_connection, log_audit_event
from backend.services.timeline_service import TimelineService, MedicationTimelineStatus
from backend.services.clinical_extractor import ClinicalExtractor

@pytest.fixture
def app_and_client(tmp_path):
    db_file = str(tmp_path / "test_timeline.db")
    app = create_app({"TESTING": True, "DATABASE": db_file})
    with app.app_context():
        init_db()
        yield app, app.test_client(), db_file

def _create_sample_record(client, record_data):
    """Helper to create a record via API."""
    res = client.post("/api/records", json=record_data)
    assert res.status_code == 201
    return res.get_json()["data"]

# ==============================================================================
# Test 1 & 2: Chronological BP readings and separate Systolic/Diastolic series
# ==============================================================================
def test_case_1_and_2_chronological_bp_and_separate_series(app_and_client):
    """
    Requirements 1 & 2:
    - 3 BP readings (10:05, 10:15, 10:25) appear in correct chronological order.
    - Plot systolic and diastolic blood pressure as separate series.
    """
    app, client, _ = app_and_client

    patient = create_patient({
        "full_name": "Eleanor Vance",
        "dob": "1980-03-12",
        "gender": "Female"
    })

    record_payload = {
        "call_number": "CAD-701",
        "responder_id": "Paramedic-John",
        "patient_id": patient["id"],
        "corrected_transcript": "At 10:15 BP 118/78. At 10:05 BP 120/80. At 10:25 BP 115/76.",
        "clinical_data": {
            "vital_signs": [
                # Deliberately inserted out of chronological order
                {"id": "bp-2", "name": "BP", "value": "118/78", "systolic": 118, "diastolic": 78, "unit": "mmHg", "time": "10:15", "source_phrase": "At 10:15 BP 118/78"},
                {"id": "bp-1", "name": "BP", "value": "120/80", "systolic": 120, "diastolic": 80, "unit": "mmHg", "time": "10:05", "source_phrase": "At 10:05 BP 120/80"},
                {"id": "bp-3", "name": "BP", "value": "115/76", "systolic": 115, "diastolic": 76, "unit": "mmHg", "time": "10:25", "source_phrase": "At 10:25 BP 115/76"}
            ]
        }
    }
    rec = _create_sample_record(client, record_payload)
    rec_id = rec["id"]

    timeline = TimelineService.build_case_timeline(rec_id)
    assert timeline is not None
    assert timeline["record_id"] == rec_id

    # Filter BP events
    bp_events = [e for e in timeline["events"] if e.get("subtype") == "BLOOD_PRESSURE"]
    assert len(bp_events) == 3

    # Check strictly chronological ordering: 10:05 -> 10:15 -> 10:25
    timestamps = [e["timestamp_display"] for e in bp_events]
    assert [t.replace(" IST", "") for t in timestamps] == ["10:05", "10:15", "10:25"]

    values = [e["value"] for e in bp_events]
    assert values == ["120/80", "118/78", "115/76"]

    # Check separate chart series
    systolic_series = timeline["chart_series"]["systolic"]
    diastolic_series = timeline["chart_series"]["diastolic"]

    assert len(systolic_series) == 3
    assert len(diastolic_series) == 3

    # Systolic values
    assert [p["value"] for p in systolic_series] == [120, 118, 115]
    assert [p["time"].replace(" IST", "") for p in systolic_series] == ["10:05", "10:15", "10:25"]

    # Diastolic values
    assert [p["value"] for p in diastolic_series] == [80, 78, 76]
    assert [p["time"].replace(" IST", "") for p in diastolic_series] == ["10:05", "10:15", "10:25"]

# ==============================================================================
# Test 3: Heart rate with correct units and series
# ==============================================================================
def test_case_3_heart_rate_correct_units_and_series(app_and_client):
    """
    Requirement 3:
    - Display heart rate using appropriate units ('bpm') and values.
    """
    app, client, _ = app_and_client

    record_payload = {
        "call_number": "CAD-702",
        "responder_id": "Paramedic-John",
        "clinical_data": {
            "vital_signs": [
                {"id": "hr-1", "name": "Heart Rate", "value": "88", "unit": "bpm", "time": "10:05", "source_phrase": "pulse 88 bpm"},
                {"id": "hr-2", "name": "Heart Rate", "value": "92", "unit": "bpm", "time": "10:15", "source_phrase": "pulse 92 bpm"},
                {"id": "hr-3", "name": "Heart Rate", "value": "96", "unit": "bpm", "time": "10:25", "source_phrase": "pulse 96 bpm"}
            ]
        }
    }
    rec = _create_sample_record(client, record_payload)
    timeline = TimelineService.build_case_timeline(rec["id"])

    hr_series = timeline["chart_series"]["heart_rate"]
    assert len(hr_series) == 3
    assert [p["value"] for p in hr_series] == [88, 92, 96]
    assert all(p["unit"] == "bpm" for p in hr_series)

# ==============================================================================
# Test 4: Missing measurements do not fabricate values (no interpolation)
# ==============================================================================
def test_case_4_missing_measurements_no_fabrication(app_and_client):
    """
    Requirement 4:
    - Irregular measurement intervals and missing values handled correctly.
    - Missing measurements must NOT produce fabricated/interpolated values.
    """
    app, client, _ = app_and_client

    record_payload = {
        "call_number": "CAD-703",
        "responder_id": "Paramedic-John",
        "clinical_data": {
            "vital_signs": [
                # SpO2 measured at 10:05 and 10:25, but missing at 10:15
                {"id": "spo2-1", "name": "SpO2", "value": "98", "unit": "%", "time": "10:05"},
                {"id": "spo2-2", "name": "SpO2", "value": "95", "unit": "%", "time": "10:25"},
                # BP measured only at 10:15
                {"id": "bp-1", "name": "BP", "value": "130/85", "systolic": 130, "diastolic": 85, "unit": "mmHg", "time": "10:15"}
            ]
        }
    }
    rec = _create_sample_record(client, record_payload)
    timeline = TimelineService.build_case_timeline(rec["id"])

    # SpO2 series has strictly 2 points; no 10:15 interpolation
    spo2_series = timeline["chart_series"]["oxygen_saturation"]
    assert len(spo2_series) == 2
    assert [p["time"] for p in spo2_series] == ["10:05", "10:25"]
    assert [p["value"] for p in spo2_series] == [98.0, 95.0]

    # Systolic series has strictly 1 point; no 10:05 or 10:25 points
    sys_series = timeline["chart_series"]["systolic"]
    assert len(sys_series) == 1
    assert sys_series[0]["time"] == "10:15"
    assert sys_series[0]["value"] == 130

# ==============================================================================
# Test 5: Events with missing timestamps remain accessible
# ==============================================================================
def test_case_5_events_with_missing_timestamps_accessible(app_and_client):
    """
    Requirement 5:
    - Events with missing or uncertain timestamps must not be discarded
      and must not have fabricated chronological positions.
    - Clearly identified in unspecified_time_events.
    """
    app, client, _ = app_and_client

    record_payload = {
        "call_number": "CAD-704",
        "responder_id": "Paramedic-John",
        "clinical_data": {
            "vital_signs": [
                {"id": "v-timed", "name": "BP", "value": "120/80", "unit": "mmHg", "time": "10:05"},
                {"id": "v-notime", "name": "GCS", "value": "15", "unit": "", "time": None}
            ],
            "medications": [
                {"id": "m-notime", "canonical_name": "Paracetamol", "dosage": "1000", "unit": "mg", "route": "Oral", "time": "Unknown"}
            ]
        }
    }
    rec = _create_sample_record(client, record_payload)
    timeline = TimelineService.build_case_timeline(rec["id"])

    assert timeline["total_event_count"] == 3
    assert timeline["timestamped_event_count"] == 1
    assert timeline["unspecified_time_event_count"] == 2

    # Unspecified time events list
    unspec = timeline["unspecified_time_events"]
    assert len(unspec) == 2
    unspec_ids = [e["item_id"] for e in unspec]
    assert "v-notime" in unspec_ids
    assert "m-notime" in unspec_ids
    assert all(e["timestamp_known"] is False for e in unspec)

# ==============================================================================
# Test 6: Reported vs Confirmed medication administration
# ==============================================================================
def test_case_6_reported_vs_confirmed_medication_status(app_and_client):
    """
    Requirement 6:
    - Distinguish ADMINISTERED_REPORTED (unverified narrative) from
      ADMINISTERED_CONFIRMED (verified by clinician).
    """
    app, client, _ = app_and_client

    record_payload = {
        "call_number": "CAD-705",
        "responder_id": "Paramedic-John",
        "clinical_data": {
            "medications": [
                {
                    "id": "med-rep",
                    "canonical_name": "Morphine",
                    "raw_mention": "morphine",
                    "dosage": "5",
                    "unit": "mg",
                    "route": "IV",
                    "time": "10:12",
                    "verification_state": "Extracted"  # Not yet verified
                },
                {
                    "id": "med-conf",
                    "canonical_name": "Aspirin",
                    "raw_mention": "aspirin",
                    "dosage": "300",
                    "unit": "mg",
                    "route": "Oral",
                    "time": "10:08",
                    "verification_state": "Verified"  # Clinician verified
                }
            ]
        }
    }
    rec = _create_sample_record(client, record_payload)
    timeline = TimelineService.build_case_timeline(rec["id"])

    med_events = {e["item_id"]: e for e in timeline["events"] if e.get("event_type") == "MEDICATION"}

    # Reported event
    rep_event = med_events["med-rep"]
    assert rep_event["medication_status"] == MedicationTimelineStatus.ADMINISTERED_REPORTED
    assert rep_event["marker_type"] == "REPORTED"
    assert rep_event["is_confirmed"] is False

    # Confirmed event
    conf_event = med_events["med-conf"]
    assert conf_event["medication_status"] == MedicationTimelineStatus.ADMINISTERED_CONFIRMED
    assert conf_event["marker_type"] == "CONFIRMED"
    assert conf_event["is_confirmed"] is True

# ==============================================================================
# Test 7: Planned medication is NOT displayed as administered
# ==============================================================================
def test_case_7_planned_medication_not_displayed_as_administered(app_and_client):
    """
    Requirement 7:
    - Planned or considered medications (e.g. 'Consider giving morphine')
      must not appear as an administered medication.
    """
    app, client, _ = app_and_client

    record_payload = {
        "call_number": "CAD-706",
        "responder_id": "Paramedic-John",
        "clinical_data": {
            "medications": [
                {
                    "id": "med-plan",
                    "canonical_name": "Morphine",
                    "raw_mention": "consider giving morphine",
                    "dosage": "2",
                    "unit": "mg",
                    "route": "IV",
                    "time": "10:14",
                    "administration_status": "PLANNED",
                    "verification_state": "Extracted"
                }
            ]
        }
    }
    rec = _create_sample_record(client, record_payload)
    timeline = TimelineService.build_case_timeline(rec["id"])

    plan_event = [e for e in timeline["events"] if e.get("item_id") == "med-plan"][0]
    assert plan_event["medication_status"] == MedicationTimelineStatus.PLANNED
    assert plan_event["status_label"] == "Planned / Considered"
    assert plan_event["marker_type"] == "PLANNED"
    assert plan_event["is_confirmed"] is False

# ==============================================================================
# Test 8: Not-administered medication represented correctly
# ==============================================================================
def test_case_8_not_administered_medication_represented_correctly(app_and_client):
    """
    Requirement 8:
    - 'Morphine was not given' must appear as a non-administration event (NOT_ADMINISTERED).
    """
    app, client, _ = app_and_client

    record_payload = {
        "call_number": "CAD-707",
        "responder_id": "Paramedic-John",
        "clinical_data": {
            "medications": [
                {
                    "id": "med-denied",
                    "canonical_name": "Morphine",
                    "raw_mention": "morphine was not given",
                    "is_negated": True,
                    "administration_status": "NOT_ADMINISTERED",
                    "time": "10:16"
                }
            ]
        }
    }
    rec = _create_sample_record(client, record_payload)
    timeline = TimelineService.build_case_timeline(rec["id"])

    denied_event = [e for e in timeline["events"] if e.get("item_id") == "med-denied"][0]
    assert denied_event["medication_status"] == MedicationTimelineStatus.NOT_ADMINISTERED
    assert denied_event["status_label"] == "Not Administered (Withheld / Denied)"
    assert denied_event["marker_type"] == "WITHHELD"

# ==============================================================================
# Test 9: Selecting an event displays source text and character spans
# ==============================================================================
def test_case_9_event_source_text_and_spans(app_and_client):
    """
    Requirement 9:
    - Every timeline event must link to original source text and transcript spans.
    """
    app, client, _ = app_and_client

    record_payload = {
        "call_number": "CAD-708",
        "responder_id": "Paramedic-John",
        "corrected_transcript": "At 10:05 blood pressure was 120/80 mmHg in the right arm.",
        "evidence_passport": [
            {
                "field_id": "bp-ev-1",
                "source_location": "blood pressure was 120/80 mmHg",
                "char_start": 9,
                "char_end": 40,
                "audio_timestamp_start": 3.2,
                "audio_timestamp_end": 6.8
            }
        ],
        "clinical_data": {
            "vital_signs": [
                {
                    "id": "bp-ev-1",
                    "name": "Blood Pressure",
                    "value": "120/80",
                    "time": "10:05",
                    "char_start": 9,
                    "char_end": 40,
                    "source_phrase": "blood pressure was 120/80 mmHg"
                }
            ]
        }
    }
    rec = _create_sample_record(client, record_payload)
    timeline = TimelineService.build_case_timeline(rec["id"])

    bp_event = [e for e in timeline["events"] if e.get("item_id") == "bp-ev-1"][0]
    assert bp_event["source_text"] == "blood pressure was 120/80 mmHg"
    assert bp_event["char_start"] == 9
    assert bp_event["char_end"] == 40
    assert bp_event["audio_timestamp_start"] == 3.2
    assert bp_event["audio_timestamp_end"] == 6.8

# ==============================================================================
# Test 10: Audio playback uses correct stored offsets
# ==============================================================================
def test_case_10_audio_playback_uses_stored_offsets(app_and_client):
    """
    Requirement 10:
    - Timeline event incorporates audio recording ID and start/end playback offsets.
    """
    app, client, _ = app_and_client

    record_payload = {
        "call_number": "CAD-709",
        "responder_id": "Paramedic-John",
        "audio_filename": "cad_709_audio.wav",
        "evidence_passport": [
            {
                "field_id": "med-audio",
                "audio_timestamp_start": 12.4,
                "audio_timestamp_end": 15.8
            }
        ],
        "clinical_data": {
            "medications": [
                {
                    "id": "med-audio",
                    "canonical_name": "Salbutamol",
                    "dosage": "5",
                    "unit": "mg",
                    "route": "Nebulised",
                    "time": "10:10"
                }
            ]
        }
    }
    rec = _create_sample_record(client, record_payload)
    timeline = TimelineService.build_case_timeline(rec["id"])

    med_event = [e for e in timeline["events"] if e.get("item_id") == "med-audio"][0]
    assert med_event["audio_recording_id"] == "cad_709_audio.wav"
    assert med_event["audio_timestamp_start"] == 12.4
    assert med_event["audio_timestamp_end"] == 15.8
    assert med_event["has_usable_audio_offsets"] is True

# ==============================================================================
# Test 11: Missing audio does not break timeline
# ==============================================================================
def test_case_11_missing_audio_does_not_break_timeline(app_and_client):
    """
    Requirement 11:
    - Missing audio recording or audio offsets must not break the timeline.
    - Gracefully set has_usable_audio_offsets to False.
    """
    app, client, _ = app_and_client

    record_payload = {
        "call_number": "CAD-710",
        "responder_id": "Paramedic-John",
        "audio_filename": None,  # No audio uploaded
        "clinical_data": {
            "vital_signs": [
                {"id": "v-no-audio", "name": "Pulse", "value": "72", "unit": "bpm", "time": "10:00"}
            ]
        }
    }
    rec = _create_sample_record(client, record_payload)
    timeline = TimelineService.build_case_timeline(rec["id"])

    assert timeline is not None
    assert timeline["audio_filename"] is None
    assert timeline["audio_url"] is None
    event = timeline["events"][0]
    assert event["audio_recording_id"] is None
    assert event["has_usable_audio_offsets"] is False

# ==============================================================================
# Test 12: Reviewer corrections preserve original extracted value
# ==============================================================================
def test_case_12_reviewer_corrections_preserve_original_value(app_and_client):
    """
    Requirement 12:
    - Preserves both original extracted value and reviewer-corrected value.
    """
    app, client, _ = app_and_client

    record_payload = {
        "call_number": "CAD-711",
        "responder_id": "Paramedic-John",
        "clinical_data": {
            "medications": [
                {
                    "id": "med-corr",
                    "canonical_name": "Aspirin",
                    "raw_mention": "aspiran",
                    "dosage": "300",
                    "unit": "mg",
                    "route": "Oral",
                    "time": "10:05",
                    "corrected_canonical_name": "Aspirin (Correction Approved)",
                    "verification_state": "Verified"
                }
            ],
            "vital_signs": [
                {
                    "id": "v-corr",
                    "name": "Blood Pressure",
                    "value": "120/80",
                    "corrected_value": "122/82",
                    "unit": "mmHg",
                    "time": "10:05"
                }
            ]
        }
    }
    rec = _create_sample_record(client, record_payload)
    timeline = TimelineService.build_case_timeline(rec["id"])

    items = {e["item_id"]: e for e in timeline["events"]}

    med = items["med-corr"]
    assert med["original_extracted_value"] == "aspiran"
    assert med["corrected_value"] == "Aspirin (Correction Approved)"

    vit = items["v-corr"]
    assert vit["original_extracted_value"] == "120/80"
    assert vit["corrected_value"] == "122/82"

# ==============================================================================
# Test 13: Duplicate events do not appear after sync retries
# ==============================================================================
def test_case_13_duplicate_events_do_not_appear_after_sync_retries(app_and_client):
    """
    Requirement 13:
    - Idempotent updates and sync retries do not produce duplicate events.
    """
    app, client, _ = app_and_client

    record_payload = {
        "call_number": "CAD-712",
        "responder_id": "Paramedic-John",
        "clinical_data": {
            "vital_signs": [
                {"id": "v-sync-1", "name": "Heart Rate", "value": "80", "unit": "bpm", "time": "10:05"}
            ]
        }
    }
    rec = _create_sample_record(client, record_payload)
    rec_id = rec["id"]

    # Initial timeline check
    t1 = TimelineService.build_case_timeline(rec_id)
    assert t1["total_event_count"] == 1

    # Simulate offline sync retry submitting the exact same record item
    sync_payload = {
        "client_items": [
            {
                "id": rec_id,
                "version": 1,
                "clinical_data": record_payload["clinical_data"]
            }
        ]
    }
    res = client.post("/api/records/sync", json=sync_payload)
    assert res.status_code == 200

    # Repeat sync again (retry)
    res2 = client.post("/api/records/sync", json=sync_payload)
    assert res2.status_code == 200

    # Timeline event count must remain exactly 1 (no duplicates)
    t2 = TimelineService.build_case_timeline(rec_id)
    assert t2["total_event_count"] == 1
    assert len(t2["events"]) == 1

# ==============================================================================
# Test 14: Chart data structure formatted for mobile view
# ==============================================================================
def test_case_14_chart_data_structure_formatted_for_mobile(app_and_client):
    """
    Requirement 14:
    - Chart data points contain numeric values, time labels, sort keys,
      and units suitable for rendering on responsive mobile views.
    """
    app, client, _ = app_and_client

    record_payload = {
        "call_number": "CAD-713",
        "responder_id": "Paramedic-John",
        "clinical_data": {
            "vital_signs": [
                {"id": "v-mob-1", "name": "BP", "value": "120/80", "time": "10:05"},
                {"id": "v-mob-2", "name": "SpO2", "value": "99", "time": "10:05"},
                {"id": "v-mob-3", "name": "Temperature", "value": "37.2", "unit": "°C", "time": "10:05"}
            ]
        }
    }
    rec = _create_sample_record(client, record_payload)
    timeline = TimelineService.build_case_timeline(rec["id"])

    series = timeline["chart_series"]
    assert "systolic" in series
    assert "diastolic" in series
    assert "oxygen_saturation" in series
    assert "temperature" in series

    # Check structure of points
    temp_pt = series["temperature"][0]
    assert temp_pt["time"] == "10:05"
    assert temp_pt["value"] == 37.2
    assert temp_pt["unit"] == "°C"
    assert "sort_key" in temp_pt
    assert "label" in temp_pt

# ==============================================================================
# Test 15: Full GET /api/records/<record_id>/timeline endpoint contract
# ==============================================================================
def test_case_15_api_endpoint_contract(app_and_client):
    """
    Requirement 15:
    - GET /api/records/<record_id>/timeline returns HTTP 200 with full
      timeline and chart payload.
    - Non-existent record returns HTTP 404.
    """
    app, client, _ = app_and_client

    # Test 404
    res_404 = client.get("/api/records/non-existent-rec-id/timeline")
    assert res_404.status_code == 404

    # Create record and test 200
    record_payload = {
        "call_number": "CAD-714",
        "responder_id": "Paramedic-John",
        "clinical_data": {
            "vital_signs": [
                {"id": "v-api-1", "name": "BP", "value": "120/80", "time": "10:05"}
            ]
        }
    }
    rec = _create_sample_record(client, record_payload)
    res_200 = client.get(f"/api/records/{rec['id']}/timeline")
    assert res_200.status_code == 200

    data = res_200.get_json()["data"]
    assert data["record_id"] == rec["id"]
    assert "events" in data
    assert "chart_series" in data
    assert "unspecified_time_events" in data
    assert data["has_chart_data"] is True
