import React, { useState, useEffect } from "react";
import {
  Users, Search, UserPlus, FileText, Calendar, Phone, Heart,
  AlertTriangle, CheckCircle2, ChevronRight, Clock, ShieldCheck,
  Activity, X, ArrowLeft
} from "lucide-react";
import { api } from "../services/api";

export function PatientsPage({ onSelectRecord }) {
  const [patients, setPatients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [successMsg, setSuccessMsg] = useState(null);

  // Search state
  const [searchName, setSearchName] = useState("");
  const [searchDob, setSearchDob] = useState("");
  const [searchPhone, setSearchPhone] = useState("");
  const [searchPatientId, setSearchPatientId] = useState("");
  const [isSearching, setIsSearching] = useState(false);
  const [searchWarning, setSearchWarning] = useState(null);

  // Selected patient details
  const [selectedPatient, setSelectedPatient] = useState(null);
  const [encounters, setEncounters] = useState([]);
  const [loadingHistory, setLoadingHistory] = useState(false);

  // New patient modal
  const [showNewModal, setShowNewModal] = useState(false);
  const [newPatient, setNewPatient] = useState({
    first_name: "",
    last_name: "",
    date_of_birth: "",
    gender: "Unspecified",
    phone: "",
    blood_type: "Unknown",
    allergies: "",
    medical_history: "",
    emergency_contact: ""
  });
  const [savingNew, setSavingNew] = useState(false);

  // Load patient list
  const loadPatients = async (queryFilters = {}) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listPatients(queryFilters);
      if (res.success && res.data) {
        setPatients(res.data.patients || []);
        if (res.data.warning) {
          setSearchWarning(res.data.warning);
        } else {
          setSearchWarning(null);
        }
      }
    } catch (err) {
      setError(err.message || "Failed to load patient registry.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadPatients();
  }, []);

  // Multi-factor search handler
  const handleSearch = async (e) => {
    if (e) e.preventDefault();
    setIsSearching(true);
    const filters = {};
    if (searchName.trim()) filters.name = searchName.trim();
    if (searchDob.trim()) filters.dob = searchDob.trim();
    if (searchPhone.trim()) filters.phone = searchPhone.trim();
    if (searchPatientId.trim()) filters.patient_id = searchPatientId.trim();

    await loadPatients(filters);
    setIsSearching(false);
  };

  const handleClearSearch = () => {
    setSearchName("");
    setSearchDob("");
    setSearchPhone("");
    setSearchPatientId("");
    setSearchWarning(null);
    loadPatients();
  };

  // Select patient to view details and longitudinal encounters
  const handleSelectPatient = async (pt) => {
    setSelectedPatient(pt);
    setLoadingHistory(true);
    try {
      const res = await api.getPatientHistory(pt.id);
      if (res.success && res.data) {
        setEncounters(res.data.encounters || []);
        if (res.data.patient) {
          setSelectedPatient((prev) => ({ ...prev, ...res.data.patient }));
        }
      }
    } catch (err) {
      setError("Failed to load patient encounter history.");
    } finally {
      setLoadingHistory(false);
    }
  };

  // Register new patient
  const handleCreatePatient = async (e) => {
    e.preventDefault();
    if (!newPatient.first_name || !newPatient.last_name || !newPatient.date_of_birth) {
      alert("First name, last name, and date of birth are required.");
      return;
    }
    setSavingNew(true);
    setError(null);
    try {
      const payload = {
        first_name: newPatient.first_name,
        last_name: newPatient.last_name,
        date_of_birth: newPatient.date_of_birth,
        gender: newPatient.gender,
        phone: newPatient.phone,
        blood_type: newPatient.blood_type,
        allergies: newPatient.allergies.split(",").map((s) => s.trim()).filter(Boolean),
        medical_history: newPatient.medical_history.split(",").map((s) => s.trim()).filter(Boolean),
        emergency_contacts: newPatient.emergency_contact
          ? [{ name: newPatient.emergency_contact, relationship: "Primary", phone: newPatient.phone }]
          : []
      };

      const res = await api.registerPatient(payload);
      if (res.success && res.data) {
        setSuccessMsg(`Patient ${res.data.patient_id_display} (${res.data.full_name}) registered successfully.`);
        setShowNewModal(false);
        setNewPatient({
          first_name: "",
          last_name: "",
          date_of_birth: "",
          gender: "Unspecified",
          phone: "",
          blood_type: "Unknown",
          allergies: "",
          medical_history: "",
          emergency_contact: ""
        });
        loadPatients();
      }
    } catch (err) {
      setError(err.message || "Failed to register patient.");
    } finally {
      setSavingNew(false);
    }
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-extrabold text-slate-900 tracking-tight">
              Patient Continuity Engine
            </h1>
            <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-clinical-teal-100 text-clinical-teal-800 border border-clinical-teal-200">
              Offline EHR Registry
            </span>
          </div>
          <p className="text-sm text-slate-500 mt-1">
            Persistent patient records, multi-factor identity verification, and longitudinal field encounter tracking.
          </p>
        </div>

        <button
          onClick={() => setShowNewModal(true)}
          className="flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-clinical-teal-600 hover:bg-clinical-teal-700 text-white text-sm font-semibold shadow-sm transition-colors"
        >
          <UserPlus className="w-4 h-4" />
          <span>Register New Patient</span>
        </button>
      </div>

      {/* Notifications */}
      {error && (
        <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-800 text-sm flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-red-600 shrink-0 mt-0.5" />
          <div className="flex-1">{error}</div>
        </div>
      )}
      {successMsg && (
        <div className="p-4 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-sm flex items-center gap-2">
          <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0" />
          <span>{successMsg}</span>
        </div>
      )}

      {/* Multi-Factor Search Card */}
      <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-5 space-y-4">
        <div className="flex items-center justify-between border-b border-slate-100 pb-3">
          <h2 className="text-sm font-bold text-slate-800 flex items-center gap-2">
            <Search className="w-4 h-4 text-clinical-teal-600" />
            <span>Multi-Factor Identity Search</span>
          </h2>
          <span className="text-[11px] text-slate-400">
            Rule: Multi-factor verification required. Never match patient by name alone.
          </span>
        </div>

        <form onSubmit={handleSearch} className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <div>
            <label className="block text-xs font-semibold text-slate-600 mb-1">Full / Partial Name</label>
            <input
              type="text"
              value={searchName}
              onChange={(e) => setSearchName(e.target.value)}
              placeholder="e.g. Eleanor Vance"
              className="w-full text-xs p-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-clinical-teal-500"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-600 mb-1">Date of Birth (YYYY-MM-DD)</label>
            <input
              type="text"
              value={searchDob}
              onChange={(e) => setSearchDob(e.target.value)}
              placeholder="e.g. 1958-03-14"
              className="w-full text-xs p-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-clinical-teal-500"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-600 mb-1">Phone Number</label>
            <input
              type="text"
              value={searchPhone}
              onChange={(e) => setSearchPhone(e.target.value)}
              placeholder="e.g. 555-0149"
              className="w-full text-xs p-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-clinical-teal-500"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-600 mb-1">Persistent Patient ID</label>
            <input
              type="text"
              value={searchPatientId}
              onChange={(e) => setSearchPatientId(e.target.value)}
              placeholder="e.g. PT-1001"
              className="w-full text-xs p-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-clinical-teal-500"
            />
          </div>

          <div className="sm:col-span-2 lg:col-span-4 flex items-center justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={handleClearSearch}
              className="px-3.5 py-2 text-xs font-semibold text-slate-600 hover:text-slate-900 bg-slate-100 hover:bg-slate-200 rounded-lg"
            >
              Reset Search
            </button>
            <button
              type="submit"
              disabled={isSearching}
              className="flex items-center gap-1.5 px-4 py-2 bg-clinical-teal-600 hover:bg-clinical-teal-700 text-white rounded-lg text-xs font-semibold shadow-sm"
            >
              <Search className="w-3.5 h-3.5" />
              <span>{isSearching ? "Searching..." : "Search Patients"}</span>
            </button>
          </div>
        </form>

        {searchWarning && (
          <div className="p-3 bg-amber-50 border border-amber-300 rounded-lg text-xs text-amber-800 flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
            <div>
              <span className="font-bold">Identity Disambiguation Advisory: </span>
              {searchWarning}
            </div>
          </div>
        )}
      </div>

      {/* Main Grid: Patient List vs. Selected Patient Continuity Detail */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Patient Directory (5 Cols) */}
        <div className="lg:col-span-5 space-y-4">
          <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-2 mb-3">
              <h2 className="text-sm font-bold text-slate-800 flex items-center gap-2">
                <Users className="w-4 h-4 text-clinical-teal-600" />
                <span>Patient Directory ({patients.length})</span>
              </h2>
            </div>

            {loading ? (
              <div className="py-8 text-center text-xs text-slate-400">Loading patients...</div>
            ) : patients.length === 0 ? (
              <div className="py-8 text-center text-xs text-slate-500">
                No matching patients found. Try adjusting search criteria or register a new patient.
              </div>
            ) : (
              <div className="space-y-2.5 max-h-[600px] overflow-y-auto pr-1">
                {patients.map((pt) => {
                  const isSelected = selectedPatient?.id === pt.id;
                  return (
                    <div
                      key={pt.id}
                      onClick={() => handleSelectPatient(pt)}
                      className={`p-3.5 rounded-xl border text-left cursor-pointer transition-all ${
                        isSelected
                          ? "bg-clinical-teal-50/70 border-clinical-teal-500 shadow-sm ring-1 ring-clinical-teal-500"
                          : "bg-white hover:bg-slate-50 border-slate-200"
                      }`}
                    >
                      <div className="flex items-start justify-between">
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-sm text-slate-900">{pt.full_name}</span>
                            <span className="text-[10px] font-mono px-1.5 py-0.5 bg-slate-100 text-slate-600 rounded">
                              {pt.patient_id_display}
                            </span>
                          </div>
                          <div className="text-xs text-slate-500 mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
                            <span>DOB: <strong className="text-slate-700">{pt.date_of_birth || pt.dob}</strong></span>
                            <span>Gender: {pt.gender}</span>
                            {pt.phone && <span>Tel: {pt.phone}</span>}
                          </div>
                        </div>
                        <ChevronRight className={`w-4 h-4 mt-1 ${isSelected ? "text-clinical-teal-700" : "text-slate-300"}`} />
                      </div>

                      {pt.allergies && pt.allergies.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1">
                          {pt.allergies.map((alg, idx) => (
                            <span key={idx} className="text-[10px] bg-red-50 text-red-700 border border-red-200 px-1.5 py-0.5 rounded font-medium">
                              Allergy: {alg}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Longitudinal Encounters & Patient History (7 Cols) */}
        <div className="lg:col-span-7 space-y-4">
          {selectedPatient ? (
            <div className="space-y-5">
              {/* Patient Banner */}
              <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-5">
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 pb-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <h2 className="text-lg font-bold text-slate-900">{selectedPatient.full_name}</h2>
                      <span className="text-xs font-mono font-bold px-2 py-0.5 bg-clinical-teal-100 text-clinical-teal-800 rounded">
                        {selectedPatient.patient_id_display}
                      </span>
                    </div>
                    <p className="text-xs text-slate-500 mt-0.5">
                      Persistent ID: <span className="font-mono">{selectedPatient.id}</span>
                    </p>
                  </div>

                  <div className="flex items-center gap-2">
                    <span className="text-xs px-2.5 py-1 bg-slate-100 text-slate-700 rounded-lg font-medium">
                      Blood: {selectedPatient.blood_type || "Unknown"}
                    </span>
                  </div>
                </div>

                {/* Patient Summary Info Grid */}
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 pt-3 text-xs">
                  <div>
                    <span className="text-slate-400 block">Date of Birth</span>
                    <span className="font-semibold text-slate-800">{selectedPatient.date_of_birth || selectedPatient.dob}</span>
                  </div>
                  <div>
                    <span className="text-slate-400 block">Gender</span>
                    <span className="font-semibold text-slate-800">{selectedPatient.gender}</span>
                  </div>
                  <div>
                    <span className="text-slate-400 block">Phone</span>
                    <span className="font-semibold text-slate-800">{selectedPatient.phone || "Not recorded"}</span>
                  </div>
                </div>

                {/* Known Allergies & Medical History */}
                <div className="mt-4 pt-3 border-t border-slate-100 space-y-2">
                  <div>
                    <span className="text-xs font-bold text-slate-700 uppercase tracking-wide block mb-1">
                      Documented Allergies
                    </span>
                    {selectedPatient.allergies && selectedPatient.allergies.length > 0 ? (
                      <div className="flex flex-wrap gap-1.5">
                        {selectedPatient.allergies.map((alg, i) => (
                          <span key={i} className="text-xs bg-rose-50 text-rose-800 border border-rose-200 px-2 py-0.5 rounded-md font-semibold">
                            {alg}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <span className="text-xs text-slate-400 italic">No allergies documented</span>
                    )}
                  </div>

                  <div>
                    <span className="text-xs font-bold text-slate-700 uppercase tracking-wide block mb-1">
                      Past Medical History
                    </span>
                    {selectedPatient.medical_history && selectedPatient.medical_history.length > 0 ? (
                      <div className="flex flex-wrap gap-1.5">
                        {selectedPatient.medical_history.map((hist, i) => (
                          <span key={i} className="text-xs bg-slate-100 text-slate-700 border border-slate-200 px-2 py-0.5 rounded-md font-medium">
                            {hist}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <span className="text-xs text-slate-400 italic">No past medical history recorded</span>
                    )}
                  </div>
                </div>
              </div>

              {/* Longitudinal Encounter Timeline */}
              <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-5 space-y-4">
                <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                  <h3 className="text-sm font-bold text-slate-900 flex items-center gap-2">
                    <Clock className="w-4 h-4 text-clinical-teal-600" />
                    <span>Longitudinal Field Encounters ({encounters.length})</span>
                  </h3>
                  <span className="text-xs text-slate-400">Chronological history</span>
                </div>

                {loadingHistory ? (
                  <div className="py-8 text-center text-xs text-slate-400">Loading encounter timeline...</div>
                ) : encounters.length === 0 ? (
                  <div className="py-8 text-center text-xs text-slate-500">
                    No field encounters linked to this patient yet. When creating a record, select this patient to maintain continuity.
                  </div>
                ) : (
                  <div className="space-y-3">
                    {encounters.map((enc) => {
                      const encType = enc.encounter_type || "NEW_ENCOUNTER";
                      const typeBadge =
                        encType === "CORRECTION" ? "bg-amber-100 text-amber-800" :
                        encType === "AMENDMENT" ? "bg-purple-100 text-purple-800" :
                        encType === "OBSERVATION" ? "bg-blue-100 text-blue-800" :
                        "bg-emerald-100 text-emerald-800";

                      return (
                        <div
                          key={enc.id}
                          className="p-4 rounded-xl border border-slate-200 bg-slate-50/60 hover:bg-slate-50 transition-colors space-y-2"
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <div className="flex items-center gap-2">
                                <span className="font-bold text-sm text-slate-900">
                                  {enc.call_number || "Field Incident"}
                                </span>
                                <span className={`text-[10px] font-bold px-2 py-0.5 rounded uppercase ${typeBadge}`}>
                                  {encType.replace("_", " ")}
                                </span>
                                <span className="text-xs px-2 py-0.5 bg-slate-200 text-slate-700 rounded font-semibold">
                                  {enc.status}
                                </span>
                              </div>
                              <p className="text-xs text-slate-500 mt-1">
                                {enc.created_at ? new Date(enc.created_at).toLocaleString() : "Date recorded"} • Unit: {enc.responder_id || "EMS Unit"}
                              </p>
                            </div>

                            {onSelectRecord && (
                              <button
                                onClick={() => onSelectRecord(enc.id, "review")}
                                className="px-3 py-1.5 rounded-lg bg-clinical-teal-600 hover:bg-clinical-teal-700 text-white text-xs font-semibold shadow-sm flex items-center gap-1"
                              >
                                <span>Open Record</span>
                                <ChevronRight className="w-3.5 h-3.5" />
                              </button>
                            )}
                          </div>

                          {enc.chief_complaint && (
                            <div className="text-xs text-slate-700">
                              <span className="font-semibold text-slate-900">Chief Complaint: </span>
                              {enc.chief_complaint}
                            </div>
                          )}

                          {enc.summary && (
                            <p className="text-xs text-slate-600 line-clamp-2 italic bg-white p-2 rounded border border-slate-100">
                              "{enc.summary}"
                            </p>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-12 text-center text-slate-500 space-y-2">
              <Users className="w-10 h-10 text-slate-300 mx-auto" />
              <h3 className="text-base font-bold text-slate-700">Select a Patient</h3>
              <p className="text-xs text-slate-400 max-w-sm mx-auto">
                Choose a patient from the directory on the left to inspect demographics, allergies, medical history, and longitudinal field encounters.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Register New Patient Modal */}
      {showNewModal && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
                <UserPlus className="w-5 h-5 text-clinical-teal-600" />
                <span>Register New Patient Profile</span>
              </h3>
              <button
                onClick={() => setShowNewModal(false)}
                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleCreatePatient} className="space-y-3.5">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-bold text-slate-700 block mb-1">First Name *</label>
                  <input
                    type="text"
                    required
                    value={newPatient.first_name}
                    onChange={(e) => setNewPatient({ ...newPatient, first_name: e.target.value })}
                    className="w-full p-2.5 rounded-lg border border-slate-300 text-xs focus:ring-2 focus:ring-clinical-teal-500"
                    placeholder="e.g. Eleanor"
                  />
                </div>
                <div>
                  <label className="text-xs font-bold text-slate-700 block mb-1">Last Name *</label>
                  <input
                    type="text"
                    required
                    value={newPatient.last_name}
                    onChange={(e) => setNewPatient({ ...newPatient, last_name: e.target.value })}
                    className="w-full p-2.5 rounded-lg border border-slate-300 text-xs focus:ring-2 focus:ring-clinical-teal-500"
                    placeholder="e.g. Vance"
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="text-xs font-bold text-slate-700 block mb-1">Date of Birth *</label>
                  <input
                    type="date"
                    required
                    value={newPatient.date_of_birth}
                    onChange={(e) => setNewPatient({ ...newPatient, date_of_birth: e.target.value })}
                    className="w-full p-2.5 rounded-lg border border-slate-300 text-xs focus:ring-2 focus:ring-clinical-teal-500"
                  />
                </div>
                <div>
                  <label className="text-xs font-bold text-slate-700 block mb-1">Gender</label>
                  <select
                    value={newPatient.gender}
                    onChange={(e) => setNewPatient({ ...newPatient, gender: e.target.value })}
                    className="w-full p-2.5 rounded-lg border border-slate-300 text-xs focus:ring-2 focus:ring-clinical-teal-500"
                  >
                    <option value="Female">Female</option>
                    <option value="Male">Male</option>
                    <option value="Non-Binary">Non-Binary</option>
                    <option value="Unspecified">Unspecified</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs font-bold text-slate-700 block mb-1">Blood Type</label>
                  <select
                    value={newPatient.blood_type}
                    onChange={(e) => setNewPatient({ ...newPatient, blood_type: e.target.value })}
                    className="w-full p-2.5 rounded-lg border border-slate-300 text-xs focus:ring-2 focus:ring-clinical-teal-500"
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
              </div>

              <div>
                <label className="text-xs font-bold text-slate-700 block mb-1">Phone Number</label>
                <input
                  type="text"
                  value={newPatient.phone}
                  onChange={(e) => setNewPatient({ ...newPatient, phone: e.target.value })}
                  placeholder="e.g. 555-0149"
                  className="w-full p-2.5 rounded-lg border border-slate-300 text-xs focus:ring-2 focus:ring-clinical-teal-500"
                />
              </div>

              <div>
                <label className="text-xs font-bold text-slate-700 block mb-1">Documented Allergies (comma-separated)</label>
                <input
                  type="text"
                  value={newPatient.allergies}
                  onChange={(e) => setNewPatient({ ...newPatient, allergies: e.target.value })}
                  placeholder="e.g. Penicillin, Codeine, Peanuts"
                  className="w-full p-2.5 rounded-lg border border-slate-300 text-xs focus:ring-2 focus:ring-clinical-teal-500"
                />
              </div>

              <div>
                <label className="text-xs font-bold text-slate-700 block mb-1">Medical History (comma-separated)</label>
                <input
                  type="text"
                  value={newPatient.medical_history}
                  onChange={(e) => setNewPatient({ ...newPatient, medical_history: e.target.value })}
                  placeholder="e.g. Hypertension, COPD, Type 2 Diabetes"
                  className="w-full p-2.5 rounded-lg border border-slate-300 text-xs focus:ring-2 focus:ring-clinical-teal-500"
                />
              </div>

              <div>
                <label className="text-xs font-bold text-slate-700 block mb-1">Primary Emergency Contact</label>
                <input
                  type="text"
                  value={newPatient.emergency_contact}
                  onChange={(e) => setNewPatient({ ...newPatient, emergency_contact: e.target.value })}
                  placeholder="e.g. spouse John Vance (555-0199)"
                  className="w-full p-2.5 rounded-lg border border-slate-300 text-xs focus:ring-2 focus:ring-clinical-teal-500"
                />
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setShowNewModal(false)}
                  className="px-4 py-2 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={savingNew}
                  className="px-5 py-2 rounded-lg bg-clinical-teal-600 hover:bg-clinical-teal-700 text-white text-xs font-semibold shadow-md disabled:bg-slate-300"
                >
                  {savingNew ? "Saving..." : "Register Patient"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
