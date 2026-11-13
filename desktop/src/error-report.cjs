'use strict';
// Automatic error report from the app (spec 2026-11-13 §1.4): a failure the person sees becomes a Case for the operator.
// Body: {source:'desktop', stage, code, http_status?, exit_code?, app_version, os: mac|win|linux, occurred_at}.
// Stage and code come from fixed lists and patterns only — never an error's text, a path, URL, token or record content.
// The server bundles the same (user, source, stage, code) per KST day and counts; the app only spaces repeats.
// One send, no retry, a failed report is never reported. Without a session (401) the report is dropped.
// No Electron here: request() and the clock are injected.
const {ERROR_REPORT_PATH} = require('./desktop-contract.cjs');

const STAGES = Object.freeze(['sync/run-once', 'sync/connect', 'connect/auto', 'update/error', 'ai/status', 'ai/connect',
  'agent/chat', 'agent/viewer', 'agent/jobs', 'app/command']);
const CODE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$/;
const REPEAT_MS = 10 * 60 * 1000;   // the same stage and code is sent at most once per 10 minutes from this app run

function osKind(platform) { return platform === 'darwin' ? 'mac' : platform === 'win32' ? 'win' : 'linux'; }
const smallInt = v => Number.isInteger(v) && v >= -255 && v <= 999;

// The report body, or null when the stage or code is not one of the fixed forms (then nothing is sent).
function buildReport(stage, code, {status, exit} = {}, {version, platform, now}) {
  if (!STAGES.includes(stage) || typeof code !== 'string' || !CODE.test(code)) return null;
  const body = {source: 'desktop', stage, code, app_version: String(version || ''), os: osKind(platform),
    occurred_at: new Date(now()).toISOString().replace(/\.\d{3}Z$/, 'Z')};
  if (smallInt(status)) body.http_status = status;
  if (smallInt(exit)) body.exit_code = exit;
  return body;
}

// deps: request(method, url, body, headers) -> {status}   main: net.request with the dashboard session
//       hosted · version · platform · log(component, event, code) · now()
function createReporter({request, hosted, version, platform = process.platform, log = () => {}, now = Date.now, repeatMs = REPEAT_MS}) {
  const origin = new URL(hosted).origin, url = new URL(ERROR_REPORT_PATH, hosted).href;
  const last = new Map();
  async function report(stage, code, extra = {}) {
    const body = buildReport(stage, code, extra, {version, platform, now});
    if (!body) { log('report', 'invalid'); return false; }
    const key = stage + '|' + code, t = now();
    if (last.has(key) && t - last.get(key) < repeatMs) return false;
    last.set(key, t);
    try {
      const res = await request('POST', url, body, {'Origin': origin, 'Content-Type': 'application/json'});
      const ok = !!res && res.status >= 200 && res.status < 300;
      log('report', ok ? 'sent' : 'dropped', res?.status);
      return ok;
    } catch { log('report', 'dropped'); return false; }
  }
  return Object.freeze({report});
}

module.exports = Object.freeze({createReporter, buildReport, STAGES, REPEAT_MS, osKind});
