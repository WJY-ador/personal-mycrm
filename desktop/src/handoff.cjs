'use strict';
// Login handoff (system browser -> mycrm:// deep link -> in-app claim). Pure helpers, no Electron,
// so they can be tested directly. The verifier stays in app memory; only its challenge leaves the app.
const crypto = require('node:crypto');
const TTL_MS = 10 * 60 * 1000;
const B64URL = /^[A-Za-z0-9_-]+$/;
const MAX_LINK = 1024;
const b64url = buf => Buffer.from(buf).toString('base64url'); // RFC 4648 §5, no padding
function challengeOf(verifier) { return b64url(crypto.createHash('sha256').update(verifier, 'ascii').digest()); }
// One login at a time: a new begin() replaces the previous pending value.
function begin(now = Date.now(), random = crypto.randomBytes) {
  const verifier = b64url(random(32)), state = b64url(random(16));
  return {verifier, state, challenge: challengeOf(verifier), expiresAt: now + TTL_MS};
}
// fresh: the intercepted login asked for a new sign-in (start page after logout links /login?fresh=1).
// The server then skips its "already signed in in this browser" shortcut and shows the login form.
function loginUrl(hosted, challenge, state, fresh = false) {
  const u = new URL('desktop/login', hosted);
  const q = {challenge, state};
  if (fresh) q.fresh = '1';
  u.search = new URLSearchParams(q).toString();
  return u.href;
}
function wantsFresh(input) {
  try { return new URL(input).searchParams.get('fresh') === '1'; } catch { return false; }
}
// mycrm://auth/callback?code=<base64url>&state=<base64url> — exactly these two parameters, once each.
function parseCallback(raw) {
  if (typeof raw !== 'string' || raw.length > MAX_LINK) return null;
  let u;
  try { u = new URL(raw); } catch { return null; }
  if (u.protocol !== 'mycrm:' || u.hostname !== 'auth' || !/^\/callback\/?$/.test(u.pathname)) return null;
  if (u.username || u.password || u.port || u.hash) return null;
  const keys = [...u.searchParams.keys()];
  if (keys.length !== 2 || !keys.includes('code') || !keys.includes('state')) return null;
  const code = u.searchParams.get('code'), state = u.searchParams.get('state');
  if (!B64URL.test(code) || code.length < 16 || code.length > 128) return null;
  if (!B64URL.test(state) || state.length < 16 || state.length > 64) return null;
  return {code, state};
}
function sameState(a, b) {
  const x = Buffer.from(String(a)), y = Buffer.from(String(b));
  return x.length === y.length && crypto.timingSafeEqual(x, y);
}
// 'ok' | 'format' | 'none' | 'expired' | 'state'. A mismatched state leaves the pending login intact,
// so a stray or injected link cannot cancel the user's real login.
function accept(pending, parsed, now = Date.now()) {
  if (!parsed) return 'format';
  if (!pending) return 'none';
  if (now > pending.expiresAt) return 'expired';
  if (!sameState(pending.state, parsed.state)) return 'state';
  return 'ok';
}
function claimBody(code, verifier, state) { return new URLSearchParams({code, verifier, state}).toString(); }
// The claim is a browser-initiated POST whose Origin is "null"; a cross-site form in a sandboxed frame can send
// the same Origin but cannot add a custom header, so the server requires X-MyCRM-Desktop: 1.
function claimRequest(hosted, code, verifier, state) {
  return {
    url: new URL('desktop/claim', hosted).href,
    options: {
      postData: [{type: 'rawData', bytes: Buffer.from(claimBody(code, verifier, state))}],
      extraHeaders: 'Content-Type: application/x-www-form-urlencoded\nX-MyCRM-Desktop: 1',
    },
  };
}
function findLink(argv) { return (Array.isArray(argv) ? argv : []).find(a => typeof a === 'string' && /^mycrm:/i.test(a)) || null; }
// In-app navigations that start a login are taken over by the app: /login (any query) and /desktop/login.
function isLoginNav(input, hosted) {
  try {
    const u = new URL(input);
    return u.origin === new URL(hosted).origin && (u.pathname === '/login' || u.pathname === '/desktop/login');
  } catch { return false; }
}
module.exports = {TTL_MS, challengeOf, begin, loginUrl, wantsFresh, parseCallback, accept, claimBody, claimRequest, findLink, isLoginNav};
