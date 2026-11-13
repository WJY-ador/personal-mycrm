'use strict';
// "이 PC" line on the dashboard settings (spec 2026-11-13 §1.1; desktop-contract.cjs pc:get). The last sync is kept in a
// small userData file so it survives a restart: a time, ok or failed, and a short code only.
// No Electron here: the store, the clock and the live values are injected.
const {CODE} = require('./desktop-contract.cjs');
const ID = /^[A-Za-z0-9_-]{1,128}$/;
const RESULTS = new Set(['ok', 'failed']);

function parseLast(raw) {
  try {
    const j = typeof raw === 'string' ? JSON.parse(raw) : raw;
    const at = typeof j?.at === 'string' && Number.isFinite(Date.parse(j.at)) ? j.at : null;
    if (!at || !RESULTS.has(j.result)) return null;
    return {at, result: j.result, code: typeof j.code === 'string' && CODE.test(j.code) ? j.code : null};
  } catch { return null; }
}

// deps: store {load() -> string|null, save(record)} · now() · version · changed()
//       live() -> {signedIn: bool, deviceId: string|null, syncing: bool, login: bool, stopped: bool, blocked: bool}
//         login: no session (the dashboard shows its login screen) · stopped: the person stopped the PC processes
//         blocked: this PC cannot connect (released by the server, device limit, display name, failed connection)
function createPcState({store, live, version, now = Date.now, changed = () => {}}) {
  let last = parseLast(store.load());
  function view() {
    const l = live() || {};
    const state = l.syncing ? 'syncing' : l.login ? 'login' : l.stopped ? 'stopped'
      : (l.blocked || last?.result === 'failed') ? 'failed' : 'ok';
    return {signed_in: !!l.signedIn, device_id: typeof l.deviceId === 'string' && ID.test(l.deviceId) ? l.deviceId : null,
      state, last_sync_at: last?.at || null, last_result: last?.result || null, last_code: last?.code || null,
      app_version: String(version || '')};
  }
  // outcome: failures.cjs {kind, code}. ok -> ok; anything else -> failed with its code (or its kind as the code).
  function record({kind, code}) {
    const ok = kind === 'ok', c = ok ? null : (typeof code === 'string' && CODE.test(code) ? code : CODE.test(kind || '') ? kind : 'unknown');
    last = {at: new Date(now()).toISOString().replace(/\.\d{3}Z$/, 'Z'), result: ok ? 'ok' : 'failed', code: c};
    try { store.save(last); } catch {}
    changed();
  }
  return Object.freeze({view, record});
}

module.exports = Object.freeze({createPcState, parseLast});
