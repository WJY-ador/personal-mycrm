'use strict';
// PC connection flow in the app's main process: installation registration, grant polling and redeem, automatic device
// connection when collection is first turned on, session rotate, revoked and account-switch handling.
// No Electron here — every side effect is injected, so the flow is tested against a fake server and a fake sidecar.
// Server contract: /desktop/* v1 (installations · grants · redeem · device/auto · device/rotate).
//
// Token rule: a token exists only between parseIssued() and install(); it is never logged, notified, stored, returned
// to the renderer or put into an Error. log() takes fixed event names and integer codes only.
const g = require('./grants.cjs');

// message: login | revoked | limit | name | failed — main maps it to fixed text (failures.cjs).
// code: the server's classified code (grants.CODES or FAILED / RATE-LIMIT) for a 'failed' — a fixed word, safe to report.
class ConnectError extends Error { constructor(message, code = null) { super(message); this.code = code; } }
const RESET = new Set(['NOT-OWNER', 'INSTALLATION-UNKNOWN']);
const NOT_LINKED_RETRY_MS = 24 * 60 * 60 * 1000;   // rotate NOT-FOUND: this installation has no device (token pasted by hand)
// Automatic connection (spec 2026-11-13 §1.2) is tried again no sooner than this after a failure. A missing display name
// is fixed by the person on the web right after login, so it is tried again soon; a full device list waits longer.
// A login or a sync tries at once.
const AUTO_RETRY_MS = 10 * 60 * 1000;
const AUTO_NAME_MS = 2 * 60 * 1000;
const AUTO_LONG_MS = 60 * 60 * 1000;
// Why this PC has no usable connection, for the dashboard's "이 PC" line: null | login | revoked | name | limit | failed.
const BLOCKS = new Set(['login', 'revoked', 'name', 'limit', 'failed']);

class Connector {
  // request(method, url, body?) -> {status, body, retryAfter}   session cookies + X-MyCRM-Desktop (main: net.request)
  // store: {load() -> record, save(record)}                      userData file
  // install(scope, token) -> {code, detail}                       sidecar stdin; caller already holds the app lock
  // forgetLocal() -> {code}                                       sidecar `disconnect --local-only`; caller holds the lock
  // exclusive(fn)                                                 runs fn under the app lock; rejects with 'busy'
  // canDeliver() -> bool                                          sidecar ready, app not busy or quitting
  // connection() -> {connected, expires, deviceLabel}
  constructor({hosted, request, store, install, forgetLocal, exclusive, canDeliver, connection, notify = () => {}, log = () => {},
    client, now = Date.now, changed = () => {}}) {
    Object.assign(this, {hosted, request, store, install, forgetLocal, exclusive, canDeliver, connection, notify, log, client, now, changed});
    // revoked: the server says this PC (or its device) was released · released: disconnected in an app before 0.1.7
    // (read and cleared, no longer set: the app has no disconnect button)
    // forget: the local device token belongs to another account and is to be removed (M3)
    this.record = g.parseRecord(store.load());
    this.registered = false;    // upserted in this run (app start, after login, after an account change)
    this.session = 'unknown';   // 'unknown' | 'ok' | 'none'
    this.poller = {lastAt: -Infinity, backoffUntil: 0, inFlight: false};
    this.nextRotateAt = 0;
    this.nextAutoAt = 0;
    this.blocked = null;
  }
  blockReason() {
    if (this.record.revoked) return 'revoked';
    if (!this.needsAuto()) return null;
    if (this.session === 'none') return 'login';
    return this.blocked;
  }
  setBlocked(value) { const v = BLOCKS.has(value) ? value : null; if (v !== this.blocked) { this.blocked = v; this.changed(); } }
  // Renderer-safe view. No ids, no tokens. A release reported by the server is always shown (the local token is dead).
  view() {
    return {session: this.session, revoked: this.record.revoked, registered: this.registered};
  }
  save(patch) { this.record = {...this.record, ...patch}; this.store.save(this.record); this.changed(); }
  setSession(value) { if (this.session !== value) { this.session = value; this.changed(); } }
  applyInstallation(inst) {
    const st = g.installationState(inst);
    if (st && st.revoked !== this.record.revoked) this.save({revoked: st.revoked});
  }
  // Shared handling of a non-200 answer. Returns the classified code.
  rejected(res, event) {
    const code = g.errorCode(res.status, res.body);
    this.log('connect', event + '-' + code.toLowerCase(), res.status);
    if (code === 'NO-SESSION') this.setSession('none');
    else if (code === 'RATE-LIMIT') this.poller.backoffUntil = this.now() + g.backoffMs(res.retryAfter);
    else if (code === 'DEVICE-REVOKED') this.save({revoked: true});
    else if (code === 'NOT-OWNER') { this.registered = false; this.save({installationId: null, forget: this.connection().connected}); }
    else if (code === 'INSTALLATION-UNKNOWN') { this.registered = false; this.save({installationId: null}); }
    return code;
  }
  async call(method, kind, id, body) {
    const res = await this.request(method, g.endpoint(this.hosted, kind, id), body);
    if (res.status !== 401) this.setSession('ok');
    return res;
  }
  // Upsert: sends the saved id when there is one; NOT-OWNER / INSTALLATION-UNKNOWN registers again without it.
  async register() {
    for (let attempt = 0; attempt < 2; attempt++) {
      const body = {...this.client};
      if (this.record.installationId) body.installation_id = this.record.installationId;
      const res = await this.call('POST', 'installations', null, body);
      if (res.status !== 200) {
        const code = this.rejected(res, 'register');
        if (RESET.has(code) && body.installation_id) continue;
        return null;
      }
      const id = g.parseInstallation(res.body);
      if (!id) { this.log('connect', 'register-invalid'); return null; }
      this.registered = true;
      if (id !== this.record.installationId) this.save({installationId: id});
      this.applyInstallation(res.body);
      this.log('connect', 'registered');
      return id;
    }
    return null;
  }
  async installation() { return this.registered && this.record.installationId ? this.record.installationId : this.register(); }
  // M3: remove the previous account's device token before anything else uses this PC's connection.
  async settleForget(locked) {
    if (!this.record.forget) return;
    if (!this.connection().connected) { this.save({forget: false}); return; }
    const run = async () => { const {code} = await this.forgetLocal(); this.log('connect', 'forget-local', code); if (code === 0) this.save({forget: false}); };
    if (locked) await run();
    else if (this.canDeliver()) await this.exclusive(run).catch(() => this.log('connect', 'forget-skipped'));
  }
  // reason: 'timer' | 'focus' | 'login'. One poll at a time, spaced by grants.shouldPoll. 'login' upserts the installation.
  async poll(reason = 'timer') {
    if (reason === 'login') this.registered = false;
    const now = this.now();
    if (!g.shouldPoll(this.poller, now)) return 'skipped';
    this.poller.inFlight = true; this.poller.lastAt = now;
    try {
      let res;
      for (let attempt = 0; attempt < 2; attempt++) {
        const id = await this.installation();
        if (!id) return 'no-installation';
        await this.settleForget(false);
        res = await this.call('GET', 'grants', id);
        if (res.status === 200) break;
        const code = this.rejected(res, 'poll');
        if (!RESET.has(code) || attempt === 1) return code;
      }
      this.applyInstallation(res.body?.installation);
      for (const grant of g.parseGrants(res.body)) {
        if (!this.canDeliver()) break;   // the grant stays waiting on the server; a later poll takes it
        await this.redeem(grant);
      }
      await this.maybeRotate();
      return 'ok';
    } catch { this.log('connect', 'poll-error'); return 'error'; }
    finally { this.poller.inFlight = false; }
  }
  async redeem(grant) {
    try {
      await this.exclusive(async () => {
        const id = this.record.installationId;
        if (!id) return;
        const res = await this.call('POST', 'redeem', grant.id, {installation_id: id});
        if (res.status !== 200) { this.rejected(res, 'redeem'); return; }
        const issued = g.parseIssued(res.body, grant.scope);
        if (!issued) { this.log('connect', 'redeem-invalid'); this.notify(g.failedNotice(grant.scope)); return; }
        await this.deliver(issued, 'redeem');
      });
    } catch { this.log('connect', 'redeem-skipped'); }
  }
  // Hands the token to the sidecar and drops it, then reports with account and device names only.
  // A failed sidecar leaves the issued token unused; it expires on its own and the previous one stays valid (M2).
  async deliver(issued, event) {
    const {scope, accountLabel, deviceLabel} = issued;
    const {code} = await this.install(scope, issued.token);
    issued.token = null;
    this.log('connect', event + '-installed', code);
    if (code !== 0) { this.notify(g.failedNotice(scope)); return code; }
    if (scope === 'device') this.save({revoked: false, released: false, forget: false});
    this.notify(g.deliveredNotice(scope, accountLabel, deviceLabel || this.connection().deviceLabel));
    return 0;
  }
  // Session rotate, 30 days before expiry. Without a session it waits for the user's [로그인] (M4: no browser here).
  async maybeRotate() {
    const c = this.connection(), now = this.now(), r = this.record;
    if (!c.connected || r.revoked || r.released || r.forget || !r.installationId || !g.needsRotate(c.expires, now)
      || now < this.nextRotateAt || !this.canDeliver()) return 'idle';
    this.nextRotateAt = now + g.ROTATE_RETRY_MS;
    let result = 'failed';
    try {
      await this.exclusive(async () => {
        const res = await this.call('POST', 'rotate', null, {installation_id: r.installationId});
        if (res.status !== 200) {
          result = this.rejected(res, 'rotate');
          if (result === 'NOT-FOUND') this.nextRotateAt = now + NOT_LINKED_RETRY_MS;
          if (result === 'NOT-OWNER') await this.settleForget(true);
          return;
        }
        const issued = g.parseIssued(res.body, 'device');
        if (!issued) { this.log('connect', 'rotate-invalid'); return; }
        const {code} = await this.install('device', issued.token);
        issued.token = null;
        this.log('connect', 'rotate-installed', code);
        result = code === 0 ? 'rotated' : 'failed';
      });
    } catch { this.log('connect', 'rotate-skipped'); this.nextRotateAt = 0; return 'skipped'; }
    return result;
  }
  // Collection is being turned on ([지금 동기화]) and this PC has no usable device token: ask for one with the app session.
  // The server answers with the installation's own device (lost token) or a new one. Called while the app lock is held.
  // A release the server reports (revoked: the person disconnected this PC, e.g. in a conversation) stays: only a
  // connection the person asks for (a grant) brings it back. A release made in an older app (released) no longer blocks.
  async autoConnect() {
    if (this.record.revoked) throw new ConnectError('revoked');
    let res;
    for (let attempt = 0; attempt < 2; attempt++) {
      const id = await this.installation();
      if (!id) throw new ConnectError(this.session === 'none' ? 'login' : 'failed');
      await this.settleForget(true);
      if (this.record.revoked) throw new ConnectError('revoked');
      res = await this.call('POST', 'auto', null, {installation_id: id, ...this.client});
      if (res.status === 200) break;
      const code = this.rejected(res, 'auto');
      if (RESET.has(code) && attempt === 0) continue;
      throw new ConnectError({'NO-SESSION': 'login', 'DEVICE-REVOKED': 'revoked', 'DEVICE-LIMIT': 'limit', 'NAME-REQUIRED': 'name'}[code] || 'failed', code);
    }
    const issued = g.parseIssued(res.body, 'device');
    if (!issued) { this.log('connect', 'auto-invalid'); throw new ConnectError('failed'); }
    if (await this.deliver(issued, 'auto') !== 0) throw new ConnectError('failed');
  }
  // Before collection runs: connect automatically when there is no device, or when the local one belongs to another account.
  needsAuto() { return !this.connection().connected || this.record.forget; }
  // Automatic connection outside a sync (spec §1.2): at app start, after a login and on the poll timer. Takes the app lock.
  // reason: 'startup' | 'login' | 'timer'. Returns 'connected' (nothing to do), 'issued' (a token was installed),
  // 'revoked', 'login' (no session: the dashboard shows its login screen), 'waiting' (spaced after a failure) or 'busy'.
  // Throws the ConnectError of a failed attempt.
  async ensureDevice(reason = 'timer') {
    if (!this.needsAuto()) { this.setBlocked(null); return 'connected'; }
    if (this.record.revoked) return 'revoked';
    if (this.session === 'none' && reason !== 'login') return 'login';
    const now = this.now();
    if (reason !== 'login' && now < this.nextAutoAt) return 'waiting';
    try {
      await this.exclusive(() => this.autoConnect());
    } catch (e) {
      const m = e?.message;
      if (m === 'busy' || m === 'closing') return 'busy';
      this.nextAutoAt = now + (m === 'name' ? AUTO_NAME_MS : m === 'limit' ? AUTO_LONG_MS : AUTO_RETRY_MS);
      this.setBlocked(m);
      if (m === 'login') return 'login';
      throw e;
    }
    this.nextAutoAt = 0;
    this.setBlocked(null);
    this.log('connect', 'auto-' + reason);
    return 'issued';
  }
}
module.exports = {Connector, ConnectError, AUTO_RETRY_MS, AUTO_NAME_MS, AUTO_LONG_MS};
