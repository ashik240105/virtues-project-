import React, { useState, useEffect } from "react";
import {
  Printer, Download, ArrowLeft, ShieldCheck, AlertTriangle,
  Clock, FileText, CheckCircle2, AlertCircle, User, Activity
} from "lucide-react";
import { api } from "../services/api";
import { offlineStorage } from "../services/offlineStorage";

export function HospitalHandoverPage({ recordId, onBack }) {
  const [handoverData, setHandoverData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let isMounted = true;
    const fetchHandover = async () => {
      try {
        let data = null;
        try {
          const res = await api.getHandover(recordId);
          if (res.success && res.data) {
            data = res.data;
          }
        } catch (netErr) {
          // If offline, attempt local generation from IndexedDB cache
          const localRec = await offlineStorage.getOfflineRecord(recordId);
          if (localRec) {
            data = buildFallbackHandoverData(localRec);
          }
        }

        if (!data) {
          const localRec = await offlineStorage.getOfflineRecord(recordId);
          if (localRec) {
            data = buildFallbackHandoverData(localRec);
          }
        }

        if (isMounted && data) {
          setHandoverData(data);
        } else if (isMounted) {
          setError(`Handover data for record '${recordId}' could not be loaded.`);
        }
      } catch (err) {
        if (isMounted) setError(err.message || "Failed to load handover document.");
      } finally {
        if (isMounted) setLoading(false);
      }
    };

    fetchHandover();
    return () => { isMounted = false; };
  }, [recordId]);

  const handlePrint = () => {
    window.print();
  };

  if (loading) {
    return <div className="p-12 text-center text-slate-500 font-sans">Compiling Hospital Handover Document...</div>;
  }

  if (error || !handoverData) {
    return (
      <div className="p-8 max-w-xl mx-auto text-center space-y-4">
        <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-700 text-sm">
          {error || "Handover record not found."}
        </div>
        <button
          onClick={onBack}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-slate-700 text-white text-xs font-semibold"
        >
          <ArrowLeft className="w-4 h-4" />
          <span>Return</span>
        </button>
      </div>
    );
  }

  const {
    document_metadata: meta,
    section_a_incident: inc,
    section_b_patient: pt,
    section_c_vitals_timeline: vitals,
    section_d_medications: meds,
    section_e_clinical_summary: summary,
    section_f_safety_alerts: alerts,
    section_g_provenance_signoff: prov
  } = handoverData;

  const docState = meta.document_state;
  const isApproved = docState.includes("FINALIZED");
  const isPreliminary = docState.includes("PRELIMINARY");

  return (
    <div className="max-w-[210mm] mx-auto space-y-4 font-sans text-slate-900 pb-12">
      {/* ACTION BAR (Hidden in print) */}
      <div className="no-print flex flex-wrap items-center justify-between gap-3 bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
        <div className="flex items-center gap-2">
          <button
            onClick={onBack}
            className="p-2 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700"
            title="Back to Review"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <span className="text-sm font-bold text-slate-900">Hospital Handover Document</span>
            <span className="text-xs text-slate-500 block">Printable A4 & Downloadable ReportLab PDF</span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <a
            href={api.getHandoverPdfUrl(recordId)}
            target="_blank"
            rel="noreferrer"
            download={`handover_${recordId}.pdf`}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Download PDF (A4)</span>
          </a>

          <button
            onClick={handlePrint}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-clinical-teal-700 hover:bg-clinical-teal-800 text-white text-xs font-bold shadow-sm"
          >
            <Printer className="w-4 h-4" />
            <span>Print Document</span>
          </button>
        </div>
      </div>

      {/* PRINTABLE A4 PAGE CONTAINER */}
      <div className="handover-document bg-white border border-slate-300 p-6 sm:p-8 rounded-lg shadow-sm print:border-none print:shadow-none print:p-0 space-y-3.5">
        {/* Document Header */}
        <div className="border-b-2 border-slate-900 pb-2 flex flex-wrap items-start justify-between gap-2">
          <div>
            <h1 className="text-lg font-black tracking-tight text-slate-950 uppercase">
              Field-to-Record • Emergency Hospital Handover
            </h1>
            <p className="text-[11px] font-bold text-slate-700 tracking-wide uppercase">
              Pre-Hospital to Emergency Department Clinical Transfer Record
            </p>
          </div>
          <div className="text-right text-xs">
            <span className="font-mono font-bold text-slate-900 text-sm block">CASE: {meta.call_number}</span>
            <span className="text-[10px] text-slate-500 font-mono">EMS ID: {meta.record_id.slice(0, 12)} • UTC</span>
          </div>
        </div>

        {/* Feature 5 Req 9: Unambiguous Document State Banner */}
        <div
          className={`py-1.5 px-3 text-center text-xs font-black uppercase tracking-wider text-white ${
            isApproved ? "bg-slate-950" : isPreliminary ? "bg-slate-800" : "bg-slate-700"
          }`}
        >
          {docState} (Version {meta.version})
        </div>

        {/* SECTION A: INCIDENT & TRANSPORT DETAILS */}
        <div className="space-y-1">
          <div className="bg-slate-900 text-white text-[11px] font-bold px-2 py-0.5 uppercase tracking-wider">
            Section A • Incident & Transport Details
          </div>
          <div className="border border-slate-400 bg-slate-50/50 p-2 text-xs grid grid-cols-2 sm:grid-cols-4 gap-2">
            <div>
              <span className="font-bold text-slate-700 block text-[10px] uppercase">Incident / Call #:</span>
              <span className="font-semibold text-slate-900">{inc.call_number}</span>
            </div>
            <div>
              <span className="font-bold text-slate-700 block text-[10px] uppercase">Incident Location:</span>
              <span className="font-medium text-slate-900 truncate block">{inc.location}</span>
            </div>
            <div>
              <span className="font-bold text-slate-700 block text-[10px] uppercase">Dispatch Time:</span>
              <span className="font-medium text-slate-900">{inc.dispatch_time}</span>
            </div>
            <div>
              <span className="font-bold text-slate-700 block text-[10px] uppercase">Scene Arrival:</span>
              <span className="font-medium text-slate-900">{inc.arrival_time}</span>
            </div>
            <div>
              <span className="font-bold text-slate-700 block text-[10px] uppercase">ED Arrival Time:</span>
              <span className="font-medium text-slate-900">{inc.hospital_arrival_time}</span>
            </div>
            <div>
              <span className="font-bold text-slate-700 block text-[10px] uppercase">Normalized Timezone:</span>
              <span className="font-medium text-slate-900">UTC (All Timestamps)</span>
            </div>
            <div className="sm:col-span-2">
              <span className="font-bold text-slate-700 block text-[10px] uppercase">EMS Unit / Run ID:</span>
              <span className="font-mono text-slate-900">{meta.record_id}</span>
            </div>
          </div>
        </div>

        {/* SECTION B: PATIENT INFORMATION & ALLERGY STATUS */}
        <div className="space-y-1">
          <div className="bg-slate-900 text-white text-[11px] font-bold px-2 py-0.5 uppercase tracking-wider">
            Section B • Patient Information & Allergy Status
          </div>
          <div className="border border-slate-400 bg-slate-50/50 p-2 text-xs grid grid-cols-2 sm:grid-cols-4 gap-2">
            <div>
              <span className="font-bold text-slate-700 block text-[10px] uppercase">Patient Name:</span>
              <span className="font-bold text-slate-950">{pt.name}</span>
            </div>
            <div>
              <span className="font-bold text-slate-700 block text-[10px] uppercase">DOB / Age:</span>
              <span className="font-medium text-slate-900">{pt.dob || pt.date_of_birth}</span>
            </div>
            <div>
              <span className="font-bold text-slate-700 block text-[10px] uppercase">Gender:</span>
              <span className="font-medium text-slate-900">{pt.gender}</span>
            </div>
            <div>
              <span className="font-bold text-slate-700 block text-[10px] uppercase">Blood Type:</span>
              <span className="font-medium text-slate-900">{pt.blood_type}</span>
            </div>
            <div className="sm:col-span-4 border-t border-slate-200 pt-1">
              <span className="font-bold text-slate-700 block text-[10px] uppercase">Relevant Medical History:</span>
              <span className="font-medium text-slate-900">
                {pt.medical_history && pt.medical_history.length > 0 ? pt.medical_history.join(", ") : "No chronic history explicitly documented"}
              </span>
            </div>
          </div>

          {/* High-visibility Allergy Safety Box */}
          <div className="border-2 border-slate-900 bg-slate-100 p-2 text-xs space-y-0.5">
            <div className="flex items-center gap-1.5 font-black uppercase text-slate-950">
              <ShieldCheck className="w-3.5 h-3.5 text-slate-900 shrink-0" />
              <span>
                {pt.allergy_status.overall_state === "CONFIRMED_ALLERGY_CONFLICT" ? "[CRITICAL ALLERGY ALERT — CONFIRMED CONFLICT]" :
                 pt.allergy_status.overall_state === "POSSIBLE_ALLERGY_CONFLICT" ? "[ALLERGY WARNING — POSSIBLE CLASS CROSS-REACTIVITY]" :
                 pt.allergy_status.overall_state === "ALLERGY_STATUS_UNKNOWN" ? "[ALLERGY STATUS UNKNOWN — NO ALLERGY HISTORY DOCUMENTED]" :
                 pt.allergy_status.explicit_nkda_documented ? "[NO KNOWN DRUG ALLERGIES (NKDA) EXPLICITLY DOCUMENTED]" :
                 "[ALLERGY STATUS ASSESSED — NO KNOWN CONFLICT DETECTED]"}
              </span>
            </div>
            <p className="text-[11px] text-slate-800 font-medium">
              {pt.allergy_status.explanation}
            </p>
            {pt.allergy_status.overall_state === "ALLERGY_STATUS_UNKNOWN" && (
              <p className="text-[10px] text-slate-600 italic">
                Clinical Safety Rule: Missing allergy information must NOT be treated as proof of absence of allergies.
              </p>
            )}
          </div>
        </div>

        {/* SECTION C: TIMELINE OF VITAL SIGNS */}
        <div className="space-y-1">
          <div className="bg-slate-900 text-white text-[11px] font-bold px-2 py-0.5 uppercase tracking-wider flex items-center justify-between">
            <span>Section C • Timeline of Physiological Vital Signs</span>
            <span className="text-[10px] font-normal">{vitals.length} Observation(s)</span>
          </div>
          {vitals.length === 0 ? (
            <p className="text-xs text-slate-500 italic p-2 border border-slate-300">
              No physiological vital signs captured in encounter narrative.
            </p>
          ) : (
            <div className="border border-slate-400 overflow-x-auto">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="bg-slate-800 text-white text-[10px] uppercase font-bold">
                    <th className="p-1.5 border-r border-slate-600">Time (UTC)</th>
                    <th className="p-1.5 border-r border-slate-600">Vital Sign</th>
                    <th className="p-1.5 border-r border-slate-600">Reading</th>
                    <th className="p-1.5 border-r border-slate-600">Unit</th>
                    <th className="p-1.5 border-r border-slate-600">Verification</th>
                    <th className="p-1.5">Evidence Phrase</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200">
                  {vitals.map((v, i) => (
                    <tr key={i} className={i % 2 === 1 ? "bg-slate-50" : "bg-white"}>
                      <td className="p-1.5 font-mono text-[11px] border-r border-slate-200">{v.time}</td>
                      <td className="p-1.5 font-bold border-r border-slate-200">{v.name}</td>
                      <td className="p-1.5 font-mono font-bold text-slate-900 border-r border-slate-200">{v.value}</td>
                      <td className="p-1.5 text-slate-600 border-r border-slate-200">{v.unit}</td>
                      <td className="p-1.5 border-r border-slate-200">
                        <span className="font-semibold text-[10px]">{v.verification_state}</span>
                      </td>
                      <td className="p-1.5 text-slate-500 italic text-[10px] truncate max-w-xs">
                        "{v.source_phrase}"
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* SECTION D: MEDICATION ADMINISTRATION RECORD */}
        <div className="space-y-1">
          <div className="bg-slate-900 text-white text-[11px] font-bold px-2 py-0.5 uppercase tracking-wider flex items-center justify-between">
            <span>Section D • Medication Administration Record</span>
            <span className="text-[10px] font-normal">{meds.length} Medication Mention(s)</span>
          </div>
          {meds.length === 0 ? (
            <p className="text-xs text-slate-500 italic p-2 border border-slate-300">
              No medication administration documented during encounter.
            </p>
          ) : (
            <div className="border border-slate-400 overflow-x-auto">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="bg-slate-800 text-white text-[10px] uppercase font-bold">
                    <th className="p-1.5 border-r border-slate-600">Medication</th>
                    <th className="p-1.5 border-r border-slate-600">Dose & Unit</th>
                    <th className="p-1.5 border-r border-slate-600">Route</th>
                    <th className="p-1.5 border-r border-slate-600">Time (UTC)</th>
                    <th className="p-1.5 border-r border-slate-600">Administration Status</th>
                    <th className="p-1.5">Verification</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200">
                  {meds.map((m, i) => (
                    <tr key={i} className={i % 2 === 1 ? "bg-slate-50" : "bg-white"}>
                      <td className="p-1.5 font-bold border-r border-slate-200 text-slate-950">
                        {m.name}
                        {m.raw_mention && m.raw_mention !== m.name && (
                          <span className="text-[10px] text-slate-500 block font-normal">Mentioned: "{m.raw_mention}"</span>
                        )}
                      </td>
                      <td className="p-1.5 border-r border-slate-200 font-mono">{m.dose} {m.unit}</td>
                      <td className="p-1.5 border-r border-slate-200">{m.route}</td>
                      <td className="p-1.5 font-mono text-[11px] border-r border-slate-200">{m.time}</td>
                      <td className="p-1.5 font-bold border-r border-slate-200">
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-black border ${
                          m.status === "ADMINISTERED" ? "bg-slate-900 text-white border-slate-900" :
                          m.status === "NOT_ADMINISTERED" ? "bg-slate-100 text-slate-900 border-slate-400 line-through" :
                          "bg-slate-200 text-slate-800 border-slate-300"
                        }`}>
                          {m.status_display}
                        </span>
                      </td>
                      <td className="p-1.5 text-[10px] font-semibold text-slate-700">
                        {m.verification_state}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* SECTION E: CLINICAL SUMMARY & PRIMARY OBSERVATIONS */}
        <div className="space-y-1">
          <div className="bg-slate-900 text-white text-[11px] font-bold px-2 py-0.5 uppercase tracking-wider">
            Section E • Clinical Summary & Primary Observations
          </div>
          <div className="border border-slate-400 bg-slate-50/50 p-2 text-xs space-y-1.5">
            <div>
              <span className="font-bold text-slate-800 block text-[10px] uppercase">Chief Complaint:</span>
              <p className="font-semibold text-slate-900">{summary.chief_complaint}</p>
            </div>
            <div>
              <span className="font-bold text-slate-800 block text-[10px] uppercase">Summary of Events:</span>
              <p className="text-slate-800 text-[11px] leading-relaxed">{summary.summary_of_events}</p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-1 border-t border-slate-200">
              <div>
                <span className="font-bold text-slate-800 block text-[10px] uppercase">Symptoms (Observed & Denied):</span>
                <p className="text-[11px] text-slate-800">
                  {summary.symptoms && summary.symptoms.length > 0 ? (
                    summary.symptoms.map((s, idx) => (
                      <span key={idx} className="mr-1.5">
                        {s.is_negated ? <span className="line-through text-slate-600 font-semibold">[DENIED: {s.symptom}]</span> : <span>{s.symptom}</span>}
                      </span>
                    ))
                  ) : "None explicitly documented"}
                </p>
              </div>
              <div>
                <span className="font-bold text-slate-800 block text-[10px] uppercase">Interventions & Procedures:</span>
                <p className="text-[11px] text-slate-800">
                  {summary.procedures && summary.procedures.length > 0 ? (
                    summary.procedures.map((p, idx) => (
                      <span key={idx} className="mr-1.5 font-semibold">[{p.procedure}]</span>
                    ))
                  ) : "None documented"}
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* SECTION F: SAFETY ALERTS, UNKNOWN DRUGS & REVIEW FLAGS */}
        <div className="space-y-1">
          <div className="bg-slate-900 text-white text-[11px] font-bold px-2 py-0.5 uppercase tracking-wider flex items-center justify-between">
            <span>Section F • Safety Alerts, Unknown Drugs & Review Flags</span>
            <span className="text-[10px] font-normal">
              {(alerts.allergy_warnings?.length || 0) + (alerts.unknown_medication_reviews?.length || 0) + (alerts.critical_flags?.length || 0)} Alert(s)
            </span>
          </div>
          <div className="border border-slate-400 bg-slate-50/50 p-2 text-xs space-y-1">
            {alerts.allergy_warnings && alerts.allergy_warnings.length > 0 && (
              alerts.allergy_warnings.map((aw) => (
                <div key={aw.id} className="p-1.5 bg-slate-100 border border-slate-400 text-slate-900 text-[11px]">
                  <span className="font-bold uppercase">[ALLERGY ALERT - {aw.status}]: </span>
                  <span>{aw.medication_name}: {aw.explanation}</span>
                  {aw.reviewer_decision && (
                    <span className="block text-[10px] font-semibold text-slate-700 mt-0.5">
                      Clinician Justification: "{aw.reviewer_decision}" ({aw.reviewer_id})
                    </span>
                  )}
                </div>
              ))
            )}

            {alerts.unknown_medication_reviews && alerts.unknown_medication_reviews.length > 0 && (
              alerts.unknown_medication_reviews.map((unk) => (
                <div key={unk.id} className="p-1.5 bg-slate-100 border border-slate-400 text-slate-900 text-[11px]">
                  <span className="font-bold uppercase">[UNKNOWN DRUG - {unk.review_status}]: </span>
                  <span>Suspected entity '{unk.suspected_entity_name}' in text "{unk.original_text}"</span>
                  {unk.reviewer_decision && (
                    <span className="block text-[10px] font-semibold text-slate-700 mt-0.5">
                      Decision: {unk.reviewer_decision} by {unk.reviewer_id} (Notes: {unk.notes})
                    </span>
                  )}
                </div>
              ))
            )}

            {(!alerts.allergy_warnings || alerts.allergy_warnings.length === 0) &&
             (!alerts.unknown_medication_reviews || alerts.unknown_medication_reviews.length === 0) && (
              <p className="text-[11px] text-slate-700 italic">
                [CLEAR] All automated safety rules passed with zero active critical allergy conflicts or unresolved unknown-drug alerts.
              </p>
            )}
          </div>
        </div>

        {/* SECTION G: PROVENANCE, AUDIT & CLINICAL SIGN-OFF */}
        <div className="space-y-1">
          <div className="bg-slate-900 text-white text-[11px] font-bold px-2 py-0.5 uppercase tracking-wider">
            Section G • Provenance, Audit & Clinical Sign-off
          </div>
          <div className="border border-slate-400 bg-slate-50/50 p-2 text-xs grid grid-cols-2 sm:grid-cols-4 gap-2">
            <div>
              <span className="font-bold text-slate-700 block text-[10px] uppercase">Author / First Responder:</span>
              <span className="font-semibold text-slate-950">{prov.reporting_responder}</span>
            </div>
            <div>
              <span className="font-bold text-slate-700 block text-[10px] uppercase">Supervisory Reviewer:</span>
              <span className="font-semibold text-slate-950">{prov.reviewer_supervisor}</span>
            </div>
            <div>
              <span className="font-bold text-slate-700 block text-[10px] uppercase">Sign-off Timestamp:</span>
              <span className="font-medium text-slate-900">{prov.signoff_timestamp}</span>
            </div>
            <div>
              <span className="font-bold text-slate-700 block text-[10px] uppercase">Document Version / Audit:</span>
              <span className="font-mono text-slate-900">v{prov.version} ({meta.doc_badge_class.toUpperCase()})</span>
            </div>
            <div className="sm:col-span-4 border-t border-slate-200 pt-1 text-[10px] text-slate-500 flex justify-between">
              <span>Platform: {prov.platform}</span>
              <span>Generated: {meta.generated_at.slice(0, 19).replace("T", " ")} UTC</span>
            </div>
          </div>
        </div>

        {/* Document Footer Notice */}
        <div className="border-t border-slate-300 pt-2 text-center text-[9px] text-slate-500 uppercase tracking-wider">
          Confidential Emergency Medical Document • Handover from First Responders to Hospital Emergency Receiving Team
        </div>
      </div>
    </div>
  );
}

// Fallback helper if offline
function buildFallbackHandoverData(rec) {
  const cd = rec.clinical_data || {};
  return {
    document_metadata: {
      call_number: rec.call_number || "EMS-OFFLINE",
      record_id: rec.id,
      version: rec.version || 1,
      document_state: rec.status === "Approved" ? "FINALIZED & AUDITED CLINICAL RECORD" : "PRELIMINARY RESPONDER-APPROVED NOTE",
      doc_badge_class: rec.status === "Approved" ? "approved" : "preliminary",
      generated_at: new Date().toISOString()
    },
    section_a_incident: {
      call_number: rec.call_number || "EMS-OFFLINE",
      record_id: rec.id,
      location: "Incident Scene",
      dispatch_time: rec.created_at || "N/A",
      arrival_time: rec.recording_time || rec.created_at || "N/A",
      hospital_arrival_time: "In Transit / Arrived",
      timezone: "UTC"
    },
    section_b_patient: {
      patient_id: rec.patient_id || "ANONYMOUS",
      name: rec.patient_summary?.name || "Patient",
      dob: rec.patient_summary?.dob || rec.patient_summary?.date_of_birth || "Unknown",
      gender: rec.patient_summary?.gender || "Unspecified",
      blood_type: "Unknown",
      medical_history: [],
      allergy_status: {
        overall_state: "ALLERGY_STATUS_UNKNOWN",
        explanation: "Offline record. Allergy safety checks were computed on device."
      }
    },
    section_c_vitals_timeline: (cd.vital_signs || []).map((v) => ({
      time: "Encounter",
      name: v.name,
      value: v.value,
      unit: v.unit,
      verification_state: v.verification_state || "Extracted",
      source_phrase: v.source_phrase || ""
    })),
    section_d_medications: (cd.medications || []).map((m) => ({
      name: m.canonical_name || m.raw_mention,
      raw_mention: m.raw_mention,
      dose: m.dosage || "Unspecified",
      unit: m.unit || "",
      route: m.route || "Unspecified",
      time: "Encounter",
      status: m.is_negated ? "NOT_ADMINISTERED" : "ADMINISTERED",
      status_display: m.is_negated ? "[WITHHELD / DENIED]" : "[ADMINISTERED]",
      verification_state: m.verification_state || "Extracted"
    })),
    section_e_clinical_summary: {
      chief_complaint: cd.symptoms?.[0]?.symptom || "Emergency presentation",
      summary_of_events: rec.corrected_transcript || rec.machine_transcript || "Narrative note recorded.",
      symptoms: cd.symptoms || [],
      procedures: cd.procedures || []
    },
    section_f_safety_alerts: {
      allergy_warnings: rec.allergy_warnings || [],
      unknown_medication_reviews: rec.unknown_medication_reviews || []
    },
    section_g_provenance_signoff: {
      reporting_responder: rec.responder_id || "First Responder",
      reviewer_supervisor: rec.status === "Approved" ? "Authorized Supervisor" : "Pending Supervisor",
      signoff_timestamp: rec.approved_at || "Pending",
      version: rec.version || 1,
      platform: "Field-to-Record Pre-Hospital Platform v1.3.0"
    }
  };
}

