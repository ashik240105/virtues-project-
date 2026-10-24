/**
 * Offline Storage Service using browser-native IndexedDB.
 * Provides resilient, refresh-proof persistence for in-flight drafts,
 * offline clinical records, sync queues, and device metadata.
 * Survives page reloads, browser closing, and intermittent power loss.
 */

const DB_NAME = "FieldToRecordDB";
const DB_VERSION = 1;

let dbPromise = null;

function openDB() {
  if (dbPromise) return dbPromise;

  dbPromise = new Promise((resolve, reject) => {
    if (typeof window === "undefined" || !window.indexedDB) {
      reject(new Error("IndexedDB is not supported on this device/browser."));
      return;
    }

    const request = indexedDB.open(DB_NAME, DB_VERSION);

    request.onupgradeneeded = (event) => {
      const db = event.target.result;

      // 1. In-flight clinical drafts (refresh-safe draft notes & recordings)
      if (!db.objectStoreNames.contains("drafts")) {
        db.createObjectStore("drafts", { keyPath: "draftKey" });
      }

      // 2. Incident records saved or edited offline
      if (!db.objectStoreNames.contains("offline_records")) {
        const recordStore = db.createObjectStore("offline_records", { keyPath: "id" });
        recordStore.createIndex("updated_at", "updated_at", { unique: false });
        recordStore.createIndex("sync_status", "sync_status", { unique: false });
      }

      // 3. Synchronization Queue (FIFO with retry tracking)
      if (!db.objectStoreNames.contains("sync_queue")) {
        const queueStore = db.createObjectStore("sync_queue", { keyPath: "id" });
        queueStore.createIndex("queued_at", "queued_at", { unique: false });
        queueStore.createIndex("status", "status", { unique: false });
      }

      // 4. Device metadata & audit retention
      if (!db.objectStoreNames.contains("device_meta")) {
        db.createObjectStore("device_meta", { keyPath: "key" });
      }
    };

    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });

  return dbPromise;
}

// Generic transaction helper
async function performTx(storeName, mode, callback) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, mode);
    const store = tx.objectStore(storeName);
    let result;

    tx.oncomplete = () => resolve(result);
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(new Error("IndexedDB transaction aborted"));

    try {
      result = callback(store);
    } catch (err) {
      reject(err);
    }
  });
}

export const offlineStorage = {
  // ==========================================
  // In-Flight Clinical Drafts (Refresh-Safe)
  // ==========================================
  async saveDraft(draftKey = "active_voice_draft", draftData) {
    const payload = {
      draftKey,
      data: draftData,
      saved_at: new Date().toISOString()
    };
    return performTx("drafts", "readwrite", (store) => {
      store.put(payload);
      return payload;
    });
  },

  async getDraft(draftKey = "active_voice_draft") {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction("drafts", "readonly");
      const store = tx.objectStore("drafts");
      const req = store.get(draftKey);
      req.onsuccess = () => resolve(req.result ? req.result.data : null);
      req.onerror = () => reject(req.error);
    });
  },

  async clearDraft(draftKey = "active_voice_draft") {
    return performTx("drafts", "readwrite", (store) => {
      store.delete(draftKey);
      return true;
    });
  },

  // ==========================================
  // Offline Records (Created or Edited Offline)
  // ==========================================
  async saveOfflineRecord(record) {
    const enhancedRecord = {
      ...record,
      local_saved_at: new Date().toISOString(),
      sync_status: record.sync_status || "PENDING_SYNC"
    };
    return performTx("offline_records", "readwrite", (store) => {
      store.put(enhancedRecord);
      return enhancedRecord;
    });
  },

  async getOfflineRecord(id) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction("offline_records", "readonly");
      const store = tx.objectStore("offline_records");
      const req = store.get(id);
      req.onsuccess = () => resolve(req.result || null);
      req.onerror = () => reject(req.error);
    });
  },

  async getAllOfflineRecords() {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction("offline_records", "readonly");
      const store = tx.objectStore("offline_records");
      const req = store.getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = () => reject(req.error);
    });
  },

  async deleteOfflineRecord(id) {
    return performTx("offline_records", "readwrite", (store) => {
      store.delete(id);
      return true;
    });
  },

  // ==========================================
  // Synchronization Queue
  // ==========================================
  async enqueueSync(queueItem) {
    const item = {
      id: queueItem.id || `sync-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`,
      record_id: queueItem.record_id,
      action: queueItem.action || "CREATE", // CREATE | UPDATE | AMEND
      payload: queueItem.payload,
      queued_at: queueItem.queued_at || new Date().toISOString(),
      retry_count: 0,
      status: "PENDING", // PENDING | SYNCING | FAILED | CONFLICT
      last_error: null
    };

    await performTx("sync_queue", "readwrite", (store) => {
      store.put(item);
    });
    return item;
  },

  async getSyncQueue() {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction("sync_queue", "readonly");
      const store = tx.objectStore("sync_queue");
      const req = store.getAll();
      req.onsuccess = () => {
        // Return sorted by queued_at (FIFO)
        const items = req.result || [];
        items.sort((a, b) => new Date(a.queued_at) - new Date(b.queued_at));
        resolve(items);
      };
      req.onerror = () => reject(req.error);
    });
  },

  async updateSyncItem(id, updates) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction("sync_queue", "readwrite");
      const store = tx.objectStore("sync_queue");
      const req = store.get(id);
      req.onsuccess = () => {
        if (!req.result) {
          resolve(null);
          return;
        }
        const updated = { ...req.result, ...updates };
        store.put(updated);
        resolve(updated);
      };
      req.onerror = () => reject(req.error);
    });
  },

  async removeSyncItem(id) {
    return performTx("sync_queue", "readwrite", (store) => {
      store.delete(id);
      return true;
    });
  },

  // ==========================================
  // Device Persistence & Quota Inquiries
  // ==========================================
  async requestStoragePersistence() {
    if (typeof navigator !== "undefined" && navigator.storage && navigator.storage.persist) {
      try {
        const isPersisted = await navigator.storage.persist();
        return isPersisted;
      } catch (err) {
        return false;
      }
    }
    return false;
  },

  async getStorageQuotaEstimate() {
    if (typeof navigator !== "undefined" && navigator.storage && navigator.storage.estimate) {
      try {
        const estimate = await navigator.storage.estimate();
        const usageMB = ((estimate.usage || 0) / (1024 * 1024)).toFixed(2);
        const quotaMB = ((estimate.quota || 0) / (1024 * 1024)).toFixed(2);
        const percentUsed = estimate.quota ? Math.round((estimate.usage / estimate.quota) * 100) : 0;
        return { usageMB, quotaMB, percentUsed, raw: estimate };
      } catch (err) {
        return { usageMB: "0", quotaMB: "0", percentUsed: 0 };
      }
    }
    return { usageMB: "N/A", quotaMB: "N/A", percentUsed: 0 };
  },

  // ==========================================
  // Safe Decommissioning / Device Data Purge
  // ==========================================
  async clearAllLocalData() {
    const db = await openDB();
    const storeNames = ["drafts", "offline_records", "sync_queue", "device_meta"];
    return new Promise((resolve, reject) => {
      const tx = db.transaction(storeNames, "readwrite");
      storeNames.forEach((s) => tx.objectStore(s).clear());
      tx.oncomplete = () => resolve(true);
      tx.onerror = () => reject(tx.error);
    });
  }
};

