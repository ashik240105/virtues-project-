import React, { useState, useEffect } from "react";
import { FileText, Search, Filter, Download, ArrowRight, Mic, Plus, CloudUpload } from "lucide-react";
import { api } from "../services/api";
import { offlineStorage } from "../services/offlineStorage";
import { StatusBadge } from "../components/StatusBadge";

export function RecordsPage({ onSelectRecord, onNewRecord }) {
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");

  useEffect(() => {
    let isMounted = true;
    const fetchRecords = async () => {
      try {
        let serverRecords = [];
        try {
          const params = {};
          if (statusFilter !== "ALL") params.status = statusFilter;
          const res = await api.listRecords(params);
          serverRecords = res.data || [];
        } catch (netErr) {
          console.warn("Backend offline or unreachable, serving from local storage:", netErr);
        }

        // Retrieve local offline records
        let offlineList = [];
        try {
          offlineList = await offlineStorage.getAllOfflineRecords();
        } catch (e) {
          console.warn("Could not read local offline storage:", e);
        }

        // Merge: server records + unsynced/local offline records (offline takes precedence for unsynced changes)
        const recordMap = new Map();
        for (const s of serverRecords) {
          recordMap.set(s.id, s);
        }
        for (const off of offlineList) {
          if (!recordMap.has(off.id) || off.sync_status === "PENDING_SYNC" || off.sync_status === "CONFLICT") {
            recordMap.set(off.id, off);
          }
        }

        const merged = Array.from(recordMap.values());
        // Sort newest first
        merged.sort((a, b) => new Date(b.created_at || b.updated_at) - new Date(a.created_at || a.updated_at));

        if (isMounted) setRecords(merged);
      } catch (err) {
        console.error("Failed to load records list:", err);
      } finally {
        if (isMounted) setLoading(false);
      }
    };
    fetchRecords();
    return () => { isMounted = false; };
  }, [statusFilter]);

  const filtered = records.filter((r) => {
    if (!searchTerm) return true;
    const q = searchTerm.toLowerCase();
    const call = (r.call_number || "").toLowerCase();
    const id = (r.id || "").toLowerCase();
    const text = (r.corrected_transcript || r.machine_transcript || "").toLowerCase();
    return call.includes(q) || id.includes(q) || text.includes(q);
  });

  const statuses = ["ALL", "Draft", "Needs Review", "Reviewed", "Approved", "Amended"];

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Header & Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold text-slate-900 tracking-tight">
            Clinical Field Records
          </h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Local offline pre-hospital medical encounter documentation
          </p>
        </div>

        <button
          onClick={onNewRecord}
          className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-clinical-teal-600 hover:bg-clinical-teal-700 text-white text-sm font-semibold shadow-md active:scale-95"
        >
          <Plus className="w-4 h-4" />
          <span>New Record</span>
        </button>
      </div>

      {/* Filter & Search Bar */}
      <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-3">
        {/* Search */}
        <div className="relative flex-1 max-w-md">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-3" />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Search by Call #, Record ID, or narrative keywords..."
            className="w-full pl-9 pr-3 py-2 text-xs rounded-lg border border-slate-300 focus:ring-2 focus:ring-clinical-teal-500 focus:border-clinical-teal-500"
          />
        </div>

        {/* Status Pill Filters */}
        <div className="flex flex-wrap items-center gap-1.5">
          {statuses.map((st) => (
            <button
              key={st}
              onClick={() => setStatusFilter(st)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                statusFilter === st
                  ? "bg-clinical-navy-800 text-white shadow-sm"
                  : "bg-slate-100 hover:bg-slate-200 text-slate-600"
              }`}
            >
              {st}
            </button>
          ))}
        </div>
      </div>

      {/* Records Table */}
      <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
        {loading ? (
          <div className="p-12 text-center text-slate-400 text-sm">Loading records...</div>
        ) : filtered.length === 0 ? (
          <div className="p-12 text-center space-y-3">
            <FileText className="w-12 h-12 text-slate-300 mx-auto" />
            <p className="text-sm font-semibold text-slate-700">No matching clinical records found</p>
            <p className="text-xs text-slate-500">Try adjusting your status filter or search keywords.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-slate-600 font-semibold text-xs border-b border-slate-200">
                <tr>
                  <th className="px-6 py-3.5">Encounter / Incident</th>
                  <th className="px-6 py-3.5">Date & Time</th>
                  <th className="px-6 py-3.5">Status</th>
                  <th className="px-6 py-3.5">Narrative Snippet</th>
                  <th className="px-6 py-3.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {filtered.map((rec) => (
                  <tr key={rec.id} className="hover:bg-slate-50/80 transition-colors">
                    <td className="px-6 py-4">
                      <div className="font-semibold text-slate-900">{rec.call_number || "EMS Call"}</div>
                      <div className="text-xs font-mono text-slate-400">{rec.id}</div>
                    </td>
                    <td className="px-6 py-4 text-xs text-slate-600">
                      {new Date(rec.created_at).toLocaleString()}
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <StatusBadge status={rec.status} />
                        {rec.sync_status === "PENDING_SYNC" && (
                          <span className="inline-flex items-center gap-1 text-[10px] bg-amber-100 text-amber-800 font-semibold px-2 py-0.5 rounded-full border border-amber-200">
                            <CloudUpload className="w-3 h-3 text-amber-600" />
                            Offline
                          </span>
                        )}
                        {rec.sync_status === "CONFLICT" && (
                          <span className="inline-flex items-center gap-1 text-[10px] bg-rose-100 text-rose-800 font-semibold px-2 py-0.5 rounded-full border border-rose-200">
                            Conflict
                          </span>
                        )}
                        {rec.version > 1 && (
                          <span className="text-[10px] bg-purple-100 text-purple-800 font-bold px-1.5 py-0.5 rounded">
                            v{rec.version}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-6 py-4 text-xs text-slate-600 max-w-xs truncate">
                      {rec.corrected_transcript || rec.machine_transcript || "No transcript"}
                    </td>
                    <td className="px-6 py-4 text-right space-x-2">
                      <button
                        onClick={() => onSelectRecord(rec.id, "review")}
                        className="px-3 py-1.5 rounded bg-clinical-teal-50 hover:bg-clinical-teal-100 text-clinical-teal-700 text-xs font-semibold"
                      >
                        Review
                      </button>
                      <button
                        onClick={() => onSelectRecord(rec.id, "details")}
                        className="px-3 py-1.5 rounded bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold"
                      >
                        Details
                      </button>
                      <a
                        href={api.getPdfUrl(rec.id)}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold"
                        title="Download PDF"
                      >
                        <Download className="w-3.5 h-3.5" />
                        <span>PDF</span>
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
