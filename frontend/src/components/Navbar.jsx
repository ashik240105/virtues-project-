import React, { useEffect, useState } from "react";
import { Activity, Mic, FileText, Settings, ShieldCheck, AlertCircle, Users } from "lucide-react";
import { api } from "../services/api";
import { SyncStatusIndicator } from "./SyncStatusIndicator";

export function Navbar({ activeTab, setActiveTab }) {
  const [modelStatus, setModelStatus] = useState({ ready: false, message: "Checking..." });

  useEffect(() => {
    let isMounted = true;
    const checkStatus = async () => {
      try {
        const res = await api.getTranscriptionStatus();
        if (isMounted) {
          setModelStatus({
            ready: res.data.is_ready,
            message: res.data.is_ready ? `${res.data.model_name} (offline)` : res.data.status
          });
        }
      } catch (err) {
        if (isMounted) {
          setModelStatus({ ready: false, message: "Backend offline" });
        }
      }
    };
    checkStatus();
    const interval = setInterval(checkStatus, 15000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  const navItems = [
    { id: "dashboard", label: "Dashboard", icon: Activity },
    { id: "voice", label: "New Record", icon: Mic },
    { id: "records", label: "Clinical Records", icon: FileText },
    { id: "patients", label: "Patients", icon: Users },
    { id: "settings", label: "System Status", icon: Settings },
  ];

  return (
    <header className="bg-clinical-navy-900 text-white shadow-md border-b border-slate-800 sticky top-0 z-40">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo & Brand */}
          <div className="flex items-center gap-3 cursor-pointer" onClick={() => setActiveTab("dashboard")}>
            <div className="w-10 h-10 rounded-lg bg-clinical-teal-600 flex items-center justify-center text-white shadow-md">
              <Activity className="w-6 h-6" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold text-lg tracking-tight">FIELD-TO-RECORD</span>
                <span className="text-[10px] font-semibold uppercase bg-clinical-teal-800/80 text-clinical-teal-200 px-2 py-0.5 rounded border border-clinical-teal-700">
                  EMS Field Note
                </span>
              </div>
              <p className="text-xs text-slate-400">Offline Clinical Documentation Assistant</p>
            </div>
          </div>

          {/* Navigation Links */}
          <nav className="flex items-center gap-1 sm:gap-2">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => setActiveTab(item.id)}
                  className={`flex items-center gap-2 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                    isActive
                      ? "bg-clinical-teal-700 text-white shadow-sm"
                      : "text-slate-300 hover:bg-clinical-navy-800 hover:text-white"
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  <span>{item.label}</span>
                </button>
              );
            })}
          </nav>

          {/* Right Status Controls */}
          <div className="flex items-center gap-2">
            <SyncStatusIndicator />

            {/* Whisper Status Badge */}
            <div className="hidden lg:flex items-center gap-2 bg-clinical-navy-800/80 px-2.5 py-1 rounded-full border border-slate-700 text-xs">
              {modelStatus.ready ? (
                <>
                  <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                  <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                  <span className="text-slate-200 font-medium">Whisper {modelStatus.message}</span>
                </>
              ) : (
                <>
                  <span className="w-2 h-2 rounded-full bg-amber-400"></span>
                  <AlertCircle className="w-3.5 h-3.5 text-amber-400" />
                  <span className="text-slate-300 font-medium">{modelStatus.message}</span>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}
