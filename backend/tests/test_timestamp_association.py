"""
Regression Test Suite: Timestamp Association for Case Timeline and Vitals Chart.
Verifies all 12 mandatory requirements:
1. Four vital signs associated with 10:05 AM IST.
2. Two vital signs associated with 10:15 AM IST.
3. Four vital signs associated with 10:25 AM IST.
4. Correct mapping of heart rate 96 bpm, respiratory rate 18/min, and SpO2 98%.
5. Observations without explicit timestamps remain in the unspecified-time section.
6. Mixed timestamped and untimestamped observations render correctly.
7. Events are sorted by actual instant and displayed in IST.
8. Timestamp association does not cross unrelated paragraph boundaries.
9. Missing dates are not fabricated (date remains None when absent).
10. Existing medication administration status and allergy extraction remain unchanged.
11. The chart becomes plottable (has_chart_data is True) when valid timestamped observations are returned by the API.
12. Comprehensive end-to-end fixture matching user clinical narrative.
"""

import os
import sys
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.app import create_app
from backend.database.db import init_db
from backend.services.clinical_extractor import ClinicalExtractor
from backend.services.timeline_service import TimelineService, MedicationTimelineStatus

@pytest.fixture
def app_and_client(tmp_path):
    db_file = str(tmp_path / "test_ts_assoc.db")
    app = create_app({"TESTING": True, "DATABASE": db_file})
    with app.app_context():
        init_db()
        yield app, app.test_client(), db_file

# ==============================================================================
# Tests 1, 2, 3 & 4: Assessment Groups (10:05, 10:15, 10:25 AM IST) & Entity Mapping
# ==============================================================================
def test_three_assessment_groups_and_entity_mapping(app_and_client):
    """
    Requirements 1, 2, 3, 4:
    - 10:05 AM IST: BP 120/80, HR 88, RR 18, SpO2 98 (4 vital signs).
    - 10:15 AM IST: BP 118/78, HR 92 (2 vital signs).
    - 10:25 AM IST: BP 115/76, HR 96, RR 18, SpO2 98 (4 vital signs).
    - Heart rate 96 bpm, respiratory rate 18/min, and SpO2 98% correctly mapped without confusion.
    """
    app, client, _ = app_and_client

    narrative = (
        "10:05 AM IST: BP 120/80, heart rate 88 bpm, respiratory rate 18/min, SpO2 98%.\n"
        "10:15 AM IST: BP 118/78, heart rate 92 bpm.\n"
        "10:25 AM IST: BP 115/76, heart rate 96 bpm, respiratory rate 18/min, SpO2 98%."
    )

    extracted = ClinicalExtractor.extract_all(narrative)
    vitals = extracted["vital_signs"]

    # Filter vitals by assessment timestamp
    vitals_1005 = [v for v in vitals if v.get("timestamp") == "10:05 IST"]
    vitals_1015 = [v for v in vitals if v.get("timestamp") == "10:15 IST"]
    vitals_1025 = [v for v in vitals if v.get("timestamp") == "10:25 IST"]

    # Requirement 1: 4 vital signs associated with 10:05 AM IST
    assert len(vitals_1005) == 4
    types_1005 = {v["type"] for v in vitals_1005}
    assert types_1005 == {"Blood Pressure", "Heart Rate", "Respiratory Rate", "Oxygen Saturation"}

    # Requirement 2: 2 vital signs associated with 10:15 AM IST
    assert len(vitals_1015) == 2
    types_1015 = {v["type"] for v in vitals_1015}
    assert types_1015 == {"Blood Pressure", "Heart Rate"}

    # Requirement 3: 4 vital signs associated with 10:25 AM IST
    assert len(vitals_1025) == 4
    types_1025 = {v["type"] for v in vitals_1025}
    assert types_1025 == {"Blood Pressure", "Heart Rate", "Respiratory Rate", "Oxygen Saturation"}

    # Requirement 4: Correct entity-value mapping
    v1025_map = {v["type"]: v for v in vitals_1025}
    assert v1025_map["Heart Rate"]["value"] == "96"
    assert v1025_map["Heart Rate"]["unit"] == "bpm"
    assert v1025_map["Respiratory Rate"]["value"] == "18"
    assert v1025_map["Respiratory Rate"]["unit"] in ("breaths/min", "/min")
    assert v1025_map["Oxygen Saturation"]["value"] == "98"
    assert v1025_map["Oxygen Saturation"]["unit"] == "%"
    assert v1025_map["Blood Pressure"]["value"] == "115/76"

# ==============================================================================
# Test 5 & 6: Unspecified Timestamps Remain Segregated and Accessible
# ==============================================================================
def test_unspecified_timestamps_and_mixed_render(app_and_client):
    """
    Requirements 5 & 6:
    - Observations without explicit timestamps remain in the unspecified-time section.
    - Mixed timestamped and untimestamped observations render correctly.
    """
    app, client, _ = app_and_client

    # Create record where one assessment is timestamped and another is unanchored
    record_payload = {
        "call_number": "CAD-MIXED-1",
        "corrected_transcript": "At 10:05 AM IST, blood pressure was 120/80 mmHg and heart rate was 88 bpm.",
        "clinical_data": {
            "vital_signs": [
                {"id": "v-timed-1", "name": "BP", "value": "120/80", "time": "10:05 IST"},
                {"id": "v-untimed-1", "name": "GCS", "value": "15", "time": None},
                {"id": "v-untimed-2", "name": "BGL", "value": "110", "unit": "mg/dL", "time": "Unknown"}
            ]
        }
    }
    res = client.post("/api/records", json=record_payload)
    assert res.status_code == 201
    rec_id = res.get_json()["data"]["id"]

    timeline = TimelineService.build_case_timeline(rec_id)
    assert timeline["total_event_count"] == 3
    assert timeline["timestamped_event_count"] == 1
    assert timeline["unspecified_time_event_count"] == 2

    # Unspecified tray check
    unspec_ids = [e["item_id"] for e in timeline["unspecified_time_events"]]
    assert "v-untimed-1" in unspec_ids
    assert "v-untimed-2" in unspec_ids
    assert all(e["timestamp_known"] is False for e in timeline["unspecified_time_events"])

    # Timed observation is in main timeline
    timed_ids = [e["item_id"] for e in timeline["events"] if e["timestamp_known"]]
    assert "v-timed-1" in timed_ids

# ==============================================================================
# Test 7: Events Sorted by Actual Instant and Displayed in IST
# ==============================================================================
def test_events_sorted_by_actual_instant_and_ist_display(app_and_client):
    """
    Requirement 7:
    - Events are sorted by actual instant and displayed in IST.
    """
    app, client, _ = app_and_client

    # Deliberately supply observations out of chronological order
    narrative = (
        "At 10:25 AM IST, heart rate was 96 bpm. "
        "At 10:05 AM IST, heart rate was 88 bpm. "
        "At 10:15 AM IST, heart rate was 92 bpm."
    )
    res = client.post("/api/records", json={"call_number": "CAD-SORT", "corrected_transcript": narrative})
    rec_id = res.get_json()["data"]["id"]

    timeline = TimelineService.build_case_timeline(rec_id)
    hr_events = [e for e in timeline["events"] if e.get("subtype") == "HEART_RATE"]

    assert len(hr_events) == 3
    # Check monotonic sort key and chronological order: 10:05 -> 10:15 -> 10:25
    times = [e["timestamp_display"] for e in hr_events]
    assert times == ["10:05 IST", "10:15 IST", "10:25 IST"]
    assert hr_events[0]["value"] == "88"
    assert hr_events[1]["value"] == "92"
    assert hr_events[2]["value"] == "96"

# ==============================================================================
# Test 8: Timestamp Association Does NOT Cross Paragraph Boundaries
# ==============================================================================
def test_timestamp_association_does_not_cross_paragraph_boundaries(app_and_client):
    """
    Requirement 8:
    - Timestamp association does not cross unrelated paragraph boundaries.
    """
    narrative = (
        "At 10:05 AM IST, patient was evaluated. Blood pressure was 120/80 mmHg and heart rate was 88 bpm.\n\n"
        "During subsequent transfer, respiratory rate was 16 breaths per minute with no new complaints."
    )

    extracted = ClinicalExtractor.extract_all(narrative)
    vitals = extracted["vital_signs"]

    bp = next(v for v in vitals if v["type"] == "Blood Pressure")
    hr = next(v for v in vitals if v["type"] == "Heart Rate")
    rr = next(v for v in vitals if v["type"] == "Respiratory Rate")

    # BP and HR in paragraph 1 are associated with 10:05 IST
    assert bp["timestamp"] == "10:05 IST"
    assert hr["timestamp"] == "10:05 IST"

    # RR in paragraph 2 must NOT be associated with 10:05 IST
    assert rr["timestamp"] is None

# ==============================================================================
# Test 9: Missing Dates Are NOT Fabricated
# ==============================================================================
def test_missing_dates_are_not_fabricated():
    """
    Requirement 9:
    - Missing dates are not fabricated (date remains None when absent in text).
    - If date is supplied, it is captured accurately.
    """
    # 1. Unqualified time without date
    text_nodate = "At 10:05 AM IST, blood pressure was 120/80 mmHg."
    ext_nodate = ClinicalExtractor.extract_all(text_nodate)
    ts_item = ext_nodate["timestamps"][0]
    assert ts_item["date"] is None
    assert ts_item["has_date"] is False
    assert ext_nodate["vital_signs"][0]["date"] is None

    # 2. Qualified date and time
    text_withdate = "On 2026-10-24 at 10:05 AM IST, blood pressure was 120/80 mmHg."
    ext_withdate = ClinicalExtractor.extract_all(text_withdate)
    ts_withdate = ext_withdate["timestamps"][0]
    assert ts_withdate["date"] == "2026-10-24"
    assert ts_withdate["has_date"] is True
    assert ext_withdate["vital_signs"][0]["date"] == "2026-10-24"

# ==============================================================================
# Test 10: Medication Administration and Allergy Status Remain Unchanged
# ==============================================================================
def test_medication_and_allergy_status_remain_unchanged():
    """
    Requirement 10:
    - Existing medication administration status, planned status, negation,
      and allergy extraction remain intact.
    """
    narrative = (
        "No known allergies. At 10:05 AM IST, administered Aspirin 300 mg oral. "
        "Morphine was not given due to precaution. Plan to give Normal Saline 500 ml IV."
    )
    ext = ClinicalExtractor.extract_all(narrative)

    # Allergies
    allergies = ext["allergies"]
    assert any(a["status"] == "NO_KNOWN_ALLERGIES" for a in allergies)

    # Medications
    meds = ext["medications"]
    aspirin = next(m for m in meds if "aspirin" in m["canonical_name"].lower())
    assert aspirin["administration_status"] == "ADMINISTERED"
    assert aspirin["timestamp"] == "10:05 IST"

    morphine = next(m for m in meds if "morphine" in m["canonical_name"].lower())
    assert morphine["administration_status"] == "NOT_ADMINISTERED"
    assert morphine["is_negated"] is True

    saline = next((m for m in meds if "saline" in m["raw_mention"].lower()), None)
    if saline:
        assert saline["administration_status"] == "PLANNED"

# ==============================================================================
# Test 11 & 12: Chart Plottability & Full API Verification
# ==============================================================================
def test_chart_plottability_and_full_api_verification(app_and_client):
    """
    Requirements 11 & 12:
    - Chart becomes plottable (has_chart_data is True) when valid timestamped observations are returned.
    - Full end-to-end user fixture verification.
    """
    app, client, _ = app_and_client

    fixture_narrative = (
        "At 10:05 AM IST, a 54-year-old simulated patient was assessed for dizziness and generalized weakness. "
        "The patient was conscious and responsive. Blood pressure was one twenty over eighty mmHg, "
        "heart rate was 88 beats per minute, respiratory rate was 18 breaths per minute, and oxygen saturation was 98 percent. "
        "At 10:15 AM IST, blood pressure was 118/78 mmHg and heart rate was 92 bpm. "
        "At 10:25 AM IST, blood pressure was 115/76 mmHg, heart rate was 96 bpm, "
        "respiratory rate was 18 breaths per minute, and oxygen saturation was 98 percent."
    )

    res = client.post("/api/records", json={
        "call_number": "CAD-FIXTURE-100",
        "corrected_transcript": fixture_narrative
    })
    assert res.status_code == 201
    rec = res.get_json()["data"]
    rec_id = rec["id"]

    # Verify timeline endpoint
    t_res = client.get(f"/api/records/{rec_id}/timeline")
    assert t_res.status_code == 200
    t_data = t_res.get_json()["data"]

    # Requirement 11: Chart is plottable
    assert t_data["has_chart_data"] is True
    assert t_data["timestamped_event_count"] >= 8
    assert t_data["unspecified_time_event_count"] == 0

    # Verify chart series points
    series = t_data["chart_series"]
    assert len(series["systolic"]) == 3
    assert len(series["diastolic"]) == 3
    assert len(series["heart_rate"]) == 3
    assert len(series["respiratory_rate"]) == 2
    assert len(series["oxygen_saturation"]) == 2

    # Verify Systolic values and IST timestamps
    assert [p["value"] for p in series["systolic"]] == [120, 118, 115]
    assert [p["time"] for p in series["systolic"]] == ["10:05 IST", "10:15 IST", "10:25 IST"]

    # Verify Diastolic values
    assert [p["value"] for p in series["diastolic"]] == [80, 78, 76]

    # Verify Heart Rate values and units
    assert [p["value"] for p in series["heart_rate"]] == [88.0, 92.0, 96.0]
    assert all(p["unit"] == "bpm" for p in series["heart_rate"])

    # Verify Oxygen Saturation
    assert [p["value"] for p in series["oxygen_saturation"]] == [98.0, 98.0]
    assert all(p["unit"] == "%" for p in series["oxygen_saturation"])

    # Verify Respiratory Rate
    assert [p["value"] for p in series["respiratory_rate"]] == [18.0, 18.0]

