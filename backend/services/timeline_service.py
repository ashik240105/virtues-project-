"""
Case Timeline and Vitals Chart Service.
Provides chronological aggregation of vital signs, medication events, procedures,
and review milestones with source evidence linking, audio segment alignment, and chart data series.

Safety & Clinical Integrity Rules:
- Preserves original extracted values and normalized values separately.
- Never interpolates or fabricates missing clinical values or timestamps.
- Explicitly separates events with known timestamps from events with unspecified/uncertain timestamps.
- Distinguishes reported medication administration from reviewer-confirmed administration,
  as well as withheld/not-administered and planned events.
- Binds each event to transcript character spans and audio start/end offsets where available.
"""

import os
import sys
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

KOLKATA_TZ = ZoneInfo("Asia/Kolkata")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.database.db import get_record, get_record_audit_logs

class MedicationTimelineStatus:
    ADMINISTERED_CONFIRMED = "ADMINISTERED_CONFIRMED"
    ADMINISTERED_REPORTED = "ADMINISTERED_REPORTED"
    NOT_ADMINISTERED = "NOT_ADMINISTERED"
    PLANNED = "PLANNED"
    UNCERTAIN = "UNCERTAIN"
    UNKNOWN = "UNKNOWN"

class TimelineService:

    @classmethod
    def _parse_time_sort_key(cls, ts_str):
        """
        Convert time string to a numeric sort key (seconds) and normalized IST display time.
        Supports:
        - "HH:MM IST", "HH:MM AM/PM IST", "HH:MM", "22:05 IST"
        - ISO strings (e.g. "2026-10-24T10:15:00Z") -> converted to Asia/Kolkata (+05:30)
        Returns (sort_key, normalized_display_time). If invalid/none, returns (None, None).
        """
        if not ts_str or not isinstance(ts_str, str):
            return None, None

        clean_ts = ts_str.strip()
        if not clean_ts or clean_ts.lower() in ("n/a", "unknown", "encounter", "unspecified time", "none"):
            return None, None

        # Check clock time pattern: HH:MM or H:MM with optional am/pm and optional timezone
        clock_match = re.search(
            r"\b([01]?[0-9]|2[0-3]):([0-5][0-9])(?::([0-5][0-9]))?\s*(am|pm)?\s*(ist|utc|gmt)?\b",
            clean_ts,
            re.IGNORECASE
        )
        if clock_match:
            hrs = int(clock_match.group(1))
            mins = int(clock_match.group(2))
            ampm = (clock_match.group(4) or "").lower()
            if ampm == "pm" and hrs < 12:
                hrs += 12
            elif ampm == "am" and hrs == 12:
                hrs = 0
            sort_sec = hrs * 3600 + mins * 60

            # If input explicitly has IST, format with IST,
            # otherwise retain clean 24h clock "HH:MM"
            has_tz = bool(clock_match.group(5)) or "ist" in clean_ts.lower()
            if has_tz:
                disp = f"{hrs:02d}:{mins:02d} IST"
            else:
                disp = f"{hrs:02d}:{mins:02d}"
            return sort_sec, disp

        # Check ISO timestamp
        try:
            iso_clean = clean_ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso_clean)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt_kolkata = dt.astimezone(KOLKATA_TZ)
            sort_sec = dt_kolkata.hour * 3600 + dt_kolkata.minute * 60
            disp = dt_kolkata.strftime("%H:%M IST")
            return sort_sec, disp
        except Exception:
            return None, clean_ts

    @classmethod
    def build_case_timeline(cls, record_id):
        """
        Aggregate, validate, and structure chronological timeline events and vital-sign series
        for an emergency incident encounter.
        """
        rec = get_record(record_id)
        if not rec:
            return None

        clinical_data = rec.get("clinical_data") or {}
        transcript = rec.get("corrected_transcript") or rec.get("machine_transcript") or ""
        vitals = clinical_data.get("vital_signs") or []
        meds = clinical_data.get("medications") or []
        procs = clinical_data.get("procedures") or []

        # Fallback correlation: If observations exist but lack timestamps,
        # correlate with narrative clock expressions so previously saved cases display correctly.
        if transcript and any((v.get("timestamp") is None and v.get("time") is None) for v in vitals):
            from backend.services.clinical_extractor import ClinicalExtractor
            ts_list = ClinicalExtractor.extract_timestamps(transcript)
            if ts_list:
                vitals = ClinicalExtractor._correlate_entity_timestamps(vitals, ts_list, transcript)
                meds = ClinicalExtractor._correlate_entity_timestamps(meds, ts_list, transcript)
                procs = ClinicalExtractor._correlate_entity_timestamps(procs, ts_list, transcript)
                clinical_data["vital_signs"] = vitals
                clinical_data["medications"] = meds
                clinical_data["procedures"] = procs

        audit_logs = get_record_audit_logs(record_id)
        evidence_entries = rec.get("evidence_passport") or []
        if isinstance(evidence_entries, dict):
            evidence_entries = evidence_entries.get("entries", [])

        # Build evidence lookup map by field_id
        evidence_by_field = {e.get("field_id"): e for e in evidence_entries if e.get("field_id")}

        # Audio file reference
        audio_filename = rec.get("audio_filename")
        is_record_approved = (rec.get("status") == "Approved")
        review_decisions = rec.get("review_decisions") or {}

        events = []
        chart_points = {
            "systolic": [],
            "diastolic": [],
            "heart_rate": [],
            "respiratory_rate": [],
            "oxygen_saturation": [],
            "temperature": []
        }

        # -------------------------------------------------------------
        # 1. Process Vital Signs Observations
        # -------------------------------------------------------------
        for v in clinical_data.get("vital_signs", []):
            v_id = v.get("id") or f"vit-{abs(hash(str(v)))}"
            ev_info = evidence_by_field.get(v_id, {})
            v_type = v.get("type", v.get("name", "Vital Sign"))

            raw_time = v.get("timestamp") or v.get("time")
            sort_key, disp_time = cls._parse_time_sort_key(raw_time)

            char_start = v.get("char_start", ev_info.get("char_start"))
            char_end = v.get("char_end", ev_info.get("char_end"))
            audio_start = v.get("audio_timestamp_start") if v.get("audio_timestamp_start") is not None else ev_info.get("audio_timestamp_start")
            audio_end = v.get("audio_timestamp_end") if v.get("audio_timestamp_end") is not None else ev_info.get("audio_timestamp_end")

            # Review status
            v_state = v.get("verification_state", "Extracted")
            is_confirmed = (v_state == "Verified" or is_record_approved)

            # Handle Blood Pressure specifically (split into systolic & diastolic for chart)
            if v_type in ("Blood Pressure", "BP") or "systolic" in v or "/" in str(v.get("value", "")):
                sys_val = v.get("systolic")
                dia_val = v.get("diastolic")
                if (sys_val is None or dia_val is None) and "/" in str(v.get("value", "")):
                    parts = str(v.get("value")).split("/")
                    try:
                        sys_val = int(parts[0].strip())
                        dia_val = int(parts[1].strip())
                    except Exception:
                        pass

                evt = {
                    "event_id": f"EVT-{v_id}",
                    "item_id": v_id,
                    "event_type": "VITAL_SIGN",
                    "subtype": "BLOOD_PRESSURE",
                    "display_name": "Blood Pressure",
                    "value": f"{sys_val}/{dia_val}" if sys_val and dia_val else v.get("value"),
                    "systolic": sys_val,
                    "diastolic": dia_val,
                    "unit": v.get("unit", "mmHg"),
                    "timestamp": raw_time,
                    "timestamp_display": disp_time or "Unspecified Time",
                    "timestamp_sort_key": sort_key,
                    "timestamp_known": (sort_key is not None),
                    "source_text": v.get("source_phrase") or ev_info.get("source_location") or str(v.get("value")),
                    "char_start": char_start,
                    "char_end": char_end,
                    "audio_recording_id": audio_filename,
                    "audio_timestamp_start": audio_start,
                    "audio_timestamp_end": audio_end,
                    "has_usable_audio_offsets": (audio_start is not None),
                    "extraction_status": v_state,
                    "review_status": "Confirmed" if is_confirmed else "Reported",
                    "is_confirmed": is_confirmed,
                    "original_extracted_value": v.get("value"),
                    "corrected_value": v.get("corrected_value")
                }
                events.append(evt)

                # Add to chart points if timestamp is known and values are valid
                if sort_key is not None and sys_val is not None and dia_val is not None:
                    chart_points["systolic"].append({
                        "time": disp_time,
                        "sort_key": sort_key,
                        "value": sys_val,
                        "unit": "mmHg",
                        "label": f"Systolic: {sys_val} mmHg",
                        "event_id": evt["event_id"],
                        "source_text": evt["source_text"]
                    })
                    chart_points["diastolic"].append({
                        "time": disp_time,
                        "sort_key": sort_key,
                        "value": dia_val,
                        "unit": "mmHg",
                        "label": f"Diastolic: {dia_val} mmHg",
                        "event_id": evt["event_id"],
                        "source_text": evt["source_text"]
                    })

            # Handle Heart Rate / Pulse
            elif v_type in ("Heart Rate", "Pulse", "Heart Rate / Pulse") or "bpm" in str(v.get("unit", "")).lower():
                try:
                    hr_num = float(v.get("value"))
                except Exception:
                    hr_num = None

                evt = {
                    "event_id": f"EVT-{v_id}",
                    "item_id": v_id,
                    "event_type": "VITAL_SIGN",
                    "subtype": "HEART_RATE",
                    "display_name": "Heart Rate",
                    "value": v.get("value"),
                    "numeric_value": hr_num,
                    "unit": v.get("unit", "bpm"),
                    "timestamp": raw_time,
                    "timestamp_display": disp_time or "Unspecified Time",
                    "timestamp_sort_key": sort_key,
                    "timestamp_known": (sort_key is not None),
                    "source_text": v.get("source_phrase") or ev_info.get("source_location") or str(v.get("value")),
                    "char_start": char_start,
                    "char_end": char_end,
                    "audio_recording_id": audio_filename,
                    "audio_timestamp_start": audio_start,
                    "audio_timestamp_end": audio_end,
                    "has_usable_audio_offsets": (audio_start is not None),
                    "extraction_status": v_state,
                    "review_status": "Confirmed" if is_confirmed else "Reported",
                    "is_confirmed": is_confirmed,
                    "original_extracted_value": v.get("value"),
                    "corrected_value": v.get("corrected_value")
                }
                events.append(evt)

                if sort_key is not None and hr_num is not None:
                    chart_points["heart_rate"].append({
                        "time": disp_time,
                        "sort_key": sort_key,
                        "value": hr_num,
                        "unit": "bpm",
                        "label": f"Heart Rate: {hr_num} bpm",
                        "event_id": evt["event_id"],
                        "source_text": evt["source_text"]
                    })

            # Handle Respiratory Rate
            elif v_type in ("Respiratory Rate", "RR") or "breaths" in str(v.get("unit", "")).lower():
                try:
                    rr_num = float(v.get("value"))
                except Exception:
                    rr_num = None

                evt = {
                    "event_id": f"EVT-{v_id}",
                    "item_id": v_id,
                    "event_type": "VITAL_SIGN",
                    "subtype": "RESPIRATORY_RATE",
                    "display_name": "Respiratory Rate",
                    "value": v.get("value"),
                    "numeric_value": rr_num,
                    "unit": v.get("unit", "breaths/min"),
                    "timestamp": raw_time,
                    "timestamp_display": disp_time or "Unspecified Time",
                    "timestamp_sort_key": sort_key,
                    "timestamp_known": (sort_key is not None),
                    "source_text": v.get("source_phrase") or ev_info.get("source_location") or str(v.get("value")),
                    "char_start": char_start,
                    "char_end": char_end,
                    "audio_recording_id": audio_filename,
                    "audio_timestamp_start": audio_start,
                    "audio_timestamp_end": audio_end,
                    "has_usable_audio_offsets": (audio_start is not None),
                    "extraction_status": v_state,
                    "review_status": "Confirmed" if is_confirmed else "Reported",
                    "is_confirmed": is_confirmed,
                    "original_extracted_value": v.get("value"),
                    "corrected_value": v.get("corrected_value")
                }
                events.append(evt)

                if sort_key is not None and rr_num is not None:
                    chart_points["respiratory_rate"].append({
                        "time": disp_time,
                        "sort_key": sort_key,
                        "value": rr_num,
                        "unit": "breaths/min",
                        "label": f"Resp Rate: {rr_num} bpm",
                        "event_id": evt["event_id"],
                        "source_text": evt["source_text"]
                    })

            # Handle Oxygen Saturation (SpO2)
            elif v_type in ("SpO2", "Oxygen Saturation") or "%" in str(v.get("unit", "")):
                try:
                    spo2_num = float(v.get("value"))
                except Exception:
                    spo2_num = None

                evt = {
                    "event_id": f"EVT-{v_id}",
                    "item_id": v_id,
                    "event_type": "VITAL_SIGN",
                    "subtype": "OXYGEN_SATURATION",
                    "display_name": "SpO2 (Oxygen Saturation)",
                    "value": v.get("value"),
                    "numeric_value": spo2_num,
                    "unit": "%",
                    "timestamp": raw_time,
                    "timestamp_display": disp_time or "Unspecified Time",
                    "timestamp_sort_key": sort_key,
                    "timestamp_known": (sort_key is not None),
                    "source_text": v.get("source_phrase") or ev_info.get("source_location") or str(v.get("value")),
                    "char_start": char_start,
                    "char_end": char_end,
                    "audio_recording_id": audio_filename,
                    "audio_timestamp_start": audio_start,
                    "audio_timestamp_end": audio_end,
                    "has_usable_audio_offsets": (audio_start is not None),
                    "extraction_status": v_state,
                    "review_status": "Confirmed" if is_confirmed else "Reported",
                    "is_confirmed": is_confirmed,
                    "original_extracted_value": v.get("value"),
                    "corrected_value": v.get("corrected_value")
                }
                events.append(evt)

                if sort_key is not None and spo2_num is not None:
                    chart_points["oxygen_saturation"].append({
                        "time": disp_time,
                        "sort_key": sort_key,
                        "value": spo2_num,
                        "unit": "%",
                        "label": f"SpO2: {spo2_num}%",
                        "event_id": evt["event_id"],
                        "source_text": evt["source_text"]
                    })

            # Handle Temperature
            elif v_type in ("Temperature", "Body Temperature") or any(u in str(v.get("unit", "")).lower() for u in ("°c", "°f", "c", "f")):
                try:
                    temp_num = float(v.get("value"))
                except Exception:
                    temp_num = None

                evt = {
                    "event_id": f"EVT-{v_id}",
                    "item_id": v_id,
                    "event_type": "VITAL_SIGN",
                    "subtype": "TEMPERATURE",
                    "display_name": "Body Temperature",
                    "value": v.get("value"),
                    "numeric_value": temp_num,
                    "unit": v.get("unit", "°C"),
                    "timestamp": raw_time,
                    "timestamp_display": disp_time or "Unspecified Time",
                    "timestamp_sort_key": sort_key,
                    "timestamp_known": (sort_key is not None),
                    "source_text": v.get("source_phrase") or ev_info.get("source_location") or str(v.get("value")),
                    "char_start": char_start,
                    "char_end": char_end,
                    "audio_recording_id": audio_filename,
                    "audio_timestamp_start": audio_start,
                    "audio_timestamp_end": audio_end,
                    "has_usable_audio_offsets": (audio_start is not None),
                    "extraction_status": v_state,
                    "review_status": "Confirmed" if is_confirmed else "Reported",
                    "is_confirmed": is_confirmed,
                    "original_extracted_value": v.get("value"),
                    "corrected_value": v.get("corrected_value")
                }
                events.append(evt)

                if sort_key is not None and temp_num is not None:
                    chart_points["temperature"].append({
                        "time": disp_time,
                        "sort_key": sort_key,
                        "value": temp_num,
                        "unit": v.get("unit", "°C"),
                        "label": f"Temp: {temp_num} {v.get('unit', '°C')}",
                        "event_id": evt["event_id"],
                        "source_text": evt["source_text"]
                    })

            # Other vital sign (GCS, BGL, etc.)
            else:
                events.append({
                    "event_id": f"EVT-{v_id}",
                    "item_id": v_id,
                    "event_type": "VITAL_SIGN",
                    "subtype": v_type.upper().replace(" ", "_"),
                    "display_name": v.get("name", v_type),
                    "value": v.get("value"),
                    "unit": v.get("unit", ""),
                    "timestamp": raw_time,
                    "timestamp_display": disp_time or "Unspecified Time",
                    "timestamp_sort_key": sort_key,
                    "timestamp_known": (sort_key is not None),
                    "source_text": v.get("source_phrase") or ev_info.get("source_location") or str(v.get("value")),
                    "char_start": char_start,
                    "char_end": char_end,
                    "audio_recording_id": audio_filename,
                    "audio_timestamp_start": audio_start,
                    "audio_timestamp_end": audio_end,
                    "has_usable_audio_offsets": (audio_start is not None),
                    "extraction_status": v_state,
                    "review_status": "Confirmed" if is_confirmed else "Reported",
                    "is_confirmed": is_confirmed,
                    "original_extracted_value": v.get("value"),
                    "corrected_value": v.get("corrected_value")
                })

        # -------------------------------------------------------------
        # 2. Process Medication Events (Feature C)
        # -------------------------------------------------------------
        for m in clinical_data.get("medications", []):
            m_id = m.get("id") or f"med-{abs(hash(str(m)))}"
            ev_info = evidence_by_field.get(m_id, {})
            m_name = m.get("canonical_name") or m.get("raw_mention", "Medication")

            raw_time = m.get("administration_time") or m.get("timestamp") or m.get("time")
            sort_key, disp_time = cls._parse_time_sort_key(raw_time)

            is_negated = m.get("is_negated", False)
            raw_admin = m.get("administration_status", "ADMINISTERED" if not is_negated else "NOT_ADMINISTERED")
            v_state = m.get("verification_state", "Extracted")
            is_verified = (v_state == "Verified" or is_record_approved)

            # Distinguish statuses explicitly (Feature C):
            if is_negated or raw_admin == "NOT_ADMINISTERED":
                med_status = MedicationTimelineStatus.NOT_ADMINISTERED
                status_label = "Not Administered (Withheld / Denied)"
                marker_type = "WITHHELD"
            elif raw_admin == "PLANNED":
                med_status = MedicationTimelineStatus.PLANNED
                status_label = "Planned / Considered"
                marker_type = "PLANNED"
            elif v_state == "Uncertain" or raw_admin == "UNCERTAIN":
                med_status = MedicationTimelineStatus.UNCERTAIN
                status_label = "Uncertain Administration"
                marker_type = "UNCERTAIN"
            elif is_verified:
                med_status = MedicationTimelineStatus.ADMINISTERED_CONFIRMED
                status_label = "Administered (Confirmed by Clinician)"
                marker_type = "CONFIRMED"
            else:
                med_status = MedicationTimelineStatus.ADMINISTERED_REPORTED
                status_label = "Administered (Reported in Narrative)"
                marker_type = "REPORTED"

            char_start = m.get("char_start", ev_info.get("char_start"))
            char_end = m.get("char_end", ev_info.get("char_end"))
            audio_start = m.get("audio_timestamp_start") if m.get("audio_timestamp_start") is not None else ev_info.get("audio_timestamp_start")
            audio_end = m.get("audio_timestamp_end") if m.get("audio_timestamp_end") is not None else ev_info.get("audio_timestamp_end")

            dose_str = f"{m.get('dosage') or 'Unspecified'} {m.get('unit') or ''}".strip()
            route_str = m.get("route") or "Unspecified route"

            events.append({
                "event_id": f"EVT-{m_id}",
                "item_id": m_id,
                "event_type": "MEDICATION",
                "subtype": "MEDICATION_EVENT",
                "display_name": m_name,
                "medication_name": m_name,
                "raw_mention": m.get("raw_mention", ""),
                "value": f"{dose_str} via {route_str}",
                "dose": m.get("dosage"),
                "unit": m.get("unit", ""),
                "route": m.get("route"),
                "formatted_dosage": f"{dose_str} via {route_str}",
                "timestamp": raw_time,
                "timestamp_display": disp_time or "Unspecified Time",
                "timestamp_sort_key": sort_key,
                "timestamp_known": (sort_key is not None),
                "medication_status": med_status,
                "status_label": status_label,
                "marker_type": marker_type,
                "source_text": m.get("source_phrase") or ev_info.get("source_location") or m.get("raw_mention", ""),
                "char_start": char_start,
                "char_end": char_end,
                "audio_recording_id": audio_filename,
                "audio_timestamp_start": audio_start,
                "audio_timestamp_end": audio_end,
                "has_usable_audio_offsets": (audio_start is not None),
                "extraction_status": v_state,
                "review_status": "Confirmed" if is_verified else "Reported",
                "is_confirmed": is_verified,
                "original_extracted_value": m.get("raw_mention"),
                "corrected_value": m.get("corrected_canonical_name") or m.get("corrected_value"),
                "provenance": m.get("provenance", "Local Catalogue")
            })

        # -------------------------------------------------------------
        # 3. Process Procedures & Interventions
        # -------------------------------------------------------------
        for p in clinical_data.get("procedures", []):
            p_id = p.get("id") or f"proc-{abs(hash(str(p)))}"
            ev_info = evidence_by_field.get(p_id, {})
            raw_time = p.get("timestamp") or p.get("time")
            sort_key, disp_time = cls._parse_time_sort_key(raw_time)

            proc_audio_start = p.get("audio_timestamp_start") if p.get("audio_timestamp_start") is not None else ev_info.get("audio_timestamp_start")
            proc_audio_end = p.get("audio_timestamp_end") if p.get("audio_timestamp_end") is not None else ev_info.get("audio_timestamp_end")

            events.append({
                "event_id": f"EVT-{p_id}",
                "item_id": p_id,
                "event_type": "PROCEDURE",
                "subtype": "CLINICAL_INTERVENTION",
                "display_name": p.get("procedure", "Procedure"),
                "value": "Performed",
                "unit": "",
                "timestamp": raw_time,
                "timestamp_display": disp_time or "Unspecified Time",
                "timestamp_sort_key": sort_key,
                "timestamp_known": (sort_key is not None),
                "source_text": p.get("source_phrase") or ev_info.get("source_location") or p.get("procedure", ""),
                "char_start": p.get("char_start", ev_info.get("char_start")),
                "char_end": p.get("char_end", ev_info.get("char_end")),
                "audio_recording_id": audio_filename,
                "audio_timestamp_start": proc_audio_start,
                "audio_timestamp_end": proc_audio_end,
                "has_usable_audio_offsets": (proc_audio_start is not None),
                "extraction_status": p.get("verification_state", "Extracted"),
                "review_status": "Confirmed" if is_record_approved else "Reported",
                "is_confirmed": is_record_approved,
                "original_extracted_value": p.get("procedure"),
                "corrected_value": None
            })

        # -------------------------------------------------------------
        # 4. Process Review Decisions & Milestones
        # -------------------------------------------------------------
        for log in audit_logs:
            act = log.get("action")
            if act in ("APPROVE", "AMEND", "ACKNOWLEDGE_ALLERGY_WARNING", "RESOLVE_UNKNOWN_MEDICATION"):
                log_time = log.get("timestamp")
                sort_key, disp_time = cls._parse_time_sort_key(log_time)
                events.append({
                    "event_id": f"EVT-log-{log.get('id', abs(hash(str(log))))}",
                    "item_id": str(log.get("id")),
                    "event_type": "REVIEW_EVENT",
                    "subtype": act,
                    "display_name": f"Clinician Review: {act.replace('_', ' ').title()}",
                    "value": f"By {log.get('actor', 'Clinician')}",
                    "unit": "",
                    "timestamp": log_time,
                    "timestamp_display": disp_time or "Audit Timestamp",
                    "timestamp_sort_key": sort_key,
                    "timestamp_known": (sort_key is not None),
                    "source_text": f"Audit entry: {log.get('actor')} performed {act}",
                    "char_start": None,
                    "char_end": None,
                    "audio_recording_id": None,
                    "audio_timestamp_start": None,
                    "audio_timestamp_end": None,
                    "has_usable_audio_offsets": False,
                    "extraction_status": "Verified",
                    "review_status": "Audited",
                    "is_confirmed": True,
                    "original_extracted_value": None,
                    "corrected_value": None
                })

        # -------------------------------------------------------------
        # 5. Chronological Sorting & Segregation of Unknown Times
        # -------------------------------------------------------------
        # Events with established timestamps are sorted in exact chronological order.
        # Events with missing timestamps are NEVER discarded and their order is NOT fabricated.
        timestamped_events = [e for e in events if e["timestamp_known"]]
        timestamped_events.sort(key=lambda x: x["timestamp_sort_key"])

        unspecified_time_events = [e for e in events if not e["timestamp_known"]]

        # Combined chronological sequence: ordered timestamped events first,
        # followed by explicitly marked unspecified-time events.
        ordered_timeline = timestamped_events + unspecified_time_events

        # Sort chart series points by time
        for k in chart_points:
            chart_points[k].sort(key=lambda p: p["sort_key"])

        return {
            "record_id": record_id,
            "call_number": rec.get("call_number"),
            "audio_filename": audio_filename,
            "audio_url": f"/api/audio/{audio_filename}" if audio_filename else None,
            "total_event_count": len(events),
            "timestamped_event_count": len(timestamped_events),
            "unspecified_time_event_count": len(unspecified_time_events),
            "events": ordered_timeline,
            "unspecified_time_events": unspecified_time_events,
            "chart_series": chart_points,
            "has_chart_data": any(len(pts) > 0 for pts in chart_points.values()),
            "compiled_at": datetime.now(timezone.utc).isoformat()
        }
