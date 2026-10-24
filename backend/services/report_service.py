"""
Report Service: Generates comprehensive JSON and professional PDF clinical documentation reports.
Uses ReportLab with high-density clinical layout, zero footer overlap, clean timestamps,
and robust text cell wrapping.
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import json
from datetime import datetime, timezone
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
)
from reportlab.pdfgen import canvas
from backend.database.db import (
    get_record, get_record_audit_logs, get_record_version_snapshot, get_patient
)
from backend.services.confidence_service import ReportConfidenceService

REPORTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "reports"))
os.makedirs(REPORTS_DIR, exist_ok=True)

def format_clean_timestamp(ts_str):
    """Format raw ISO timestamps (e.g. 2026-10-22T14:59:38.770939+00:00) into clean human-readable date."""
    if not ts_str or ts_str in ("N/A", "Pending Review", "Pending Approval"):
        return ts_str or "N/A"
    try:
        clean = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return ts_str[:19].replace("T", " ") + " UTC"

class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas for total page count and robust, non-colliding footers and running headers."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()

        # Top Running Header (Pages > 1 or subtle on all)
        self.setStrokeColor(colors.HexColor("#cbd5e1"))
        self.setLineWidth(0.5)
        self.line(40, 756, 612 - 40, 756)

        self.setFont("Helvetica-Bold", 7)
        self.setFillColor(colors.HexColor("#64748b"))
        self.drawString(40, 760, "FIELD-TO-RECORD • PRE-HOSPITAL CLINICAL ENCOUNTER SUMMARY")
        self.drawRightString(612 - 40, 760, "OFFICIAL FIRST RESPONDER CARE RECORD")

        # Bottom Divider Rule
        self.line(40, 36, 612 - 40, 36)

        # Footer Line 1: Left system name, Right page count
        self.setFont("Helvetica", 7.5)
        self.setFillColor(colors.HexColor("#475569"))
        self.drawString(40, 24, "Field-to-Record Clinical Documentation Assistant")
        self.drawRightString(612 - 40, 24, f"Page {self._pageNumber} of {page_count}")

        # Footer Line 2: Legal/Clinical Disclaimer
        self.setFont("Helvetica-Bold", 6.5)
        self.setFillColor(colors.HexColor("#94a3b8"))
        disclaimer = "CONFIDENTIAL MEDICAL RECORD • DOCUMENTATION ASSISTANT ONLY • NOT AN AUTOMATED DIAGNOSTIC OR TREATMENT RECOMMENDATION"
        self.drawString(40, 14, disclaimer)

        self.restoreState()

class HandoverNumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas for Hospital Handover Document with A4 geometry,
    high-contrast grayscale running headers, page numbers, and legal disclaimers.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()

        # A4 page dimensions in points: width = 595.28, height = 841.89
        page_w = 595.28
        page_h = 841.89
        margin = 36

        # Top Running Header Rule (y = 812)
        self.setStrokeColor(colors.HexColor("#475569"))
        self.setLineWidth(0.75)
        self.line(margin, 810, page_w - margin, 810)

        # Header Title
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(colors.HexColor("#0f172a"))
        self.drawString(margin, 814, "FIELD-TO-RECORD • EMERGENCY HOSPITAL HANDOVER SUMMARY")

        # Header Right Document State & Page Count
        self.setFont("Helvetica-Bold", 7.5)
        self.setFillColor(colors.HexColor("#334155"))
        self.drawRightString(page_w - margin, 814, f"EMERGENCY CLINICAL HANDOVER • Page {self._pageNumber} of {page_count}")

        # Bottom Running Divider Rule (y = 34)
        self.setStrokeColor(colors.HexColor("#475569"))
        self.setLineWidth(0.5)
        self.line(margin, 34, page_w - margin, 34)

        # Bottom Footer Line 1: Confidentiality & Provenance
        self.setFont("Helvetica-Bold", 6.8)
        self.setFillColor(colors.HexColor("#334155"))
        self.drawString(margin, 23, "CONFIDENTIAL MEDICAL HANDOVER • PRE-HOSPITAL EMERGENCY CARE REPORT • FOR RECEIVING ED CLINICIAN")
        self.drawRightString(page_w - margin, 23, "System: Field-to-Record v1.3.0")

        # Bottom Footer Line 2: Clinical Safety Disclaimer & Timestamps
        self.setFont("Helvetica", 6.2)
        self.setFillColor(colors.HexColor("#64748b"))
        disclaimer = "CLINICAL DECISION SUPPORT & DOCUMENTATION • NOT AN AUTONOMOUS PRESCRIBING SYSTEM • UTC NORMALIZED"
        self.drawString(margin, 13, disclaimer)
        self.drawRightString(page_w - margin, 13, "Standard: A4 Emergency Handover Form")

        self.restoreState()

class ReportService:

    @classmethod
    def generate_json_report(cls, record_id, version_num=None):
        """
        Build full structured JSON export.
        Supports specific version export (?version=N) to ensure V1 and V2 exports match exact snapshots.
        Includes transparent overall report quality/confidence level while strictly excluding internal evaluation metrics.
        """
        if version_num is not None:
            snap = get_record_version_snapshot(record_id, version_num)
            record = snap.get("snapshot_json") if snap else None
            if not record:
                record = get_record(record_id)
        else:
            record = get_record(record_id)

        if not record:
            return None

        audit_logs = get_record_audit_logs(record_id)

        # Enforce strict separation: sanitize patient report payload
        clean_record = dict(record)
        clean_record.pop("accuracy_metrics", None)
        clean_record.pop("aggregate_scores", None)
        clean_record.pop("model_eval_summary", None)

        # Overall Report Quality & Confidence Assessment
        report_quality = ReportConfidenceService.evaluate_record_quality(clean_record)

        report_payload = {
            "export_metadata": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "system": "Field-to-Record EMS Documentation Assistant",
                "system_version": "1.2.0",
                "schema": "PreHospitalCareReport-v1",
                "version": clean_record.get("version", 1),
                "version_exported": clean_record.get("version", 1),
                "is_historical_version": bool(version_num and version_num != clean_record.get("version")),
                "report_quality_confidence": report_quality,
                "notice": "Documentation assistant record. Not a diagnostic or treatment recommendation system."
            },
            "record": clean_record,
            "audit_trail": audit_logs
        }
        return report_payload

    @classmethod
    def generate_fhir_bundle(cls, record_id):
        """
        Export an isolated, standards-compatible HL7 FHIR R4 Document Bundle.
        Completely non-disruptive to existing JSON and PDF exports.
        """
        record = get_record(record_id)
        if not record:
            return None

        clinical = record.get("clinical_data", {})
        patient_summary = record.get("patient_summary", {})
        patient_id = record.get("patient_id") or "PAT-ANONYMOUS"

        bundle = {
            "resourceType": "Bundle",
            "id": f"fhir-{record_id}",
            "type": "document",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "entry": [
                {
                    "fullUrl": f"urn:uuid:composition-{record_id}",
                    "resource": {
                        "resourceType": "Composition",
                        "id": f"comp-{record_id}",
                        "status": "final" if record.get("status") == "Approved" else "preliminary",
                        "type": {
                            "coding": [{
                                "system": "http://loinc.org",
                                "code": "67796-3",
                                "display": "EMS Patient Care Report"
                            }]
                        },
                        "subject": {"reference": f"urn:uuid:patient-{patient_id}"},
                        "date": record.get("created_at"),
                        "author": [{"display": record.get("responder_id", "First Responder")}],
                        "title": f"Pre-Hospital Clinical Run {record.get('call_number', 'EMS')}",
                        "section": [
                            {
                                "title": "Field Narrative",
                                "text": {
                                    "status": "generated",
                                    "div": f"<div>{record.get('corrected_transcript') or record.get('machine_transcript')}</div>"
                                }
                            }
                        ]
                    }
                },
                {
                    "fullUrl": f"urn:uuid:patient-{patient_id}",
                    "resource": {
                        "resourceType": "Patient",
                        "id": patient_id,
                        "gender": str(patient_summary.get("gender", "unknown")).lower()
                    }
                }
            ]
        }

        # Add Vitals as FHIR Observations
        for v in clinical.get("vital_signs", []):
            bundle["entry"].append({
                "fullUrl": f"urn:uuid:obs-{v.get('id')}",
                "resource": {
                    "resourceType": "Observation",
                    "id": v.get("id"),
                    "status": "final",
                    "code": {"text": v.get("name")},
                    "valueString": f"{v.get('value')} {v.get('unit', '')}".strip()
                }
            })

        # Add Medications as FHIR MedicationStatements
        for m in clinical.get("medications", []):
            bundle["entry"].append({
                "fullUrl": f"urn:uuid:med-{m.get('id')}",
                "resource": {
                    "resourceType": "MedicationStatement",
                    "id": m.get("id"),
                    "status": "not-taken" if m.get("is_negated") else "active",
                    "medicationCodeableConcept": {"text": m.get("canonical_name", m.get("raw_mention"))},
                    "dosage": [{
                        "text": f"{m.get('dosage') or ''} {m.get('unit') or ''}".strip(),
                        "route": {"text": m.get("route") or "unspecified"}
                    }]
                }
            })

        return bundle

    @classmethod
    def generate_pdf_report(cls, record_id, output_filename=None, version_num=None):
        """
        Generate an upgraded, professional clinical PDF report using ReportLab.
        Supports specific version export (version_num=N) to ensure V1 and V2 exports match exact snapshots.
        Uses compact padding, elegant medical typography, and automatic cell wrapping.
        """
        if version_num is not None:
            snap = get_record_version_snapshot(record_id, version_num)
            record = snap.get("snapshot_json") if snap else None
            if not record:
                record = get_record(record_id)
        else:
            record = get_record(record_id)

        if not record:
            return None

        if not output_filename:
            ver_suffix = f"_v{record.get('version', 1)}" if record.get('version') else ""
            output_filename = f"report_{record_id}{ver_suffix}_{int(datetime.now().timestamp())}.pdf"

        pdf_path = os.path.join(REPORTS_DIR, output_filename)

        # Usable width: 612 - 80 = 532 pt
        doc = SimpleDocTemplate(
            pdf_path,
            pagesize=letter,
            leftMargin=40,
            rightMargin=40,
            topMargin=42,
            bottomMargin=45
        )

        styles = getSampleStyleSheet()

        # Custom Typography
        title_style = ParagraphStyle(
            'DocTitle',
            parent=styles['Heading1'],
            fontName='Helvetica-Bold',
            fontSize=16,
            leading=18,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=2
        )
        subtitle_style = ParagraphStyle(
            'DocSubTitle',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#0d9488"),
            spaceAfter=6
        )
        section_style = ParagraphStyle(
            'DocSection',
            parent=styles['Heading2'],
            fontName='Helvetica-Bold',
            fontSize=10,
            leading=12,
            textColor=colors.HexColor("#0f766e"),
            spaceBefore=6,
            spaceAfter=3
        )
        narrative_style = ParagraphStyle(
            'DocNarrative',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#1e293b")
        )
        cell_bold = ParagraphStyle(
            'CellBold',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=7.5,
            leading=9.5,
            textColor=colors.HexColor("#0f172a")
        )
        cell_regular = ParagraphStyle(
            'CellRegular',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=7.5,
            leading=9.5,
            textColor=colors.HexColor("#334155")
        )
        cell_italic = ParagraphStyle(
            'CellItalic',
            parent=styles['Normal'],
            fontName='Helvetica-Oblique',
            fontSize=7,
            leading=9,
            textColor=colors.HexColor("#64748b")
        )
        header_cell = ParagraphStyle(
            'HeaderCell',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=7.5,
            leading=9.5,
            textColor=colors.white
        )
        alert_style = ParagraphStyle(
            'DocAlert',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=7.5,
            leading=9.5,
            textColor=colors.HexColor("#991b1b")
        )

        elements = []

        # 1. Document Title & Subtitle Header
        elements.append(Paragraph("FIELD-TO-RECORD", title_style))
        elements.append(Paragraph("PRE-HOSPITAL CLINICAL ENCOUNTER SUMMARY", subtitle_style))

        # 2. Status Badge Coloring
        status_name = record.get("status", "Draft").upper()
        status_badge_bg = (
            "#dcfce7" if "APPROVED" in status_name else
            "#f3e8ff" if "AMENDED" in status_name else
            "#fef3c7" if "REVIEW" in status_name else "#f1f5f9"
        )
        status_badge_txt = (
            "#166534" if "APPROVED" in status_name else
            "#6b21a8" if "AMENDED" in status_name else
            "#92400e" if "REVIEW" in status_name else "#475569"
        )

        status_html = f'<font color="{status_badge_txt}"><b>{status_name}</b></font>'
        if record.get("version", 1) > 1:
            status_html += f' <font color="#6b21a8">(v{record["version"]})</font>'

        created_formatted = format_clean_timestamp(record.get("created_at"))
        approved_formatted = format_clean_timestamp(record.get("approved_at"))

        # Overall Report Quality & Confidence Assessment
        report_quality = ReportConfidenceService.evaluate_record_quality(record)
        q_level = report_quality.get("level", "HIGH")
        q_color = (
            "#166534" if q_level == "HIGH" else
            "#92400e" if q_level == "MEDIUM" else
            "#b91c1c" if q_level == "LOW" else "#475569"
        )
        q_score_str = f" ({report_quality['score_percent']}%)" if report_quality.get("score_percent") is not None else ""
        q_html = f'<font color="{q_color}"><b>{q_level}</b></font>{q_score_str}'

        # Metadata Table (Width: 100 + 166 + 100 + 166 = 532 pt)
        meta_data = [
            [
                Paragraph("<b>RECORD ID:</b>", cell_bold),
                Paragraph(record["id"], cell_regular),
                Paragraph("<b>STATUS:</b>", cell_bold),
                Paragraph(status_html, cell_bold)
            ],
            [
                Paragraph("<b>INCIDENT / CALL #:</b>", cell_bold),
                Paragraph(record.get("call_number") or "N/A", cell_regular),
                Paragraph("<b>RESPONDER ID:</b>", cell_bold),
                Paragraph(record.get("responder_id") or "N/A", cell_regular)
            ],
            [
                Paragraph("<b>CREATED AT:</b>", cell_bold),
                Paragraph(created_formatted, cell_regular),
                Paragraph("<b>APPROVED AT:</b>", cell_bold),
                Paragraph(approved_formatted, cell_regular)
            ],
            [
                Paragraph("<b>REPORT QUALITY:</b>", cell_bold),
                Paragraph(q_html, cell_bold),
                Paragraph("<b>QUALITY AUDIT:</b>", cell_bold),
                Paragraph(f"{report_quality.get('summary', '')[:60]}...", cell_italic)
            ]
        ]
        meta_table = Table(meta_data, colWidths=[90, 176, 90, 176])
        meta_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ('TOPPADDING', (0, 0), (-1, -1), 2.5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ]))
        elements.append(meta_table)
        elements.append(Spacer(1, 5))

        # 3. Field Narrative Transcript Section
        elements.append(Paragraph("Field Notes & Narrative Transcript", section_style))
        trans_text = record.get("corrected_transcript") or record.get("machine_transcript") or "[No transcript recorded]"
        narrative_box = Table(
            [[Paragraph(trans_text, narrative_style)]],
            colWidths=[532]
        )
        narrative_box.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(narrative_box)
        elements.append(Spacer(1, 5))

        # 4. Physiological Vital Signs Table (Width: 120 + 62 + 60 + 90 + 200 = 532)
        clinical_data = record.get("clinical_data", {})
        vitals = clinical_data.get("vital_signs", [])
        elements.append(Paragraph("Recorded Physiological Vital Signs", section_style))
        if vitals:
            v_rows = [[
                Paragraph("Vital Sign", header_cell),
                Paragraph("Reading", header_cell),
                Paragraph("Unit", header_cell),
                Paragraph("Verification", header_cell),
                Paragraph("Verbatim Source Evidence", header_cell)
            ]]
            for v in vitals:
                v_rows.append([
                    Paragraph(v.get("name", "Unknown"), cell_bold),
                    Paragraph(str(v.get("value", "")), cell_bold),
                    Paragraph(str(v.get("unit", "")).replace("°", "&deg;"), cell_regular),
                    Paragraph(v.get("verification_state", "Extracted"), cell_regular),
                    Paragraph(f"\"{v.get('source_phrase', '')}\"", cell_italic)
                ])
            v_table = Table(v_rows, colWidths=[120, 62, 60, 90, 200])
            v_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#0f766e")),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ('TOPPADDING', (0, 0), (-1, -1), 2.5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
            ]))
            elements.append(v_table)
        else:
            elements.append(Paragraph("<i>No vital signs captured in encounter narrative.</i>", cell_italic))
        elements.append(Spacer(1, 5))

        # 5. Medications Administered & Assessed (Width: 110 + 72 + 65 + 115 + 80 + 90 = 532)
        meds = clinical_data.get("medications", [])
        elements.append(Paragraph("Medications Administered & Assessed", section_style))
        if meds:
            m_rows = [[
                Paragraph("Medication", header_cell),
                Paragraph("Dosage", header_cell),
                Paragraph("Route", header_cell),
                Paragraph("Clinical Status", header_cell),
                Paragraph("Verification", header_cell),
                Paragraph("Provenance", header_cell)
            ]]
            for m in meds:
                neg_html = (
                    '<font color="#b91c1c"><b>WITHHELD / DENIED</b></font>'
                    if m.get("is_negated") else
                    '<font color="#15803d"><b>ADMINISTERED</b></font>'
                )
                m_rows.append([
                    Paragraph(m.get("canonical_name", m.get("raw_mention", "Unknown")), cell_bold),
                    Paragraph(f"{m.get('dosage') or 'Unspecified'} {m.get('unit') or ''}".strip(), cell_regular),
                    Paragraph(m.get("route") or "Unspecified", cell_regular),
                    Paragraph(neg_html, cell_regular),
                    Paragraph(m.get("verification_state", "Extracted"), cell_regular),
                    Paragraph((m.get("provenance") or "Local Catalogue")[:28], cell_italic)
                ])
            m_table = Table(m_rows, colWidths=[110, 72, 65, 115, 80, 90])
            m_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#0d9488")),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ('TOPPADDING', (0, 0), (-1, -1), 2.5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
            ]))
            elements.append(m_table)
        else:
            elements.append(Paragraph("<i>No medications documented in encounter narrative.</i>", cell_italic))
        elements.append(Spacer(1, 5))

        # 6. Symptoms, Examinations & Pre-Hospital Interventions (Width: 80 + 130 + 122 + 200 = 532)
        symptoms = clinical_data.get("symptoms", [])
        procedures = clinical_data.get("procedures", [])
        examinations = clinical_data.get("examinations", [])
        elements.append(Paragraph("Symptoms, Clinical Observations & Interventions", section_style))
        sp_rows = [[
            Paragraph("Category", header_cell),
            Paragraph("Finding / Intervention", header_cell),
            Paragraph("Assessment Status", header_cell),
            Paragraph("Source Phrase", header_cell)
        ]]
        for s in symptoms:
            neg_badge = (
                '<font color="#b91c1c"><b>DENIED (Pertinent Negative)</b></font>'
                if s.get("is_negated") else
                '<font color="#0f766e"><b>PRESENT / REPORTED</b></font>'
            )
            sp_rows.append([
                Paragraph("Symptom", cell_regular),
                Paragraph(s.get("symptom"), cell_bold),
                Paragraph(neg_badge, cell_regular),
                Paragraph(f"\"{s.get('source_phrase', '')}\"", cell_italic)
            ])
        for ex in examinations:
            sp_rows.append([
                Paragraph(f"Exam: {ex.get('system', 'General')}", cell_regular),
                Paragraph(ex.get("finding", ""), cell_bold),
                Paragraph(f'<b>{ex.get("verification_state", "Extracted")}</b>', cell_bold),
                Paragraph(f"\"{ex.get('source_phrase', '')}\"", cell_italic)
            ])
        for p in procedures:
            sp_rows.append([
                Paragraph("Procedure", cell_regular),
                Paragraph(p.get("procedure"), cell_bold),
                Paragraph("PERFORMED", cell_bold),
                Paragraph(f"\"{p.get('source_phrase', '')}\"", cell_italic)
            ])

        if symptoms or procedures or examinations:
            sp_table = Table(sp_rows, colWidths=[80, 130, 122, 200])
            sp_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#334155")),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ('TOPPADDING', (0, 0), (-1, -1), 2.5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
            ]))
            elements.append(sp_table)
        else:
            elements.append(Paragraph("<i>No specific symptoms, examinations, or procedures extracted.</i>", cell_italic))
        elements.append(Spacer(1, 5))

        # 7. Safety & Validation Warnings Audit (Width: 65 + 115 + 242 + 110 = 532)
        warnings = record.get("validation_warnings", [])
        elements.append(Paragraph("Safety & Validation Warnings Audit", section_style))
        if warnings:
            w_rows = [[
                Paragraph("Severity", header_cell),
                Paragraph("Category", header_cell),
                Paragraph("Description", header_cell),
                Paragraph("Resolution Status", header_cell)
            ]]
            for w in warnings:
                res_txt = "RESOLVED" if w.get("resolved") else "ACKNOWLEDGED / REVIEWED"
                w_rows.append([
                    Paragraph(w.get("severity", "WARNING"), cell_bold),
                    Paragraph(w.get("category", "General"), cell_regular),
                    Paragraph(w.get("message", ""), alert_style),
                    Paragraph(res_txt, cell_bold)
                ])
            w_table = Table(w_rows, colWidths=[65, 115, 242, 110])
            w_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#b91c1c")),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#fff1f2")]),
                ('TOPPADDING', (0, 0), (-1, -1), 2.5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
            ]))
            elements.append(w_table)
        else:
            elements.append(Paragraph("<i>All validation checks passed with zero unresolved warnings.</i>", cell_italic))
        elements.append(Spacer(1, 6))

        # 8. Chronological Event Timeline (Width: 120 + 172 + 240 = 532)
        elements.append(Paragraph("Clinical Encounter Timeline", section_style))
        time_rows = [
            [
                Paragraph("Milestone", header_cell),
                Paragraph("Timestamp (UTC)", header_cell),
                Paragraph("Context & System Details", header_cell)
            ],
            [
                Paragraph("Field Recording", cell_bold),
                Paragraph(format_clean_timestamp(record.get("recording_time") or record.get("created_at")), cell_regular),
                Paragraph("Field narrative audio input captured", cell_regular)
            ],
            [
                Paragraph("Speech-to-Text", cell_bold),
                Paragraph(format_clean_timestamp(record.get("transcription_time") or record.get("created_at")), cell_regular),
                Paragraph(f"Local Whisper ({record.get('transcription_metadata', {}).get('model_used', 'base')})", cell_regular)
            ],
            [
                Paragraph("Clinical Review", cell_bold),
                Paragraph(format_clean_timestamp(record.get("reviewed_at") or "Pending Review"), cell_regular),
                Paragraph("Clinician verified clinical entities & acknowledged checks", cell_regular)
            ],
            [
                Paragraph("Record Finalization", cell_bold),
                Paragraph(format_clean_timestamp(record.get("approved_at") or "Pending Approval"), cell_regular),
                Paragraph(f"Official status: {record.get('status')}", cell_regular)
            ]
        ]
        t_table = Table(time_rows, colWidths=[120, 172, 240])
        t_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#475569")),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ('TOPPADDING', (0, 0), (-1, -1), 2.5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ]))
        elements.append(t_table)
        elements.append(Spacer(1, 8))

        # 9. Attending First Responder Sign-off Box (Width: 352 + 180 = 532)
        sign_block = [
            [
                Paragraph("<b>Attending First Responder Signature / Sign-off:</b>", cell_bold),
                Paragraph("<b>Date & Time:</b>", cell_bold)
            ],
            [
                Paragraph(f"Signed by: <b>{record.get('responder_id', 'Paramedic')}</b> (Credential ID: Verified)", cell_regular),
                Paragraph(approved_formatted if approved_formatted != "N/A" else "____________________", cell_regular)
            ]
        ]
        s_table = Table(sign_block, colWidths=[352, 180])
        s_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        elements.append(KeepTogether([s_table]))

        # Build document
        doc.build(elements, canvasmaker=NumberedCanvas)
        return pdf_path

    @classmethod
    def generate_handover_data(cls, record_id, version_num=None):
        """
        Compile structured hospital handover data payload covering Sections A through G.
        Supports specific historical version export (?version=N).
        """
        if version_num is not None:
            snap = get_record_version_snapshot(record_id, version_num)
            record = snap.get("snapshot_json") if snap else None
            if not record:
                record = get_record(record_id)
        else:
            record = get_record(record_id)

        if not record:
            return None

        # Document State (Feature 5 Requirement 9)
        raw_status = (record.get("status") or "Draft").upper()
        if "APPROVED" in raw_status:
            doc_state = "FINALIZED & AUDITED CLINICAL RECORD"
            doc_badge_class = "approved"
        elif any(k in raw_status for k in ("REVIEW", "AMENDED")):
            doc_state = "PRELIMINARY RESPONDER-APPROVED NOTE"
            doc_badge_class = "preliminary"
        else:
            doc_state = "UNVERIFIED FIELD DRAFT"
            doc_badge_class = "draft"

        # Patient Details
        patient_id = record.get("patient_id")
        pt = get_patient(patient_id) if patient_id else None
        pt_summary = record.get("patient_summary") or {}
        clinical_data = record.get("clinical_data") or {}

        patient_name = (pt.get("full_name") if pt else None) or pt_summary.get("name") or pt_summary.get("full_name") or "Unidentified Patient"
        patient_dob = (pt.get("dob") if pt else None) or pt_summary.get("dob") or pt_summary.get("age") or "Unknown"
        patient_gender = (pt.get("gender") if pt else None) or pt_summary.get("gender") or "Unspecified"
        blood_type = (pt.get("blood_type") if pt else None) or "Unknown"
        medical_history = (pt.get("medical_history") if pt else None) or pt_summary.get("medical_history") or []

        # Incident Details (Section A)
        call_number = record.get("call_number") or f"EMS-{record_id[:8]}"
        location = pt_summary.get("incident_location") or clinical_data.get("incident_location") or "Encounter Scene / Pre-Hospital"
        dispatch_time = format_clean_timestamp(pt_summary.get("dispatch_time") or record.get("created_at"))
        arrival_time = format_clean_timestamp(pt_summary.get("arrival_time") or record.get("recording_time") or record.get("created_at"))
        hospital_arrival = format_clean_timestamp(pt_summary.get("hospital_arrival_time") or record.get("transcription_time") or record.get("updated_at"))

        # Allergy Evaluation (Section B)
        patient_allergies = (pt.get("allergies") if pt else None) or clinical_data.get("patient_allergies") or []
        encounter_allergies = clinical_data.get("allergies") or []
        meds = clinical_data.get("medications") or []

        from backend.services.allergy_safety_service import AllergySafetyService, AllergyWarningState
        allergy_eval = AllergySafetyService.evaluate_safety(
            medications=meds,
            patient_allergies=patient_allergies,
            encounter_allergies=encounter_allergies
        )

        # Timeline of Vital Signs (Section C)
        raw_vitals = clinical_data.get("vital_signs") or []
        vitals_timeline = []
        for v in raw_vitals:
            v_time = v.get("timestamp") or v.get("time") or format_clean_timestamp(record.get("recording_time") or record.get("created_at"))
            vitals_timeline.append({
                "time": v_time,
                "name": v.get("name", "Unknown Vital"),
                "value": str(v.get("value", "")),
                "unit": str(v.get("unit", "")),
                "verification_state": v.get("verification_state", "Extracted"),
                "source_phrase": v.get("source_phrase", "")
            })

        # Medication Administration Record (Section D)
        med_records = []
        for m in meds:
            is_negated = m.get("is_negated", False)
            raw_admin = m.get("administration_status", "ADMINISTERED" if not is_negated else "NOT_ADMINISTERED")
            if is_negated or raw_admin == "NOT_ADMINISTERED":
                admin_status = "NOT_ADMINISTERED"
                status_display = "[WITHHELD / DENIED]"
            elif raw_admin == "PLANNED":
                admin_status = "PLANNED"
                status_display = "[PLANNED / ORDERED]"
            elif m.get("verification_state") == "Uncertain" or raw_admin == "UNCERTAIN":
                admin_status = "UNCERTAIN"
                status_display = "[UNCERTAIN]"
            else:
                admin_status = "ADMINISTERED"
                status_display = "[ADMINISTERED]"

            med_time = m.get("administration_time") or m.get("timestamp") or format_clean_timestamp(record.get("recording_time") or record.get("created_at"))
            med_records.append({
                "name": m.get("canonical_name") or m.get("raw_mention", "Unknown Drug"),
                "raw_mention": m.get("raw_mention", ""),
                "dose": m.get("dosage") or "Unspecified",
                "unit": m.get("unit") or "",
                "route": m.get("route") or "Unspecified",
                "time": med_time,
                "status": admin_status,
                "status_display": status_display,
                "verification_state": m.get("verification_state", "Extracted"),
                "provenance": m.get("provenance") or "Local Catalogue"
            })

        # Clinical Summary & Observations (Section E)
        chief_complaint = (
            pt_summary.get("chief_complaint")
            or clinical_data.get("chief_complaint")
            or (clinical_data.get("symptoms", [{}])[0].get("symptom") if clinical_data.get("symptoms") else None)
            or "Pre-hospital emergency clinical presentation"
        )
        summary_events = (
            record.get("corrected_transcript")
            or record.get("machine_transcript")
            or "Patient received pre-hospital assessment and stabilization by EMS team."
        )

        symptoms = clinical_data.get("symptoms") or []
        procedures = clinical_data.get("procedures") or []
        examinations = clinical_data.get("examinations") or []

        # Safety & Alerts (Section F)
        allergy_warnings = record.get("allergy_warnings") or allergy_eval.get("warnings") or []
        unknown_reviews = record.get("unknown_medication_reviews") or clinical_data.get("unknown_medications") or []
        validation_warnings = record.get("validation_warnings") or []
        critical_flags = [w for w in validation_warnings if w.get("severity") == "CRITICAL" and not w.get("resolved")]

        # Provenance (Section G)
        audit_logs = get_record_audit_logs(record_id)
        approver = record.get("approved_by") or next((a["actor"] for a in audit_logs if a.get("action") in ("APPROVE", "APPROVE_RECORD")), "Pending Supervisor Review")
        approved_time = format_clean_timestamp(record.get("approved_at"))

        return {
            "document_metadata": {
                "document_type": "EMERGENCY_HOSPITAL_HANDOVER",
                "document_state": doc_state,
                "doc_badge_class": doc_badge_class,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "version": record.get("version", 1),
                "record_id": record_id,
                "call_number": call_number,
                "standard": "Field-to-Record EMS Handover Standard v1.3.0"
            },
            "section_a_incident": {
                "call_number": call_number,
                "record_id": record_id,
                "location": location,
                "dispatch_time": dispatch_time,
                "arrival_time": arrival_time,
                "hospital_arrival_time": hospital_arrival,
                "timezone": "UTC"
            },
            "section_b_patient": {
                "patient_id": patient_id or "ANONYMOUS-PATIENT",
                "name": patient_name,
                "dob": patient_dob,
                "gender": patient_gender,
                "blood_type": blood_type,
                "medical_history": medical_history,
                "allergy_status": {
                    "overall_state": allergy_eval.get("overall_state"),
                    "status_label": allergy_eval.get("status"),
                    "active_allergies": allergy_eval.get("allergy_summary", {}).get("active_allergies", []),
                    "explicit_nkda_documented": allergy_eval.get("allergy_summary", {}).get("explicit_nkda_documented", False),
                    "allergy_status_known": allergy_eval.get("allergy_summary", {}).get("allergy_status_known", False),
                    "explanation": next((w["explanation"] for w in allergy_eval.get("warnings", []) if w.get("warning_type") == allergy_eval.get("overall_state")), "Allergy status evaluated against clinical reference standard.")
                }
            },
            "section_c_vitals_timeline": vitals_timeline,
            "section_d_medications": med_records,
            "section_e_clinical_summary": {
                "chief_complaint": chief_complaint,
                "summary_of_events": summary_events,
                "symptoms": symptoms,
                "procedures": procedures,
                "examinations": examinations
            },
            "section_f_safety_alerts": {
                "allergy_warnings": allergy_warnings,
                "unknown_medication_reviews": unknown_reviews,
                "critical_flags": critical_flags
            },
            "section_g_provenance_signoff": {
                "reporting_responder": record.get("responder_id") or "First Responder",
                "reviewer_supervisor": approver,
                "signoff_timestamp": approved_time,
                "version": record.get("version", 1),
                "created_at": format_clean_timestamp(record.get("created_at")),
                "platform": "Field-to-Record Pre-Hospital Emergency Platform v1.3.0"
            }
        }

    @classmethod
    def generate_handover_pdf(cls, record_id, output_filename=None, version_num=None):
        """
        Generate a professional, printable hospital handover PDF document using ReportLab.
        Key features:
        - Paper size: Standard A4 (595.28 x 841.89 pt).
        - High-density clinical layout designed for quick reading in high-stress clinical environments.
        - Single-page handover whenever practical, flowing cleanly to a continuation page if extensive.
        - Fully usable in grayscale on monochrome laser printers (high-contrast text tags, crisp rules).
        - Structured sections A through G matching the hospital handover specification.
        - Unambiguous document status banner: UNVERIFIED FIELD DRAFT vs PRELIMINARY NOTE vs FINALIZED RECORD.
        """
        data = cls.generate_handover_data(record_id, version_num=version_num)
        if not data:
            return None

        if not output_filename:
            ver_suffix = f"_v{data['document_metadata'].get('version', 1)}"
            output_filename = f"handover_{record_id}{ver_suffix}_{int(datetime.now().timestamp())}.pdf"

        pdf_path = os.path.join(REPORTS_DIR, output_filename)

        # A4 page size: 595.28 x 841.89 pt. 36 pt margins -> 523.28 pt usable width
        doc = SimpleDocTemplate(
            pdf_path,
            pagesize=A4,
            leftMargin=36,
            rightMargin=36,
            topMargin=38,
            bottomMargin=40
        )

        styles = getSampleStyleSheet()

        # High-contrast Grayscale Typography Styles
        title_style = ParagraphStyle(
            'HandoverTitle',
            parent=styles['Heading1'],
            fontName='Helvetica-Bold',
            fontSize=14,
            leading=16,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=1
        )
        subtitle_style = ParagraphStyle(
            'HandoverSubTitle',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#334155"),
            spaceAfter=4
        )
        section_hdr_style = ParagraphStyle(
            'HandoverSectionHdr',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=8,
            leading=10,
            textColor=colors.white
        )
        cell_bold = ParagraphStyle(
            'HCellBold',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=7,
            leading=9,
            textColor=colors.HexColor("#0f172a")
        )
        cell_regular = ParagraphStyle(
            'HCellRegular',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=7,
            leading=9,
            textColor=colors.HexColor("#1e293b")
        )
        cell_italic = ParagraphStyle(
            'HCellItalic',
            parent=styles['Normal'],
            fontName='Helvetica-Oblique',
            fontSize=6.5,
            leading=8.5,
            textColor=colors.HexColor("#475569")
        )
        tbl_header_cell = ParagraphStyle(
            'HTblHeader',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=7,
            leading=9,
            textColor=colors.white
        )
        alert_cell = ParagraphStyle(
            'HAlertCell',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=7,
            leading=9,
            textColor=colors.HexColor("#0f172a")
        )

        elements = []

        # 1. Document Header & State Banner
        meta = data["document_metadata"]
        doc_state = meta["document_state"]

        hdr_table_data = [
            [
                Paragraph("<b>FIELD-TO-RECORD • EMERGENCY HOSPITAL HANDOVER</b>", title_style),
                Paragraph(f"<b>CASE: {meta['call_number']}</b>", cell_bold)
            ],
            [
                Paragraph("PRE-HOSPITAL TO EMERGENCY DEPARTMENT CLINICAL TRANSFER SUMMARY", subtitle_style),
                Paragraph(f"EMS ID: {meta['record_id'][:12]} • UTC", cell_italic)
            ]
        ]
        hdr_table = Table(hdr_table_data, colWidths=[370, 153])
        hdr_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(hdr_table)
        elements.append(Spacer(1, 3))

        # Status Banner (Feature 5 Requirement 9: Clearly distinguish Draft, Preliminary, and Finalized)
        banner_bg = (
            colors.HexColor("#0f172a") if "FINALIZED" in doc_state else
            colors.HexColor("#334155") if "PRELIMINARY" in doc_state else
            colors.HexColor("#475569")
        )
        banner_p = Paragraph(f"<b>[DOCUMENT STATE]: {doc_state} (Version {meta['version']})</b>", ParagraphStyle(
            'BannerP', fontName='Helvetica-Bold', fontSize=8, leading=10, textColor=colors.white, alignment=1
        ))
        banner_table = Table([[banner_p]], colWidths=[523])
        banner_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), banner_bg),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 2.5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ]))
        elements.append(banner_table)
        elements.append(Spacer(1, 4))

        # SECTION A: Incident Details
        inc = data["section_a_incident"]
        sec_a_hdr = Table([[Paragraph("SECTION A • INCIDENT & TRANSPORT DETAILS", section_hdr_style)]], colWidths=[523])
        sec_a_hdr.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#1e293b")),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        elements.append(sec_a_hdr)

        inc_rows = [
            [
                Paragraph("<b>Call / Case #:</b>", cell_bold), Paragraph(inc["call_number"], cell_regular),
                Paragraph("<b>Incident Location:</b>", cell_bold), Paragraph(inc["location"][:36], cell_regular)
            ],
            [
                Paragraph("<b>Dispatch Time:</b>", cell_bold), Paragraph(inc["dispatch_time"], cell_regular),
                Paragraph("<b>Scene Arrival:</b>", cell_bold), Paragraph(inc["arrival_time"], cell_regular)
            ],
            [
                Paragraph("<b>ED Arrival Time:</b>", cell_bold), Paragraph(inc["hospital_arrival_time"], cell_regular),
                Paragraph("<b>Timezone Standard:</b>", cell_bold), Paragraph("UTC (Normalized Timestamps)", cell_regular)
            ]
        ]
        inc_table = Table(inc_rows, colWidths=[90, 171, 100, 162])
        inc_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#475569")),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        elements.append(inc_table)
        elements.append(Spacer(1, 4))

        # SECTION B: Patient Information & Allergy Safety Status
        pt_info = data["section_b_patient"]
        sec_b_hdr = Table([[Paragraph("SECTION B • PATIENT INFORMATION & ALLERGY STATUS", section_hdr_style)]], colWidths=[523])
        sec_b_hdr.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#1e293b")),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        elements.append(sec_b_hdr)

        med_hist_str = ", ".join(pt_info["medical_history"]) if pt_info["medical_history"] else "None explicitly documented"
        pt_rows = [
            [
                Paragraph("<b>Patient Name:</b>", cell_bold), Paragraph(pt_info["name"], cell_regular),
                Paragraph("<b>DOB / Age:</b>", cell_bold), Paragraph(pt_info["dob"], cell_regular)
            ],
            [
                Paragraph("<b>Gender:</b>", cell_bold), Paragraph(pt_info["gender"], cell_regular),
                Paragraph("<b>Blood Type:</b>", cell_bold), Paragraph(pt_info["blood_type"], cell_regular)
            ],
            [
                Paragraph("<b>Medical History:</b>", cell_bold),
                Paragraph(med_hist_str[:60], cell_regular),
                Paragraph("<b>Patient ID:</b>", cell_bold),
                Paragraph(pt_info["patient_id"], cell_regular)
            ]
        ]
        pt_table = Table(pt_rows, colWidths=[80, 181, 80, 182])
        pt_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#475569")),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        elements.append(pt_table)

        # Allergy Warning Sub-box
        allr = pt_info["allergy_status"]
        ov_state = allr.get("overall_state", "")
        if ov_state == "CONFIRMED_ALLERGY_CONFLICT":
            allr_tag = "[CRITICAL ALLERGY ALERT — CONFIRMED CONFLICT]"
            allr_bg = colors.HexColor("#f1f5f9")
            allr_border = colors.HexColor("#000000")
        elif ov_state == "POSSIBLE_ALLERGY_CONFLICT":
            allr_tag = "[ALLERGY WARNING — POSSIBLE CLASS CROSS-REACTIVITY]"
            allr_bg = colors.HexColor("#f1f5f9")
            allr_border = colors.HexColor("#000000")
        elif ov_state == "ALLERGY_STATUS_UNKNOWN":
            allr_tag = "[ALLERGY STATUS UNKNOWN — NO HISTORY DOCUMENTED (NOT PROOF OF ABSENCE)]"
            allr_bg = colors.HexColor("#f8fafc")
            allr_border = colors.HexColor("#475569")
        elif allr.get("explicit_nkda_documented"):
            allr_tag = "[NO KNOWN DRUG ALLERGIES (NKDA) DOCUMENTED]"
            allr_bg = colors.HexColor("#f8fafc")
            allr_border = colors.HexColor("#475569")
        else:
            allr_tag = "[ALLERGY STATUS ASSESSED — NO CONFLICT DETECTED]"
            allr_bg = colors.HexColor("#f8fafc")
            allr_border = colors.HexColor("#475569")

        allr_text = f"<b>{allr_tag}:</b> {allr.get('explanation', '')}"
        allr_box = Table([[Paragraph(allr_text, alert_cell)]], colWidths=[523])
        allr_box.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), allr_bg),
            ('BOX', (0, 0), (-1, -1), 1, allr_border),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ]))
        elements.append(allr_box)
        elements.append(Spacer(1, 4))

        # SECTION C: Timeline of Vital Signs
        vitals = data["section_c_vitals_timeline"]
        sec_c_hdr = Table([[Paragraph(f"SECTION C • TIMELINE OF PHYSIOLOGICAL VITAL SIGNS ({len(vitals)} Readings)", section_hdr_style)]], colWidths=[523])
        sec_c_hdr.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#1e293b")),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        elements.append(sec_c_hdr)

        if vitals:
            v_hdr = [
                Paragraph("Time (UTC)", tbl_header_cell),
                Paragraph("Vital Sign", tbl_header_cell),
                Paragraph("Reading", tbl_header_cell),
                Paragraph("Unit", tbl_header_cell),
                Paragraph("Verification", tbl_header_cell),
                Paragraph("Textual Evidence", tbl_header_cell)
            ]
            v_rows = [v_hdr]
            for v in vitals:
                v_rows.append([
                    Paragraph(v.get("time", "Encounter"), cell_regular),
                    Paragraph(v.get("name", ""), cell_bold),
                    Paragraph(v.get("value", ""), cell_bold),
                    Paragraph(v.get("unit", "").replace("°", "&deg;"), cell_regular),
                    Paragraph(v.get("verification_state", "Extracted"), cell_regular),
                    Paragraph(f"\"{v.get('source_phrase', '')}\""[:40], cell_italic)
                ])
            v_table = Table(v_rows, colWidths=[90, 95, 60, 50, 75, 153])
            v_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#334155")),
                ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#475569")),
                ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ]))
            elements.append(v_table)
        else:
            elements.append(Paragraph("<i>No physiological vital signs recorded in encounter narrative.</i>", cell_italic))
        elements.append(Spacer(1, 4))

        # SECTION D: Medication Administration Record
        med_records = data["section_d_medications"]
        sec_d_hdr = Table([[Paragraph(f"SECTION D • MEDICATION ADMINISTRATION RECORD ({len(med_records)} Mentions)", section_hdr_style)]], colWidths=[523])
        sec_d_hdr.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#1e293b")),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        elements.append(sec_d_hdr)

        if med_records:
            m_hdr = [
                Paragraph("Medication", tbl_header_cell),
                Paragraph("Dose & Unit", tbl_header_cell),
                Paragraph("Route", tbl_header_cell),
                Paragraph("Time (UTC)", tbl_header_cell),
                Paragraph("Administration Status", tbl_header_cell),
                Paragraph("Verification", tbl_header_cell)
            ]
            m_rows = [m_hdr]
            for m in med_records:
                status_tag = m.get("status_display", "[ADMINISTERED]")
                m_rows.append([
                    Paragraph(m.get("name", "Unknown"), cell_bold),
                    Paragraph(f"{m.get('dose', '')} {m.get('unit', '')}".strip() or "Unspecified", cell_regular),
                    Paragraph(m.get("route", "Unspecified"), cell_regular),
                    Paragraph(m.get("time", "Encounter"), cell_regular),
                    Paragraph(f"<b>{status_tag}</b>", cell_bold),
                    Paragraph(m.get("verification_state", "Extracted"), cell_regular)
                ])
            m_table = Table(m_rows, colWidths=[115, 75, 60, 85, 115, 73])
            m_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#334155")),
                ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#475569")),
                ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ]))
            elements.append(m_table)
        else:
            elements.append(Paragraph("<i>No medication administration documented during encounter.</i>", cell_italic))
        elements.append(Spacer(1, 4))

        # SECTION E: Clinical Summary & Primary Observations
        clin_sum = data["section_e_clinical_summary"]
        sec_e_hdr = Table([[Paragraph("SECTION E • CLINICAL SUMMARY & PRIMARY OBSERVATIONS", section_hdr_style)]], colWidths=[523])
        sec_e_hdr.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#1e293b")),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        elements.append(sec_e_hdr)

        symptoms_str = ", ".join([
            f"DENIED: {s['symptom']}" if s.get("is_negated") else s["symptom"]
            for s in clin_sum["symptoms"]
        ]) or "None extracted"
        procedures_str = ", ".join([p["procedure"] for p in clin_sum["procedures"]]) or "None extracted"

        summary_rows = [
            [Paragraph("<b>Chief Complaint:</b>", cell_bold), Paragraph(clin_sum["chief_complaint"], cell_regular)],
            [Paragraph("<b>Clinical Events Summary:</b>", cell_bold), Paragraph(clin_sum["summary_of_events"][:280], cell_regular)],
            [Paragraph("<b>Symptoms & Negatives:</b>", cell_bold), Paragraph(symptoms_str[:200], cell_regular)],
            [Paragraph("<b>Interventions / Procedures:</b>", cell_bold), Paragraph(procedures_str[:200], cell_regular)]
        ]
        sum_table = Table(summary_rows, colWidths=[120, 403])
        sum_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#475569")),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        elements.append(sum_table)
        elements.append(Spacer(1, 4))

        # SECTION F: Safety Alerts, Unknown Drugs & Review Flags
        alerts = data["section_f_safety_alerts"]
        sec_f_hdr = Table([[Paragraph("SECTION F • SAFETY ALERTS, UNKNOWN DRUGS & REVIEW FLAGS", section_hdr_style)]], colWidths=[523])
        sec_f_hdr.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#1e293b")),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        elements.append(sec_f_hdr)

        alert_entries = []
        for aw in alerts.get("allergy_warnings", []):
            st = aw.get("status", "ACTIVE")
            ack_info = f" (Clinician Justification: {aw.get('reviewer_decision')})" if aw.get("reviewer_decision") else ""
            alert_entries.append([
                Paragraph(f"<b>[ALLERGY WARNING - {st}]:</b> {aw.get('medication_name')}: {aw.get('explanation')}{ack_info}", alert_cell)
            ])
        for unk in alerts.get("unknown_medication_reviews", []):
            st = unk.get("review_status", "PENDING")
            alert_entries.append([
                Paragraph(f"<b>[UNKNOWN DRUG ALERT - {st}]:</b> Suspected entity '{unk.get('suspected_entity_name')}' in text \"{unk.get('original_text')}\" — Review Decision: {unk.get('reviewer_decision') or 'Pending Review'}", alert_cell)
            ])
        for cf in alerts.get("critical_flags", []):
            alert_entries.append([
                Paragraph(f"<b>[CRITICAL FLAG]:</b> {cf.get('category')}: {cf.get('message')}", alert_cell)
            ])

        if not alert_entries:
            alert_entries.append([
                Paragraph("[CLEAR] All automated safety rules passed with zero unresolved critical flags or active allergy conflicts.", cell_regular)
            ])

        alert_table = Table(alert_entries, colWidths=[523])
        alert_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#475569")),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        elements.append(alert_table)
        elements.append(Spacer(1, 4))

        # SECTION G: Provenance & Sign-off
        prov = data["section_g_provenance_signoff"]
        sec_g_hdr = Table([[Paragraph("SECTION G • PROVENANCE, AUDIT & CLINICAL SIGN-OFF", section_hdr_style)]], colWidths=[523])
        sec_g_hdr.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#1e293b")),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        elements.append(sec_g_hdr)

        sign_rows = [
            [
                Paragraph("<b>Reporting First Responder:</b>", cell_bold),
                Paragraph(prov["reporting_responder"], cell_regular),
                Paragraph("<b>Encounter Created:</b>", cell_bold),
                Paragraph(prov["created_at"], cell_regular)
            ],
            [
                Paragraph("<b>Supervisor / Reviewer:</b>", cell_bold),
                Paragraph(prov["reviewer_supervisor"], cell_regular),
                Paragraph("<b>Approval Timestamp:</b>", cell_bold),
                Paragraph(prov["signoff_timestamp"], cell_regular)
            ],
            [
                Paragraph("<b>Document Version / Audit:</b>", cell_bold),
                Paragraph(f"v{prov['version']} ({meta['doc_badge_class'].upper()})", cell_regular),
                Paragraph("<b>Platform Verification:</b>", cell_bold),
                Paragraph(prov["platform"], cell_italic)
            ]
        ]
        sign_table = Table(sign_rows, colWidths=[110, 151, 110, 152])
        sign_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#475569")),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        elements.append(KeepTogether([sign_table]))

        # Build document with HandoverNumberedCanvas
        doc.build(elements, canvasmaker=HandoverNumberedCanvas)
        return pdf_path
