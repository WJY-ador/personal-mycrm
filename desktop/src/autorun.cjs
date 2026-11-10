'use strict';
const {hasLiveProcess} = require('./sidecar.cjs');
// Starting the connection device. The [연결 장치 시작] button and the automatic start when the app opens run the same
// startConnection(), so a start the button refuses (not connected, CLI not chosen, consent lock) is refused here too.
// No Electron here — every side effect is injected, so the gates are tested with the real Supervisor and lock guard.

// Preference file: allowCli (default false) and autoRun (the user's last start or stop; absent = start automatically).
function readPreferences(text) {
  try {
    const p = JSON.parse(text);
    return {allowCli: p.allowCli === true, ...(typeof p.autoRun === 'boolean' ? {autoRun: p.autoRun} : {})};
  } catch { return {allowCli: false}; }
}

// deps: supervisor, prefs() -> {allowCli}, connection() -> {connected, cliConfigured}, consentLock, startChat()
async function startProcesses(names, {supervisor, prefs, connection, consentLock, startChat}) {
  if (names.includes('chat') && !consentLock?.canStart()) throw new Error('consent-lock-' + (consentLock?.status() || 'unsupported'));
  if (names.includes('viewer')) supervisor.start('viewer', ['serve']);
  if (names.includes('jobs') && prefs().allowCli && connection().cliConfigured) supervisor.start('jobs', ['serve', '--jobs'], {allowCli: true});
  if (names.includes('chat') && connection().connected) await startChat();
}
// deps also: ready() -> bool (sidecar binary matches this app)
// pick(name) narrows the list; the gates above it (ready, connected, CLI chosen) and the consent lock check inside
// startProcesses apply to every list. The button always starts the full list.
async function startConnection(deps, pick = () => true) {
  if (!deps.ready() || !deps.connection().connected) throw new Error('not-connected');
  const allowCli = deps.prefs().allowCli === true;
  if (allowCli && !deps.connection().cliConfigured) throw new Error('cli');
  await startProcesses(['viewer', ...(allowCli ? ['jobs'] : []), 'chat'].filter(pick), deps);
}
// Automatic start: the full list when the consent lock allows chat, otherwise the same list without chat (the viewer
// and, with allowCli, jobs — what the button started before chat existed). Chat is never started without the lock.
// Returns whether chat was in the list. The caller holds the app lock.
async function startAutomatically(deps) {
  const chat = deps.consentLock?.canStart() === true;
  await startConnection(deps, chat ? undefined : name => name !== 'chat');
  return chat;
}
// Adds the held chat once the lock allows it. Processes already running are left as they are.
function addChat(deps) { return startConnection(deps, name => name === 'chat'); }

// The consent lock's onLock stops chat. When chat was running, the automatic start holds it again so it comes back
// after the unlock (focus or timer, with the lock open). The stop's own result is returned unchanged.
async function stopChatForLock(supervisor, autorun) {
  const wasLive = hasLiveProcess({chat: supervisor.snapshot().chat});
  const result = await supervisor.stop('chat');
  if (wasLive) autorun?.chatPausedByLock();
  return result;
}

// Fixed failure kinds for the log; any other error is 'error' (its text could carry sidecar or server content).
const KINDS = new Set(['not-connected', 'cli', 'busy', 'closing', 'consent-lock-unsupported', 'consent-lock-locked', 'consent-lock-revoke-unconfirmed']);
// Held: the start may pass a moment later without anything changing in the app (screen in use, app lock released).
// A held start is tried again on the next timer or window focus and does not count as an attempt.
const HELD = new Set(['busy', 'consent-lock-locked', 'consent-lock-revoke-unconfirmed']);
const MAX_ATTEMPTS = 3;
const kindOf = e => (KINDS.has(e?.message) ? e.message : 'error');

class AutoRun {
  // wanted() -> bool       the saved preference is not autoRun:false
  // connected() -> bool    this PC holds a device connection (connection().connected)
  // idle() -> bool         the app is not busy or quitting
  // start() -> Promise<bool>  startAutomatically() under the app lock; true when chat was included
  // chatReady() -> bool    the consent lock allows chat now (consentLock.canStart())
  // addChat() -> Promise   addChat() under the app lock
  // remember(bool)         saves autoRun to the preference file
  // log(component, event)  fixed event names only
  constructor({wanted, connected, idle, start, chatReady, addChat: add, remember, log = () => {}, defer = setImmediate}) {
    Object.assign(this, {wanted, connected, idle, start, chatReady, addChat: add, remember, log, defer});
    // 'start' → 'chat' (started without chat; chat waits for the consent lock) → 'done'.
    // 'done' also when the user started or stopped by hand, or the preference is off.
    this.phase = 'start';
    this.attempts = 0;        // counted failures of the current phase (held ones excluded)
    this.blocked = false;     // the last try failed or was held: only a timer or focus tries again (no change-driven loop)
    this.queued = false; this.inFlight = false; this.last = null;
    this.stopped = false;     // the user pressed stop in this run
    this.lastConnected = null;  // connection seen at the previous check, to catch a disconnect and reconnect
  }
  // A reconnect while chat is held (a disconnect stopped the viewer and jobs too) starts over with the full decision.
  track() {
    let now;
    try { now = this.connected() === true; } catch { return; }
    if (now && this.lastConnected === false && this.phase === 'chat' && !this.stopped) {
      this.phase = 'start'; this.attempts = 0; this.blocked = false; this.last = null; this.note('reconnected');
    }
    this.lastConnected = now;
  }
  get done() { return this.phase === 'done'; }
  // reason: 'startup' | 'change' | 'timer' | 'focus'. Never throws; the check runs after the caller returns.
  nudge(reason) {
    if (this.done || this.queued || this.inFlight) return;
    this.track();
    if (this.attempts >= MAX_ATTEMPTS) return;
    if ((this.blocked || this.phase === 'chat') && reason !== 'timer' && reason !== 'focus') return;
    this.queued = true;
    this.defer(() => { this.queued = false; this.run(reason).catch(() => {}); });
  }
  note(event) { if (event !== this.last) { this.last = event; this.log('autorun', event); } }
  result(reason, event) { this.last = null; this.note('attempt-' + reason); this.note(event); }
  fail(reason, kind, prefix) {
    this.blocked = true;
    if (HELD.has(kind)) { if (this.last !== prefix + 'held-' + kind) this.result(reason, prefix + 'held-' + kind); return; }
    this.attempts++; this.result(reason, prefix + 'failed-' + kind);
    if (this.attempts >= MAX_ATTEMPTS) this.note(prefix + 'gave-up');
  }
  async run(reason) {
    if (this.done || this.inFlight) return;
    this.track();
    if (this.attempts >= MAX_ATTEMPTS) return;
    this.inFlight = true;
    try {
      if (!this.wanted()) { this.phase = 'done'; this.note('off'); return; }
      if (!this.connected()) { if (this.phase === 'start') this.blocked = false; this.note('waiting-connection'); return; }
      if (!this.idle()) return;
      if (this.phase === 'chat') { await this.runChat(reason); return; }
      let kind, withChat;
      try { withChat = await this.start(); }
      catch (e) { kind = kindOf(e); }
      if (this.done) return;   // the user started or stopped by hand meanwhile
      if (kind) { this.fail(reason, kind, ''); return; }
      this.blocked = false;
      if (withChat) { this.phase = 'done'; this.result(reason, 'started'); }
      else { this.phase = 'chat'; this.attempts = 0; this.result(reason, 'started-without-chat'); }
    } catch { this.log('autorun', 'check-error'); }
    finally { this.inFlight = false; }
  }
  // The consent lock is checked before taking the app lock, so a closed lock costs no app lock and no log line.
  async runChat(reason) {
    if (!this.chatReady()) { this.note('chat-held'); return; }
    let kind;
    try { await this.addChat(); }
    catch (e) { kind = kindOf(e); }
    if (this.done) return;
    if (kind) { this.fail(reason, kind, 'chat-'); return; }
    this.phase = 'done'; this.result(reason, 'chat-added');
  }
  // Chat was stopped by a screen lock or sleep, not by the user: hold it again unless the user stopped or turned it off.
  chatPausedByLock() {
    try {
      if (this.stopped || !this.wanted()) return;
      this.phase = 'chat'; this.attempts = 0; this.blocked = false; this.last = null; this.note('chat-paused-lock');
    } catch { this.log('autorun', 'check-error'); }
  }
  save(value) { try { this.remember(value); } catch { this.log('autorun', 'save-failed'); } }
  // The user's [연결 장치 시작] succeeded: start automatically next time, and nothing is left to do in this run.
  manualStarted() { this.phase = 'done'; this.stopped = false; this.save(true); }
  // The user pressed stop (window or tray): stay off next time and in this run, held chat included. Quitting is not a stop.
  userStopped() { this.phase = 'done'; this.stopped = true; this.save(false); }
}

module.exports = {AutoRun, readPreferences, startConnection, startAutomatically, addChat, startProcesses, stopChatForLock, MAX_ATTEMPTS};
