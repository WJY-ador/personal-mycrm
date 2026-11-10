'use strict';
// In-app update: one place checks for a new release and, in supported builds, downloads and installs it.
// No Electron here — the app, electron-updater and the install steps are injected, so the state machine is tested
// with fakes. main.cjs is the only file that requires electron-updater.
//
// UpdateState (the contract the dashboard reads through dash-preload.cjs):
//   {inApp, phase: idle|checking|available|downloading|downloaded|error, current: 'X.Y.Z', version: 'X.Y.Z'|null,
//    percent: 0..100|null (downloading only), reason: network|verify|install|unknown|null (error only)}
// The state carries versions, progress and an error kind only — never a path, URL or error text.
const {newerVersion} = require('./policy.cjs');

const CHECK_EVERY_MS = 6 * 60 * 60 * 1000;
// After quitAndInstall the app should start quitting. On macOS Squirrel first fetches the zip from the local proxy and
// checks its signature, so the wait is generous. A failure inside it arrives as an 'error' event.
const INSTALL_WAIT_MS = 120 * 1000;
const VERSION = /^v?(\d+\.\d+\.\d+)$/;
const cleanVersion = v => VERSION.exec(typeof v === 'string' ? v : '')?.[1] || null;

// Supported: a packaged build without a test server, on Windows, or on macOS when the release build carries the marker
// (signed with the release certificate). Development runs and mycrmDevHosted builds only announce a new release.
function inAppSupported({isPackaged, platform, pkg = {}}) {
  return isPackaged === true && !pkg.mycrmDevHosted
    && (platform === 'win32' || (platform === 'darwin' && pkg.mycrmMacUpdater === true));
}

// Error kind for the state and the log. The error's own text and paths never leave this function.
function errorKind(e) {
  const code = typeof e?.code === 'string' ? e.code : '';
  if (['ERR_CHECKSUM_MISMATCH', 'ERR_UPDATER_INVALID_SIGNATURE', 'ERR_UPDATER_NO_CHECKSUM'].includes(code)) return 'verify';
  if (/^E(NOTFOUND|CONNRESET|CONNREFUSED|CONNABORTED|TIMEDOUT|AI_AGAIN|NETUNREACH|HOSTUNREACH|PIPE)$/.test(code)) return 'network';
  if (Number.isInteger(e?.statusCode)) return 'network';
  let message = '';
  try { message = String(e?.message || ''); } catch {}
  if (/net::ERR_/.test(message)) return 'network';
  if (/checksum mismatch/i.test(message)) return 'verify';
  return 'unknown';
}

// deps:
//   inApp                 inAppSupported(...) for this build
//   current               app version 'X.Y.Z'
//   load() -> autoUpdater electron-updater's autoUpdater; called only when inApp
//   checkRelease(current) -> {state:'available'|'current'|'not-published', version}   (policy.checkUpdate)
//   powerMonitor          'resume' starts a check
//   prepare() -> {quitting() -> bool, abort()}   main's install steps before quitAndInstall; rejects 'busy' or
//                                               'closing'. abort() makes the app usable again when it did not quit.
//   log(component, event) fixed event names only
function createUpdater({inApp, current, load, checkRelease, powerMonitor = null, prepare, log = () => {},
  timers = {setTimeout, clearTimeout, setInterval, clearInterval}}) {
  let updater = null;
  if (inApp) {
    try {
      updater = load();
      updater.logger = null;               // its logger writes URLs and paths
      updater.autoDownload = false;
      updater.autoInstallOnAppQuit = false;
      updater.allowPrerelease = false;
      updater.allowDowngrade = false;
    } catch { updater = null; inApp = false; log('update', 'load-failed'); }
  }
  let state = Object.freeze({inApp: !!inApp, phase: 'idle', current: cleanVersion(current) || '0.0.0', version: null, percent: null, reason: null});
  const listeners = new Set();
  let flight = null, interval = null, installing = false, settleInstall = null, started = false;

  function set(patch) {
    const next = {...state, ...patch};
    if (next.phase !== 'downloading') next.percent = null;
    if (next.phase !== 'error') next.reason = null;
    if (next.phase === 'idle' || next.phase === 'checking') next.version = null;
    if (['inApp', 'phase', 'current', 'version', 'percent', 'reason'].every(k => next[k] === state[k])) return;
    state = Object.freeze(next);
    for (const fn of listeners) { try { fn(state); } catch {} }
  }
  function fail(reason) { log('update', reason === 'install' ? 'install-failed' : 'download-failed-' + reason); set({phase: 'error', reason}); }

  if (updater) {
    // electron-updater also emits 'error' for failures it rejects; without a listener the emit itself would throw.
    // Outside an install the rejected promise is what counts. During an install the event is the failure signal.
    updater.on('error', () => { settleInstall?.('error'); });
    updater.on('download-progress', p => {
      if (state.phase !== 'downloading') return;
      const n = Number(p?.percent);
      if (Number.isFinite(n)) set({percent: Math.max(0, Math.min(100, Math.round(n)))});   // whole numbers 0..100
    });
  }

  // One check at a time. A failed check keeps the state it had (a background check never shows an error). Returns
  // 'ok', 'failed' or 'skipped' (a download or install is under way, or an error waits for the user's retry).
  function check() {
    if (flight) return flight;
    if (!['idle', 'available'].includes(state.phase) || installing) return Promise.resolve('skipped');
    const before = state.phase;
    if (before === 'idle') set({phase: 'checking'});   // a known new version stays 'available' while it is checked again
    flight = (async () => {
      let found;
      try {
        if (updater) {
          const r = await updater.checkForUpdates();
          if (!r) throw new Error('inactive');
          const version = cleanVersion(r.updateInfo?.version);
          // The web band drops a state whose version is not above current, so both must hold.
          found = r.isUpdateAvailable !== false && version && newerVersion(version, state.current) ? version : null;
        } else {
          const r = await checkRelease(state.current);
          const version = cleanVersion(r?.version);
          found = r?.state === 'available' && version && newerVersion(version, state.current) ? version : null;
        }
      } catch {
        log('update', 'check-failed');
        if (state.phase === 'checking') set({phase: before});
        return 'failed';
      }
      // A download the user started meanwhile is not overwritten by this answer.
      if (['idle', 'checking', 'available'].includes(state.phase)) {
        if (found && found !== state.version) log('update', 'available');
        set(found ? {phase: 'available', version: found} : {phase: 'idle'});
      }
      return 'ok';
    })().finally(() => { flight = null; });
    return flight;
  }

  // Starts the download the user asked for; the result comes as state. Also the retry from an error.
  async function download() {
    if (!updater || installing || !state.version || !['available', 'error'].includes(state.phase)) return;
    set({phase: 'downloading', percent: 0});
    log('update', 'download-started');
    try { await updater.downloadUpdate(); }
    catch (e) { if (state.phase === 'downloading') fail(errorKind(e)); return; }
    if (state.phase === 'downloading') { set({phase: 'downloaded'}); log('update', 'downloaded'); }
  }

  // The user's restart. main's prepare() takes the app lock, stops the connection device and waits for running
  // commands. quitAndInstall then quits the app; before-quit runs the usual cleanup. When the app does not start
  // quitting (an 'error' event, a throw or the wait running out), main's abort() makes the app usable again.
  async function install() {
    if (!updater || installing || state.phase !== 'downloaded') return;
    installing = true;
    log('update', 'install-started');
    let session;
    try { session = await prepare(); }
    catch (e) { installing = false; if (e?.message !== 'closing') fail('install'); return; }
    let timer = null;
    const outcome = new Promise(resolve => {
      settleInstall = resolve;
      timer = timers.setTimeout(() => resolve('timeout'), INSTALL_WAIT_MS);
    });
    try { updater.quitAndInstall(true, true); }
    catch { settleInstall?.('error'); }
    await outcome;
    settleInstall = null; timers.clearTimeout(timer);
    let closing = false;
    try { closing = session.quitting() === true; } catch {}
    if (closing) return;   // the app is quitting; nothing to undo
    try { await session.abort(); } catch { log('update', 'install-abort-failed'); }
    installing = false;
    fail('install');
  }

  function start() {
    if (started) return; started = true;
    check();
    interval = timers.setInterval(check, CHECK_EVERY_MS);
    powerMonitor?.on?.('resume', onResume);
  }
  function onResume() { check(); }
  function dispose() {
    if (interval) timers.clearInterval(interval);
    interval = null;
    powerMonitor?.removeListener?.('resume', onResume);
  }
  return Object.freeze({
    state: () => state,
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    check, download, install, start, dispose,
  });
}

// Dashboard bridge (main side). The dashboard window also shows notice() pages (data:) and its preload runs there too,
// so every call is checked: the dashboard's webContents, its top-level frame, a page on the hosted origin. The calls
// take no arguments. download and install answer at once; their results come as state.
const CHANNELS = Object.freeze({get: 'update:get', download: 'update:download', install: 'update:install', changed: 'update:changed'});
function trustedSender(event, contents, allowedUrl) {
  try {
    const frame = event?.senderFrame;
    return !!contents && event.sender === contents && !!frame && frame.parent === null
      && typeof frame.url === 'string' && allowedUrl(frame.url) === true;
  } catch { return false; }
}
function registerDashboardBridge({ipcMain, updater, trusted}) {
  const guard = fn => (event, ...args) => { if (args.length || !trusted(event)) throw new Error('sender'); return fn(); };
  ipcMain.handle(CHANNELS.get, guard(() => updater.state()));
  ipcMain.handle(CHANNELS.download, guard(() => { updater.download().catch(() => {}); }));
  ipcMain.handle(CHANNELS.install, guard(() => { updater.install().catch(() => {}); }));
}

module.exports = {createUpdater, inAppSupported, errorKind, trustedSender, registerDashboardBridge, CHANNELS, CHECK_EVERY_MS, INSTALL_WAIT_MS};
