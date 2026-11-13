'use strict';
// AI connection in the app (spec 2026-11-13 §1.3): the provider's own CLI login on this PC, kept by the CLI, and a local
// "disconnect" mark. The agent sidecar does the work (agent/ai_connection.py holds the CLI names and arguments):
//   ai-status                    -> {"ai": {claude: State, codex: State}}
//   ai-connect --provider P      -> clears the mark; when signed out, runs the provider login (browser) -> {"ai": {P: State}}
//   ai-disconnect --provider P   -> sets the mark -> {"ai": {P: "off"}}
// State ∈ ready | signed-out | missing | off | unsupported | error (agent/ai_connection.STATES).
// The chat agent reads both at its start, so a change takes effect through a chat restart (restartChat).
// No Electron here: run(), restartChat(), report() and the clock are injected.
const {PROVIDERS} = require('./desktop-contract.cjs');

const STATES = Object.freeze(['ready', 'signed-out', 'missing', 'off', 'unsupported', 'error']);
const STATUS_TIMEOUT_MS = 60 * 1000;
const CONNECT_TIMEOUT_MS = 11 * 60 * 1000;   // the agent waits up to 10 minutes for the browser login

// The sidecar's last output line {"ai": {...}}. Only provider names and state words are kept.
function parseStates(line) {
  try {
    const ai = JSON.parse(line)?.ai;
    if (!ai || typeof ai !== 'object' || Array.isArray(ai)) return null;
    const out = {};
    for (const p of PROVIDERS) if (STATES.includes(ai[p])) out[p] = ai[p];
    return Object.keys(out).length ? out : null;
  } catch { return null; }
}

// deps: run(args, {timeoutMs}) -> {code, last}   sidecar command (main: command()); last = its last output line
//       restartChat() -> Promise                 restarts a running chat agent under the app lock; may reject 'busy'
//       report(stage, code)                      error-report.cjs · log(component, event, code) · changed() · now()
function createAiLink({run, restartChat = async () => {}, report = () => {}, log = () => {}, changed = () => {}, now = Date.now}) {
  const states = Object.fromEntries(PROVIDERS.map(p => [p, 'unknown']));
  let checkedAt = null, connecting = null, refreshing = null;
  const view = () => ({providers: {...states}, connecting, checkedAt});
  const apply = (parsed, providers) => {
    for (const p of providers) states[p] = parsed?.[p] || 'error';
    checkedAt = now(); changed();
  };
  async function call(args, timeoutMs) {
    try { const r = await run(args, {timeoutMs}); return r && r.code === 0 ? parseStates(r.last) : null; }
    catch { return null; }
  }
  // At app start and when the dashboard asks (maxAgeMs: a check younger than this is reused). One at a time.
  // A provider that became ready or stopped being ready since the last check (a login or logout in a terminal) reaches
  // the chat agent through a restart, as a change made here does. The first check after start restarts nothing.
  function refresh(maxAgeMs = 0) {
    if (refreshing) return refreshing;
    if (maxAgeMs > 0 && checkedAt !== null && now() - checkedAt < maxAgeMs) return Promise.resolve(view());
    refreshing = (async () => {
      const before = {...states};
      const parsed = await call(['ai-status'], STATUS_TIMEOUT_MS);
      if (!parsed) { log('ai', 'status-failed'); report('ai/status', 'unavailable'); }
      apply(parsed, PROVIDERS);
      const crossed = parsed && PROVIDERS.find(p => before[p] !== 'unknown' && (before[p] === 'ready') !== (states[p] === 'ready'));
      if (crossed) await afterChange(crossed, 'changed');
      return view();
    })().finally(() => { refreshing = null; });
    return refreshing;
  }
  async function afterChange(provider, event) {
    log('ai', event + '-' + provider);
    try { await restartChat(); } catch { log('ai', 'chat-restart-failed'); }
  }
  // One provider login at a time; the app lock is not held, so sync keeps running while the browser is open.
  async function connect(provider) {
    if (!PROVIDERS.includes(provider)) throw new Error('input');
    if (connecting) throw new Error('busy');
    connecting = provider; changed();
    try {
      const parsed = await call(['ai-connect', '--provider', provider], CONNECT_TIMEOUT_MS);
      apply(parsed, [provider]);
      const state = states[provider];
      if (state === 'error') { log('ai', 'connect-failed'); report('ai/connect', parsed ? 'error' : 'unavailable'); }
      if (state === 'ready') await afterChange(provider, 'connected');
    } finally { connecting = null; changed(); }
    return view();
  }
  async function disconnect(provider) {
    if (!PROVIDERS.includes(provider)) throw new Error('input');
    const parsed = await call(['ai-disconnect', '--provider', provider], STATUS_TIMEOUT_MS);
    apply(parsed, [provider]);
    if (states[provider] === 'off') await afterChange(provider, 'disconnected');
    else report('ai/connect', 'disconnect-failed');
    return view();
  }
  return Object.freeze({view, refresh, connect, disconnect});
}

module.exports = Object.freeze({createAiLink, parseStates, STATES, STATUS_TIMEOUT_MS, CONNECT_TIMEOUT_MS});
