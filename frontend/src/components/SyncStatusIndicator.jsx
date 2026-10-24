import React, { useState, useEffect } from "react";
import {
  Wifi, WifiOff, RefreshCw, CheckCircle2, AlertTriangle,
  CloudUpload, ShieldAlert, HardDrive, Trash2, X, Info
} from "lucide-react";
import { syncManager, SyncState } from "../services/syncManager";
import { offlineStorage } from "../services/offlineStorage";

export function SyncStatusIndicator() {
  const [syncInfo, setSyncInfo] = useState(syncManager.getStateSnapshot());
  const [pendingCount, setPendingCount] = useState(0);
  const [showModal, setShowModal] = useState(false);
  const [storageStats, setStorageStats] = useState(null);
  const [isPersisted, setIsPersisted] = useState(false);
  const [confirmWipe, setConfirmWipe] = useState(false);

  useEffect(() => {
    const unsubscribe = syncManager.subscribe((state) => {
      setSyncInfo(state);
      updatePendingCount();
    });

    updatePendingCount();
    checkStorage();

    return () => unsubscribe();
  }, []);

  const updatePendingCount = async () => {
    try {
      const queue = await offlineStorage.getSyncQueue();
      setPendingCount(queue.length);
    } catch (err) {
      // ignore
    }
  };

  const checkStorage = async () => {
    const stats = await offlineStorage.getStorageQuotaEstimate();
    setStorageStats(stats);
    if (typeof navigator !== "undefined" && navigator.storage && navigator.storage.persisted) {
      try {
        const persisted = await navigator.storage.persisted();
        setIsPersisted(persisted);
      } catch (e) {
        // ignore
      }
    }
  };

  const handleRequestPersistence = async () => {
    const res = await offlineStorage.requestStoragePersistence();
    setIsPersisted(res);
  };

  const handleManualSync = async () => {
    await syncManager.triggerSync();
    updatePendingCount();
  };

  const handleDeviceWipe = async () => {
    await offlineStorage.clearAllLocalData();
    setConfirmWipe(false);
    setShowModal(false);
    updatePendingCount();
    alert("Local device clinical records and offline drafts have been securely purged.");
  };

  // Badge appearance by state
  const getBadgeConfig = () => {
    if (!syncInfo.isOnline) {
      return {
        bg: "bg-slate-800 text-slate-200 border-slate-700",
        icon: <WifiOff className="w-3.5 h-3.5 text-slate-400" />,
        text: pendingCount > 0 ? `Offline (${pendingCount} pending)` : "Offline"
      };
    }
    if (syncInfo.isSyncing || syncInfo.syncState === SyncState.SYNCING) {
      return {
        bg: "bg-sky-50 text-sky-700 border-sky-300",
        icon: <RefreshCw className="w-3.5 h-3.5 text-sky-600 animate-spin" />,
        text: "Synchronizing..."
      };
    }
    if (syncInfo.syncState === SyncState.FAILED) {
      return {
        bg: "bg-rose-50 text-rose-700 border-rose-300",
        icon: <AlertTriangle className="w-3.5 h-3.5 text-rose-600" />,
        text: "Sync Failed (Retry)"
      };
    }
    if (syncInfo.syncState === SyncState.CONFLICT) {
      return {
        bg: "bg-amber-50 text-amber-800 border-amber-300",
        icon: <ShieldAlert className="w-3.5 h-3.5 text-amber-600" />,
        text: "Conflict Detected"
      };
    }
    if (pendingCount > 0 || syncInfo.syncState === SyncState.PENDING) {
      return {
        bg: "bg-amber-50 text-amber-800 border-amber-300",
        icon: <CloudUpload className="w-3.5 h-3.5 text-amber-600" />,
        text: `Pending sync (${pendingCount})`
      };
    }
    return {
      bg: "bg-emerald-50 text-emerald-800 border-emerald-300",
      icon: <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />,
      text: "Synchronized"
    };
  };

  const badge = getBadgeConfig();

  return (
    <>
      <button
        onClick={() => {
          checkStorage();
          setShowModal(true);
        }}
        title="View Offline & Synchronization Diagnostics"
        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border shadow-xs transition-all hover:opacity-90 active:scale-95 ${badge.bg}`}
      >
        {badge.icon}
        <span>{badge.text}</span>
      </button>

      {/* Diagnostics & Sync Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4 backdrop-blur-xs">
          <div className="bg-white rounded-xl shadow-2xl max-w-md w-full border border-slate-200 overflow-hidden animate-in fade-in zoom-in duration-150">
            {/* Header */}
            <div className="bg-slate-900 text-white px-5 py-4 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <HardDrive className="w-5 h-5 text-teal-400" />
                <h3 className="font-semibold text-sm">Offline & Synchronization Manager</h3>
              </div>
              <button
                onClick={() => setShowModal(false)}
                className="text-slate-400 hover:text-white p-1 rounded-md"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Body */}
            <div className="p-5 space-y-4 text-xs text-slate-700">
              {/* Status Row */}
              <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg border border-slate-200">
                <span className="font-medium text-slate-600">Connection State:</span>
                <span className={`inline-flex items-center gap-1.5 font-semibold ${syncInfo.isOnline ? "text-emerald-700" : "text-slate-600"}`}>
                  {syncInfo.isOnline ? <Wifi className="w-4 h-4 text-emerald-600" /> : <WifiOff className="w-4 h-4 text-slate-500" />}
                  {syncInfo.isOnline ? "Online (Server Reachable)" : "Offline (Local Storage Only)"}
                </span>
              </div>

              <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg border border-slate-200">
                <span className="font-medium text-slate-600">Sync Status:</span>
                <span className="font-semibold text-slate-900">{syncInfo.syncState}</span>
              </div>

              <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg border border-slate-200">
                <span className="font-medium text-slate-600">Pending Queue:</span>
                <span className={`font-semibold px-2 py-0.5 rounded-full ${pendingCount > 0 ? "bg-amber-100 text-amber-800" : "bg-emerald-100 text-emerald-800"}`}>
                  {pendingCount} record(s) queued
                </span>
              </div>

              {/* Conflict details if any */}
              {syncInfo.conflicts && syncInfo.conflicts.length > 0 && (
                <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg text-amber-900">
                  <div className="flex items-center gap-1.5 font-semibold mb-1">
                    <ShieldAlert className="w-4 h-4 text-amber-600" />
                    Conflict Detected ({syncInfo.conflicts.length})
                  </div>
                  <p className="text-[11px] text-amber-800">
                    A record on the hospital server was updated while you were offline. Local changes have been preserved safely and will not be overwritten.
                  </p>
                </div>
              )}

              {/* Storage Quota & Persistence */}
              <div className="space-y-2 p-3 bg-slate-50 rounded-lg border border-slate-200">
                <div className="flex items-center justify-between">
                  <span className="font-medium text-slate-600">Device Storage Quota:</span>
                  <span className="font-mono text-slate-800">
                    {storageStats ? `${storageStats.usageMB} MB / ${storageStats.quotaMB} MB` : "Estimating..."}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="font-medium text-slate-600">Persistent Storage:</span>
                  <span className={`font-semibold ${isPersisted ? "text-emerald-700" : "text-amber-700"}`}>
                    {isPersisted ? "Granted (Protected from eviction)" : "Standard (Browser managed)"}
                  </span>
                </div>
                {!isPersisted && (
                  <button
                    onClick={handleRequestPersistence}
                    className="w-full mt-1 text-center py-1.5 px-2 bg-teal-50 hover:bg-teal-100 text-teal-800 border border-teal-200 rounded-md font-medium text-[11px]"
                  >
                    Request Persistent Storage Lock
                  </button>
                )}
              </div>

              {/* Documentation Note on Storage Lifecycles */}
              <div className="p-2.5 bg-blue-50 border border-blue-200 rounded-md text-[11px] text-blue-900 flex gap-2">
                <Info className="w-4 h-4 text-blue-600 shrink-0 mt-0.5" />
                <p>
                  <strong>Browser Storage Lifecycle:</strong> In-flight drafts and offline records are stored in browser IndexedDB.
                  They survive page reloads and browser restarts. However, manually clearing "Browser Cookies and Site Data" will wipe unsynchronized local data.
                </p>
              </div>

              {/* Actions */}
              <div className="pt-2 flex flex-col gap-2">
                <button
                  onClick={handleManualSync}
                  disabled={!syncInfo.isOnline || syncInfo.isSyncing || pendingCount === 0}
                  className="w-full flex items-center justify-center gap-2 py-2 px-4 bg-teal-700 hover:bg-teal-800 disabled:bg-slate-300 text-white rounded-lg font-medium text-xs shadow-xs"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${syncInfo.isSyncing ? "animate-spin" : ""}`} />
                  {syncInfo.isSyncing ? "Synchronizing Now..." : "Trigger Manual Synchronization"}
                </button>

                {!confirmWipe ? (
                  <button
                    onClick={() => setConfirmWipe(true)}
                    className="w-full py-1.5 text-center text-rose-600 hover:text-rose-800 hover:bg-rose-50 rounded-md text-[11px] font-medium"
                  >
                    Safe Logout & Purge Device Data
                  </button>
                ) : (
                  <div className="p-3 bg-rose-50 border border-rose-200 rounded-lg space-y-2">
                    <p className="font-semibold text-rose-800 text-[11px]">
                      Are you sure? This will permanently delete all cached records and drafts on this tablet.
                    </p>
                    <div className="flex gap-2">
                      <button
                        onClick={handleDeviceWipe}
                        className="flex-1 py-1 px-2 bg-rose-700 hover:bg-rose-800 text-white rounded font-medium text-xs"
                      >
                        Confirm Purge
                      </button>
                      <button
                        onClick={() => setConfirmWipe(false)}
                        className="flex-1 py-1 px-2 bg-slate-200 hover:bg-slate-300 text-slate-800 rounded font-medium text-xs"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

