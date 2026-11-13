'use strict';
// Starting the PC processes (viewer, jobs, chat). The tray's start and the automatic start when the app opens run the same
// startConnection(), so a start the tray refuses (not connected, CLI not chosen) is refused here too.
// The screen lock does not gate or stop chat.
// No Electron here — every side effect is injected, so the gates are tested with the real Supervisor.

// Preference file: autoRun (the user's last start or stop; absent = start automatically) and openAtLogin (set once, then
// by the tray). allowCli is read for old files only: main derives it from the Claude link (jobs run while Claude is linked).
function readPreferences(text) {
  try {
    const p = JSON.parse(text);
    return {allowCli: p.allowCli === true, ...(typeof p.autoRun === 'boolean' ? {autoRun: p.autoRun} : {}),
      ...(typeof p.openAtLogin === 'boolean' ? {openAtLogin: p.openAtLogin} : {})};
  } catch { return {allowCli: false}; }
}

// deps: supervisor, prefs() -> {allowCli} (main: Claude linked), connection() -> {connected, cliConfigured}, startChat()
async function startProcesses(names, {supervisor, prefs, connection, startChat}) {
  if (names.includes('viewer')) supervisor.start('viewer', ['serve']);
  if (names.includes('jobs') && prefs().allowCli && connection().cliConfigured) supervisor.start('jobs', ['serve', '--jobs'], {allowCli: true});
  if (names.includes('chat') && connection().connected) await startChat();
}
// deps also: ready() -> bool (sidecar binary matches this app)
// The gates (ready, connected, CLI chosen) apply to the button and the automatic start alike.
async function startConnection(deps) {
  if (!deps.ready() || !deps.connection().connected) throw new Error('not-connected');
  const allowCli = deps.prefs().allowCli === true;
  if (allowCli && !deps.connection().cliConfigured) throw new Error('cli');
  await startProcesses(['viewer', ...(allowCli ? ['jobs'] : []), 'chat'], deps);
}
// Automatic start: the same full list as the button. The caller holds the app lock.
function startAutomatically(deps) { return startConnection(deps); }

// Fixed failure kinds for the log; any other error is 'error' (its text could carry sidecar or server content).
const KINDS = new Set(['not-connected', 'cli', 'busy', 'closing']);
// Held: the start may pass a moment later without anything changing in the app (app lock released).
// A held start is tried again on the next timer or window focus and does not count as an attempt.
const HELD = new Set(['busy']);
const MAX_ATTEMPTS = 3;
const kindOf = e => (KINDS.has(e?.message) ? e.message : 'error');

class AutoRun {
  // wanted() -> bool       the saved preference is not autoRun:false
  // connected() -> bool    this PC holds a device connection (connection().connected)
  // idle() -> bool         the app is not busy or quitting
  // start() -> Promise   startAutomatically() under the app lock
  // remember(bool)         saves autoRun to the preference file
  // log(component, event)  fixed event names only
  constructor({wanted, connected, idle, start, remember, log = () => {}, defer = setImmediate}) {
    Object.assign(this, {wanted, connected, idle, start, remember, log, defer});
    // 'start' → 'done'. 'done' also when the user started or stopped by hand, or the preference is off.
    this.phase = 'start';
    this.attempts = 0;        // counted failures of the current phase (held ones excluded)
    this.blocked = false;     // the last try failed or was held: only a timer or focus tries again (no change-driven loop)
    this.queued = false; this.inFlight = false; this.last = null;
  }
  get done() { return this.phase === 'done'; }
  // reason: 'startup' | 'change' | 'timer' | 'focus'. Never throws; the check runs after the caller returns.
  nudge(reason) {
    if (this.done || this.queued || this.inFlight) return;
    if (this.attempts >= MAX_ATTEMPTS) return;
    if (this.blocked && reason !== 'timer' && reason !== 'focus') return;
    this.queued = true;
    this.defer(() => { this.queued = false; this.run(reason).catch(() => {}); });
  }
  note(event) { if (event !== this.last) { this.last = event; this.log('autorun', event); } }
  result(reason, event) { this.last = null; this.note('attempt-' + reason); this.note(event); }
  fail(reason, kind) {
    this.blocked = true;
    if (HELD.has(kind)) { if (this.last !== 'held-' + kind) this.result(reason, 'held-' + kind); return; }
    this.attempts++; this.result(reason, 'failed-' + kind);
    if (this.attempts >= MAX_ATTEMPTS) this.note('gave-up');
  }
  async run(reason) {
    if (this.done || this.inFlight) return;
    if (this.attempts >= MAX_ATTEMPTS) return;
    this.inFlight = true;
    try {
      if (!this.wanted()) { this.phase = 'done'; this.note('off'); return; }
      if (!this.connected()) { if (this.phase === 'start') this.blocked = false; this.note('waiting-connection'); return; }
      if (!this.idle()) return;
      let kind;
      try { await this.start(); }
      catch (e) { kind = kindOf(e); }
      if (this.done) return;   // the user started or stopped by hand meanwhile
      if (kind) { this.fail(reason, kind); return; }
      this.blocked = false;
      this.phase = 'done'; this.result(reason, 'started');
    } catch { this.log('autorun', 'check-error'); }
    finally { this.inFlight = false; }
  }
  save(value) { try { this.remember(value); } catch { this.log('autorun', 'save-failed'); } }
  // The user's start (tray) succeeded: start automatically next time, and nothing is left to do in this run.
  manualStarted() { this.phase = 'done'; this.save(true); }
  // The user pressed stop (tray): stay off next time and in this run. Quitting is not a stop.
  userStopped() { this.phase = 'done'; this.save(false); }
}

module.exports = {AutoRun, readPreferences, startConnection, startAutomatically, startProcesses, MAX_ATTEMPTS};
