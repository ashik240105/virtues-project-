/**
 * Synchronization Manager for Offline-First Operation.
 * Coordinates network detection, background sync queues, retry logic,
 * conflict handling, and UI state notifications.
 */

import { offlineStorage } from "./offlineStorage";
import { api } from "./api";

export const SyncState = {
  ONLINE: "Online",
  OFFLINE: "Offline",
  PENDING: "Pending synchronization",
  SYNCING: "Synchronizing",
  SYNCHRONIZED: "Synchronized",
  FAILED: "Synchronization failed",
  CONFLICT: "Conflict detected"
};

class SyncManager {
  constructor() {
    this.isOnline = typeof navigator !== "undefined" ? navigator.onLine : true;
    this.syncState = this.isOnline ? SyncState.SYNCHRONIZED : SyncState.OFFLINE;
    this.listeners = new Set();
    this.isSyncing = false;
    this.lastSyncTime = null;
    this.lastError = null;
    this.conflicts = [];
    this.deviceId = this.getOrCreateDeviceId();

    if (typeof window !== "undefined") {
      window.addEventListener("online", () => this.handleNetworkChange(true));
      window.addEventListener("offline", () => this.handleNetworkChange(false));
      // Periodic check or startup check
      setTimeout(() => this.checkQueueAndSync(), 1500);
    }
  }

  getOrCreateDeviceId() {
    if (typeof localStorage === "undefined") return "AMB-UNIT-DEV";
    let id = localStorage.getItem("f2r_device_id");
    if (!id) {
      id = `AMB-UNIT-${Math.floor(100 + Math.random() * 900)}`;
      localStorage.setItem("f2r_device_id", id);
    }
    return id;
  }

  subscribe(listener) {
    this.listeners.add(listener);
    // Emit immediate current state
    listener(this.getStateSnapshot());
    return () => this.listeners.delete(listener);
  }

  notify() {
    const snapshot = this.getStateSnapshot();
    for (const listener of this.listeners) {
      try {
        listener(snapshot);
      } catch (err) {
        console.error("SyncManager listener error:", err);
      }
    }
  }

  getStateSnapshot() {
    return {
      isOnline: this.isOnline,
      syncState: this.syncState,
      isSyncing: this.isSyncing,
      lastSyncTime: this.lastSyncTime,
      lastError: this.lastError,
      conflicts: this.conflicts,
      deviceId: this.deviceId
    };
  }

  async handleNetworkChange(online) {
    this.isOnline = online;
    if (!online) {
      this.syncState = SyncState.OFFLINE;
      this.notify();
    } else {
      // Reconnected! Automatically attempt synchronization
      const queue = await offlineStorage.getSyncQueue();
      if (queue.length > 0) {
        this.syncState = SyncState.PENDING;
        this.notify();
        await this.triggerSync();
      } else {
        this.syncState = SyncState.ONLINE;
        this.notify();
      }
    }
  }

  async checkQueueAndSync() {
    try {
      const queue = await offlineStorage.getSyncQueue();
      if (queue.length > 0) {
        this.syncState = this.isOnline ? SyncState.PENDING : SyncState.OFFLINE;
        this.notify();
        if (this.isOnline) {
          await this.triggerSync();
        }
      } else {
        this.syncState = this.isOnline ? SyncState.SYNCHRONIZED : SyncState.OFFLINE;
        this.notify();
      }
    } catch (err) {
      console.warn("Could not check sync queue:", err);
    }
  }

  /**
   * Primary synchronization executor with conflict handling and retry safety.
   */
  async triggerSync() {
    if (this.isSyncing) return;
    if (!this.isOnline) {
      this.syncState = SyncState.OFFLINE;
      this.notify();
      return;
    }

    const queue = await offlineStorage.getSyncQueue();
    if (queue.length === 0) {
      this.syncState = SyncState.SYNCHRONIZED;
      this.notify();
      return;
    }

    this.isSyncing = true;
    this.syncState = SyncState.SYNCING;
    this.lastError = null;
    this.notify();

    try {
      // Prepare records batch
      const recordsToSync = queue.map((item) => item.payload);

      const response = await api.syncRecords({
        device_id: this.deviceId,
        records: recordsToSync
      });

      const syncResult = response.data || {};
      const syncedItems = syncResult.synced || [];
      const conflictItems = syncResult.conflicts || [];
      const failedItems = syncResult.failed || [];

      // 1. Process successfully synced records
      for (const syncedRec of syncedItems) {
        const queueMatch = queue.find((q) => q.record_id === syncedRec.id || q.payload.id === syncedRec.id);
        if (queueMatch) {
          await offlineStorage.removeSyncItem(queueMatch.id);
        }
        // Mark local record as SYNCHRONIZED
        await offlineStorage.saveOfflineRecord({
          ...syncedRec,
          sync_status: "SYNCHRONIZED"
        });
      }

      // 2. Process conflicts without silently overwriting
      if (conflictItems.length > 0) {
        this.conflicts = conflictItems;
        for (const conf of conflictItems) {
          const queueMatch = queue.find((q) => q.record_id === conf.id || q.payload.id === conf.id);
          if (queueMatch) {
            await offlineStorage.updateSyncItem(queueMatch.id, {
              status: "CONFLICT",
              last_error: conf.reason
            });
          }
        }
        this.syncState = SyncState.CONFLICT;
      } else if (failedItems.length > 0) {
        this.syncState = SyncState.FAILED;
        this.lastError = `${failedItems.length} record(s) failed during synchronization.`;
      } else {
        this.syncState = SyncState.SYNCHRONIZED;
        this.lastSyncTime = new Date().toISOString();
        this.conflicts = [];
      }
    } catch (err) {
      console.error("Synchronization network error:", err);
      this.syncState = SyncState.FAILED;
      this.lastError = err.message || "Network error during synchronization.";

      // Update retry counts on queue items
      for (const item of queue) {
        await offlineStorage.updateSyncItem(item.id, {
          retry_count: (item.retry_count || 0) + 1,
          last_error: this.lastError
        });
      }
    } finally {
      this.isSyncing = false;
      this.notify();
    }
  }

  /**
   * Save an incident case locally and enqueue for sync.
   * Works whether currently online or offline.
   */
  async saveAndEnqueueRecord(recordData) {
    const stableId = recordData.id || `REC-${new Date().toISOString().slice(0, 10).replace(/-/g, "")}-${Math.random().toString(36).substring(2, 8).toUpperCase()}`;
    const nowIso = new Date().toISOString();

    const record = {
      ...recordData,
      id: stableId,
      created_at: recordData.created_at || nowIso,
      client_updated_at: nowIso,
      device_id: this.deviceId,
      sync_status: "PENDING_SYNC"
    };

    // 1. Immediately persist in IndexedDB
    await offlineStorage.saveOfflineRecord(record);

    // 2. Add to FIFO sync queue
    const queueItem = await offlineStorage.enqueueSync({
      record_id: stableId,
      action: "CREATE",
      payload: record
    });

    // 3. Clear in-flight draft since case has been permanently committed to local storage
    await offlineStorage.clearDraft("active_voice_draft");

    // 4. If online, immediately attempt synchronization
    if (this.isOnline) {
      this.triggerSync();
    } else {
      this.syncState = SyncState.PENDING;
      this.notify();
    }

    return record;
  }
}

export const syncManager = new SyncManager();

