import React, { useState, useEffect } from "react";
import {
  CheckCircle2, AlertTriangle, ShieldCheck, FileText, ArrowLeft,
  Clock, Download, RefreshCw, XCircle, HelpCircle, Save, Edit2,
  FileCheck2, Compass, HelpCircle as HelpIcon, Layers, AlertCircle
} from "lucide-react";
import { api } from "../services/api";
import { StatusBadge, SeverityBadge, VerificationBadge } from "../components/StatusBadge";

export function ClinicalReviewPage({ recordId, onBack, onNavigateTimeline, onNavigateHandover }) {
  const [record, setRecord] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [successMsg, setSuccessMsg] = useState(null);

  // Active view tab: "structured" | "passport" | "uncertainty"
  const [activeReviewTab, setActiveReviewTab] = useState("structured");

  // Selected item for evidence drawer
  const [focusedEvidenceItem, setFocusedEvidenceItem] = useState(null);

  // Editable fields
  const [correctedTranscript, setCorrectedTranscript] = useState("");
  const [clinicalData, setClinicalData] = useState({
    vital_signs: [],
    medications: [],
    symptoms: [],
    procedures: [],
    examinations: [],
    timestamps: []
  });
  const [warnings, setWarnings] = useState([]);
  const [unknownReviews, setUnknownReviews] = useState([]);
  const [allergyWarnings, setAllergyWarnings] = useState([]);
  const [overrideNotes, setOverrideNotes] = useState("");
  const [showOverrideModal, setShowOverrideModal] = useState(false);

  useEffect(() => {
    let isMounted = true;
    const fetchRecord = async () => {
      try {
        const res = await api.getRecord(recordId);
        if (isMounted && res.success && res.data) {
          const rec = res.data;
          setRecord(rec);
          setCorrectedTranscript(rec.corrected_transcript || rec.machine_transcript || "");
          setClinicalData({
            vital_signs: rec.clinical_data?.vital_signs || [],
            medications: rec.clinical_data?.medications || [],
            symptoms: rec.clinical_data?.symptoms || [],
            procedures: rec.clinical_data?.procedures || [],
            examinations: rec.clinical_data?.examinations || [],
            timestamps: rec.clinical_data?.timestamps || []
          });
          setWarnings(rec.validation_warnings || []);
          setUnknownReviews(rec.unknown_medication_reviews || []);
          setAllergyWarnings(rec.allergy_warnings || []);
        }
      } catch (err) {
        if (isMounted) setError(err.message || "Failed to load clinical record.");
      } finally {
        if (isMounted) setLoading(false);
      }
    };
    fetchRecord();
    return () => { isMounted = false; };
  }, [recordId]);

  // Re-extract clinical entities from updated transcript
  const handleReExtract = async () => {
    setSaving(true);
    setError(null);
    try {
      const res = await api.extractClinical(correctedTranscript);
      if (res.success && res.data) {
        setClinicalData(res.data.entities);
        setWarnings(res.data.validation_warnings);
        setSuccessMsg("Clinical entities successfully re-extracted from edited transcript.");
      }
    } catch (err) {
      setError(err.message || "Failed to re-extract clinical entities.");
    } finally {
      setSaving(false);
    }
  };

  // Toggle verification state of a vital or medication
  const toggleItemVerification = (category, itemId) => {
    setClinicalData((prev) => {
      const list = prev[category] || [];
      const updated = list.map((item) => {
        if (item.id === itemId) {
          const nextState =
            item.verification_state === "Verified" ? "Rejected" :
            item.verification_state === "Rejected" ? "Uncertain" : "Verified";
          return { ...item, verification_state: nextState };
        }
        return item;
      });
      return { ...prev, [category]: updated };
    });
  };

  // Resolve Ambiguous Medication with selected candidate
  const handleResolveAmbiguity = (medId, chosenCanonical) => {
    setClinicalData((prev) => {
      const updatedMeds = (prev.medications || []).map((m) => {
        if (m.id === medId) {
          return {
            ...m,
            canonical_name: chosenCanonical,
            match_status: "RESOLVED_MANUAL",
            verification_state: "Verified"
          };
        }
        return m;
      });
      return { ...prev, medications: updatedMeds };
    });

    // Mark ambiguity warning as resolved
    setWarnings((prev) =>
      prev.map((w) => (w.item_id === medId ? { ...w, resolved: true } : w))
    );
  };

  // Toggle warning resolved state
  const handleToggleWarningResolved = (warningId) => {
    setWarnings((prev) =>
      prev.map((w) => (w.id === warningId ? { ...w, resolved: !w.resolved } : w))
    );
  };

  // Handle Unknown Drug Resolution (Feature 3)
  const handleResolveUnknown = async (itemId, action) => {
    let correctedName = null;
    if (action === "CORRECT") {
      correctedName = prompt("Enter the verified canonical medication name from approved formulary:");
      if (!correctedName) return;
    }
    const notes = prompt(`Enter clinical justification notes for marking this item as ${action}:`);
    if (notes === null) return;

    setSaving(true);
    try {
      const res = await api.resolveUnknownMedication(recordId, itemId, {
        action,
        reviewer_id: "First Responder / Supervisor",
        corrected_name: correctedName,
        notes
      });
      if (res.success && res.data) {
        setUnknownReviews((prev) =>
          prev.map((item) => (item.id === itemId ? res.data : item))
        );
        setWarnings((prev) =>
          prev.map((w) => (w.item_id === itemId ? { ...w, resolved: action !== "UNRESOLVED" } : w))
        );
        setSuccessMsg(`Unknown medication item successfully marked as ${action}.`);
      }
    } catch (err) {
      setError(err.message || "Failed to resolve unknown medication.");
    } finally {
      setSaving(false);
    }
  };

  // Handle Allergy Warning Acknowledgment (Feature 4)
  const handleAcknowledgeAllergyWarning = async (warningId) => {
    const reason = prompt("Enter clinical justification / rationale for acknowledging this allergy warning (e.g., emergent indication, tolerance verified):");
    if (!reason) return;

    setSaving(true);
    try {
      const res = await api.acknowledgeAllergyWarning(recordId, warningId, {
        reviewer_id: "First Responder / Supervisor",
        decision_reason: reason,
        notes: "Acknowledged via clinical review interface"
      });
      if (res.success && res.data) {
        setAllergyWarnings((prev) =>
          prev.map((w) => (w.id === warningId ? res.data : w))
        );
        setWarnings((prev) =>
          prev.map((w) => (w.id === warningId ? { ...w, resolved: true } : w))
        );
        setSuccessMsg("Allergy warning acknowledged with clinical justification logged in audit trail.");
      }
    } catch (err) {
      setError(err.message || "Failed to acknowledge allergy warning.");
    } finally {
      setSaving(false);
    }
  };

  // Save changes to backend
  const handleSaveChanges = async (targetStatus = null) => {
    setSaving(true);
    setError(null);
    setSuccessMsg(null);

    try {
      const payload = {
        corrected_transcript: correctedTranscript,
        clinical_data: clinicalData,
        status: targetStatus || record.status,
        review_decisions: {
          resolved_warning_ids: warnings.filter((w) => w.resolved).map((w) => w.id),
          override_notes: overrideNotes
        }
      };

      const res = await api.updateRecord(recordId, payload);
      if (res.success && res.data) {
        setRecord(res.data);
        setWarnings(res.data.validation_warnings);
        setSuccessMsg("Clinical review progress saved. Evidence Passport & Uncertainty Ledger updated.");
      }
    } catch (err) {
      setError(err.message || "Failed to update record.");
    } finally {
      setSaving(false);
    }
  };

  // Finalize & Approve Record
  const handleApprove = async () => {
    const criticalUnresolved = warnings.filter(
      (w) => w.severity === "CRITICAL" && !w.resolved
    );

    if (criticalUnresolved.length > 0 && !overrideNotes) {
      setShowOverrideModal(true);
      return;
    }

    setSaving(true);
    setError(null);

    try {
      // First persist current edits
      await handleSaveChanges("Reviewed");

      const res = await api.approveRecord(recordId, {
        reviewer_id: "First Responder / Supervisor",
        override_notes: overrideNotes
      });

      if (res.success && res.data) {
        setRecord(res.data);
        setSuccessMsg("Record officially approved and signed off.");
        setShowOverrideModal(false);
      }
    } catch (err) {
      setError(err.message || "Approval rejected by server.");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="p-12 text-center text-slate-500">Loading clinical review...</div>;
  }

  if (!record) {
    return (
      <div className="p-12 text-center text-red-600">
        Record not found or database unreachable.
        <button onClick={onBack} className="block mx-auto mt-4 underline text-sm">
          Return to Dashboard
        </button>
      </div>
    );
  }

  const criticalWarnings = warnings.filter((w) => w.severity === "CRITICAL" && !w.resolved);
  const evidenceEntries = record.evidence_passport?.entries || [];
  const uncertaintyItems = record.uncertainty_ledger?.items || [];
  const uncertaintyCounts = record.uncertainty_ledger?.counts || {
    not_mentioned: 0, unknown: 0, unclear: 0, conflicting: 0
  };
  const changeRadar = record.change_impact_radar;

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Top Navigation & Status Bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="p-2 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700"
            title="Back"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-lg font-bold text-slate-900">{record.call_number || "Field Record"}</span>
              <StatusBadge status={record.status} />
              {record.version > 1 && (
                <span className="text-xs bg-purple-100 text-purple-800 font-semibold px-2 py-0.5 rounded">
                  v{record.version}
                </span>
              )}
            </div>
            <p className="text-xs text-slate-500">
              Encounter ID: <span className="font-mono">{record.id}</span> • Unit: {record.responder_id}
            </p>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex flex-wrap items-center gap-2.5">
          <button
            onClick={() => onNavigateHandover ? onNavigateHandover(record.id) : null}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-teal-50 hover:bg-teal-100 text-teal-800 border border-teal-200 text-xs font-bold"
            title="Open printable hospital handover page (Sections A-G)"
          >
            <FileText className="w-3.5 h-3.5 text-teal-700" />
            <span>Hospital Handover</span>
          </button>
          <a
            href={api.getHandoverPdfUrl(record.id)}
            target="_blank"
            rel="noreferrer"
            download={`handover_${record.id}.pdf`}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold"
            title="Download printable A4 hospital handover PDF"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Handover PDF</span>
          </a>
          <button
            onClick={() => onNavigateTimeline(record.id)}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold"
          >
            <Clock className="w-3.5 h-3.5" />
            <span>Timeline</span>
          </button>
          <a
            href={api.getPdfUrl(record.id)}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold"
          >
            <Download className="w-3.5 h-3.5" />
            <span>PDF Report</span>
          </a>
          <button
            onClick={() => handleSaveChanges()}
            disabled={saving || record.status === "Approved"}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-slate-700 hover:bg-slate-800 text-white text-xs font-semibold disabled:bg-slate-300"
          >
            <Save className="w-3.5 h-3.5" />
            <span>Save Progress</span>
          </button>
          {record.status !== "Approved" && (
            <button
              onClick={handleApprove}
              disabled={saving}
              className="flex items-center gap-1.5 px-5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold shadow-md active:scale-95 disabled:bg-slate-300"
            >
              <CheckCircle2 className="w-4 h-4" />
              <span>Approve Record</span>
            </button>
          )}
        </div>
      </div>

      {/* Transparent Overall Report Quality & Confidence Assessment */}
      {record.report_confidence && (
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-5 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 pb-3">
            <div className="flex items-center gap-2.5">
              <ShieldCheck className="w-5 h-5 text-clinical-teal-600 shrink-0" />
              <div>
                <h2 className="text-sm font-bold text-slate-900">
                  Transparent Report Quality & Confidence Assessment
                </h2>
                <p className="text-xs text-slate-500">
                  Deterministic evaluation based on acoustic probabilities, formulary precision, unsupported claims, and critical alerts.
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <span
                className={`text-xs font-bold px-3 py-1 rounded-full uppercase tracking-wider ${
                  record.report_confidence.quality_level === "HIGH"
                    ? "bg-emerald-100 text-emerald-800 border border-emerald-300"
                    : record.report_confidence.quality_level === "MEDIUM"
                    ? "bg-amber-100 text-amber-800 border border-amber-300"
                    : record.report_confidence.quality_level === "LOW"
                    ? "bg-rose-100 text-rose-800 border border-rose-300"
                    : "bg-slate-100 text-slate-700 border border-slate-300"
                }`}
              >
                {record.report_confidence.quality_level} QUALITY
              </span>
              {record.report_confidence.score_percent !== null && (
                <span className="text-xs font-bold font-mono text-slate-800 bg-slate-100 px-2.5 py-1 rounded-lg border border-slate-200">
                  {record.report_confidence.score_percent}%
                </span>
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
            <div className="p-3 bg-slate-50 rounded-lg border border-slate-200 flex items-center justify-between">
              <div>
                <span className="font-semibold text-slate-700 block">Speech Model Acoustic Clarity</span>
                <span className="text-[11px] text-slate-500">Faster-Whisper beam probability decoding</span>
              </div>
              <span className="font-bold text-clinical-teal-800 font-mono text-xs uppercase px-2 py-0.5 rounded bg-white border border-slate-200">
                {record.report_confidence.speech_confidence_level}
              </span>
            </div>

            <div className="p-3 bg-slate-50 rounded-lg border border-slate-200 flex items-center justify-between">
              <div>
                <span className="font-semibold text-slate-700 block">Practitioner Sign-Off Status</span>
                <span className="text-[11px] text-slate-500">Supervisory clinician approval & oversight</span>
              </div>
              <span
                className={`font-bold font-mono text-xs uppercase px-2 py-0.5 rounded ${
                  record.report_confidence.clinical_signoff_status === "APPROVED"
                    ? "bg-emerald-100 text-emerald-800"
                    : "bg-amber-100 text-amber-800"
                }`}
              >
                {record.report_confidence.clinical_signoff_status}
              </span>
            </div>
          </div>

          {/* Distinction Note */}
          <div className="p-3 bg-blue-50/70 border border-blue-200 rounded-lg text-xs text-blue-900 flex items-start gap-2">
            <HelpIcon className="w-4 h-4 text-blue-600 shrink-0 mt-0.5" />
            <div className="space-y-0.5">
              <span className="font-bold">Crucial Distinction: </span>
              <span>{record.report_confidence.distinction_note}</span>
            </div>
          </div>

          {/* Reasons / Quality Notes */}
          {record.report_confidence.reasons && record.report_confidence.reasons.length > 0 && (
            <div className="text-[11px] text-slate-600 space-y-1 pt-1">
              <span className="font-semibold text-slate-700">Quality Deductions & Safety Notices:</span>
              <ul className="list-disc list-inside space-y-0.5 text-slate-600 pl-1">
                {record.report_confidence.reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Review Tab Sub-navigation */}
      <div className="flex border-b border-slate-200 bg-white rounded-xl p-1.5 shadow-sm gap-2 text-xs font-bold">
        <button
          onClick={() => setActiveReviewTab("structured")}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-all ${
            activeReviewTab === "structured"
              ? "bg-clinical-teal-600 text-white shadow-sm"
              : "text-slate-600 hover:bg-slate-100"
          }`}
        >
          <FileText className="w-4 h-4" />
          <span>Structured Review & Validation</span>
        </button>

        <button
          onClick={() => setActiveReviewTab("passport")}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-all ${
            activeReviewTab === "passport"
              ? "bg-clinical-teal-600 text-white shadow-sm"
              : "text-slate-600 hover:bg-slate-100"
          }`}
        >
          <FileCheck2 className="w-4 h-4" />
          <span>Evidence Passport ({evidenceEntries.length})</span>
          {record.evidence_passport?.unsupported_claims_count > 0 && (
            <span className="bg-amber-400 text-slate-900 text-[10px] px-1.5 py-0.2 rounded-full">
              {record.evidence_passport.unsupported_claims_count} unsupported
            </span>
          )}
        </button>

        <button
          onClick={() => setActiveReviewTab("uncertainty")}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-all ${
            activeReviewTab === "uncertainty"
              ? "bg-clinical-teal-600 text-white shadow-sm"
              : "text-slate-600 hover:bg-slate-100"
          }`}
        >
          <HelpCircle className="w-4 h-4" />
          <span>Uncertainty Ledger ({uncertaintyItems.length})</span>
        </button>
      </div>

      {/* Change Impact Radar Notification */}
      {changeRadar?.has_changes && (
        <div className="p-4 rounded-xl bg-purple-50 border border-purple-200 text-purple-900 space-y-2">
          <div className="flex items-center gap-2 text-xs font-bold">
            <Compass className="w-4 h-4 text-purple-700" />
            <span>Change Impact Radar: Downstream Consequences Detected</span>
          </div>
          <p className="text-xs text-purple-800">{changeRadar.summary}</p>
          {changeRadar.changes_detected?.length > 0 && (
            <ul className="list-disc list-inside text-[11px] text-purple-700 space-y-0.5">
              {changeRadar.changes_detected.map((cd, i) => (
                <li key={i}>{cd}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Notifications */}
      {error && (
        <div className="p-4 rounded-lg bg-red-50 border border-red-200 text-red-800 text-sm flex items-start gap-2">
          <AlertTriangle className="w-5 h-5 text-red-600 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}
      {successMsg && (
        <div className="p-4 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 text-sm flex items-center gap-2">
          <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0" />
          <span>{successMsg}</span>
        </div>
      )}

      {/* Critical Warnings Alert Banner */}
      {criticalWarnings.length > 0 && (
        <div className="p-4 rounded-xl bg-red-50 border-2 border-red-300 text-red-900 space-y-2">
          <div className="flex items-center gap-2 font-bold text-sm">
            <AlertTriangle className="w-5 h-5 text-red-600" />
            <span>UNRESOLVED CRITICAL VALIDATION WARNINGS ({criticalWarnings.length})</span>
          </div>
          <p className="text-xs text-red-700">
            Field-to-Record enforces clinician review. The following clinical warnings require acknowledgment or correction prior to finalizing:
          </p>
          <ul className="list-disc list-inside text-xs space-y-1 pl-1">
            {criticalWarnings.map((w) => (
              <li key={w.id}>
                <span className="font-semibold">{w.category}: </span>
                {w.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* VIEW: STRUCTURED REVIEW & VALIDATION */}
      {activeReviewTab === "structured" && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left Column: Transcript (5 Cols) */}
          <div className="lg:col-span-5 space-y-5">
            <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-5 space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-bold text-slate-800 flex items-center gap-2">
                  <FileText className="w-4 h-4 text-clinical-teal-600" />
                  <span>Field Narrative Transcript</span>
                </h2>
                <button
                  onClick={handleReExtract}
                  disabled={saving || record.status === "Approved"}
                  className="inline-flex items-center gap-1 text-xs text-clinical-teal-700 hover:text-clinical-teal-800 font-semibold"
                  title="Re-run entity extraction on edited transcript"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  <span>Re-Extract Entities</span>
                </button>
              </div>

              <textarea
                rows={8}
                value={correctedTranscript}
                onChange={(e) => setCorrectedTranscript(e.target.value)}
                disabled={record.status === "Approved"}
                className="w-full p-3 rounded-lg border border-slate-300 text-sm font-sans focus:ring-2 focus:ring-clinical-teal-500 bg-white"
              />

              {record.machine_transcript && record.machine_transcript !== correctedTranscript && (
                <div className="text-xs p-3 bg-slate-50 border border-slate-200 rounded-lg">
                  <span className="font-semibold text-slate-600 block mb-1">Original Machine Audio Transcript:</span>
                  <p className="font-mono text-slate-500 italic">"{record.machine_transcript}"</p>
                </div>
              )}
            </div>

            {/* Validation Warnings List */}
            <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-5 space-y-3">
              <h3 className="text-sm font-bold text-slate-800 flex items-center gap-2">
                <ShieldCheck className="w-4 h-4 text-slate-600" />
                <span>Safety & Completeness Checks ({warnings.length})</span>
              </h3>

              {warnings.length === 0 ? (
                <p className="text-xs text-emerald-700 bg-emerald-50 p-3 rounded-lg">
                  All automated validation rules passed cleanly.
                </p>
              ) : (
                <div className="space-y-2.5 max-h-80 overflow-y-auto pr-1">
                  {warnings.map((w) => (
                    <div
                      key={w.id}
                      className={`p-3 rounded-lg border text-xs space-y-1.5 transition-colors ${
                        w.resolved
                          ? "bg-slate-50 border-slate-200 opacity-60"
                          : w.severity === "CRITICAL"
                          ? "bg-red-50/70 border-red-200"
                          : "bg-amber-50/70 border-amber-200"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <SeverityBadge severity={w.severity} />
                        <button
                          onClick={() => handleToggleWarningResolved(w.id)}
                          disabled={record.status === "Approved"}
                          className={`text-[11px] font-semibold px-2 py-0.5 rounded ${
                            w.resolved
                              ? "bg-emerald-100 text-emerald-800"
                              : "bg-slate-200 hover:bg-slate-300 text-slate-700"
                          }`}
                        >
                          {w.resolved ? "Acknowledged [OK]" : "Acknowledge"}
                        </button>
                      </div>
                      <p className="font-medium text-slate-800">{w.message}</p>
                      {w.recommendation && (
                        <p className="text-[11px] text-slate-500 italic">Rec: {w.recommendation}</p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Right Column: Structured Clinical Cards (7 Cols) */}
          <div className="lg:col-span-7 space-y-5">
            {/* Physiological Vital Signs */}
            <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-5 space-y-3">
              <div className="flex items-center justify-between border-b border-slate-100 pb-2">
                <h3 className="text-sm font-bold text-slate-900">
                  Physiological Vital Signs
                </h3>
                <span className="text-xs text-slate-400">Click pill to toggle verification</span>
              </div>

              {clinicalData.vital_signs.length === 0 ? (
                <p className="text-xs text-slate-400 italic py-2">No vital signs extracted from transcript.</p>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {clinicalData.vital_signs.map((v) => (
                    <div key={v.id} className="p-3 bg-slate-50 rounded-lg border border-slate-200 space-y-1">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-slate-700">{v.name}</span>
                        <button
                          onClick={() => toggleItemVerification("vital_signs", v.id)}
                          disabled={record.status === "Approved"}
                          title="Click to toggle: Extracted -> Verified -> Rejected -> Uncertain"
                        >
                          <VerificationBadge state={v.verification_state || "Extracted"} />
                        </button>
                      </div>
                      <div className="text-lg font-bold text-clinical-teal-800 font-mono">
                        {v.value} <span className="text-xs font-normal text-slate-500">{v.unit}</span>
                      </div>
                      {v.source_phrase ? (
                        <div className="text-[11px] text-slate-400 truncate italic">
                          Evidence: "{v.source_phrase}"
                        </div>
                      ) : (
                        <div className="text-[10px] text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded font-semibold">
                          ⚠️ Unsupported Claim
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Medications & Interventions with Ambiguity Engine */}
            <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-5 space-y-3">
              <div className="flex items-center justify-between border-b border-slate-100 pb-2">
                <h3 className="text-sm font-bold text-slate-900">
                  Medications Administered & Assessed
                </h3>
                <span className="text-xs text-slate-400">Ambiguity Engine: Phonetic & Strength Matching</span>
              </div>

              {clinicalData.medications.length === 0 ? (
                <p className="text-xs text-slate-400 italic py-2">No medication mentions detected.</p>
              ) : (
                <div className="space-y-3">
                  {clinicalData.medications.map((m) => (
                    <div
                      key={m.id}
                      className={`p-3.5 rounded-lg border space-y-2 ${
                        m.match_status === "AMBIGUOUS"
                          ? "bg-amber-50/70 border-amber-300"
                          : "bg-slate-50 border-slate-200"
                      }`}
                    >
                      <div className="flex items-start justify-between">
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-sm text-slate-900">
                              {m.canonical_name || m.raw_mention}
                            </span>
                            {m.is_negated ? (
                              <span className="bg-rose-100 text-rose-800 text-[10px] font-bold px-2 py-0.5 rounded">
                                WITHHELD / DENIED
                              </span>
                            ) : (
                              <span className="bg-emerald-100 text-emerald-800 text-[10px] font-bold px-2 py-0.5 rounded">
                                ADMINISTERED
                              </span>
                            )}
                            {m.pediatric_warning && (
                              <span className="bg-amber-100 text-amber-800 text-[10px] font-bold px-1.5 py-0.5 rounded">
                                Peds Warning
                              </span>
                            )}
                          </div>
                          <p className="text-xs text-slate-500 mt-0.5">
                            Mentioned as: "{m.raw_mention}" • Dose: {m.dosage || "N/A"} {m.unit || ""} • Route: {m.route || "N/A"}
                          </p>
                        </div>

                        <button
                          onClick={() => toggleItemVerification("medications", m.id)}
                          disabled={record.status === "Approved"}
                        >
                          <VerificationBadge state={m.verification_state || "Extracted"} />
                        </button>
                      </div>

                      {/* Ambiguity Resolution Selector with phonetic & strength comparison */}
                      {m.match_status === "AMBIGUOUS" && m.candidates && (
                        <div className="p-3 bg-amber-100/80 rounded-lg border border-amber-300 text-xs space-y-2">
                          <div className="flex items-center gap-2">
                            <AlertCircle className="w-4 h-4 text-amber-800" />
                            <span className="font-bold text-amber-900">
                              Medicine Ambiguity Engine: Human confirmation required for "{m.raw_mention}"
                            </span>
                          </div>
                          <p className="text-[11px] text-amber-800">
                            Phonetic Soundex and spelling analysis found multiple matches. Compare available strengths and confirm:
                          </p>
                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-1">
                            {m.candidates.map((cand) => (
                              <div
                                key={cand.canonical_name}
                                className="p-2.5 bg-white rounded-lg border border-amber-200 text-left space-y-1.5 shadow-sm"
                              >
                                <div className="flex items-center justify-between">
                                  <span className="font-bold text-slate-900 text-xs">{cand.canonical_name}</span>
                                  <span className="text-[10px] font-mono px-1.5 py-0.2 bg-amber-100 text-amber-800 rounded font-semibold">
                                    {cand.score}% {cand.soundex_match ? "• Phonetic" : ""}
                                  </span>
                                </div>
                                {cand.standard_strengths && (
                                  <div className="text-[10px] text-slate-500">
                                    Strengths: {cand.standard_strengths.join(", ")}
                                  </div>
                                )}
                                {cand.standard_routes && (
                                  <div className="text-[10px] text-slate-500">
                                    Routes: {cand.standard_routes.join(", ")}
                                  </div>
                                )}
                                <button
                                  onClick={() => handleResolveAmbiguity(m.id, cand.canonical_name)}
                                  disabled={record.status === "Approved"}
                                  className="w-full mt-1 py-1 px-2 bg-clinical-teal-600 hover:bg-clinical-teal-700 text-white rounded text-[11px] font-semibold text-center shadow-sm"
                                >
                                  Confirm & Commit {cand.canonical_name}
                                </button>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      <div className="text-[11px] text-slate-400">
                        Provenance: {m.provenance || "Local Catalogue"}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* FEATURE 3: UNKNOWN MEDICATION ALERTS & REVIEW QUEUE */}
            {(unknownReviews.length > 0 || (clinicalData.unknown_medications && clinicalData.unknown_medications.length > 0)) && (
              <div className="bg-white rounded-xl shadow-sm border-2 border-amber-300 p-5 space-y-3">
                <div className="flex items-center justify-between border-b border-amber-200 pb-2">
                  <div className="flex items-center gap-2">
                    <AlertTriangle className="w-4 h-4 text-amber-600" />
                    <h3 className="text-sm font-bold text-amber-950">
                      Unknown Medication — Review Required ({unknownReviews.length || clinicalData.unknown_medications?.length})
                    </h3>
                  </div>
                  <span className="text-[11px] bg-amber-100 text-amber-900 font-semibold px-2 py-0.5 rounded">
                    Formulary Exception Queue
                  </span>
                </div>
                <p className="text-xs text-amber-800">
                  Suspected drug entities documented with dosage/route that are not recognized in the approved ambulance catalogue. Authorized clinical reviewer action required:
                </p>

                <div className="space-y-3">
                  {(unknownReviews.length > 0 ? unknownReviews : (clinicalData.unknown_medications || [])).map((unk) => (
                    <div key={unk.id} className="p-3.5 bg-amber-50/70 border border-amber-200 rounded-lg space-y-2">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-sm text-slate-900">
                              {unk.suspected_entity_name || "Uncatalogued Drug"}
                            </span>
                            <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${
                              unk.review_status === "CONFIRMED" ? "bg-emerald-100 text-emerald-800" :
                              unk.review_status === "CORRECTED" ? "bg-blue-100 text-blue-800" :
                              unk.review_status === "REJECTED" ? "bg-rose-100 text-rose-800" :
                              "bg-amber-100 text-amber-800"
                            }`}>
                              STATUS: {unk.review_status || "PENDING"}
                            </span>
                          </div>
                          <p className="text-xs text-slate-600 mt-1">
                            Original text: <span className="font-mono italic">"{unk.original_text}"</span>
                          </p>
                          {unk.notes && (
                            <p className="text-[11px] text-slate-500 italic mt-0.5">
                              Reviewer Notes: {unk.notes}
                            </p>
                          )}
                        </div>

                        {/* Reviewer Action Buttons */}
                        {unk.review_status === "PENDING" || unk.review_status === "UNRESOLVED" ? (
                          <div className="flex flex-wrap items-center gap-1.5">
                            <button
                              onClick={() => handleResolveUnknown(unk.id, "CONFIRM")}
                              disabled={saving || record.status === "Approved"}
                              className="px-2.5 py-1 bg-emerald-600 hover:bg-emerald-700 text-white rounded text-xs font-semibold shadow-sm"
                              title="Confirm as valid non-formulary transfer drug without auto-promoting to catalogue"
                            >
                              Confirm
                            </button>
                            <button
                              onClick={() => handleResolveUnknown(unk.id, "CORRECT")}
                              disabled={saving || record.status === "Approved"}
                              className="px-2.5 py-1 bg-blue-600 hover:bg-blue-700 text-white rounded text-xs font-semibold shadow-sm"
                              title="Map to approved catalogue medication"
                            >
                              Correct
                            </button>
                            <button
                              onClick={() => handleResolveUnknown(unk.id, "REJECT")}
                              disabled={saving || record.status === "Approved"}
                              className="px-2.5 py-1 bg-rose-600 hover:bg-rose-700 text-white rounded text-xs font-semibold shadow-sm"
                              title="Reject spurious mention"
                            >
                              Reject
                            </button>
                            <button
                              onClick={() => handleResolveUnknown(unk.id, "UNRESOLVED")}
                              disabled={saving || record.status === "Approved"}
                              className="px-2.5 py-1 bg-slate-200 hover:bg-slate-300 text-slate-700 rounded text-xs font-semibold"
                              title="Leave for subsequent clinical supervisor audit"
                            >
                              Unresolved
                            </button>
                          </div>
                        ) : (
                          <div className="text-[11px] text-slate-500 text-right">
                            Resolved by <span className="font-semibold">{unk.reviewer_id}</span>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
                <p className="text-[11px] text-slate-500 italic pt-1">
                  Governance Rule: Reviewer confirmation records clinical justification for this encounter only and never automatically promotes unknown names into the trusted formulary.
                </p>
              </div>
            )}

            {/* FEATURE 4: ALLERGY & MEDICATION SAFETY WARNINGS */}
            {allergyWarnings.length > 0 && (
              <div className="bg-white rounded-xl shadow-sm border-2 border-red-300 p-5 space-y-3">
                <div className="flex items-center justify-between border-b border-red-200 pb-2">
                  <div className="flex items-center gap-2">
                    <ShieldCheck className="w-4 h-4 text-red-600" />
                    <h3 className="text-sm font-bold text-red-950">
                      Allergy & Medication Safety Decision Support ({allergyWarnings.length})
                    </h3>
                  </div>
                  <span className="text-[11px] bg-red-100 text-red-900 font-semibold px-2 py-0.5 rounded">
                    Safety Decision Support
                  </span>
                </div>

                <div className="space-y-3">
                  {allergyWarnings.map((aw) => (
                    <div
                      key={aw.id}
                      className={`p-3.5 rounded-lg border space-y-2 ${
                        aw.status === "ACKNOWLEDGED"
                          ? "bg-slate-50 border-slate-200 opacity-75"
                          : aw.severity === "CRITICAL"
                          ? "bg-red-50/80 border-red-300"
                          : "bg-amber-50/80 border-amber-300"
                      }`}
                    >
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-sm text-slate-900">
                              {aw.medication_name}
                            </span>
                            <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${
                              aw.warning_type === "CONFIRMED_ALLERGY_CONFLICT" ? "bg-red-100 text-red-800" :
                              aw.warning_type === "POSSIBLE_ALLERGY_CONFLICT" ? "bg-amber-100 text-amber-800" :
                              "bg-slate-200 text-slate-800"
                            }`}>
                              {aw.warning_type}
                            </span>
                            {aw.status === "ACKNOWLEDGED" && (
                              <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-100 text-emerald-800">
                                ACKNOWLEDGED
                              </span>
                            )}
                          </div>
                          {aw.recorded_allergy && (
                            <p className="text-xs text-red-800 font-semibold mt-1">
                              Recorded Allergen: {aw.recorded_allergy} {aw.allergy_source ? `(${aw.allergy_source})` : ""}
                            </p>
                          )}
                          <p className="text-xs text-slate-700 mt-1">
                            {aw.explanation}
                          </p>
                          {aw.reviewer_decision && (
                            <p className="text-[11px] text-emerald-800 font-medium mt-1">
                              Clinician Justification: "{aw.reviewer_decision}" ({aw.reviewer_id})
                            </p>
                          )}
                        </div>

                        {aw.status !== "ACKNOWLEDGED" && (
                          <button
                            onClick={() => handleAcknowledgeAllergyWarning(aw.id)}
                            disabled={saving || record.status === "Approved"}
                            className="px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white rounded text-xs font-semibold shrink-0 shadow-sm"
                          >
                            Acknowledge Warning
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>

                <div className="p-2.5 bg-slate-50 border border-slate-200 rounded text-[11px] text-slate-600 space-y-0.5">
                  <span className="font-semibold text-slate-700 block">Clinical Safety Notice:</span>
                  <p>
                    This is a clinical documentation and decision-support module, not an autonomous prescribing system. It does not recommend treatment, establish absolute drug safety, or block emergency administration. Missing allergy data is not treated as proof that the patient has no allergies.
                  </p>
                </div>
              </div>
            )}

            {/* Symptoms & Pertinent Negatives */}
            <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-5 space-y-3">
              <h3 className="text-sm font-bold text-slate-900 border-b border-slate-100 pb-2">
                Clinical Symptoms & Negative Findings
              </h3>

              {clinicalData.symptoms.length === 0 ? (
                <p className="text-xs text-slate-400 italic py-2">No symptoms extracted.</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {clinicalData.symptoms.map((s) => (
                    <span
                      key={s.id}
                      className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border ${
                        s.is_negated
                          ? "bg-slate-100 text-slate-700 border-slate-300 line-through"
                          : "bg-teal-50 text-teal-800 border-teal-200"
                      }`}
                    >
                      {s.is_negated && <span className="no-underline text-rose-600 font-bold">DENIED:</span>}
                      <span>{s.symptom}</span>
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Procedures & Interventions */}
            <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-5 space-y-3">
              <h3 className="text-sm font-bold text-slate-900 border-b border-slate-100 pb-2">
                Interventions & Procedures
              </h3>

              {clinicalData.procedures.length === 0 ? (
                <p className="text-xs text-slate-400 italic py-2">No procedures extracted.</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {clinicalData.procedures.map((p) => (
                    <span
                      key={p.id}
                      className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-slate-100 text-slate-800 border border-slate-300"
                    >
                      <span>{p.procedure}</span>
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Clinical Examinations & Physical Findings */}
            <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-5 space-y-3">
              <div className="flex items-center justify-between border-b border-slate-100 pb-2">
                <h3 className="text-sm font-bold text-slate-900">
                  Clinical Examinations & Observations
                </h3>
                <span className="text-xs text-slate-400">Cardiovascular, Neurological, Respiratory</span>
              </div>

              {(!clinicalData.examinations || clinicalData.examinations.length === 0) ? (
                <p className="text-xs text-slate-400 italic py-2">No physical examination findings extracted.</p>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {clinicalData.examinations.map((ex) => (
                    <div key={ex.id} className="p-3 bg-slate-50 rounded-lg border border-slate-200 space-y-1">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-slate-800">{ex.finding || ex.system}</span>
                        <button
                          onClick={() => toggleItemVerification("examinations", ex.id)}
                          disabled={record.status === "Approved"}
                          title="Click to toggle verification"
                        >
                          <VerificationBadge state={ex.verification_state || "Extracted"} />
                        </button>
                      </div>
                      <div className="text-sm font-semibold text-clinical-teal-800">
                        {ex.value || "Normal"} <span className="text-[11px] font-normal text-slate-500">({ex.system})</span>
                      </div>
                      {ex.source_phrase && (
                        <div className="text-[11px] text-slate-400 italic truncate">
                          "{ex.source_phrase}"
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* VIEW: EVIDENCE PASSPORT */}
      {activeReviewTab === "passport" && (
        <div className="space-y-5">
          <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-5">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 pb-3">
              <div>
                <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
                  <FileCheck2 className="w-5 h-5 text-clinical-teal-600" />
                  <span>Clinical Evidence Passport</span>
                </h2>
                <p className="text-xs text-slate-500 mt-0.5">
                  Every structured assertion is bound to verbatim speech phrases, audio timestamps, source provenance, and verification state.
                </p>
              </div>

              {record.evidence_passport?.unsupported_claims_count > 0 && (
                <div className="px-3 py-1.5 bg-amber-50 border border-amber-300 rounded-lg text-xs font-bold text-amber-800">
                  ⚠️ {record.evidence_passport.unsupported_claims_count} Unsupported Claim(s) Flagged
                </div>
              )}
            </div>

            {evidenceEntries.length === 0 ? (
              <div className="py-12 text-center text-xs text-slate-400">
                No clinical entities extracted to generate Evidence Passport.
              </div>
            ) : (
              <div className="space-y-3 pt-4">
                {evidenceEntries.map((entry, idx) => (
                  <div
                    key={idx}
                    className={`p-4 rounded-xl border text-xs space-y-2 ${
                      !entry.is_supported
                        ? "bg-amber-50/70 border-amber-300"
                        : "bg-slate-50/70 border-slate-200"
                    }`}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-slate-900 text-sm">{entry.field_name}:</span>
                        <span className="font-mono font-bold text-clinical-teal-900 bg-white px-2 py-0.5 rounded border border-slate-200">
                          {entry.field_value}
                        </span>
                        <span className="text-[10px] uppercase font-semibold px-2 py-0.5 rounded bg-slate-200 text-slate-700">
                          {entry.source_type || "ORIGINAL_TRANSCRIPT"}
                        </span>
                      </div>

                      <div className="flex items-center gap-2">
                        {entry.is_supported ? (
                          <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
                            <CheckCircle2 className="w-3.5 h-3.5" />
                            <span>Supported by Narrative</span>
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-amber-800 bg-amber-100 px-2 py-0.5 rounded border border-amber-300">
                            <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />
                            <span>Unsupported Claim</span>
                          </span>
                        )}
                        <VerificationBadge state={entry.reviewer_decision || "Extracted"} />
                      </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1">
                      <div className="p-2.5 bg-white rounded-lg border border-slate-200">
                        <span className="font-bold text-slate-500 block text-[10px] uppercase">Supporting Audio Text:</span>
                        <p className="font-mono text-slate-800 italic mt-0.5">
                          "{entry.supporting_phrase || "No direct supporting phrase extracted"}"
                        </p>
                      </div>

                      <div className="p-2.5 bg-white rounded-lg border border-slate-200 flex flex-col justify-between">
                        <span className="font-bold text-slate-500 block text-[10px] uppercase">Audio / Segment Reference:</span>
                        <span className="font-mono text-slate-700 mt-0.5">
                          {entry.timestamp_range
                            ? `Audio range: ${entry.timestamp_range[0]}s - ${entry.timestamp_range[1]}s`
                            : "Preserved from encounter recording"}
                        </span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* VIEW: UNCERTAINTY LEDGER */}
      {activeReviewTab === "uncertainty" && (
        <div className="space-y-5">
          <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-5 space-y-4">
            <div className="border-b border-slate-100 pb-3">
              <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
                <HelpCircle className="w-5 h-5 text-clinical-teal-600" />
                <span>Clinical Uncertainty Ledger</span>
              </h2>
              <p className="text-xs text-slate-500 mt-0.5">
                Explicit classification of omissions, low-confidence phrases, conflicting observations, and unknown values.
              </p>
            </div>

            {/* Uncertainty summary badges */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div className="p-3 rounded-xl bg-slate-50 border border-slate-200 text-center">
                <span className="text-[10px] font-bold text-slate-500 uppercase">Not Mentioned</span>
                <div className="text-xl font-black text-slate-800 font-mono mt-0.5">{uncertaintyCounts.not_mentioned}</div>
              </div>
              <div className="p-3 rounded-xl bg-blue-50 border border-blue-200 text-center">
                <span className="text-[10px] font-bold text-blue-700 uppercase">Unknown</span>
                <div className="text-xl font-black text-blue-900 font-mono mt-0.5">{uncertaintyCounts.unknown}</div>
              </div>
              <div className="p-3 rounded-xl bg-amber-50 border border-amber-200 text-center">
                <span className="text-[10px] font-bold text-amber-700 uppercase">Unclear / Muffled</span>
                <div className="text-xl font-black text-amber-900 font-mono mt-0.5">{uncertaintyCounts.unclear}</div>
              </div>
              <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-center">
                <span className="text-[10px] font-bold text-rose-700 uppercase">Conflicting</span>
                <div className="text-xl font-black text-rose-900 font-mono mt-0.5">{uncertaintyCounts.conflicting}</div>
              </div>
            </div>

            {/* List of uncertainty items */}
            {uncertaintyItems.length === 0 ? (
              <div className="py-8 text-center text-xs text-slate-400">
                No active uncertainty records flagged. All clinical data complete and resolved.
              </div>
            ) : (
              <div className="space-y-3 pt-2">
                {uncertaintyItems.map((item, i) => {
                  const catBadge =
                    item.category === "CONFLICTING" ? "bg-rose-100 text-rose-800 border-rose-200" :
                    item.category === "UNCLEAR" ? "bg-amber-100 text-amber-800 border-amber-200" :
                    item.category === "UNKNOWN" ? "bg-blue-100 text-blue-800 border-blue-200" :
                    "bg-slate-100 text-slate-700 border-slate-300";

                  return (
                    <div key={i} className="p-3.5 rounded-xl border border-slate-200 bg-slate-50/60 text-xs space-y-1.5">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className={`text-[10px] font-bold px-2 py-0.5 rounded border uppercase ${catBadge}`}>
                            {item.category.replace("_", " ")}
                          </span>
                          <span className="font-bold text-slate-900">{item.field}</span>
                        </div>
                      </div>
                      <p className="text-slate-700">{item.description}</p>
                      {item.suggested_action && (
                        <p className="text-[11px] text-slate-500 italic">
                          Recommended Action: {item.suggested_action}
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Clinician Override Modal for Critical Warnings */}
      {showOverrideModal && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center gap-2 text-red-600 font-bold text-base">
              <AlertTriangle className="w-6 h-6 shrink-0" />
              <span>Clinician Override Required</span>
            </div>
            <p className="text-xs text-slate-600">
              There are {criticalWarnings.length} unresolved critical warnings on this record.
              To approve this record, medical protocol requires an explicit clinician override explanation:
            </p>
            <textarea
              rows={3}
              value={overrideNotes}
              onChange={(e) => setOverrideNotes(e.target.value)}
              placeholder="e.g. Critical values confirmed accurate on scene with manual sphygmomanometer; medication verbally confirmed by medical control..."
              className="w-full p-3 rounded-lg border border-slate-300 text-sm focus:ring-2 focus:ring-red-500"
            />
            <div className="flex justify-end gap-2.5 pt-2">
              <button
                onClick={() => setShowOverrideModal(false)}
                className="px-4 py-2 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold"
              >
                Cancel
              </button>
              <button
                onClick={handleApprove}
                disabled={!overrideNotes.trim()}
                className="px-5 py-2 rounded-lg bg-red-600 hover:bg-red-700 disabled:bg-slate-300 text-white text-xs font-semibold shadow-md"
              >
                Submit Override & Finalize
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
