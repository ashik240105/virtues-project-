import React, { useState, useEffect } from "react";
import {
  FileText, ArrowLeft, Download, ShieldCheck, Clock, User,
  Volume2, AlertTriangle, Edit3, CheckCircle2, History,
  Layers, ExternalLink, Calendar, Phone, Activity, UserPlus, X, Tag
} from "lucide-react";
import { api } from "../services/api";
import { StatusBadge, VerificationBadge } from "../components/StatusBadge";

export function RecordDetailsPage({ recordId, onBack, onNavigateReview, onNavigateTimeline }) {
  const [record, setRecord] = useState(null);
  const [auditLogs, setAuditLogs] = useState([]);
  const [versions, setVersions] = useState([]);
  const [patientInfo, setPatientInfo] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showAmendModal, setShowAmendModal] = useState(false);
  const [amendReason, setAmendReason] = useState("");
  const [amendText, setAmendText] = useState("");
  const [isSubmittingAmend, setIsSubmittingAmend] = useState(false);

  // Version snapshot viewing state
  const [selectedVersionNum, setSelectedVersionNum] = useState(null);
  const [versionSnapshot, setVersionSnapshot] = useState(null);
  const [loadingVersion, setLoadingVersion] = useState(false);

  // Link Unidentified Patient state
  const [showLinkModal, setShowLinkModal] = useState(false);
  const [availablePatients, setAvailablePatients] = useState([]);
  const [targetPatientId, setTargetPatientId] = useState("");
  const [isLinkingPatient, setIsLinkingPatient] = useState(false);
  const [linkError, setLinkError] = useState(null);

  const loadDetails = async () => {
    try {
      const [recRes, auditRes, verRes] = await Promise.all([
        api.getRecord(recordId),
        api.getAuditTrail(recordId),
        api.getRecordVersions(recordId)
      ]);

      if (recRes.success && recRes.data) {
        const r = recRes.data;
        setRecord(r);
        setAmendText(r.corrected_transcript || r.machine_transcript || "");

        // If patient is linked, fetch patient details
        const ptId = r.patient_id || r.patient_summary?.patient_id;
        if (ptId) {
          try {
            const ptRes = await api.getPatient(ptId);
            if (ptRes.success && ptRes.data) {
              setPatientInfo(ptRes.data);
            }
          } catch (e) {
            // Ignore patient fetch error
          }
        } else {
          setPatientInfo(null);
        }
      }

      if (auditRes.success && auditRes.data) {
        setAuditLogs(auditRes.data);
      }

      if (verRes.success && verRes.data) {
        setVersions(verRes.data.versions || []);
      }
    } catch (err) {
      setError(err.message || "Failed to load record details.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDetails();
  }, [recordId]);

  const handleSelectVersion = async (vNum) => {
    if (!vNum || vNum === record?.version) {
      setSelectedVersionNum(null);
      setVersionSnapshot(null);
      return;
    }

    setLoadingVersion(true);
    try {
      const res = await api.getVersionSnapshot(recordId, vNum);
      if (res.success && res.data) {
        setSelectedVersionNum(vNum);
        setVersionSnapshot(res.data);
      }
    } catch (err) {
      alert("Failed to load historical version snapshot: " + err.message);
    } finally {
      setLoadingVersion(false);
    }
  };

  const handleOpenLinkModal = async () => {
    setLinkError(null);
    try {
      const res = await api.listPatients();
      if (res.success && res.data) {
        setAvailablePatients(res.data.patients || []);
      }
    } catch (e) {
      // Ignore
    }
    setShowLinkModal(true);
  };

  const handleLinkPatientSubmit = async () => {
    if (!targetPatientId) {
      setLinkError("Please select a registered patient profile.");
      return;
    }

    setIsLinkingPatient(true);
    setLinkError(null);
    try {
      const res = await api.linkPatientEncounter(targetPatientId, {
        record_id: recordId,
        encounter_type: "NEW_ENCOUNTER",
        actor: "Paramedic / Triage"
      });

      if (res.success) {
        setShowLinkModal(false);
        await loadDetails();
      } else {
        throw new Error(res.error || "Failed to link encounter.");
      }
    } catch (err) {
      setLinkError(err.message || "Failed to link patient.");
    } finally {
      setIsLinkingPatient(false);
    }
  };

  const handleAmendSubmit = async () => {
    if (!amendReason.trim()) {
      alert("A clear clinical reason for amendment is mandatory.");
      return;
    }

    setIsSubmittingAmend(true);
    try {
      const res = await api.amendRecord(recordId, {
        reason: amendReason,
        corrected_transcript: amendText
      });

      if (res.success && res.data) {
        setRecord(res.data);
        setShowAmendModal(false);
        setAmendReason("");
        setSelectedVersionNum(null);
        setVersionSnapshot(null);

        // Reload audit trail & versions
        const [auditRes, verRes] = await Promise.all([
          api.getAuditTrail(recordId),
          api.getRecordVersions(recordId)
        ]);
        if (auditRes.success) setAuditLogs(auditRes.data);
        if (verRes.success) setVersions(verRes.data.versions || []);
      }
    } catch (err) {
      alert(err.message || "Failed to submit amendment.");
    } finally {
      setIsSubmittingAmend(false);
    }
  };

  if (loading) {
    return <div className="p-12 text-center text-slate-500">Loading record details...</div>;
  }

  if (!record) {
    return (
      <div className="p-12 text-center text-red-600">
        Record not found.
        <button onClick={onBack} className="block mx-auto mt-4 text-xs underline">Back</button>
      </div>
    );
  }

  // Active view payload (either historical snapshot or current record)
  const isViewingHistorical = selectedVersionNum !== null && versionSnapshot !== null;
  const activeNarrative = isViewingHistorical
    ? (versionSnapshot.snapshot_data?.corrected_transcript || versionSnapshot.snapshot_data?.machine_transcript || "")
    : (record.corrected_transcript || record.machine_transcript || "No transcript recorded");

  const clinical = isViewingHistorical
    ? (versionSnapshot.snapshot_data?.clinical_data || {})
    : (record.clinical_data || {});

  const audioUrl = api.getAudioUrl(record.audio_filename);
  const pdfDownloadUrl = api.getPdfUrl(record.id, selectedVersionNum);
  const jsonExportUrl = `${api.getPdfUrl(record.id, selectedVersionNum).replace("/export/pdf", "/export/json")}`;

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Top Bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="p-2 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700">
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold text-slate-900">{record.call_number || "Field Record"}</h1>
              <StatusBadge status={record.status} />
              {record.version > 1 && (
                <span className="text-xs bg-purple-100 text-purple-800 font-bold px-2 py-0.5 rounded">
                  Current: v{record.version}
                </span>
              )}
            </div>
            <p className="text-xs text-slate-500 font-mono mt-0.5">{record.id}</p>
          </div>
        </div>

        {/* Version Selector & Action Buttons */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Version Dropdown */}
          {versions.length > 0 && (
            <div className="flex items-center gap-1.5 bg-slate-100 p-1 rounded-lg border border-slate-200">
              <Layers className="w-3.5 h-3.5 text-purple-700 ml-1.5" />
              <select
                value={selectedVersionNum || record.version}
                onChange={(e) => handleSelectVersion(parseInt(e.target.value, 10))}
                className="text-xs font-semibold bg-transparent text-slate-800 pr-1 py-1 focus:outline-none cursor-pointer"
              >
                <option value={record.version}>v{record.version} (Active)</option>
                {versions.map((ver) => (
                  <option key={ver.version_number} value={ver.version_number}>
                    v{ver.version_number} (Snapshot)
                  </option>
                ))}
              </select>
            </div>
          )}

          <button
            onClick={() => onNavigateTimeline(record.id)}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold"
          >
            <Clock className="w-3.5 h-3.5" />
            <span>Timeline</span>
          </button>
          <button
            onClick={() => onNavigateReview(record.id)}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-clinical-teal-50 hover:bg-clinical-teal-100 text-clinical-teal-700 text-xs font-semibold"
          >
            <FileText className="w-3.5 h-3.5" />
            <span>Clinical Review</span>
          </button>
          {record.status === "Approved" && !isViewingHistorical && (
            <button
              onClick={() => setShowAmendModal(true)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-purple-50 hover:bg-purple-100 text-purple-800 text-xs font-semibold"
            >
              <Edit3 className="w-3.5 h-3.5" />
              <span>Amend Record</span>
            </button>
          )}

          {/* Versioned JSON Export */}
          <a
            href={jsonExportUrl}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold"
            title="Download JSON Report"
          >
            <Download className="w-3.5 h-3.5" />
            <span>JSON {isViewingHistorical ? `(v${selectedVersionNum})` : ""}</span>
          </a>

          {/* Hospital Handover PDF (Feature 5) */}
          <a
            href={api.getHandoverPdfUrl(record.id, selectedVersionNum)}
            target="_blank"
            rel="noreferrer"
            download={`handover_${record.id}.pdf`}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-teal-50 hover:bg-teal-100 text-teal-800 border border-teal-200 text-xs font-semibold"
            title="Download printable A4 hospital handover PDF"
          >
            <Download className="w-3.5 h-3.5 text-teal-700" />
            <span>Handover PDF</span>
          </a>

          {/* Versioned PDF Export */}
          <a
            href={pdfDownloadUrl}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-clinical-teal-600 hover:bg-clinical-teal-700 text-white text-xs font-semibold shadow-sm"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Export PDF {isViewingHistorical ? `(v${selectedVersionNum})` : ""}</span>
          </a>
        </div>
      </div>

      {/* Historical Snapshot Viewing Banner */}
      {isViewingHistorical && (
        <div className="p-4 bg-purple-50 border border-purple-200 rounded-xl text-purple-900 flex flex-wrap items-center justify-between gap-3 text-xs shadow-sm">
          <div className="flex items-center gap-2.5">
            <Layers className="w-5 h-5 text-purple-700 shrink-0" />
            <div>
              <span className="font-bold text-sm">
                Viewing Immutable Historical Snapshot: Version {selectedVersionNum}
              </span>
              <p className="text-[11px] text-purple-800 mt-0.5">
                Snapshotted on {new Date(versionSnapshot.snapshotted_at).toLocaleString()}. {versionSnapshot.change_summary || "Audit baseline."}
              </p>
            </div>
          </div>
          <button
            onClick={() => handleSelectVersion(record.version)}
            className="px-3 py-1.5 rounded-lg bg-purple-700 hover:bg-purple-800 text-white font-semibold text-xs shadow-sm"
          >
            Return to Active Version (v{record.version})
          </button>
        </div>
      )}

      {/* Linked Patient Profile Card */}
      {patientInfo ? (
        <div className="bg-clinical-teal-50/80 border border-clinical-teal-200 rounded-xl p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-clinical-teal-600 text-white flex items-center justify-center font-bold">
              <User className="w-4 h-4" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold text-slate-900 text-sm">{patientInfo.full_name}</span>
                <span className="font-mono bg-white px-2 py-0.5 rounded text-clinical-teal-900 font-semibold border border-clinical-teal-200">
                  {patientInfo.patient_id_display}
                </span>
              </div>
              <p className="text-slate-600 mt-0.5">
                DOB: <strong>{patientInfo.date_of_birth || patientInfo.dob}</strong> • Blood: {patientInfo.blood_type || "Unknown"} • Phone: {patientInfo.phone || "N/A"}
              </p>
            </div>
          </div>
          {patientInfo.allergies && patientInfo.allergies.length > 0 && (
            <div className="text-[11px] font-semibold text-rose-700 bg-rose-50 px-2.5 py-1 rounded border border-rose-200 shrink-0">
              Known Allergies: {patientInfo.allergies.join(", ")}
            </div>
          )}
        </div>
      ) : (
        /* Unidentified Encounter Card */
        <div className="bg-amber-50/90 border border-amber-200 rounded-xl p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-amber-500 text-white flex items-center justify-center font-bold">
              <User className="w-4 h-4" />
            </div>
            <div>
              <span className="font-bold text-amber-900 text-sm">
                Unidentified Emergency Field Encounter
              </span>
              <p className="text-amber-800 text-[11px] mt-0.5">
                Captured without registered identity. Can be verified and linked to a persistent patient profile at triage.
              </p>
            </div>
          </div>
          <button
            onClick={handleOpenLinkModal}
            className="px-3.5 py-2 rounded-lg bg-amber-700 hover:bg-amber-800 text-white font-semibold text-xs flex items-center gap-1.5 shadow-sm shrink-0"
          >
            <UserPlus className="w-3.5 h-3.5" />
            <span>Link to Registered Patient</span>
          </button>
        </div>
      )}

      {/* Audio Playback Box */}
      {audioUrl && (
        <div className="bg-slate-900 text-white p-4 rounded-xl flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-sm">
          <div className="flex items-center gap-3">
            <Volume2 className="w-5 h-5 text-clinical-teal-400" />
            <div>
              <p className="text-sm font-semibold">Preserved Field Audio Recording</p>
              <p className="text-xs text-slate-400 font-mono">
                {record.audio_filename} • {record.audio_duration_seconds}s
              </p>
            </div>
          </div>
          <audio controls src={audioUrl} className="h-8 max-w-xs w-full" />
        </div>
      )}

      {/* Field Narrative Card */}
      <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 space-y-3">
        <h2 className="text-sm font-bold text-slate-800 uppercase tracking-wider flex items-center gap-2">
          <FileText className="w-4 h-4 text-clinical-teal-600" />
          <span>
            {isViewingHistorical ? `Snapshot Clinical Narrative (v${selectedVersionNum})` : "Final Verified Clinical Narrative"}
          </span>
        </h2>
        <div className="p-4 bg-slate-50 rounded-lg text-slate-800 text-sm whitespace-pre-wrap font-sans border border-slate-200 font-mono">
          {activeNarrative}
        </div>
      </div>

      {/* Extracted Clinical Data Summary */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Vitals */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-5 space-y-3">
          <h3 className="text-sm font-bold text-slate-900 border-b border-slate-100 pb-2">
            Recorded Vitals
          </h3>
          {clinical.vital_signs?.length > 0 ? (
            <div className="space-y-2">
              {clinical.vital_signs.map((v) => (
                <div key={v.id} className="flex items-center justify-between p-2.5 bg-slate-50 rounded-lg text-xs">
                  <span className="font-semibold text-slate-700">{v.name}</span>
                  <span className="font-bold text-clinical-teal-800 font-mono text-sm">
                    {v.value} {v.unit}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-slate-400 italic">No vitals captured.</p>
          )}
        </div>

        {/* Medications */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-5 space-y-3">
          <h3 className="text-sm font-bold text-slate-900 border-b border-slate-100 pb-2">
            Medications Administered
          </h3>
          {clinical.medications?.length > 0 ? (
            <div className="space-y-2">
              {clinical.medications.map((m) => (
                <div key={m.id} className="p-2.5 bg-slate-50 rounded-lg text-xs flex items-center justify-between">
                  <div>
                    <span className="font-bold text-slate-800">{m.canonical_name || m.raw_mention}</span>
                    <span className="text-slate-500 ml-2">
                      {m.dosage || ""} {m.unit || ""} {m.route ? `via ${m.route}` : ""}
                    </span>
                  </div>
                  <span className={m.is_negated ? "text-rose-600 font-bold" : "text-emerald-700 font-bold"}>
                    {m.is_negated ? "WITHHELD" : "ADMINISTERED"}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-slate-400 italic">No medications recorded.</p>
          )}
        </div>
        {/* Examinations & Physical Observations */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-5 space-y-3 md:col-span-2">
          <h3 className="text-sm font-bold text-slate-900 border-b border-slate-100 pb-2">
            Clinical Examinations & Physical Observations
          </h3>
          {clinical.examinations?.length > 0 ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
              {clinical.examinations.map((ex) => (
                <div key={ex.id} className="p-2.5 bg-slate-50 rounded-lg text-xs flex items-center justify-between border border-slate-200">
                  <div>
                    <span className="font-semibold text-slate-800">{ex.finding || ex.system}</span>
                    <span className="text-slate-500 ml-2">({ex.system})</span>
                  </div>
                  <span className="font-bold text-clinical-teal-800 font-mono">
                    {ex.value || "Normal"}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-slate-400 italic">No specific physical examinations recorded.</p>
          )}
        </div>
      </div>

      {/* Immutable Version Snapshots */}
      {versions.length > 0 && (
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 space-y-4">
          <h2 className="text-sm font-bold text-slate-900 uppercase tracking-wider flex items-center gap-2">
            <Layers className="w-4 h-4 text-clinical-teal-600" />
            <span>Immutable Version History Snapshots ({versions.length})</span>
          </h2>

          <div className="space-y-2">
            {versions.map((ver) => (
              <div
                key={ver.version_number}
                className={`p-3 rounded-lg border text-xs flex flex-wrap items-center justify-between gap-3 transition-colors ${
                  selectedVersionNum === ver.version_number
                    ? "bg-purple-50 border-purple-300"
                    : "bg-slate-50 border-slate-200"
                }`}
              >
                <div>
                  <span className="font-bold text-slate-900">Version {ver.version_number}</span>
                  <span className="text-slate-500 ml-2">
                    Snapshotted at: {new Date(ver.snapshotted_at).toLocaleString()}
                  </span>
                  {ver.change_summary && (
                    <p className="text-slate-600 text-[11px] mt-0.5 italic">{ver.change_summary}</p>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleSelectVersion(ver.version_number)}
                    className="px-2.5 py-1 rounded bg-purple-100 hover:bg-purple-200 text-purple-800 text-[11px] font-semibold"
                  >
                    {selectedVersionNum === ver.version_number ? "Currently Viewing" : "Inspect Snapshot"}
                  </button>
                  <a
                    href={api.getPdfUrl(record.id, ver.version_number)}
                    target="_blank"
                    rel="noreferrer"
                    className="p-1 rounded text-slate-500 hover:text-slate-800"
                    title={`Download Version ${ver.version_number} PDF`}
                  >
                    <Download className="w-3.5 h-3.5" />
                  </a>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Immutable Audit Trail Section */}
      <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 space-y-4">
        <h2 className="text-sm font-bold text-slate-900 uppercase tracking-wider flex items-center gap-2">
          <History className="w-4 h-4 text-clinical-teal-600" />
          <span>Immutable Traceability & Audit Log ({auditLogs.length})</span>
        </h2>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 text-slate-600 font-semibold border-b border-slate-200">
              <tr>
                <th className="px-4 py-2.5">Timestamp (UTC)</th>
                <th className="px-4 py-2.5">Action</th>
                <th className="px-4 py-2.5">Actor</th>
                <th className="px-4 py-2.5">Payload Diff / Event Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 font-mono">
              {auditLogs.map((log) => (
                <tr key={log.id} className="hover:bg-slate-50/60">
                  <td className="px-4 py-2.5 text-slate-500 whitespace-nowrap">
                    {new Date(log.timestamp).toLocaleString()}
                  </td>
                  <td className="px-4 py-2.5 font-bold text-slate-800">{log.action}</td>
                  <td className="px-4 py-2.5 text-clinical-teal-700 font-semibold">{log.actor}</td>
                  <td className="px-4 py-2.5 text-slate-600 max-w-sm truncate">
                    {JSON.stringify(log.details)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Link to Registered Patient Modal */}
      {showLinkModal && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <UserPlus className="w-5 h-5 text-amber-600" />
                <h3 className="text-base font-bold text-slate-900">
                  Link Encounter to Patient Profile
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setShowLinkModal(false)}
                className="text-slate-400 hover:text-slate-700"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <p className="text-xs text-slate-600">
              Attach this field record ({record.call_number}) to a verified patient profile. Encounter classification will be recorded as <strong>NEW_ENCOUNTER</strong> in their history.
            </p>

            {linkError && (
              <div className="p-2.5 bg-red-50 text-red-800 border border-red-200 rounded text-xs">
                {linkError}
              </div>
            )}

            <div className="space-y-1">
              <label className="text-xs font-bold text-slate-700 uppercase">Select Registered Patient</label>
              <select
                value={targetPatientId}
                onChange={(e) => setTargetPatientId(e.target.value)}
                className="w-full p-2.5 rounded-lg border border-slate-300 text-xs focus:ring-2 focus:ring-amber-500 bg-white"
              >
                <option value="">-- Choose Patient Candidate --</option>
                {availablePatients.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.full_name} ({p.patient_id_display}) • DOB: {p.date_of_birth || p.dob}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex justify-end gap-2.5 pt-2">
              <button
                onClick={() => setShowLinkModal(false)}
                className="px-4 py-2 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold"
              >
                Cancel
              </button>
              <button
                onClick={handleLinkPatientSubmit}
                disabled={isLinkingPatient || !targetPatientId}
                className="px-5 py-2 rounded-lg bg-amber-600 hover:bg-amber-700 disabled:bg-slate-300 text-white text-xs font-semibold shadow-md"
              >
                {isLinkingPatient ? "Linking..." : "Confirm & Link Patient"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Amendment Modal */}
      {showAmendModal && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-4">
            <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
              <Edit3 className="w-5 h-5 text-purple-600" />
              <span>Traceable Clinical Record Amendment</span>
            </h3>
            <p className="text-xs text-slate-600">
              Approved medical records cannot be overwritten silently. Any amendment creates a new version (v{record.version + 1}) and logs an immutable audit trail entry. All clinical entities will be re-extracted.
            </p>

            <div className="space-y-1">
              <label className="text-xs font-bold text-slate-700 uppercase">Reason for Amendment (Mandatory)</label>
              <input
                type="text"
                value={amendReason}
                onChange={(e) => setAmendReason(e.target.value)}
                placeholder="e.g. Added secondary vital signs recorded by triage..."
                className="w-full p-2.5 rounded-lg border border-slate-300 text-xs focus:ring-2 focus:ring-purple-500"
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs font-bold text-slate-700 uppercase">Updated Narrative</label>
              <textarea
                rows={4}
                value={amendText}
                onChange={(e) => setAmendText(e.target.value)}
                className="w-full p-2.5 rounded-lg border border-slate-300 text-xs focus:ring-2 focus:ring-purple-500"
              />
            </div>

            <div className="flex justify-end gap-2.5 pt-2">
              <button
                onClick={() => setShowAmendModal(false)}
                className="px-4 py-2 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold"
              >
                Cancel
              </button>
              <button
                onClick={handleAmendSubmit}
                disabled={isSubmittingAmend || !amendReason.trim()}
                className="px-5 py-2 rounded-lg bg-purple-700 hover:bg-purple-800 disabled:bg-slate-300 text-white text-xs font-semibold shadow-md"
              >
                {isSubmittingAmend ? "Submitting..." : "Submit Amendment"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
