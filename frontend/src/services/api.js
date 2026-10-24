/**
 * Frontend API client communicating with Flask backend.
 * Configured via import.meta.env.VITE_API_BASE_URL.
 * No browser-side AI or database access.
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

async function handleResponse(res) {
  const isJson = res.headers.get("content-type")?.includes("application/json");
  const data = isJson ? await res.json() : await res.text();

  if (!res.ok) {
    const errorMsg = data?.error || data?.message || `HTTP ${res.status}: ${res.statusText}`;
    const err = new Error(errorMsg);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

export const api = {
  // System Diagnostics
  async getHealth() {
    const res = await fetch(`${API_BASE}/api/health`);
    return handleResponse(res);
  },

  async getTranscriptionStatus() {
    const res = await fetch(`${API_BASE}/api/transcription/status`);
    return handleResponse(res);
  },

  async loadTranscriptionModel(modelName, device = "cpu", computeType = "int8") {
    const res = await fetch(`${API_BASE}/api/transcription/load`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_name: modelName, device, compute_type: computeType })
    });
    return handleResponse(res);
  },

  // Speech Transcription
  async getTranscriptionLanguages() {
    const res = await fetch(`${API_BASE}/api/transcription/languages`);
    return handleResponse(res);
  },

  async transcribeAudio(formData) {
    const res = await fetch(`${API_BASE}/api/transcription/transcribe`, {
      method: "POST",
      body: formData // multipart/form-data; browser sets boundary
    });
    return handleResponse(res);
  },

  // Records CRUD
  async createRecord(recordData) {
    const res = await fetch(`${API_BASE}/api/records`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(recordData)
    });
    return handleResponse(res);
  },

  async listRecords(params = {}) {
    const query = new URLSearchParams(params).toString();
    const url = `${API_BASE}/api/records${query ? `?${query}` : ""}`;
    const res = await fetch(url);
    return handleResponse(res);
  },

  async getRecord(recordId) {
    const res = await fetch(`${API_BASE}/api/records/${encodeURIComponent(recordId)}`);
    return handleResponse(res);
  },

  async updateRecord(recordId, recordData) {
    const res = await fetch(`${API_BASE}/api/records/${encodeURIComponent(recordId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(recordData)
    });
    return handleResponse(res);
  },

  async approveRecord(recordId, approvalData = {}) {
    const res = await fetch(`${API_BASE}/api/records/${encodeURIComponent(recordId)}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(approvalData)
    });
    return handleResponse(res);
  },

  async amendRecord(recordId, amendmentData) {
    const res = await fetch(`${API_BASE}/api/records/${encodeURIComponent(recordId)}/amend`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(amendmentData)
    });
    return handleResponse(res);
  },

  async syncRecords(syncPayload) {
    const res = await fetch(`${API_BASE}/api/records/sync`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(syncPayload)
    });
    return handleResponse(res);
  },

  async exportJson(recordId, version = null) {
    const url = `${API_BASE}/api/records/${encodeURIComponent(recordId)}/export/json${version ? `?version=${version}` : ""}`;
    const res = await fetch(url);
    return handleResponse(res);
  },

  getPdfUrl(recordId, version = null) {
    return `${API_BASE}/api/records/${encodeURIComponent(recordId)}/export/pdf${version ? `?version=${version}` : ""}`;
  },

  // Feature 5: Hospital Handover Document
  async getHandover(recordId, version = null) {
    const url = `${API_BASE}/api/records/${encodeURIComponent(recordId)}/handover${version ? `?version=${version}` : ""}`;
    const res = await fetch(url);
    return handleResponse(res);
  },

  getHandoverPdfUrl(recordId, version = null) {
    return `${API_BASE}/api/records/${encodeURIComponent(recordId)}/handover/pdf${version ? `?version=${version}` : ""}`;
  },

  // Ongoing Case Timeline & Vitals Chart
  async getTimeline(recordId) {
    const res = await fetch(`${API_BASE}/api/records/${encodeURIComponent(recordId)}/timeline`);
    return handleResponse(res);
  },

  getAudioUrl(filename) {
    if (!filename) return null;
    return `${API_BASE}/api/audio/${encodeURIComponent(filename)}`;
  },

  async getAuditTrail(recordId) {
    const res = await fetch(`${API_BASE}/api/records/${encodeURIComponent(recordId)}/audit`);
    return handleResponse(res);
  },

  // Clinical Processing & Medicine Catalogue
  async extractClinical(text) {
    const res = await fetch(`${API_BASE}/api/clinical/extract`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text })
    });
    return handleResponse(res);
  },

  async validateClinical(clinicalData) {
    const res = await fetch(`${API_BASE}/api/clinical/validate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clinical_data: clinicalData })
    });
    return handleResponse(res);
  },

  async searchMedicines(query) {
    const res = await fetch(`${API_BASE}/api/medicines/search?q=${encodeURIComponent(query)}`);
    return handleResponse(res);
  },

  async getMedicineCatalogue() {
    const res = await fetch(`${API_BASE}/api/medicines/catalogue`);
    return handleResponse(res);
  },

  async addFormularyEntry(entryData) {
    const res = await fetch(`${API_BASE}/api/medicines/catalogue`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(entryData)
    });
    return handleResponse(res);
  },

  // Feature 3: Unknown Medication Reviews
  async getUnknownMedications(recordId) {
    const res = await fetch(`${API_BASE}/api/records/${encodeURIComponent(recordId)}/unknown-medications`);
    return handleResponse(res);
  },

  async resolveUnknownMedication(recordId, itemId, resolutionData) {
    const res = await fetch(`${API_BASE}/api/records/${encodeURIComponent(recordId)}/unknown-medications/${encodeURIComponent(itemId)}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(resolutionData)
    });
    return handleResponse(res);
  },

  // Feature 4: Allergy & Medication Safety Warnings
  async getAllergyWarnings(recordId) {
    const res = await fetch(`${API_BASE}/api/records/${encodeURIComponent(recordId)}/allergy-warnings`);
    return handleResponse(res);
  },

  async acknowledgeAllergyWarning(recordId, warningId, ackData) {
    const res = await fetch(`${API_BASE}/api/records/${encodeURIComponent(recordId)}/allergy-warnings/${encodeURIComponent(warningId)}/acknowledge`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(ackData)
    });
    return handleResponse(res);
  },

  // Patient Continuity Engine
  async listPatients(params = {}) {
    const query = new URLSearchParams(params).toString();
    const url = `${API_BASE}/api/patients${query ? `?${query}` : ""}`;
    const res = await fetch(url);
    return handleResponse(res);
  },

  async getPatient(patientId) {
    const res = await fetch(`${API_BASE}/api/patients/${encodeURIComponent(patientId)}`);
    return handleResponse(res);
  },

  async getPatientHistory(patientId) {
    const res = await fetch(`${API_BASE}/api/patients/${encodeURIComponent(patientId)}/history`);
    return handleResponse(res);
  },

  async registerPatient(patientData) {
    const res = await fetch(`${API_BASE}/api/patients`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patientData)
    });
    return handleResponse(res);
  },

  async linkPatientEncounter(patientId, linkData) {
    const res = await fetch(`${API_BASE}/api/patients/${encodeURIComponent(patientId)}/link`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(linkData)
    });
    return handleResponse(res);
  },

  // Version History Snapshots
  async getRecordVersions(recordId) {
    const res = await fetch(`${API_BASE}/api/records/${encodeURIComponent(recordId)}/versions`);
    return handleResponse(res);
  },

  async getVersionSnapshot(recordId, versionNum) {
    const res = await fetch(`${API_BASE}/api/records/${encodeURIComponent(recordId)}/versions/${versionNum}`);
    return handleResponse(res);
  },

  // Offline Trust Monitor & Draft Recovery
  async getTrustStatus() {
    const res = await fetch(`${API_BASE}/api/trust/status`);
    return handleResponse(res);
  },

  async autosaveDraft(sessionId, draft) {
    const res = await fetch(`${API_BASE}/api/trust/drafts/save`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, draft })
    });
    return handleResponse(res);
  },

  async getAutosavedDraft(sessionId) {
    const res = await fetch(`${API_BASE}/api/trust/drafts/${encodeURIComponent(sessionId)}`);
    return handleResponse(res);
  },

  async clearAutosavedDraft(sessionId) {
    const res = await fetch(`${API_BASE}/api/trust/drafts/${encodeURIComponent(sessionId)}`, {
      method: "DELETE"
    });
    return handleResponse(res);
  },

  // Clinical Accuracy Evaluation Dashboard
  async getAccuracyMetrics() {
    const res = await fetch(`${API_BASE}/api/accuracy/metrics`);
    return handleResponse(res);
  },

  async triggerEvaluation(modelName = null) {
    const res = await fetch(`${API_BASE}/api/accuracy/evaluate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_name: modelName })
    });
    return handleResponse(res);
  },

  // Standards-Compatible Export (HL7 FHIR R4 Bundle)
  getFhirUrl(recordId) {
    return `${API_BASE}/api/records/${encodeURIComponent(recordId)}/export/fhir`;
  },

  async exportFhir(recordId) {
    const res = await fetch(this.getFhirUrl(recordId));
    return handleResponse(res);
  }
};
