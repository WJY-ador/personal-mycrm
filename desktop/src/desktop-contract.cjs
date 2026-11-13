'use strict';
// Contracts with the server and the hosted dashboard (spec 2026-11-13 §2; S's source of truth, approved by main
// 2026-11-13). This file is the only place on the app side that names them. dash-preload.cjs cannot require local
// files (sandboxed preload) and repeats DASH and PROVIDERS; a test keeps them equal.

// Dashboard page ↔ app IPC. Every call is checked with trustedSender; a change is an empty *:changed signal, after
// which the page calls *:get again.
//   pc:get   -> {signed_in: bool, device_id: string|null, state: ok|syncing|failed|login|stopped,
//                last_sync_at: ISO-UTC|null, last_result: ok|failed|null, last_code: string|null, app_version}
//   pc:sync  -> undefined at once; the result arrives as state through pc:changed
//   ai:get   -> {providers: [{provider: claude|codex, state: linked|signed_out|off|missing|checking|linking,
//                code: string|null}]}
//   ai:connect provider    -> undefined at once. Clears the local mark; starts the provider login when signed out;
//                             checks again and has the chat agent send hello again.
//   ai:disconnect provider -> undefined at once. Sets the local mark (no provider logout); hello again.
// last_code and code match CODE.
const DASH = Object.freeze({
  pcGet: 'pc:get', pcSync: 'pc:sync', pcChanged: 'pc:changed',
  aiGet: 'ai:get', aiConnect: 'ai:connect', aiDisconnect: 'ai:disconnect', aiChanged: 'ai:changed',
});
const PROVIDERS = Object.freeze(['claude', 'codex']);
const CODE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$/;

// Error report (spec §1.4). The app sends with its login session: POST /desktop/error-reports with the session
// cookie, Origin and X-MyCRM-Desktop (the same gate as /desktop/device/auto). Strict JSON, at most 2 KiB:
// {source: app|agent, stage, code, app_version, os: mac|win|other, occurred_at: '…Z', count: 1..1000}.
// Answers: 200 {accepted, state} · 400 · 401/403 · 429. A failed report is sent again once and never reported.
const ERROR_REPORT_PATH = '/desktop/error-reports';
const STAGE = /^[a-z][a-z0-9-]{0,23}(\/[a-z0-9-]{1,32}){0,2}$/;

module.exports = Object.freeze({DASH, PROVIDERS, CODE, STAGE, ERROR_REPORT_PATH});
