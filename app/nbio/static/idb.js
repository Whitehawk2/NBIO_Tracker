/* Tiny IndexedDB wrapper for outbox + local cache. */
(function () {
  const DB_NAME = "nbio";
  const DB_VERSION = 1;
  let dbPromise = null;

  function openDB() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = (ev) => {
        const db = req.result;
        if (!db.objectStoreNames.contains("outbox")) {
          db.createObjectStore("outbox", { keyPath: "idem" });
        }
        if (!db.objectStoreNames.contains("kv")) {
          db.createObjectStore("kv", { keyPath: "k" });
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    return dbPromise;
  }

  function tx(store, mode) {
    return openDB().then((db) => db.transaction(store, mode).objectStore(store));
  }

  window.NBIO_IDB = {
    enqueue(item) {
      return tx("outbox", "readwrite").then((s) => new Promise((res, rej) => {
        const r = s.put(item);
        r.onsuccess = () => res();
        r.onerror = () => rej(r.error);
      }));
    },
    dequeue(idem) {
      return tx("outbox", "readwrite").then((s) => new Promise((res, rej) => {
        const r = s.delete(idem);
        r.onsuccess = () => res();
        r.onerror = () => rej(r.error);
      }));
    },
    listOutbox() {
      return tx("outbox", "readonly").then((s) => new Promise((res, rej) => {
        const r = s.getAll();
        r.onsuccess = () => res(r.result || []);
        r.onerror = () => rej(r.error);
      }));
    },
    countOutbox() {
      return tx("outbox", "readonly").then((s) => new Promise((res, rej) => {
        const r = s.count();
        r.onsuccess = () => res(r.result || 0);
        r.onerror = () => rej(r.error);
      }));
    },
    getKV(k) {
      return tx("kv", "readonly").then((s) => new Promise((res, rej) => {
        const r = s.get(k);
        r.onsuccess = () => res(r.result ? r.result.v : null);
        r.onerror = () => rej(r.error);
      }));
    },
    setKV(k, v) {
      return tx("kv", "readwrite").then((s) => new Promise((res, rej) => {
        const r = s.put({ k, v });
        r.onsuccess = () => res();
        r.onerror = () => rej(r.error);
      }));
    },
  };
})();
