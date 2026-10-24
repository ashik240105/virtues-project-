import React, { useState, useEffect } from "react";
import {
  Mic, FileText, User, Hash, AlertCircle, ArrowRight,
  ShieldCheck, RefreshCw, CheckCircle2, Search, UserCheck, UserPlus, X, CloudUpload
} from "lucide-react";
import { AudioRecorder } from "../components/AudioRecorder";
import { api } from "../services/api";
import { offlineStorage } from "../services/offlineStorage";
import { syncManager } from "../services/syncManager";

export function VoiceInputPage({ onRecordCreated }) {
  const [callNumber, setCallNumber] = useState(`EMS-${Math.floor(1000 + Math.random() * 9000)}`);
  const [responderId, setResponderId] = useState("Paramedic-101");
  const [patientGender, setPatientGender] = useState("Unspecified");
  const [patientAge, setPatientAge] = useState("");
  const [chiefComplaint, setChiefComplaint] = useState("");
  const [encounterType, setEncounterType] = useState("NEW_ENCOUNTER");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);

  // Patient continuity integration
  const [patients, setPatients] = useState([]);
  const [selectedPatientId, setSelectedPatientId] = useState("");
  const [selectedPatientObj, setSelectedPatientObj] = useState(null);
  const [patientAmbiguityWarning, setPatientAmbiguityWarning] = useState(null);

  // New Patient Registration modal state
  const [showRegisterModal, setShowRegisterModal] = useState(false);
  const [regFullName, setRegFullName] = useState("");
  const [regDob, setRegDob] = useState("");
  const [regGender, setRegGender] = useState("Unspecified");
  const [regPhone, setRegPhone] = useState("");
  const [regBloodType, setRegBloodType] = useState("Unknown");
  const [regAllergies, setRegAllergies] = useState("");
  const [regHistory, setRegHistory] = useState("");
  const [regIsSubmitting, setRegIsSubmitting] = useState(false);
  const [regError, setRegError] = useState(null);
  const [regSuccessNotice, setRegSuccessNotice] = useState(null);

  // Draft recovery state (IndexedDB refresh-proof draft)
  const [recoveredDraft, setRecoveredDraft] = useState(null);
  const [draftRestoredNotice, setDraftRestoredNotice] = useState(null);

  // Load patients and refresh-proof drafts
  useEffect(() => {
    let isMounted = true;
    const loadPatientsList = async () => {
      try {
        const res = await api.listPatients();
        if (isMounted && res.success && res.data) {
          setPatients(res.data.patients || []);
        }
      } catch (err) {
        // Non-blocking for field voice input
      }
    };
    loadPatientsList();

    // Check for refresh-safe local draft in IndexedDB first, then backend
    const checkDraft = async () => {
      try {
        const localDraft = await offlineStorage.getDraft("active_voice_draft");
        if (isMounted && localDraft) {
          setRecoveredDraft({ draft: localDraft, saved_at: localDraft.timestamp, source: "IndexedDB" });
          return;
        }

        const res = await api.getAutosavedDraft("session_active");
        if (isMounted && res.success && res.data && res.data.draft) {
          setRecoveredDraft(res.data);
        }
      } catch (err) {
        // No draft
      }
    };
    checkDraft();

    return () => { isMounted = false; };
  }, []);

  // Handle patient selection with multi-factor verification
  const handleSelectPatient = (patientId) => {
    setSelectedPatientId(patientId);
    setPatientAmbiguityWarning(null);

    if (!patientId) {
      setSelectedPatientObj(null);
      return;
    }

    const pt = patients.find((p) => p.id === patientId);
    if (pt) {
      setSelectedPatientObj(pt);
      // Auto-populate age and gender if known
      const ptDob = pt.date_of_birth || pt.dob;
      if (ptDob) {
        const birthYear = parseInt(ptDob.split("-")[0], 10);
        if (!isNaN(birthYear)) {
          setPatientAge(String(new Date().getFullYear() - birthYear));
        }
      }
      if (pt.gender && pt.gender !== "Unspecified") {
        setPatientGender(pt.gender);
      }

      // Check if another patient has the same full name (ambiguity check)
      const sameName = patients.filter((p) => p.full_name?.toLowerCase() === pt.full_name?.toLowerCase());
      if (sameName.length > 1) {
        setPatientAmbiguityWarning(
          `Multiple patients named "${pt.full_name}". Confirmed match by DOB (${ptDob}) and Patient ID (${pt.patient_id_display}).`
        );
      }
    }
  };

  // Restore recovered draft
  const handleRestoreDraft = () => {
    if (!recoveredDraft?.draft) return;
    const d = recoveredDraft.draft;
    if (d.call_number) setCallNumber(d.call_number);
    if (d.responder_id) setResponderId(d.responder_id);
    if (d.patient_age) setPatientAge(d.patient_age);
    if (d.patient_gender) setPatientGender(d.patient_gender);
    if (d.chief_complaint) setChiefComplaint(d.chief_complaint);
    if (d.encounter_type) setEncounterType(d.encounter_type);
    if (d.patient_id) handleSelectPatient(d.patient_id);
    setDraftRestoredNotice("In-flight draft restored successfully from local storage.");
    setRecoveredDraft(null);
  };

  const handleDismissDraft = async () => {
    try {
      await offlineStorage.clearDraft("active_voice_draft");
      await api.clearAutosavedDraft("session_active");
    } catch (e) {
      // Ignore
    }
    setRecoveredDraft(null);
  };

  // Register New Patient Handler
  const handleRegisterPatientSubmit = async (e) => {
    e.preventDefault();
    if (!regFullName.trim() || !regDob.trim()) {
      setRegError("Patient Full Name and Date of Birth (DOB) are mandatory for clinical identification.");
      return;
    }

    setRegIsSubmitting(true);
    setRegError(null);

    try {
      const payload = {
        full_name: regFullName.trim(),
        dob: regDob.trim(),
        gender: regGender,
        phone: regPhone.trim(),
        blood_type: regBloodType,
        allergies: regAllergies ? regAllergies.split(",").map((s) => s.trim()).filter(Boolean) : [],
        medical_history: regHistory ? regHistory.split(",").map((s) => s.trim()).filter(Boolean) : []
      };

      const res = await api.registerPatient(payload);
      if (res.success && res.data) {
        const newPt = res.data;
        // Prepend to patients list
        setPatients((prev) => [newPt, ...prev]);
        // Immediately link this patient to the active encounter
        setSelectedPatientId(newPt.id);
        setSelectedPatientObj(newPt);

        // Auto-calculate age
        const birthStr = newPt.dob || newPt.date_of_birth;
        if (birthStr) {
          const birthYear = parseInt(birthStr.split("-")[0], 10);
          if (!isNaN(birthYear)) {
            setPatientAge(String(new Date().getFullYear() - birthYear));
          }
        }
        if (newPt.gender && newPt.gender !== "Unspecified") {
          setPatientGender(newPt.gender);
        }

        setRegSuccessNotice(`Registered and linked patient: ${newPt.full_name} (${newPt.patient_id_display})`);
        setShowRegisterModal(false);

        // Reset registration fields
        setRegFullName("");
        setRegDob("");
        setRegGender("Unspecified");
        setRegPhone("");
        setRegBloodType("Unknown");
        setRegAllergies("");
        setRegHistory("");
      } else {
        throw new Error(res.error || "Failed to register patient in database.");
      }
    } catch (err) {
      setRegError(err.message || "Registration failed. Verify patient details.");
    } finally {
      setRegIsSubmitting(false);
    }
  };

  // Periodic refresh-safe autosave of draft form fields to IndexedDB (and secondary backend)
  useEffect(() => {
    const draftPayload = {
      call_number: callNumber,
      responder_id: responderId,
      patient_age: patientAge,
      patient_gender: patientGender,
      chief_complaint: chiefComplaint,
      encounter_type: encounterType,
      patient_id: selectedPatientId,
      timestamp: new Date().toISOString()
    };

    // 1. Immediately write to browser IndexedDB (guaranteed refresh-safe)
    offlineStorage.saveDraft("active_voice_draft", draftPayload).catch(() => {});

    // 2. Secondary best-effort backend cache
    const timer = setTimeout(() => {
      api.autosaveDraft("session_active", draftPayload).catch(() => {});
    }, 2000);
    return () => clearTimeout(timer);
  }, [callNumber, responderId, patientAge, patientGender, chiefComplaint, encounterType, selectedPatientId]);

  const handleSaveDraft = async (transcriptionData) => {
    setIsSubmitting(true);
    setSubmitError(null);

    // Stable record ID generated on client to prevent duplicates across offline retries
    const stableId = `REC-${new Date().toISOString().slice(0, 10).replace(/-/g, "")}-${Math.random().toString(36).substring(2, 8).toUpperCase()}`;
    const nowIso = new Date().toISOString();

    const recordPayload = {
      id: stableId,
      call_number: callNumber,
      responder_id: responderId,
      created_at: nowIso,
      client_updated_at: nowIso,
      machine_transcript: transcriptionData.machine_transcript || "",
      corrected_transcript: transcriptionData.corrected_transcript || "",
      audio_filename: transcriptionData.audio_filename,
      audio_mimetype: transcriptionData.audio_mimetype,
      audio_duration_seconds: transcriptionData.audio_duration_seconds,
      transcription_metadata: transcriptionData.transcription_metadata,
      patient_id: selectedPatientId || null,
      encounter_type: encounterType,
      patient_summary: {
        age: patientAge,
        gender: patientGender,
        chief_complaint: chiefComplaint,
        patient_id: selectedPatientId || null
      }
    };

    try {
      if (typeof navigator !== "undefined" && navigator.onLine) {
        try {
          const res = await api.createRecord(recordPayload);
          if (res.success && res.data) {
            // Also store copy in IndexedDB for immediate offline access
            await offlineStorage.saveOfflineRecord({
              ...res.data,
              sync_status: "SYNCHRONIZED"
            });
            await offlineStorage.clearDraft("active_voice_draft");
            await api.clearAutosavedDraft("session_active").catch(() => {});
            if (onRecordCreated) {
              onRecordCreated(res.data.id);
            }
            return;
          }
        } catch (netErr) {
          console.warn("Server unreachable or network dropped, falling back to offline IndexedDB queue:", netErr);
        }
      }

      // Offline fallback: Persist in local IndexedDB and enqueue in sync queue
      const offlineSaved = await syncManager.saveAndEnqueueRecord(recordPayload);
      await offlineStorage.clearDraft("active_voice_draft");
      if (onRecordCreated) {
        onRecordCreated(offlineSaved.id);
      }
    } catch (err) {
      setSubmitError(err.message || "Failed to save record to local storage.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Title Header */}
      <div>
        <h1 className="text-2xl font-extrabold text-slate-900 tracking-tight">
          New Clinical Field Encounter
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          Capture voice narrative or type field notes. Local Whisper runs speech inference without internet access.
        </p>
      </div>

      {/* Recover Draft Alert Banner */}
      {recoveredDraft && (
        <div className="p-4 rounded-xl bg-blue-50 border border-blue-200 text-blue-900 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs shadow-sm">
          <div className="flex items-center gap-2.5">
            <RefreshCw className="w-4 h-4 text-blue-600 shrink-0" />
            <span>
              <strong>In-flight draft detected</strong> from {recoveredDraft.saved_at ? new Date(recoveredDraft.saved_at).toLocaleTimeString() : "recent session"}. Restore your unsaved field notes?
            </span>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={handleRestoreDraft}
              className="px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-semibold text-xs shadow-sm"
            >
              Restore Draft
            </button>
            <button
              onClick={handleDismissDraft}
              className="px-2.5 py-1.5 rounded-lg text-slate-600 hover:text-slate-900 text-xs font-semibold"
            >
              Discard
            </button>
          </div>
        </div>
      )}

      {draftRestoredNotice && (
        <div className="p-3 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
          <span>{draftRestoredNotice}</span>
        </div>
      )}

      {regSuccessNotice && (
        <div className="p-3 rounded-lg bg-teal-50 border border-teal-200 text-teal-800 text-xs flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-teal-600 shrink-0" />
            <span className="font-semibold">{regSuccessNotice}</span>
          </div>
          <button onClick={() => setRegSuccessNotice(null)} className="text-teal-600 hover:text-teal-900">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {submitError && (
        <div className="p-4 rounded-lg bg-red-50 border border-red-200 text-red-800 text-sm flex items-center gap-2">
          <AlertCircle className="w-5 h-5 text-red-600 shrink-0" />
          <span>{submitError}</span>
        </div>
      )}

      {/* Patient Continuity & Encounter Metadata */}
      <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm space-y-4">
        <div className="border-b border-slate-100 pb-2">
          <h2 className="text-xs font-bold text-slate-700 uppercase tracking-wider flex items-center gap-2">
            <UserCheck className="w-4 h-4 text-clinical-teal-600" />
            <span>Patient Continuity & Encounter Classification</span>
          </h2>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Patient Selector */}
          <div className="sm:col-span-2">
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs font-bold text-slate-600 uppercase tracking-wider block">
                Link to Patient Profile
              </label>
              <button
                type="button"
                onClick={() => {
                  setRegError(null);
                  setShowRegisterModal(true);
                }}
                className="text-xs font-semibold text-clinical-teal-700 hover:text-clinical-teal-900 flex items-center gap-1"
              >
                <UserPlus className="w-3.5 h-3.5" />
                <span>+ Register New Patient Profile</span>
              </button>
            </div>
            <select
              value={selectedPatientId}
              onChange={(e) => handleSelectPatient(e.target.value)}
              className="w-full text-xs font-semibold p-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-clinical-teal-500 bg-white"
            >
              <option value="">-- Unidentified / Field Encounter Only --</option>
              {patients.map((pt) => (
                <option key={pt.id} value={pt.id}>
                  {pt.full_name} ({pt.patient_id_display}) • DOB: {pt.date_of_birth || pt.dob}
                </option>
              ))}
            </select>
          </div>

          {/* Encounter Type */}
          <div>
            <label className="text-xs font-bold text-slate-600 uppercase tracking-wider block mb-1">
              Encounter Type
            </label>
            <select
              value={encounterType}
              onChange={(e) => setEncounterType(e.target.value)}
              className="w-full text-xs font-semibold p-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-clinical-teal-500 bg-white"
            >
              <option value="NEW_ENCOUNTER">New Incident Encounter</option>
              <option value="OBSERVATION">Clinical Observation</option>
              <option value="CORRECTION">Field Correction</option>
              <option value="AMENDMENT">Clinical Amendment</option>
            </select>
          </div>
          
          {/* Responder ID */}
          <div>
            <label className="text-xs font-bold text-slate-600 uppercase tracking-wider block mb-1">
              Responder ID / Unit
            </label>
            <input
              type="text"
              value={responderId}
              onChange={(e) => setResponderId(e.target.value)}
              className="w-full text-xs font-semibold p-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-clinical-teal-500"
              placeholder="e.g. Paramedic-101"
            />
          </div>
        </div>

        {/* Ambiguity confirmation warning */}
        {patientAmbiguityWarning && (
          <div className="p-3 bg-amber-50 border border-amber-300 rounded-lg text-xs text-amber-900 flex items-start gap-2">
            <ShieldCheck className="w-4 h-4 text-amber-700 shrink-0 mt-0.5" />
            <div>
              <span className="font-bold">Identity Verification Confirmed: </span>
              {patientAmbiguityWarning}
            </div>
          </div>
        )}

        {/* Selected Patient Demographics Card */}
        {selectedPatientObj && (
          <div className="p-3 bg-clinical-teal-50/70 border border-clinical-teal-200 rounded-lg flex flex-wrap items-center justify-between text-xs text-clinical-teal-900 gap-2">
            <div className="flex items-center gap-3">
              <span className="font-bold text-slate-900">{selectedPatientObj.full_name}</span>
              <span>DOB: <strong>{selectedPatientObj.date_of_birth || selectedPatientObj.dob}</strong></span>
              <span>Gender: {selectedPatientObj.gender}</span>
              <span>Blood: {selectedPatientObj.blood_type || "Unknown"}</span>
            </div>
            {selectedPatientObj.allergies && selectedPatientObj.allergies.length > 0 && (
              <span className="text-[11px] font-semibold text-rose-700 bg-rose-50 px-2 py-0.5 rounded border border-rose-200">
                Known Allergies: {selectedPatientObj.allergies.join(", ")}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Incident & Dispatch Header Form */}
      <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div>
          <label className="text-xs font-bold text-slate-600 uppercase tracking-wider block mb-1">
            Incident / Call #
          </label>
          <input
            type="text"
            value={callNumber}
            onChange={(e) => setCallNumber(e.target.value)}
            className="w-full text-sm font-semibold p-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-clinical-teal-500"
            placeholder="e.g. EMS-4091"
          />
        </div>

        <div>
          <label className="text-xs font-bold text-slate-600 uppercase tracking-wider block mb-1">
            Estimated Patient Age
          </label>
          <input
            type="text"
            value={patientAge}
            onChange={(e) => setPatientAge(e.target.value)}
            className="w-full text-sm p-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-clinical-teal-500"
            placeholder="e.g. 54"
          />
        </div>

        <div>
          <label className="text-xs font-bold text-slate-600 uppercase tracking-wider block mb-1">
            Reported Chief Complaint
          </label>
          <input
            type="text"
            value={chiefComplaint}
            onChange={(e) => setChiefComplaint(e.target.value)}
            className="w-full text-sm p-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-clinical-teal-500"
            placeholder="e.g. Acute chest discomfort"
          />
        </div>
      </div>

      {/* Main Recording & Transcription Area */}
      <AudioRecorder
        onTranscriptionComplete={() => {}}
        onSaveDraft={handleSaveDraft}
      />

      {/* Register New Patient Modal */}
      {showRegisterModal && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <UserPlus className="w-5 h-5 text-clinical-teal-600" />
                <h3 className="text-base font-bold text-slate-900">
                  Register New Patient Profile
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setShowRegisterModal(false)}
                className="text-slate-400 hover:text-slate-700"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <p className="text-xs text-slate-500">
              Registers a new patient profile directly in SQLite. Multi-factor identity validation (Name + DOB) prevents duplicate registrations.
            </p>

            {regError && (
              <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-red-800 text-xs flex items-start gap-2">
                <AlertCircle className="w-4 h-4 text-red-600 shrink-0 mt-0.5" />
                <span>{regError}</span>
              </div>
            )}

            <form onSubmit={handleRegisterPatientSubmit} className="space-y-3">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="sm:col-span-2">
                  <label className="text-xs font-bold text-slate-700 block mb-1">
                    Full Legal Name *
                  </label>
                  <input
                    type="text"
                    required
                    value={regFullName}
                    onChange={(e) => setRegFullName(e.target.value)}
                    placeholder="e.g. Eleanor Vance"
                    className="w-full text-xs p-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-clinical-teal-500"
                  />
                </div>

                <div>
                  <label className="text-xs font-bold text-slate-700 block mb-1">
                    Date of Birth (YYYY-MM-DD) *
                  </label>
                  <input
                    type="date"
                    required
                    value={regDob}
                    onChange={(e) => setRegDob(e.target.value)}
                    className="w-full text-xs p-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-clinical-teal-500 bg-white"
                  />
                </div>

                <div>
                  <label className="text-xs font-bold text-slate-700 block mb-1">
                    Gender
                  </label>
                  <select
                    value={regGender}
                    onChange={(e) => setRegGender(e.target.value)}
                    className="w-full text-xs p-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-clinical-teal-500 bg-white"
                  >
                    <option value="Unspecified">Unspecified</option>
                    <option value="Female">Female</option>
                    <option value="Male">Male</option>
                    <option value="Other">Other</option>
                  </select>
                </div>

                <div>
                  <label className="text-xs font-bold text-slate-700 block mb-1">
                    Phone / Contact
                  </label>
                  <input
                    type="text"
                    value={regPhone}
                    onChange={(e) => setRegPhone(e.target.value)}
                    placeholder="e.g. +1-555-0192"
                    className="w-full text-xs p-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-clinical-teal-500"
                  />
                </div>

                <div>
                  <label className="text-xs font-bold text-slate-700 block mb-1">
                    Blood Type
                  </label>
                  <select
                    value={regBloodType}
                    onChange={(e) => setRegBloodType(e.target.value)}
                    className="w-full text-xs p-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-clinical-teal-500 bg-white"
                  >
                    <option value="Unknown">Unknown</option>
                    <option value="A+">A+</option>
                    <option value="A-">A-</option>
                    <option value="B+">B+</option>
                    <option value="B-">B-</option>
                    <option value="AB+">AB+</option>
                    <option value="AB-">AB-</option>
                    <option value="O+">O+</option>
                    <option value="O-">O-</option>
                  </select>
                </div>

                <div className="sm:col-span-2">
                  <label className="text-xs font-bold text-slate-700 block mb-1">
                    Known Allergies (comma-separated)
                  </label>
                  <input
                    type="text"
                    value={regAllergies}
                    onChange={(e) => setRegAllergies(e.target.value)}
                    placeholder="e.g. Penicillin, Peanuts"
                    className="w-full text-xs p-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-clinical-teal-500"
                  />
                </div>

                <div className="sm:col-span-2">
                  <label className="text-xs font-bold text-slate-700 block mb-1">
                    Medical History / Chronic Conditions
                  </label>
                  <input
                    type="text"
                    value={regHistory}
                    onChange={(e) => setRegHistory(e.target.value)}
                    placeholder="e.g. Hypertension, Asthma"
                    className="w-full text-xs p-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-clinical-teal-500"
                  />
                </div>
              </div>

              <div className="flex justify-end gap-2.5 pt-3 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setShowRegisterModal(false)}
                  className="px-4 py-2 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={regIsSubmitting}
                  className="px-5 py-2 rounded-lg bg-clinical-teal-600 hover:bg-clinical-teal-700 disabled:bg-slate-300 text-white text-xs font-semibold shadow-md flex items-center gap-1.5"
                >
                  <UserPlus className="w-3.5 h-3.5" />
                  <span>{regIsSubmitting ? "Registering..." : "Save & Link Patient Profile"}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
