'use strict';
// AI connection in the app (spec 2026-11-13 §1.3): the provider's own CLI login on this PC, kept by the CLI, and a local
// "disconnect" mark. The agent sidecar does the work (agent/ai_connection.py holds the CLI names and arguments):
//   ai-status                    -> {"ai": {claude: Link, codex: Link}}
//   ai-connect --provider P      -> clears the mark; when signed out, runs the provider login (browser, at most 5 min)
//   ai-disconnect --provider P   -> sets the mark
// Link = {state: linked|signed_out|off|missing, code: string|null}. The dashboard also sees checking and linking.
// After a change the running chat agent is told to check again and send hello again (notifyChat); it also checks
// at every conversation start, so a missed notice is not a hole. No Electron here: everything is injected.
const {PROVIDERS, CODE} = require('./desktop-contract.cjs');

const STATES = Object.freeze(['linked', 'signed_out', 'off', 'missing']);
const STATUS_TIMEOUT_MS = 60 * 1000;
const CONNECT_TIMEOUT_MS = 6 * 60 * 1000;   // the agent waits up to 5 minutes for the provider login

// The sidecar's last output line {"ai": {...}}. Only provider names, state words and well-formed codes are kept.
function parseLinks(line) {
  try {
    const ai = JSON.parse(line)?.ai;
    if (!ai || typeof ai !== 'object' || Array.isArray(ai)) return null;
    const out = {};
    for (const p of PROVIDERS) {
      const v = ai[p];
      if (v && typeof v === 'object' && STATES.includes(v.state)) out[p] = {state: v.state, code: typeof v.code === 'string' && CODE.test(v.code) ? v.code : null};
    }
    return Object.keys(out).length ? out : null;
  } catch { return null; }
}

// deps: run(args, {timeoutMs}) -> {code, last}   sidecar command (main: command()); last = its last output line
//       notifyChat()                             tells a running chat agent to check again and send hello
//       linkedChanged(provider, linked)          a provider became linked or stopped being linked (main: jobs)
//       report(stage, code) · log(component, event, code) · changed() · now()
function createAiLink({run, notifyChat = () => {}, linkedChanged = () => {}, report = () => {}, log = () => {}, changed = () => {}, now = Date.now}) {
  const links = Object.fromEntries(PROVIDERS.map(p => [p, null]));
  let checkedAt = null, connecting = null, refreshing = null;
  const view = () => ({providers: PROVIDERS.map(p => ({provider: p,
    state: connecting === p ? 'linking' : links[p] ? links[p].state : 'checking',
    code: connecting === p || !links[p] ? null : links[p].code}))});
  const linked = p => links[p]?.state === 'linked';
  // Applies a check. A provider that crossed the linked line is told to main. Returns whether any state moved.
  function apply(parsed, providers, failCode) {
    const crossed = [];let moved = false;
    for (const p of providers) {
      const before = links[p];
      let next = parsed?.[p] || {state: before?.state === 'off' ? 'off' : 'missing', code: failCode};
      // code unchecked = the sidecar did not run that CLI (Codex before it is ready: only ai:connect runs it). A linked result
      // from the user's own connect stays until a real answer (off, missing, or a run) replaces it.
      if (next.code === 'unchecked' && before?.state === 'linked') next = before;
      if ((before?.state === 'linked') !== (next.state === 'linked')) crossed.push(p);
      if (!before || before.state !== next.state) moved = true;
      links[p] = next;
    }
    checkedAt = now(); changed();
    for (const p of crossed) { try { linkedChanged(p, linked(p)); } catch {} }
    return moved;
  }
  async function call(args, timeoutMs) {
    try { const r = await run(args, {timeoutMs}); return r && r.code === 0 ? parseLinks(r.last) : null; }
    catch { return null; }
  }
  function tellChat(event) { log('ai', event); try { notifyChat(); } catch { log('ai', 'notify-failed'); } }
  // At app start and when the dashboard asks (maxAgeMs: a check younger than this is reused). One at a time.
  // A login or logout made outside the app is seen here and reaches the chat agent too.
  function refresh(maxAgeMs = 0) {
    if (refreshing) return refreshing;
    if (maxAgeMs > 0 && checkedAt !== null && now() - checkedAt < maxAgeMs) return Promise.resolve(view());
    refreshing = (async () => {
      const first = checkedAt === null;
      const parsed = await call(['ai-status'], STATUS_TIMEOUT_MS);
      if (!parsed) { log('ai', 'status-failed'); report('ai/status', 'unavailable'); }
      const moved = apply(parsed, PROVIDERS, parsed ? null : 'status-unavailable');
      if (moved && !first && parsed) tellChat('changed');
      return view();
    })().finally(() => { refreshing = null; });
    return refreshing;
  }
  // One provider login at a time; the app lock is not held, so sync keeps running while the browser is open.
  async function connect(provider) {
    if (!PROVIDERS.includes(provider)) throw new Error('input');
    if (connecting) throw new Error('busy');
    connecting = provider; changed();
    let parsed = null;
    try {
      parsed = await call(['ai-connect', '--provider', provider], CONNECT_TIMEOUT_MS);
    } finally { connecting = null; }
    apply(parsed, [provider], parsed ? null : 'connect-unavailable');
    if (!parsed) { log('ai', 'connect-failed'); report('ai/connect', 'unavailable'); }
    else if (!linked(provider) && links[provider].code) report('ai/connect', links[provider].code);
    tellChat('connected-' + provider);
    return view();
  }
  async function disconnect(provider) {
    if (!PROVIDERS.includes(provider)) throw new Error('input');
    const parsed = await call(['ai-disconnect', '--provider', provider], STATUS_TIMEOUT_MS);
    if (!parsed) { report('ai/connect', 'disconnect-unavailable'); return view(); }
    apply(parsed, [provider], null);
    tellChat('disconnected-' + provider);
    return view();
  }
  return Object.freeze({view, refresh, connect, disconnect, linked});
}

module.exports = Object.freeze({createAiLink, parseLinks, STATES, STATUS_TIMEOUT_MS, CONNECT_TIMEOUT_MS});
