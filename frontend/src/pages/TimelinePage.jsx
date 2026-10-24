import React, { useEffect, useState, useRef } from "react";
import {
  Clock, ArrowLeft, Activity, Pill, Stethoscope, ShieldCheck,
  AlertTriangle, Download, Calendar, Play, Pause, FileText,
  Volume2, VolumeX, CheckCircle2, ChevronRight, Layers, HelpCircle
} from "lucide-react";
import { api } from "../services/api";
import { StatusBadge } from "../components/StatusBadge";
import { VitalsChart } from "../components/VitalsChart";

export function TimelinePage({ recordId, onBack, onNavigateReview }) {
  const [timelineData, setTimelineData] = useState(null);
  const [record, setRecord] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Selected event for source evidence drawer
  const [selectedEventId, setSelectedEventId] = useState(null);

  // Audio Playback State
  const [isPlayingAudio, setIsPlayingAudio] = useState(false);
  const [audioPlaybackError, setAudioPlaybackError] = useState(null);
  const audioRef = useRef(null);
  const audioStopTimerRef = useRef(null);

  useEffect(() => {
    let isMounted = true;
    const fetchTimelineAndRecord = async () => {
      try {
        const [timeRes, recRes] = await Promise.all([
          api.getTimeline(recordId),
          api.getRecord(recordId)
        ]);

        if (isMounted) {
          if (timeRes.success && timeRes.data) {
            setTimelineData(timeRes.data);
            if (timeRes.data.events && timeRes.data.events.length > 0) {
              setSelectedEventId(timeRes.data.events[0].event_id);
            }
          }
          if (recRes.success && recRes.data) {
            setRecord(recRes.data);
          }
        }
      } catch (err) {
        if (isMounted) setError(err.message || "Failed to load case timeline data.");
      } finally {
        if (isMounted) setLoading(false);
      }
    };

    fetchTimelineAndRecord();
    return () => {
      isMounted = false;
      if (audioStopTimerRef.current) clearTimeout(audioStopTimerRef.current);
    };
  }, [recordId]);

  // Audio Playback Controller
  const handlePlayAudioSnippet = (startSec, endSec) => {
    setAudioPlaybackError(null);
    if (!audioRef.current) {
      setAudioPlaybackError("Audio player is not initialized.");
      return;
    }

    if (startSec === null || startSec === undefined) {
      audioRef.current.currentTime = 0;
      audioRef.current.play().then(() => setIsPlayingAudio(true)).catch((e) => {
        setAudioPlaybackError("Audio playback failed: " + e.message);
      });
      return;
    }

    try {
      audioRef.current.currentTime = startSec;
      audioRef.current.play().then(() => {
        setIsPlayingAudio(true);
        if (audioStopTimerRef.current) clearTimeout(audioStopTimerRef.current);

        const durationMs = ((endSec || startSec + 4) - startSec) * 1000;
        audioStopTimerRef.current = setTimeout(() => {
          if (audioRef.current) {
            audioRef.current.pause();
            setIsPlayingAudio(false);
          }
        }, Math.max(1000, durationMs));
      }).catch((e) => {
        setAudioPlaybackError("Unable to play audio snippet: " + e.message);
      });
    } catch (err) {
      setAudioPlaybackError("Audio seeking error: " + err.message);
    }
  };

  const handleStopAudio = () => {
    if (audioRef.current) {
      audioRef.current.pause();
      setIsPlayingAudio(false);
    }
    if (audioStopTimerRef.current) clearTimeout(audioStopTimerRef.current);
  };

  if (loading) {
    return <div className="p-12 text-center text-slate-500 font-sans">Compiling case timeline and vitals progression...</div>;
  }

  if (error || !timelineData) {
    return (
      <div className="p-12 text-center text-red-600 space-y-3 font-sans">
        <p className="text-sm">{error || "Timeline data not found."}</p>
        <button onClick={onBack} className="block mx-auto text-xs underline text-slate-600">Return to Dashboard</button>
      </div>
    );
  }

  const events = timelineData.events || [];
  const timestampedEvents = events.filter((e) => e.timestamp_known);
  const unspecifiedEvents = events.filter((e) => !e.timestamp_known);
  const selectedEvent = events.find((e) => e.event_id === selectedEventId) || events[0];

  const audioUrl = timelineData.audio_filename ? api.getAudioUrl(timelineData.audio_filename) : null;

  return (
    <div className="max-w-6xl mx-auto space-y-6 font-sans pb-12">
      {/* Hidden audio element for snippet playback */}
      {audioUrl && (
        <audio
          ref={audioRef}
          src={audioUrl}
          onEnded={() => setIsPlayingAudio(false)}
          onPause={() => setIsPlayingAudio(false)}
          className="hidden"
          preload="metadata"
        />
      )}

      {/* Top Navigation Bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="p-2 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700" title="Back">
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-bold text-slate-900">Case Timeline & Vitals Chart</h1>
              {record && <StatusBadge status={record.status} />}
              <span className="text-xs bg-slate-100 text-slate-700 px-2 py-0.5 rounded font-mono font-semibold">
                {timelineData.total_event_count} Events Recorded
              </span>
            </div>
            <p className="text-xs text-slate-500">
              Call #: <span className="font-semibold text-slate-700">{timelineData.call_number || "EMS"}</span> • ID: <span className="font-mono">{recordId}</span>
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {onNavigateReview && (
            <button
              onClick={() => onNavigateReview(recordId)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-clinical-teal-600 hover:bg-clinical-teal-700 text-white text-xs font-semibold shadow-sm"
            >
              <FileText className="w-3.5 h-3.5" />
              <span>Clinical Review</span>
            </button>
          )}
          <a
            href={api.getHandoverPdfUrl(recordId)}
            target="_blank"
            rel="noreferrer"
            download={`handover_${recordId}.pdf`}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Handover PDF</span>
          </a>
        </div>
      </div>

      {/* FEATURE B: VITAL-SIGNS CHART */}
      <VitalsChart
        chartSeries={timelineData.chart_series}
        onSelectEvent={(eventId) => setSelectedEventId(eventId)}
        selectedEventId={selectedEventId}
      />

      {/* MAIN TWO-COLUMN CONTAINER: TIMELINE (7 COLS) & SOURCE EVIDENCE DRAWER (5 COLS) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Column: Chronological Case Timeline */}
        <div className="lg:col-span-7 space-y-6">
          <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <Clock className="w-4 h-4 text-clinical-teal-600" />
                <h2 className="text-sm font-bold text-slate-900 uppercase tracking-wider">
                  Chronological Case Events ({timestampedEvents.length})
                </h2>
              </div>
              <span className="text-[11px] text-slate-400">Earliest to Latest (IST, Asia/Kolkata)</span>
            </div>

            {timestampedEvents.length === 0 ? (
              <p className="text-xs text-slate-500 italic p-3 bg-slate-50 rounded-lg">
                No explicitly timestamped clinical observations found in narrative. See unspecified timing tray below.
              </p>
            ) : (
              <div className="relative border-l-2 border-slate-200 ml-4 space-y-6 pb-2">
                {timestampedEvents.map((evt) => {
                  const isSelected = selectedEventId === evt.event_id;
                  const isMed = evt.event_type === "MEDICATION";
                  const isVital = evt.event_type === "VITAL_SIGN";
                  const isProc = evt.event_type === "PROCEDURE";
                  const isReview = evt.event_type === "REVIEW_EVENT";

                  return (
                    <div
                      key={evt.event_id}
                      onClick={() => setSelectedEventId(evt.event_id)}
                      className="relative pl-6 cursor-pointer group"
                    >
                      {/* Node Indicator */}
                      <div
                        className={`absolute -left-3 top-1 w-6 h-6 rounded-full flex items-center justify-center border-2 transition-all ${
                          isSelected
                            ? "bg-slate-900 border-clinical-teal-500 text-white scale-110 shadow-md"
                            : isMed
                            ? "bg-amber-100 border-amber-400 text-amber-900"
                            : isVital
                            ? "bg-teal-100 border-teal-400 text-teal-900"
                            : "bg-slate-100 border-slate-400 text-slate-700"
                        }`}
                      >
                        {isMed ? <Pill className="w-3 h-3" /> :
                         isVital ? <Activity className="w-3 h-3" /> :
                         isProc ? <Stethoscope className="w-3 h-3" /> :
                         <ShieldCheck className="w-3 h-3" />}
                      </div>

                      {/* Event Card */}
                      <div
                        className={`p-3.5 rounded-xl border transition-all ${
                          isSelected
                            ? "bg-slate-900 text-white border-slate-900 shadow-md"
                            : "bg-slate-50 hover:bg-slate-100/80 border-slate-200 text-slate-900"
                        }`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div>
                            <div className="flex items-center gap-2">
                              <span className={`font-mono text-xs font-bold px-1.5 py-0.5 rounded ${
                                isSelected ? "bg-slate-800 text-teal-300" : "bg-slate-200 text-slate-800"
                              }`}>
                                {evt.timestamp_display.includes("IST") ? evt.timestamp_display : `${evt.timestamp_display} IST`}
                              </span>
                              <span className="font-bold text-sm">{evt.display_name}</span>
                            </div>

                            {/* Value / Dosage Description */}
                            <p className={`text-xs mt-1 ${isSelected ? "text-slate-200" : "text-slate-700 font-medium"}`}>
                              {isVital && (
                                <span>Reading: <strong className="font-mono">{evt.value} {evt.unit}</strong></span>
                              )}
                              {isMed && (
                                <span>{evt.formatted_dosage}</span>
                              )}
                              {isProc && (
                                <span>{evt.value}</span>
                              )}
                              {isReview && (
                                <span>{evt.value}</span>
                              )}
                            </p>
                          </div>

                          {/* Distinct Visual Status Badge (Not relying on color alone) */}
                          <div className="shrink-0 text-right space-y-1">
                            {isMed && (
                              <span className={`text-[10px] font-black uppercase tracking-wider px-2 py-0.5 rounded border block ${
                                evt.marker_type === "CONFIRMED"
                                  ? (isSelected ? "bg-emerald-950 text-emerald-300 border-emerald-600" : "bg-emerald-100 text-emerald-900 border-emerald-300")
                                  : evt.marker_type === "WITHHELD"
                                  ? (isSelected ? "bg-rose-950 text-rose-300 border-rose-600 line-through" : "bg-rose-100 text-rose-900 border-rose-300 line-through")
                                  : evt.marker_type === "PLANNED"
                                  ? (isSelected ? "bg-blue-950 text-blue-300 border-blue-600" : "bg-blue-100 text-blue-900 border-blue-300")
                                  : (isSelected ? "bg-amber-950 text-amber-300 border-amber-600" : "bg-amber-100 text-amber-900 border-amber-300")
                              }`}>
                                [{evt.status_label}]
                              </span>
                            )}
                            <span className={`text-[10px] block font-mono ${isSelected ? "text-slate-400" : "text-slate-500"}`}>
                              Status: {evt.extraction_status}
                            </span>
                          </div>
                        </div>

                        {/* Source text snippet */}
                        {evt.source_text && (
                          <p className={`text-[11px] italic truncate mt-2 border-t pt-1.5 ${
                            isSelected ? "border-slate-800 text-slate-300" : "border-slate-200 text-slate-500"
                          }`}>
                            Evidence: "{evt.source_text}"
                          </p>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Tray for Events with Missing / Unspecified Timestamps */}
          {unspecifiedEvents.length > 0 && (
            <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-5 space-y-3">
              <div className="flex items-center justify-between border-b border-slate-100 pb-2">
                <div className="flex items-center gap-2">
                  <HelpCircle className="w-4 h-4 text-amber-600" />
                  <h3 className="text-xs font-bold text-slate-800 uppercase tracking-wider">
                    Observations With Unspecified Timestamps ({unspecifiedEvents.length})
                  </h3>
                </div>
                <span className="text-[10px] text-slate-400">Chronological position not established</span>
              </div>
              <p className="text-[11px] text-slate-600">
                These clinical observations were documented in the narrative note without an explicit clock timestamp. They are preserved here to avoid fabricating sequence:
              </p>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 pt-1">
                {unspecifiedEvents.map((evt) => {
                  const isSelected = selectedEventId === evt.event_id;
                  return (
                    <div
                      key={evt.event_id}
                      onClick={() => setSelectedEventId(evt.event_id)}
                      className={`p-3 rounded-lg border text-xs cursor-pointer transition-colors ${
                        isSelected
                          ? "bg-slate-900 text-white border-slate-900 shadow-sm"
                          : "bg-slate-50 hover:bg-slate-100 border-slate-200 text-slate-800"
                      }`}
                    >
                      <div className="flex items-center justify-between font-bold">
                        <span>{evt.display_name}</span>
                        <span className={`text-[10px] px-1.5 py-0.2 rounded font-mono ${
                          isSelected ? "bg-slate-800 text-slate-300" : "bg-slate-200 text-slate-600"
                        }`}>
                          [Unspecified Time]
                        </span>
                      </div>
                      <p className={`mt-1 font-mono ${isSelected ? "text-slate-200" : "text-slate-700 font-semibold"}`}>
                        {evt.value} {evt.unit}
                      </p>
                      {evt.source_text && (
                        <p className={`text-[10px] italic truncate mt-1 ${isSelected ? "text-slate-400" : "text-slate-400"}`}>
                          "{evt.source_text}"
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* Right Column: Source Evidence & Provenance Drawer (Feature D) */}
        <div className="lg:col-span-5 space-y-5 sticky top-6">
          <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-5 space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <FileText className="w-4 h-4 text-clinical-teal-600" />
                <h3 className="text-sm font-bold text-slate-900">Source Evidence & Provenance</h3>
              </div>
              <span className="text-[10px] font-mono text-slate-400">
                {selectedEvent ? selectedEvent.event_id : "No selection"}
              </span>
            </div>

            {selectedEvent ? (
              <div className="space-y-4 text-xs">
                {/* Event Heading */}
                <div className="p-3 bg-slate-50 rounded-lg border border-slate-200 space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-slate-900 text-sm">{selectedEvent.display_name}</span>
                    <span className="font-mono text-xs font-semibold text-clinical-teal-800">
                      {selectedEvent.timestamp_display}
                    </span>
                  </div>
                  <div className="font-mono text-xs text-slate-700">
                    Recorded Value: <strong>{selectedEvent.value} {selectedEvent.unit}</strong>
                  </div>
                  {selectedEvent.medication_status && (
                    <div className="text-[11px] font-bold text-amber-900 mt-1">
                      Medication Status: [{selectedEvent.status_label}]
                    </div>
                  )}
                </div>

                {/* Verbatim Source Evidence */}
                <div className="space-y-1.5">
                  <span className="font-bold text-slate-700 uppercase tracking-wider text-[10px] block">
                    Verbatim Transcript Evidence Span:
                  </span>
                  <div className="p-3 bg-teal-50/60 border border-teal-200 rounded-lg text-slate-900 font-mono text-xs leading-relaxed">
                    "{selectedEvent.source_text || "No supporting phrase captured."}"
                  </div>
                  {selectedEvent.char_start !== null && selectedEvent.char_start !== undefined && (
                    <p className="text-[10px] text-slate-500 font-mono">
                      Character Span: [{selectedEvent.char_start} to {selectedEvent.char_end}]
                    </p>
                  )}
                </div>

                {/* Audio Snippet Player */}
                <div className="space-y-2 border-t border-slate-100 pt-3">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-slate-700 uppercase tracking-wider text-[10px] block">
                      Associated Audio Recording:
                    </span>
                    {selectedEvent.has_usable_audio_offsets ? (
                      <span className="text-[10px] font-mono text-emerald-700 font-semibold bg-emerald-50 px-1.5 py-0.5 rounded">
                        Aligned: {selectedEvent.audio_timestamp_start}s - {selectedEvent.audio_timestamp_end}s
                      </span>
                    ) : (
                      <span className="text-[10px] font-mono text-slate-500 bg-slate-100 px-1.5 py-0.5 rounded">
                        No precise offset alignment
                      </span>
                    )}
                  </div>

                  {audioUrl ? (
                    <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] font-mono text-slate-600 truncate max-w-[200px]">
                          {timelineData.audio_filename}
                        </span>
                        {isPlayingAudio ? (
                          <button
                            onClick={handleStopAudio}
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-rose-600 hover:bg-rose-700 text-white rounded text-xs font-bold shadow-sm"
                          >
                            <Pause className="w-3.5 h-3.5" />
                            <span>Stop</span>
                          </button>
                        ) : (
                          <button
                            onClick={() => handlePlayAudioSnippet(selectedEvent.audio_timestamp_start, selectedEvent.audio_timestamp_end)}
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-clinical-teal-700 hover:bg-clinical-teal-800 text-white rounded text-xs font-bold shadow-sm"
                          >
                            <Play className="w-3.5 h-3.5" />
                            <span>
                              {selectedEvent.has_usable_audio_offsets
                                ? `Play Snippet (${selectedEvent.audio_timestamp_start}s)`
                                : "Play From Start"}
                            </span>
                          </button>
                        )}
                      </div>
                      {audioPlaybackError && (
                        <p className="text-[11px] text-red-600">{audioPlaybackError}</p>
                      )}
                    </div>
                  ) : (
                    <p className="text-[11px] text-slate-400 italic">
                      No raw audio file preserved for this encounter.
                    </p>
                  )}
                </div>

                {/* Audit & Verification History */}
                <div className="border-t border-slate-100 pt-3 space-y-1">
                  <span className="font-bold text-slate-700 uppercase tracking-wider text-[10px] block">
                    Review & Extraction Integrity:
                  </span>
                  <div className="grid grid-cols-2 gap-2 text-[11px]">
                    <div className="p-2 bg-slate-50 rounded border border-slate-200">
                      <span className="text-slate-400 block text-[9px] uppercase">Extraction Status</span>
                      <span className="font-semibold text-slate-800">{selectedEvent.extraction_status}</span>
                    </div>
                    <div className="p-2 bg-slate-50 rounded border border-slate-200">
                      <span className="text-slate-400 block text-[9px] uppercase">Review Status</span>
                      <span className="font-semibold text-slate-800">{selectedEvent.review_status}</span>
                    </div>
                  </div>
                  {selectedEvent.original_extracted_value && selectedEvent.corrected_value && (
                    <div className="p-2 bg-purple-50 border border-purple-200 rounded text-[11px] text-purple-900 mt-2">
                      <span className="font-bold block">Reviewer Correction History:</span>
                      <span>Extracted: "{selectedEvent.original_extracted_value}" → Corrected to: "{selectedEvent.corrected_value}"</span>
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <p className="text-xs text-slate-400 italic py-6 text-center">
                Select an observation or chart point to inspect verbatim evidence.
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
