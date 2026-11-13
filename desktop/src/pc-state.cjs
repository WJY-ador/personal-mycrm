'use strict';
// "이 PC" line on the dashboard settings (spec 2026-11-13 §1.1): connected, a sync running, the last sync time and its
// result. The last sync is kept in a small userData file so it survives a restart. Only a time, a kind and a short code.
// No Electron here: the store, the clock and the live values are injected.
const {KINDS} = require('./failures.cjs');
const CODE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$/;

function parseLast(raw) {
  try {
    const j = typeof raw === 'string' ? JSON.parse(raw) : raw;
    const at = typeof j?.at === 'string' && Number.isFinite(Date.parse(j.at)) ? j.at : null;
    if (!at || !KINDS.includes(j.kind)) return null;
    return {at, kind: j.kind, code: typeof j.code === 'string' && CODE.test(j.code) ? j.code : null};
  } catch { return null; }
}

// deps: store {load() -> string|null, save(record)} · connected() -> bool · syncing() -> bool · now()
//       blocked() -> null | login | revoked | name | limit | failed   why this PC is not connected (connector.blockReason)
//       version · changed()
const BLOCKS = new Set(['login', 'revoked', 'name', 'limit', 'failed']);
function createPcState({store, connected, syncing, blocked = () => null, version, now = Date.now, changed = () => {}}) {
  let last = parseLast(store.load());
  return Object.freeze({
    view: () => {
      const b = blocked();
      return {version, connected: !!connected(), blocked: BLOCKS.has(b) ? b : null, syncing: !!syncing(), lastSync: last ? {...last} : null};
    },
    record({kind, code}) {
      last = {at: new Date(now()).toISOString(), kind: KINDS.includes(kind) ? kind : 'unknown',
        code: typeof code === 'string' && CODE.test(code) ? code : null};
      try { store.save(last); } catch {}
      changed();
    },
  });
}

module.exports = Object.freeze({createPcState, parseLast});
