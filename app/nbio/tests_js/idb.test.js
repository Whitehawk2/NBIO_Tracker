// idb.js — outbox + KV store contract tests.
//
// These pin the public API the rest of app.js relies on for offline
// resilience: enqueue/dequeue/listOutbox/countOutbox on the outbox store,
// and getKV/setKV on the kv store. The outbox is the offline event queue
// that survives /recover (deliberately preserved alongside localStorage).
//
// Isolation strategy: idb.js caches its open-DB promise as a closure
// singleton, so a fresh DB per test isn't easily achievable without
// touching production code. Instead each test drains whatever the
// previous test left in the outbox via the public API in beforeEach —
// this also exercises dequeue + listOutbox as a side effect.

import { describe, it, expect, beforeEach } from "vitest";

describe("window.NBIO_IDB.outbox", () => {
  beforeEach(async () => {
    // Drain leftovers so each test starts with an empty outbox. Uses the
    // public API (no test-only hooks needed in production code).
    const leftovers = await window.NBIO_IDB.listOutbox();
    for (const item of leftovers) {
      await window.NBIO_IDB.dequeue(item.idem);
    }
    expect(await window.NBIO_IDB.countOutbox()).toBe(0);
  });

  it("enqueue then listOutbox returns the item", async () => {
    const item = {
      idem: "test-1",
      method: "POST",
      url: "/api/events",
      body: { type: "wee", occurred_at: "2026-06-01T03:00:00Z" },
      ts: 1717207200000,
    };
    await window.NBIO_IDB.enqueue(item);

    const list = await window.NBIO_IDB.listOutbox();
    expect(list).toHaveLength(1);
    expect(list[0]).toEqual(item);
  });

  it("enqueue with the same idem overwrites (idempotent put, not insert)", async () => {
    await window.NBIO_IDB.enqueue({ idem: "test-1", body: { v: 1 } });
    await window.NBIO_IDB.enqueue({ idem: "test-1", body: { v: 2 } });

    const list = await window.NBIO_IDB.listOutbox();
    expect(list).toHaveLength(1);
    expect(list[0].body).toEqual({ v: 2 });
  });

  it("dequeue removes the matching idem only", async () => {
    await window.NBIO_IDB.enqueue({ idem: "keep-1", body: 1 });
    await window.NBIO_IDB.enqueue({ idem: "drop-2", body: 2 });
    await window.NBIO_IDB.enqueue({ idem: "keep-3", body: 3 });

    await window.NBIO_IDB.dequeue("drop-2");

    const list = await window.NBIO_IDB.listOutbox();
    const idems = list.map((x) => x.idem).sort();
    expect(idems).toEqual(["keep-1", "keep-3"]);
  });

  it("dequeue of an unknown idem is a no-op (doesn't throw, doesn't affect count)", async () => {
    await window.NBIO_IDB.enqueue({ idem: "real" });
    await window.NBIO_IDB.dequeue("does-not-exist");
    expect(await window.NBIO_IDB.countOutbox()).toBe(1);
  });

  it("countOutbox matches listOutbox.length across mixed ops", async () => {
    for (let i = 0; i < 5; i++) {
      await window.NBIO_IDB.enqueue({ idem: `item-${i}` });
    }
    expect(await window.NBIO_IDB.countOutbox()).toBe(5);

    await window.NBIO_IDB.dequeue("item-2");
    await window.NBIO_IDB.dequeue("item-4");

    const list = await window.NBIO_IDB.listOutbox();
    expect(list).toHaveLength(3);
    expect(await window.NBIO_IDB.countOutbox()).toBe(list.length);
  });
});

describe("window.NBIO_IDB.kv", () => {
  it("getKV returns null for an unknown key", async () => {
    const v = await window.NBIO_IDB.getKV("not-set-anywhere");
    expect(v).toBeNull();
  });

  it("setKV then getKV returns the stored value", async () => {
    await window.NBIO_IDB.setKV("last-sync", "2026-06-01T12:00:00Z");
    const v = await window.NBIO_IDB.getKV("last-sync");
    expect(v).toBe("2026-06-01T12:00:00Z");
  });

  it("setKV overwrites the previous value for the same key", async () => {
    await window.NBIO_IDB.setKV("last-sync", "first");
    await window.NBIO_IDB.setKV("last-sync", "second");
    expect(await window.NBIO_IDB.getKV("last-sync")).toBe("second");
  });
});
