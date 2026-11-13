'use strict';
// Automatic error report from the app (spec 2026-11-13 §1.4): a failure the person sees becomes a Case for the operator.
// Contract (desktop-contract.cjs): POST /desktop/error-reports with the login session, body
// {source: app|agent, stage, code, app_version, os: mac|win|other, occurred_at, count}. Stage comes from the fixed list
// below; a code that does not match CODE becomes 'unknown' — never an error's text, a path, URL, token or record content.
// The server bundles the same (user, source, stage, code) per KST day; the app only spaces repeats in one run.
// A network failure or 5xx is sent once more; a failed report is never reported. No Electron here.
const {ERROR_REPORT_PATH, CODE, STAGE} = require('./desktop-contract.cjs');

const STAGES = Object.freeze(['sync/run-once', 'sync/connect', 'connect/auto', 'update/error', 'ai/status', 'ai/connect',
  'agent/chat', 'agent/viewer', 'agent/jobs', 'app/start']);
const REPEAT_MS = 10 * 60 * 1000;   // the same stage and code is sent at most once per 10 minutes from this app run

function osKind(platform) { return platform === 'darwin' ? 'mac' : platform === 'win32' ? 'win' : 'other'; }

// The report body, or null when the stage is not one of the fixed stages (then nothing is sent).
// source 'agent' is for what the agent could not report itself (its device token was refused).
function buildReport(stage, code, {source = 'app'} = {}, {version, platform, now}) {
  if (!STAGES.includes(stage) || !STAGE.test(stage) || !['app', 'agent'].includes(source)) return null;
  return {source, stage, code: typeof code === 'string' && CODE.test(code) ? code : 'unknown',
    app_version: String(version || ''), os: osKind(platform),
    occurred_at: new Date(now()).toISOString().replace(/\.\d{3}Z$/, 'Z'), count: 1};
}

// deps: request(method, url, body, headers) -> {status}   main: net.request with the dashboard session
//       hosted · version · platform · log(component, event, code) · now()
function createReporter({request, hosted, version, platform = process.platform, log = () => {}, now = Date.now, repeatMs = REPEAT_MS}) {
  const origin = new URL(hosted).origin, url = new URL(ERROR_REPORT_PATH, hosted).href;
  const last = new Map();
  async function report(stage, code, extra = {}) {
    const body = buildReport(stage, code, extra, {version, platform, now});
    if (!body) { log('report', 'invalid'); return false; }
    const key = body.source + '|' + stage + '|' + body.code, t = now();
    if (last.has(key) && t - last.get(key) < repeatMs) return false;
    last.set(key, t);
    for (let attempt = 0; attempt < 2; attempt++) {
      let res = null;
      try { res = await request('POST', url, body, {'Origin': origin, 'Content-Type': 'application/json'}); } catch {}
      const status = res?.status || 0;
      if (status >= 200 && status < 300) { log('report', res.body?.accepted === false ? 'not-accepted' : 'sent', status); return true; }
      if (status >= 400 && status < 500) { log('report', 'refused', status); return false; }
    }
    log('report', 'dropped');
    return false;
  }
  return Object.freeze({report});
}

module.exports = Object.freeze({createReporter, buildReport, STAGES, REPEAT_MS, osKind});
