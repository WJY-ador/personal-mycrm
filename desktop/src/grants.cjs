'use strict';
// PC connection (app receives tokens issued in a conversation). Pure helpers, no Electron, so they can be tested directly.
// A token lives only inside the object parseIssued() returns; callers hand it to the sidecar's stdin and drop the object.
// Nothing here logs, and nothing here builds text that contains a token.
const POLL_MS = 30 * 1000;            // background poll while the app runs
const MIN_GAP_MS = 10 * 1000;         // focus polls closer than this are skipped (server: 10 requests per IP per minute)
const RATE_BACKOFF_MS = 60 * 1000;    // after RATE-LIMIT, wait a full minute
const ROTATE_BEFORE_MS = 30 * 24 * 60 * 60 * 1000;   // rotate the device token 30 days before it expires
const ROTATE_RETRY_MS = 60 * 60 * 1000;              // a failed rotate is retried at most hourly
const ID_RE = /^[A-Za-z0-9_-]{1,128}$/;
const SCOPES = new Set(['device', 'migration']);
const CODES = new Set(['NO-ACTIVE-APP', 'INSTALLATION-UNKNOWN', 'GRANT-EXPIRED', 'GRANT-USED', 'NOT-OWNER', 'DEVICE-REVOKED',
  'MIGRATION-NOT-ALLOWED', 'NAME-REQUIRED', 'RATE-LIMIT']);
const HEADERS = Object.freeze({'X-MyCRM-Desktop': '1', 'Accept': 'application/json', 'Content-Type': 'application/json'});

function endpoint(hosted, kind, id) {
  switch (kind) {
    case 'installations': return new URL('desktop/installations', hosted).href;
    case 'grants': { const u = new URL('desktop/grants', hosted); u.search = new URLSearchParams({installation: id}).toString(); return u.href; }
    case 'redeem': return new URL(`desktop/grants/${encodeURIComponent(id)}/redeem`, hosted).href;
    case 'auto': return new URL('desktop/device/auto', hosted).href;
    case 'rotate': return new URL('desktop/device/rotate', hosted).href;
    default: throw new Error('endpoint');
  }
}
// Error classification: 'NO-SESSION' (401, sign in again), a known server code, or 'FAILED'.
// The server body is read only for its code; nothing else from it is kept.
function errorCode(status, body) {
  const raw = body && typeof body === 'object' ? (typeof body.error === 'string' ? body.error : body.error?.code ?? body.code) : null;
  if (typeof raw === 'string' && CODES.has(raw)) return raw;
  if (status === 401) return 'NO-SESSION';
  if (status === 429) return 'RATE-LIMIT';
  return 'FAILED';
}
const validId = v => typeof v === 'string' && ID_RE.test(v);
function parseInstallation(body) {
  const id = body && typeof body === 'object' ? body.installation_id : null;
  return validId(id) ? id : null;
}
// Waiting grants for this installation, oldest first as the server sends them. Malformed entries are dropped.
function parseGrants(body) {
  const list = Array.isArray(body) ? body : Array.isArray(body?.grants) ? body.grants : [];
  return list.filter(g => g && validId(g.grant_id) && SCOPES.has(g.scope)).map(g => ({id: g.grant_id, scope: g.scope})).slice(0, 10);
}
function validToken(t) { return typeof t === 'string' && t.length >= 16 && t.length <= 1024 && !/[\s\x00]/.test(t); }
function clip(value, max) {
  if (typeof value !== 'string') return '';
  return Array.from(value.replace(/[\x00-\x1f\x7f]/g, ' ').trim()).slice(0, max).join('');
}
// redeem / auto / rotate response. expectScope: the grant's scope (redeem) or 'device' (auto, rotate).
function parseIssued(body, expectScope) {
  if (!body || typeof body !== 'object') return null;
  const scope = body.scope ?? expectScope;
  if (!SCOPES.has(scope) || (expectScope && scope !== expectScope) || !validToken(body.token)) return null;
  return {scope, token: body.token, accountLabel: clip(body.account_label, 80)};
}
function sidecarArgs(scope, hosted) {
  if (scope === 'device') return ['connect', '--server', hosted, '--token-stdin'];
  if (scope === 'migration') return ['migrate', 'login', '--server', hosted, '--token-stdin'];
  throw new Error('scope');
}
// reason 'timer' | 'focus' | 'login'. Focus and login polls are skipped when the last one was less than MIN_GAP_MS ago,
// and nothing runs before a RATE-LIMIT backoff ends.
function shouldPoll({lastAt = 0, backoffUntil = 0, inFlight = false} = {}, now) {
  if (inFlight || now < backoffUntil) return false;
  return now - lastAt >= MIN_GAP_MS;
}
function needsRotate(expiresAt, now) {
  if (typeof expiresAt !== 'string' || !expiresAt) return false;
  const t = Date.parse(expiresAt);
  return Number.isFinite(t) && t - now <= ROTATE_BEFORE_MS;
}
function clientInfo(hostname, platform) {
  const os = {darwin: 'macos', win32: 'windows', linux: 'linux'}[platform] || 'other';
  return {client_name: clip(hostname, 80) || 'MyCRM PC', os};
}
// Notification text: account and device names only, never a token or grant id.
function deliveredNotice(scope, accountLabel, deviceLabel) {
  const parts = [clip(accountLabel, 80), clip(deviceLabel, 80)].filter(Boolean);
  return scope === 'migration'
    ? {title: '이관 토큰을 받았어요', body: parts[0] || '이 PC에 저장했어요'}
    : {title: '연결됐어요', body: parts.join(' · ') || '이 PC를 연결했어요'};
}
function failedNotice(scope) {
  return scope === 'migration'
    ? {title: '이관 토큰을 저장하지 못했어요', body: '연결 장치 창에서 상태를 확인한 뒤 대화에서 다시 요청해 주세요.'}
    : {title: '이 PC를 연결하지 못했어요', body: '연결 장치 창에서 상태를 확인한 뒤 대화에서 다시 요청해 주세요.'};
}
// Saved installation record (userData). Anything malformed reads as "not registered".
function parseRecord(raw) {
  try {
    const j = typeof raw === 'string' ? JSON.parse(raw) : raw;
    return {installationId: validId(j?.installationId) ? j.installationId : null, revoked: j?.revoked === true, recheck: j?.recheck === true};
  } catch { return {installationId: null, revoked: false, recheck: false}; }
}
module.exports = {POLL_MS, MIN_GAP_MS, RATE_BACKOFF_MS, ROTATE_BEFORE_MS, ROTATE_RETRY_MS, HEADERS, endpoint, errorCode, parseInstallation,
  parseGrants, parseIssued, validToken, sidecarArgs, shouldPoll, needsRotate, clientInfo, deliveredNotice, failedNotice, parseRecord, clip};
