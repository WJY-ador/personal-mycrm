'use strict';
// Contracts with the server and the hosted dashboard (spec 2026-11-13 §2). The server side (S) is the source of truth;
// this file is the only place on the app side that names them. When S's contract arrives only these values change.
// dash-preload.cjs cannot require local files (sandboxed preload) and repeats DASH; a test keeps the two equal.

// Dashboard page ↔ app IPC. The page reads with *:get and is told to read again by an empty *:changed signal.
//   pc:get                -> PcView     (pc-state.cjs view(): connected, syncing, lastSync {at, kind, code})
//   pc:sync               -> SyncResult {kind: ok|busy|disconnected|login|rejected|unknown, code: string|null}
//   ai:get                -> AiView     (ai-link.cjs view(): {providers: {claude, codex}, connecting, checkedAt})
//   ai:connect  provider  -> AiView     provider ∈ PROVIDERS. Starts the provider's own login when it is signed out.
//   ai:disconnect provider -> AiView    local mark only; the provider login stays.
const DASH = Object.freeze({
  pcGet: 'pc:get', pcSync: 'pc:sync', pcChanged: 'pc:changed',
  aiGet: 'ai:get', aiConnect: 'ai:connect', aiDisconnect: 'ai:disconnect', aiChanged: 'ai:changed',
});
const PROVIDERS = Object.freeze(['claude', 'codex']);

// Error report (spec §1.4): POST with the dashboard session cookie. Body: see error-report.cjs.
const ERROR_REPORT_PATH = '/api/errors/report';

module.exports = Object.freeze({DASH, PROVIDERS, ERROR_REPORT_PATH});
