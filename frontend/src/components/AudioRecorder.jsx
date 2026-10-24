import React, { useState, useRef, useEffect } from "react";
import {
  Mic, Square, Play, Pause, RotateCcw, Upload, Volume2, AlertTriangle,
  Clock, Sparkles, Check, HelpCircle, Edit3, ShieldAlert, Tag, ChevronDown, ChevronUp
} from "lucide-react";
import { api } from "../services/api";

export function AudioRecorder({ onTranscriptionComplete, onSaveDraft }) {
  const [mode, setMode] = useState("record"); // "record" | "upload"
  const [recordingState, setRecordingState] = useState("idle"); // "idle" | "recording" | "paused" | "stopped"
  const [duration, setDuration] = useState(0);
  const [audioBlob, setAudioBlob] = useState(null);
  const [audioUrl, setAudioUrl] = useState(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [transcriptionError, setTranscriptionError] = useState(null);
  const [machineTranscript, setMachineTranscript] = useState("");
  const [editableTranscript, setEditableTranscript] = useState("");
  const [transcriptionMeta, setTranscriptionMeta] = useState(null);
  const [selectedFile, setSelectedFile] = useState(null);
  const [transcribeElapsed, setTranscribeElapsed] = useState(0);

  // Multilingual speech recognition configuration
  const [selectedLanguage, setSelectedLanguage] = useState("en");
  const [languageStatusList, setLanguageStatusList] = useState([
    { language: "en", name: "English", available: true },
    { language: "ta", name: "Tamil", native_name: "தமிழ்", available: false },
    { language: "hi", name: "Hindi", native_name: "हिन्दी", available: false }
  ]);

  useEffect(() => {
    api.getTranscriptionLanguages()
      .then((res) => {
        if (res && res.success && res.data) {
          setLanguageStatusList(res.data);
        }
      })
      .catch(() => {});
  }, []);

  // Word token inspector state
  const [showWordInspector, setShowWordInspector] = useState(true);
  const [selectedWordIndex, setSelectedWordIndex] = useState(null);
  const [wordReplacementInput, setWordReplacementInput] = useState("");

  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const timerRef = useRef(null);
  const audioElementRef = useRef(null);
  const transcribeTimerRef = useRef(null);

  // Timer for active recording
  useEffect(() => {
    if (recordingState === "recording") {
      timerRef.current = setInterval(() => {
        setDuration((prev) => prev + 1);
      }, 1000);
    } else {
      clearInterval(timerRef.current);
    }
    return () => clearInterval(timerRef.current);
  }, [recordingState]);

  // Elapsed timer while backend transcribes
  useEffect(() => {
    if (isTranscribing) {
      setTranscribeElapsed(0);
      transcribeTimerRef.current = setInterval(() => {
        setTranscribeElapsed((prev) => +(prev + 0.1).toFixed(1));
      }, 100);
    } else {
      clearInterval(transcribeTimerRef.current);
    }
    return () => clearInterval(transcribeTimerRef.current);
  }, [isTranscribing]);

  // Clean up object URLs
  useEffect(() => {
    return () => {
      if (audioUrl) {
        URL.revokeObjectURL(audioUrl);
      }
    };
  }, [audioUrl]);

  const formatTime = (secs) => {
    const mins = Math.floor(secs / 60);
    const remaining = secs % 60;
    return `${mins.toString().padStart(2, "0")}:${remaining.toString().padStart(2, "0")}`;
  };

  const startRecording = async () => {
    setTranscriptionError(null);
    audioChunksRef.current = [];
    setAudioBlob(null);
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    setAudioUrl(null);
    setDuration(0);

    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error("Audio recording is not supported in this browser environment.");
      }

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true
        }
      });

      // Preferred supported MIME types
      let mimeType = "audio/webm;codecs=opus";
      if (!MediaRecorder.isTypeSupported(mimeType)) {
        if (MediaRecorder.isTypeSupported("audio/webm")) {
          mimeType = "audio/webm";
        } else if (MediaRecorder.isTypeSupported("audio/ogg;codecs=opus")) {
          mimeType = "audio/ogg;codecs=opus";
        } else {
          mimeType = ""; // Browser default
        }
      }

      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      recorder.onstop = () => {
        const actualMime = recorder.mimeType || "audio/webm";
        const finalBlob = new Blob(audioChunksRef.current, { type: actualMime });

        if (finalBlob.size === 0) {
          setTranscriptionError("Recording failed: Collected audio is empty (0 bytes). Check microphone permissions.");
          setRecordingState("idle");
          return;
        }

        setAudioBlob(finalBlob);
        const url = URL.createObjectURL(finalBlob);
        setAudioUrl(url);
        setRecordingState("stopped");

        // Stop all audio tracks to release microphone hardware
        stream.getTracks().forEach((track) => track.stop());
      };

      recorder.start(250); // Collect chunk every 250ms
      setRecordingState("recording");
    } catch (err) {
      setTranscriptionError(`Microphone access error: ${err.message || err.name}. Please grant microphone permissions in browser.`);
      setRecordingState("idle");
    }
  };

  const pauseRecording = () => {
    if (mediaRecorderRef.current && recordingState === "recording") {
      mediaRecorderRef.current.pause();
      setRecordingState("paused");
    }
  };

  const resumeRecording = () => {
    if (mediaRecorderRef.current && recordingState === "paused") {
      mediaRecorderRef.current.resume();
      setRecordingState("recording");
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && (recordingState === "recording" || recordingState === "paused")) {
      mediaRecorderRef.current.stop();
    }
  };

  const resetRecording = () => {
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    setAudioBlob(null);
    setAudioUrl(null);
    setDuration(0);
    setRecordingState("idle");
    setMachineTranscript("");
    setEditableTranscript("");
    setTranscriptionMeta(null);
    setTranscriptionError(null);
  };

  const togglePlayback = () => {
    if (!audioElementRef.current) return;
    if (isPlaying) {
      audioElementRef.current.pause();
      setIsPlaying(false);
    } else {
      audioElementRef.current.play();
      setIsPlaying(true);
    }
  };

  const handleFileUpload = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (file.size === 0) {
      setTranscriptionError("Selected file is empty (0 bytes).");
      return;
    }

    if (file.size > 30 * 1024 * 1024) {
      setTranscriptionError("Audio file exceeds maximum 30MB limit.");
      return;
    }

    setSelectedFile(file);
    setAudioBlob(file);
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    const url = URL.createObjectURL(file);
    setAudioUrl(url);
    setRecordingState("stopped");
    setTranscriptionError(null);
  };

  const handleTranscribe = async () => {
    if (!audioBlob) {
      setTranscriptionError("No audio available. Please record or upload an audio file first.");
      return;
    }

    setIsTranscribing(true);
    setTranscriptionError(null);

    try {
      const formData = new FormData();
      const ext = audioBlob.type?.includes("ogg") ? "ogg" : audioBlob.type?.includes("wav") ? "wav" : "webm";
      const filename = selectedFile?.name || `field_recording_${Date.now()}.${ext}`;

      formData.append("audio", audioBlob, filename);
      formData.append("language", selectedLanguage);

      const res = await api.transcribeAudio(formData);

      if (res.success && res.data) {
        setMachineTranscript(res.data.transcript);
        setEditableTranscript(res.data.transcript);
        setTranscriptionMeta(res.data);

        if (onTranscriptionComplete) {
          onTranscriptionComplete(res.data);
        }
      } else {
        throw new Error(res.error || "Transcription returned no text.");
      }
    } catch (err) {
      setTranscriptionError(err.message || "Failed to transcribe audio. Verify backend is running and Whisper is ready.");
    } finally {
      setIsTranscribing(false);
    }
  };

  const handleSaveDraft = () => {
    if (!editableTranscript.trim()) {
      setTranscriptionError("Please record and transcribe audio or type field notes before saving.");
      return;
    }

    if (onSaveDraft) {
      onSaveDraft({
        machine_transcript: machineTranscript,
        corrected_transcript: editableTranscript,
        audio_filename: transcriptionMeta?.audio_filename || null,
        audio_mimetype: audioBlob?.type || "audio/webm",
        audio_duration_seconds: duration || transcriptionMeta?.duration_seconds || 0,
        transcription_metadata: transcriptionMeta || {}
      });
    }
  };

  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
      {/* Header Tabs */}
      <div className="flex border-b border-slate-200 bg-slate-50/70 px-6 pt-4">
        <button
          onClick={() => setMode("record")}
          className={`flex items-center gap-2 pb-3 px-4 text-sm font-semibold border-b-2 transition-colors ${
            mode === "record"
              ? "border-clinical-teal-600 text-clinical-teal-700"
              : "border-transparent text-slate-500 hover:text-slate-800"
          }`}
        >
          <Mic className="w-4 h-4" />
          <span>Microphone Recording</span>
        </button>
        <button
          onClick={() => setMode("upload")}
          className={`flex items-center gap-2 pb-3 px-4 text-sm font-semibold border-b-2 transition-colors ${
            mode === "upload"
              ? "border-clinical-teal-600 text-clinical-teal-700"
              : "border-transparent text-slate-500 hover:text-slate-800"
          }`}
        >
          <Upload className="w-4 h-4" />
          <span>Upload Audio File</span>
        </button>
      </div>

      {/* Language Selector & Status */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between px-6 py-2.5 bg-slate-50/90 border-b border-slate-200 text-xs gap-2">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-slate-700">Speech Model:</span>
          <select
            value={selectedLanguage}
            onChange={(e) => setSelectedLanguage(e.target.value)}
            className="rounded border border-slate-300 bg-white px-2 py-1 text-xs text-slate-800 font-medium focus:ring-1 focus:ring-clinical-teal-500 shadow-sm"
          >
            <option value="en">English (Whisper Base - Ready)</option>
            <option value="ta">Tamil / தமிழ் (Regional model)</option>
            <option value="hi">Hindi / हिन्दी (Regional model)</option>
          </select>
        </div>
        {selectedLanguage !== "en" && (
          <div className="flex items-center gap-1.5 text-amber-800 font-medium bg-amber-50 px-2.5 py-1 rounded border border-amber-200">
            <AlertTriangle className="w-3.5 h-3.5 text-amber-600 shrink-0" />
            <span>Regional speech recognition model not installed in models/. English transcription remains active. (Typed notes in Tamil/Hindi fully supported)</span>
          </div>
        )}
      </div>

      <div className="p-6 space-y-6">
        {/* Error Alert */}
        {transcriptionError && (
          <div className="p-4 rounded-lg bg-red-50 border border-red-200 text-red-800 flex items-start gap-3 text-sm">
            <AlertTriangle className="w-5 h-5 text-red-600 shrink-0 mt-0.5" />
            <div className="flex-1">
              <span className="font-semibold">Transcription / Audio Notice: </span>
              {transcriptionError}
            </div>
          </div>
        )}

        {/* Recording Controls */}
        {mode === "record" ? (
          <div className="flex flex-col items-center justify-center p-8 bg-slate-50 rounded-xl border-2 border-dashed border-slate-200 text-center space-y-4">
            {/* Status indicator */}
            <div className="flex items-center gap-2 text-sm font-semibold">
              {recordingState === "recording" && (
                <span className="flex items-center gap-1.5 text-red-600">
                  <span className="w-2.5 h-2.5 rounded-full bg-red-600 animate-record-pulse"></span>
                  RECORDING IN PROGRESS
                </span>
              )}
              {recordingState === "paused" && (
                <span className="text-amber-600">RECORDING PAUSED</span>
              )}
              {recordingState === "stopped" && (
                <span className="text-emerald-700">AUDIO READY FOR TRANSCRIPTION</span>
              )}
              {recordingState === "idle" && (
                <span className="text-slate-500">READY TO CAPTURE CLINICAL FIELD NOTES</span>
              )}
            </div>

            {/* Timer */}
            <div className="text-4xl font-mono font-bold text-slate-800 tracking-wider">
              {formatTime(duration)}
            </div>

            {/* Control Buttons */}
            <div className="flex items-center gap-3 pt-2">
              {recordingState === "idle" && (
                <button
                  onClick={startRecording}
                  className="flex items-center gap-2 px-6 py-3 rounded-full bg-clinical-teal-600 hover:bg-clinical-teal-700 text-white font-semibold shadow-md transition-all active:scale-95"
                >
                  <Mic className="w-5 h-5" />
                  <span>Start Recording</span>
                </button>
              )}

              {recordingState === "recording" && (
                <>
                  <button
                    onClick={pauseRecording}
                    className="flex items-center gap-1.5 px-4 py-2.5 rounded-lg bg-amber-500 hover:bg-amber-600 text-white text-sm font-semibold shadow-sm"
                  >
                    <Pause className="w-4 h-4" />
                    <span>Pause</span>
                  </button>
                  <button
                    onClick={stopRecording}
                    className="flex items-center gap-1.5 px-6 py-2.5 rounded-lg bg-red-600 hover:bg-red-700 text-white text-sm font-semibold shadow-md active:scale-95"
                  >
                    <Square className="w-4 h-4" />
                    <span>Stop Recording</span>
                  </button>
                </>
              )}

              {recordingState === "paused" && (
                <>
                  <button
                    onClick={resumeRecording}
                    className="flex items-center gap-1.5 px-4 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-semibold shadow-sm"
                  >
                    <Play className="w-4 h-4" />
                    <span>Resume</span>
                  </button>
                  <button
                    onClick={stopRecording}
                    className="flex items-center gap-1.5 px-6 py-2.5 rounded-lg bg-red-600 hover:bg-red-700 text-white text-sm font-semibold shadow-md"
                  >
                    <Square className="w-4 h-4" />
                    <span>Stop</span>
                  </button>
                </>
              )}

              {recordingState === "stopped" && (
                <button
                  onClick={resetRecording}
                  className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-slate-200 hover:bg-slate-300 text-slate-700 text-sm font-semibold"
                >
                  <RotateCcw className="w-4 h-4" />
                  <span>Record Again</span>
                </button>
              )}
            </div>

            <p className="text-xs text-slate-400 max-w-md">
              Speak clearly. State patient symptoms, vital signs (e.g. BP 120/80, pulse 75), and administered medications with doses and routes.
            </p>
          </div>
        ) : (
          /* File Upload Box */
          <div className="p-8 bg-slate-50 rounded-xl border-2 border-dashed border-slate-300 text-center space-y-4">
            <Upload className="w-10 h-10 text-slate-400 mx-auto" />
            <div>
              <label
                htmlFor="audio-upload"
                className="cursor-pointer inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-clinical-teal-600 hover:bg-clinical-teal-700 text-white text-sm font-semibold shadow-sm"
              >
                <span>Select Audio File</span>
                <input
                  id="audio-upload"
                  type="file"
                  accept="audio/*,.webm,.wav,.mp3,.ogg,.m4a"
                  onChange={handleFileUpload}
                  className="hidden"
                />
              </label>
              <p className="text-xs text-slate-500 mt-2">
                Supported formats: WebM, WAV, MP3, OGG, M4A (Max 30MB)
              </p>
            </div>
            {selectedFile && (
              <div className="text-sm font-medium text-slate-700 bg-white p-2.5 rounded border border-slate-200 inline-block">
                Selected: {selectedFile.name} ({(selectedFile.size / 1024 / 1024).toFixed(2)} MB)
              </div>
            )}
          </div>
        )}

        {/* Audio Player for Review */}
        {audioUrl && (
          <div className="bg-slate-100 p-4 rounded-xl flex items-center justify-between border border-slate-200">
            <div className="flex items-center gap-3">
              <button
                onClick={togglePlayback}
                className="w-10 h-10 rounded-full bg-clinical-teal-700 text-white flex items-center justify-center hover:bg-clinical-teal-800 shadow-sm"
              >
                {isPlaying ? <Pause className="w-5 h-5" /> : <Play className="w-5 h-5 ml-0.5" />}
              </button>
              <div>
                <span className="text-sm font-semibold text-slate-800">Recorded Field Audio</span>
                <p className="text-xs text-slate-500">
                  {audioBlob ? `${(audioBlob.size / 1024).toFixed(1)} KB • ${audioBlob.type || "audio/webm"}` : ""}
                </p>
              </div>
              <audio
                ref={audioElementRef}
                src={audioUrl}
                onEnded={() => setIsPlaying(false)}
                className="hidden"
              />
            </div>

            {/* Transcribe Trigger Button */}
            <button
              onClick={handleTranscribe}
              disabled={isTranscribing}
              className="flex items-center gap-2 px-6 py-2.5 rounded-lg bg-clinical-teal-600 hover:bg-clinical-teal-700 disabled:bg-slate-300 text-white text-sm font-semibold shadow-md transition-all"
            >
              <Sparkles className="w-4 h-4" />
              <span>{isTranscribing ? `Transcribing (${transcribeElapsed}s)...` : "Transcribe with Whisper"}</span>
            </button>
          </div>
        )}

        {/* Transcribe Spinner Indicator */}
        {isTranscribing && (
          <div className="p-4 bg-teal-50 border border-teal-200 rounded-lg flex items-center gap-3 text-teal-800 text-sm">
            <div className="w-5 h-5 border-2 border-teal-600 border-t-transparent rounded-full animate-spin"></div>
            <div>
              <span className="font-semibold">Local Faster-Whisper Inference Running: </span>
              Decoding speech offline with clinical vocabulary priors... ({transcribeElapsed}s elapsed)
            </div>
          </div>
        )}

        {/* Editable Transcript Text Area */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-sm font-bold text-slate-800">
              Clinical Narrative / Field Notes Transcript
            </label>
            <span className="text-xs text-slate-500">
              {editableTranscript.trim() ? `${editableTranscript.trim().split(/\s+/).length} words` : "0 words"}
            </span>
          </div>

          <textarea
            rows={4}
            value={editableTranscript}
            onChange={(e) => setEditableTranscript(e.target.value)}
            placeholder="Whisper transcript will appear here automatically. You can also type or correct transcripts manually before extracting structured clinical data..."
            className="w-full p-3.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-clinical-teal-500 focus:border-clinical-teal-500 text-sm text-slate-800 placeholder-slate-400 bg-white shadow-inner resize-y font-mono text-sm leading-relaxed"
          />
        </div>

        {/* Word-Level Token Stream & Confidence Inspector */}
        {transcriptionMeta?.words && transcriptionMeta.words.length > 0 && (
          <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 space-y-3">
            <div className="flex items-center justify-between border-b border-slate-200/80 pb-2.5">
              <div className="flex items-center gap-2">
                <Tag className="w-4 h-4 text-clinical-teal-700" />
                <span className="text-xs font-bold text-slate-800 uppercase tracking-wider">
                  Word Tokens & Acoustic Probability Stream ({transcriptionMeta.words.length} tokens)
                </span>
              </div>
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-2 text-[10px] text-slate-500">
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block"></span> High (≥80%)
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-amber-500 inline-block"></span> Uncertain (&lt;80%)
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-slate-400 inline-block"></span> Unaligned / Typed
                  </span>
                </div>
                <button
                  onClick={() => setShowWordInspector(!showWordInspector)}
                  className="text-xs text-slate-600 hover:text-slate-900 p-1"
                  title="Toggle Word Token Viewer"
                >
                  {showWordInspector ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {showWordInspector && (
              <>
                <p className="text-[11px] text-slate-500">
                  Click any word token below to inspect acoustic probability (Faster-Whisper beam score), timing offset, catalogue verification, or make an in-place correction.
                </p>

                {/* Token Stream Chips */}
                <div className="flex flex-wrap gap-1.5 p-3 bg-white rounded-lg border border-slate-200 max-h-48 overflow-y-auto">
                  {transcriptionMeta.words.map((w, idx) => {
                    const prob = w.probability;
                    const isSelected = selectedWordIndex === idx;
                    const isMedical = w.medical_match && w.medical_match.status !== "NONE";
                    const isAmbiguous = w.medical_match && w.medical_match.requires_confirmation;

                    let bgStyle = "bg-slate-100 text-slate-800 border-slate-200 hover:bg-slate-200";
                    if (prob !== null && prob !== undefined) {
                      if (prob >= 0.8) {
                        bgStyle = "bg-emerald-50 text-emerald-900 border-emerald-200 hover:bg-emerald-100";
                      } else {
                        bgStyle = "bg-amber-50 text-amber-900 border-amber-300 hover:bg-amber-100 font-medium";
                      }
                    }

                    if (isAmbiguous) {
                      bgStyle = "bg-rose-50 text-rose-900 border-rose-300 hover:bg-rose-100 animate-pulse";
                    }

                    return (
                      <button
                        key={idx}
                        type="button"
                        onClick={() => {
                          setSelectedWordIndex(idx);
                          setWordReplacementInput(w.clean_text || w.word);
                        }}
                        className={`text-xs px-2 py-1 rounded border inline-flex items-center gap-1 transition-all ${bgStyle} ${
                          isSelected ? "ring-2 ring-clinical-teal-600 font-bold shadow-sm" : ""
                        }`}
                        title={`Click to inspect word "${w.word}"`}
                      >
                        <span>{w.word}</span>
                        {isMedical && (
                          <span className="text-[9px] px-1 py-0.2 rounded bg-clinical-teal-600 text-white font-mono">
                            Rx
                          </span>
                        )}
                        {isAmbiguous && (
                          <ShieldAlert className="w-3 h-3 text-rose-600" />
                        )}
                      </button>
                    );
                  })}
                </div>

                {/* Active Token Inspector Drawer */}
                {selectedWordIndex !== null && transcriptionMeta.words[selectedWordIndex] && (
                  <div className="p-3.5 bg-clinical-teal-50/90 rounded-lg border border-clinical-teal-200 space-y-3 text-xs">
                    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-clinical-teal-200/80 pb-2">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-slate-900 text-sm">
                          Token #{selectedWordIndex + 1}: "{transcriptionMeta.words[selectedWordIndex].word}"
                        </span>
                        <span className="text-slate-500 font-mono text-[11px]">
                          [{transcriptionMeta.words[selectedWordIndex].start}s – {transcriptionMeta.words[selectedWordIndex].end}s]
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-slate-600">Acoustic Confidence:</span>
                        {transcriptionMeta.words[selectedWordIndex].probability !== null &&
                        transcriptionMeta.words[selectedWordIndex].probability !== undefined ? (
                          <span
                            className={`font-mono font-bold px-2 py-0.5 rounded text-[11px] ${
                              transcriptionMeta.words[selectedWordIndex].probability >= 0.8
                                ? "bg-emerald-100 text-emerald-800"
                                : "bg-amber-100 text-amber-800"
                            }`}
                          >
                            {(transcriptionMeta.words[selectedWordIndex].probability * 100).toFixed(1)}% (Beam probability)
                          </span>
                        ) : (
                          <span className="bg-slate-200 text-slate-700 font-mono px-2 py-0.5 rounded text-[11px]">
                            Not available (Unaligned / Typed)
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Medical Catalogue Matching Info */}
                    {transcriptionMeta.words[selectedWordIndex].medical_match &&
                    transcriptionMeta.words[selectedWordIndex].medical_match.status !== "NONE" ? (
                      <div className="p-2.5 bg-white rounded border border-clinical-teal-200 space-y-1">
                        <div className="flex items-center justify-between">
                          <span className="font-semibold text-clinical-teal-900 flex items-center gap-1.5">
                            <Tag className="w-3.5 h-3.5 text-clinical-teal-600" />
                            Catalogue Match: {transcriptionMeta.words[selectedWordIndex].medical_match.matched_entity}
                          </span>
                          <span className="text-[10px] uppercase font-bold px-1.5 py-0.5 rounded bg-slate-100 text-slate-700">
                            {transcriptionMeta.words[selectedWordIndex].medical_match.status}
                          </span>
                        </div>
                        {transcriptionMeta.words[selectedWordIndex].medical_match.requires_confirmation && (
                          <div className="mt-1 p-2 bg-amber-50 rounded border border-amber-200 text-amber-900 flex items-center justify-between gap-2">
                            <span>
                              <strong>Ambiguity Warning:</strong> This term may refer to multiple drug formulations. Human clinician confirmation required.
                            </span>
                            <button
                              type="button"
                              onClick={() => {
                                const updatedWords = [...transcriptionMeta.words];
                                updatedWords[selectedWordIndex].medical_match.requires_confirmation = false;
                                updatedWords[selectedWordIndex].medical_match.confirmed = true;
                                setTranscriptionMeta((prev) => ({ ...prev, words: updatedWords }));
                              }}
                              className="px-2.5 py-1 bg-amber-600 hover:bg-amber-700 text-white rounded font-semibold text-[11px] shrink-0"
                            >
                              Confirm Match
                            </button>
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="text-[11px] text-slate-500 italic">
                        Standard narrative token (no critical formulary match).
                      </div>
                    )}

                    {/* Quick In-Place Word Correction */}
                    <div className="flex items-center gap-2 pt-1">
                      <input
                        type="text"
                        value={wordReplacementInput}
                        onChange={(e) => setWordReplacementInput(e.target.value)}
                        placeholder="Type word correction..."
                        className="flex-1 p-2 bg-white rounded border border-slate-300 text-xs focus:ring-2 focus:ring-clinical-teal-500 font-mono"
                      />
                      <button
                        type="button"
                        onClick={() => {
                          if (!wordReplacementInput.trim()) return;
                          const updatedWords = [...transcriptionMeta.words];
                          updatedWords[selectedWordIndex] = {
                            ...updatedWords[selectedWordIndex],
                            word: wordReplacementInput.trim(),
                            clean_text: wordReplacementInput.trim().toLowerCase(),
                            probability: null, // manual correction no longer has acoustic probability
                            confidence_category: "NOT_AVAILABLE"
                          };
                          setTranscriptionMeta((prev) => ({ ...prev, words: updatedWords }));

                          // Rebuild editable transcript
                          const updatedText = updatedWords.map((w) => w.word).join(" ");
                          setEditableTranscript(updatedText);
                          setSelectedWordIndex(null);
                        }}
                        className="px-3 py-2 bg-clinical-teal-700 hover:bg-clinical-teal-800 text-white rounded font-semibold text-xs flex items-center gap-1 shadow-sm"
                      >
                        <Edit3 className="w-3.5 h-3.5" />
                        <span>Apply Word Correction</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => setSelectedWordIndex(null)}
                        className="px-2.5 py-2 bg-slate-200 hover:bg-slate-300 text-slate-700 rounded text-xs"
                      >
                        Close
                      </button>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* If no audio tokens present (e.g. manually typed) */}
        {(!transcriptionMeta?.words || transcriptionMeta.words.length === 0) && editableTranscript.trim() && (
          <div className="p-2.5 bg-slate-50 border border-slate-200 rounded-lg text-[11px] text-slate-500 flex items-center gap-2">
            <HelpCircle className="w-4 h-4 text-slate-400 shrink-0" />
            <span>
              Transcript entered manually. Speech confidence probabilities are marked <strong>Not available</strong> for unaligned / typed notes.
            </span>
          </div>
        )}

        {/* Original Machine Transcript Diff / Display */}
        {machineTranscript && machineTranscript !== editableTranscript && (
          <div className="p-3 bg-amber-50/70 border border-amber-200 rounded-lg text-xs space-y-1">
            <div className="font-semibold text-amber-800 flex items-center gap-1.5">
              <span>Original Machine Transcript (Unmodified Audit Reference):</span>
            </div>
            <p className="text-amber-900 italic font-mono bg-white/70 p-2 rounded border border-amber-100">
              "{machineTranscript}"
            </p>
          </div>
        )}

        {/* Bottom Actions */}
        <div className="flex items-center justify-between pt-4 border-t border-slate-200">
          <div className="text-xs text-slate-500">
            {transcriptionMeta && (
              <span>
                Language: <b className="uppercase">{transcriptionMeta.language}</b> • Audio Duration:{" "}
                <b>{transcriptionMeta.duration_seconds}s</b> • Model: <b>{transcriptionMeta.model_used}</b>
              </span>
            )}
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={handleSaveDraft}
              disabled={!editableTranscript.trim()}
              className="px-6 py-2.5 rounded-lg bg-clinical-navy-800 hover:bg-clinical-navy-900 disabled:bg-slate-300 text-white text-sm font-semibold shadow-md transition-all"
            >
              Extract Clinical Events & Save Draft
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
