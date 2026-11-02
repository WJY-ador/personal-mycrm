'use strict';
// PC connection flow in the app's main process: installation registration, grant polling and redeem, automatic device
// connection when collection is first turned on, session rotate, revoked and account-switch handling.
// No Electron here — every side effect is injected, so the flow is tested against a fake server and a fake sidecar.
//
// Token rule: a token exists only between parseIssued() and install(); it is never logged, notified, stored, returned
// to the renderer or put into an Error. log() takes fixed event names and integer codes only.
const g = require('./grants.cjs');

class ConnectError extends Error {}   // message is one of: login, revoked, failed — mapped to fixed text by main

class Connector {
  // request(method, url, body?) -> {status, body}   session cookies + X-MyCRM-Desktop (main: net.request)
  // store: {load() -> record, save(record)}         userData file
  // install(scope, token) -> {code, detail}          sidecar stdin; caller already holds the app lock
  // forgetLocal() -> {code}                          sidecar `disconnect --local-only` (removes the local device token)
  // exclusive(fn)                                    runs fn under the app lock; rejects with 'busy'
  // canDeliver() -> bool                             sidecar ready, app not busy or quitting
  // connection() -> {connected, expires, streamId, deviceLabel}
  constructor({hosted, request, store, install, forgetLocal, exclusive, canDeliver, connection, notify = () => {}, log = () => {},
    client, now = Date.now, changed = () => {}}) {
    Object.assign(this, {hosted, request, store, install, forgetLocal, exclusive, canDeliver, connection, notify, log, client, now, changed});
    this.record = g.parseRecord(store.load());
    this.session = 'unknown';   // 'unknown' | 'ok' | 'none'
    this.poller = {lastAt: -Infinity, backoffUntil: 0, inFlight: false};
    this.nextRotateAt = 0;
  }
  // Renderer-safe view. No ids, no tokens.
  view() { return {session: this.session, revoked: this.record.revoked, registered: !!this.record.installationId}; }
  save(patch) { this.record = {...this.record, ...patch}; this.store.save(this.record); this.changed(); }
  setSession(value) { if (this.session !== value) { this.session = value; this.changed(); } }
  // Shared handling of a non-200 answer. Returns the classified code.
  rejected(res, event) {
    const code = g.errorCode(res.status, res.body);
    this.log('connect', event + '-' + code.toLowerCase(), res.status);
    if (code === 'NO-SESSION') this.setSession('none');
    else if (code === 'RATE-LIMIT') this.poller.backoffUntil = this.now() + g.RATE_BACKOFF_MS;
    else if (code === 'DEVICE-REVOKED') this.save({revoked: true});
    return code;
  }
  async call(method, kind, id, body) {
    const res = await this.request(method, g.endpoint(this.hosted, kind, id), body);
    if (res.status !== 401) this.setSession('ok');
    return res;
  }
  // Registers this installation for the signed-in account. Returns the id, or null without a session.
  async ensureInstallation() {
    if (this.record.installationId) return this.record.installationId;
    const res = await this.call('POST', 'installations', null, this.client);
    if (res.status !== 200 && res.status !== 201) { this.rejected(res, 'register'); return null; }
    const id = g.parseInstallation(res.body);
    if (!id) { this.log('connect', 'register-invalid'); return null; }
    this.log('connect', 'registered');
    this.save({installationId: id});
    return id;
  }
  // reason: 'timer' | 'focus' | 'login'. One poll at a time, spaced by grants.shouldPoll.
  async poll(reason = 'timer') {
    const now = this.now();
    if (!g.shouldPoll(this.poller, now)) return 'skipped';
    this.poller.inFlight = true; this.poller.lastAt = now;
    try {
      let id = await this.ensureInstallation();
      if (!id) return 'no-installation';
      let res = await this.call('GET', 'grants', id);
      if (res.status !== 200) {
        const code = this.rejected(res, 'poll');
        if (code !== 'NOT-OWNER' && code !== 'INSTALLATION-UNKNOWN') return code;
        // Signed in to another account on this PC (M3), or the server forgot the installation: register again.
        // A device connected under the previous account is checked when collection next runs (recheck).
        this.save({installationId: null, recheck: this.connection().connected});
        id = await this.ensureInstallation();
        if (!id) return 'no-installation';
        res = await this.call('GET', 'grants', id);
        if (res.status !== 200) return this.rejected(res, 'poll');
      }
      for (const grant of g.parseGrants(res.body)) {
        if (!this.canDeliver()) break;   // the grant stays waiting on the server; a later poll takes it
        await this.redeem(grant, id);
      }
      await this.maybeRotate();
      return 'ok';
    } catch { this.log('connect', 'poll-error'); return 'error'; }
    finally { this.poller.inFlight = false; }
  }
  async redeem(grant, installationId) {
    try {
      await this.exclusive(async () => {
        const res = await this.call('POST', 'redeem', grant.id, {installation_id: installationId});
        if (res.status !== 200) { this.rejected(res, 'redeem'); return; }
        const issued = g.parseIssued(res.body, grant.scope);
        if (!issued) { this.log('connect', 'redeem-invalid'); this.notify(g.failedNotice(grant.scope)); return; }
        await this.deliver(issued, 'redeem');
      });
    } catch { this.log('connect', 'redeem-skipped'); }
  }
  // Hands the token to the sidecar, then reports with account and device names only.
  async deliver(issued, event) {
    const {scope, accountLabel} = issued;
    const {code} = await this.install(scope, issued.token);
    issued.token = null;
    this.log('connect', event + '-installed', code);
    if (code !== 0) { this.notify(g.failedNotice(scope)); return code; }
    if (scope === 'device') this.save({revoked: false, recheck: false});
    this.notify(g.deliveredNotice(scope, accountLabel, this.connection().deviceLabel));
    return 0;
  }
  // Session rotate, 30 days before expiry. Without a session it waits for the user's [로그인] (M4: no browser here).
  async maybeRotate() {
    const c = this.connection(), now = this.now();
    if (!c.connected || this.record.revoked || this.record.recheck || !g.needsRotate(c.expires, now) || now < this.nextRotateAt || !this.canDeliver()) return 'idle';
    this.nextRotateAt = now + g.ROTATE_RETRY_MS;
    let result = 'failed';
    try {
      await this.exclusive(async () => {
        const res = await this.call('POST', 'rotate', null, {stream_id: c.streamId, installation_id: this.record.installationId});
        if (res.status !== 200) {
          const code = this.rejected(res, 'rotate');
          if (code === 'NOT-OWNER') { await this.forgetLocal(); this.log('connect', 'forgot-other-account'); this.changed(); }
          result = code; return;
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
  // Collection is being turned on ([지금 동기화]) and this PC has no usable device: ask for one with the app session.
  // Called while the app lock is held. Throws ConnectError('login' | 'revoked' | 'failed').
  async autoConnect() {
    if (this.record.revoked) throw new ConnectError('revoked');
    const id = await this.ensureInstallation();
    if (!id) throw new ConnectError(this.session === 'none' ? 'login' : 'failed');
    const c = this.connection();
    const body = {...this.client, installation_id: id};
    if (c.connected && c.streamId) body.stream_id = c.streamId;
    let res = await this.call('POST', 'auto', null, body);
    if (res.status !== 200 && body.stream_id && g.errorCode(res.status, res.body) === 'NOT-OWNER') {
      // The local device belongs to another account (M3): remove its token, then connect a device for this account.
      this.log('connect', 'auto-not-owner', res.status);
      await this.forgetLocal();
      delete body.stream_id;
      res = await this.call('POST', 'auto', null, body);
    }
    if (res.status !== 200) {
      const code = this.rejected(res, 'auto');
      throw new ConnectError(code === 'NO-SESSION' ? 'login' : code === 'DEVICE-REVOKED' ? 'revoked' : 'failed');
    }
    const issued = g.parseIssued(res.body, 'device');
    if (!issued) { this.log('connect', 'auto-invalid'); throw new ConnectError('failed'); }
    if (await this.deliver(issued, 'auto') !== 0) throw new ConnectError('failed');
  }
  // Before collection runs: connect automatically when there is no device, or re-check one connected under another account.
  needsAuto() { const c = this.connection(); return !c.connected || this.record.recheck; }
}
module.exports = {Connector, ConnectError};
