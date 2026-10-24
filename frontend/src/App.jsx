import React, { useState } from "react";
import { Navbar } from "./components/Navbar";
import { Dashboard } from "./pages/Dashboard";
import { VoiceInputPage } from "./pages/VoiceInputPage";
import { ClinicalReviewPage } from "./pages/ClinicalReviewPage";
import { TimelinePage } from "./pages/TimelinePage";
import { RecordsPage } from "./pages/RecordsPage";
import { RecordDetailsPage } from "./pages/RecordDetailsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { PatientsPage } from "./pages/PatientsPage";
import { AccuracyTrustPage } from "./pages/AccuracyTrustPage";
import { HospitalHandoverPage } from "./pages/HospitalHandoverPage";

export default function App() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const [selectedRecordId, setSelectedRecordId] = useState(null);

  // Router handler
  const handleSelectRecord = (recordId, view = "review") => {
    setSelectedRecordId(recordId);
    if (view === "review") {
      setActiveTab("review");
    } else if (view === "details") {
      setActiveTab("details");
    } else if (view === "timeline") {
      setActiveTab("timeline");
    } else if (view === "handover") {
      setActiveTab("handover");
    }
  };

  const handleRecordCreated = (newRecordId) => {
    setSelectedRecordId(newRecordId);
    setActiveTab("review");
  };

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col font-sans">
      <Navbar activeTab={activeTab} setActiveTab={setActiveTab} />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-8">
        {activeTab === "dashboard" && (
          <Dashboard
            onNavigate={(tab) => setActiveTab(tab)}
            onSelectRecord={handleSelectRecord}
          />
        )}

        {activeTab === "voice" && (
          <VoiceInputPage onRecordCreated={handleRecordCreated} />
        )}

        {activeTab === "records" && (
          <RecordsPage
            onSelectRecord={handleSelectRecord}
            onNewRecord={() => setActiveTab("voice")}
          />
        )}

        {activeTab === "review" && (
          <ClinicalReviewPage
            recordId={selectedRecordId}
            onBack={() => setActiveTab("records")}
            onNavigateTimeline={(id) => handleSelectRecord(id, "timeline")}
            onNavigateHandover={(id) => handleSelectRecord(id, "handover")}
          />
        )}

        {activeTab === "handover" && (
          <HospitalHandoverPage
            recordId={selectedRecordId}
            onBack={() => setActiveTab("review")}
          />
        )}

        {activeTab === "timeline" && (
          <TimelinePage
            recordId={selectedRecordId}
            onBack={() => setActiveTab("records")}
            onNavigateReview={(id) => handleSelectRecord(id, "review")}
          />
        )}

        {activeTab === "details" && (
          <RecordDetailsPage
            recordId={selectedRecordId}
            onBack={() => setActiveTab("records")}
            onNavigateReview={(id) => handleSelectRecord(id, "review")}
            onNavigateTimeline={(id) => handleSelectRecord(id, "timeline")}
          />
        )}

        {activeTab === "patients" && (
          <PatientsPage
            onSelectRecord={handleSelectRecord}
          />
        )}

        {activeTab === "settings" && <SettingsPage />}
      </main>

      <footer className="bg-white border-t border-slate-200 py-4 text-center text-xs text-slate-500">
        <p>Field-to-Record Offline Clinical Documentation Assistant • Emergency First Responder Edition</p>
        <p className="text-[11px] text-slate-400 mt-0.5">
          Documentation Assistant Only — Not an Automated Medical Diagnosis or Treatment Recommendation System.
        </p>
      </footer>
    </div>
  );
}
