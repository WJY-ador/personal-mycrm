'use strict';
// Automatic sync (spec 2026-11-13 §5): the app runs the sync (run-once) by itself — once 2 minutes after it opens,
// then every 60 minutes on that cadence. A tick is skipped, not retried early, when the user stopped the device, this PC
// is not connected, or another command holds the app; the next period tries again. A failed run is tried again on the
// next period too. The run itself is the same sync as the button (main.cjs syncOnce) and logs 'sync','completed',code.
// No Electron here: the timers and every gate are injected, so the schedule is tested with fake timers.
const FIRST_MS = 2 * 60 * 1000;
const EVERY_MS = 60 * 60 * 1000;

class AutoSync {
  // wanted() -> bool       the user did not stop the device (the saved preference is not autoRun:false)
  // connected() -> bool    this PC holds a device connection that needs no automatic connect
  // idle() -> bool         the app is not busy, quitting or installing an update
  // run() -> Promise       the sync under the app lock; rejects with 'busy' when the lock was taken meanwhile
  // log(component, event)  fixed event names only
  constructor({wanted, connected, idle, run, log = () => {}, timers = {setTimeout, clearTimeout}}) {
    Object.assign(this, {wanted, connected, idle, run, log, timers});
    this.timer = null; this.inFlight = false; this.disposed = false;
  }
  start() {
    if (this.timer || this.disposed) return;
    this.schedule(FIRST_MS);
  }
  // The next tick is set before this one runs, so the cadence stays 2, 62, 122 ... minutes whatever a run takes.
  schedule(ms) {
    this.timer = this.timers.setTimeout(() => {
      this.timer = null;
      if (this.disposed) return;
      this.schedule(EVERY_MS);
      this.tick().catch(() => {});
    }, ms);
  }
  // Returns what happened: 'ran' | 'failed' | 'stopped' | 'not-connected' | 'busy' | 'disposed'. Never throws.
  async tick() {
    if (this.disposed) return 'disposed';
    let skip = null;
    try {
      skip = this.inFlight || !this.idle() ? 'busy' : !this.wanted() ? 'stopped' : !this.connected() ? 'not-connected' : null;
    } catch { skip = 'busy'; }
    if (skip) { this.log('sync', 'auto-skipped-' + skip); return skip; }
    this.inFlight = true;
    this.log('sync', 'auto');
    try { await this.run(); return 'ran'; }
    catch (e) {
      if (e?.message === 'busy') { this.log('sync', 'auto-skipped-busy'); return 'busy'; }
      this.log('sync', 'auto-failed'); return 'failed';
    } finally { this.inFlight = false; }
  }
  dispose() {
    this.disposed = true;
    if (this.timer) this.timers.clearTimeout(this.timer);
    this.timer = null;
  }
}

module.exports = {AutoSync, FIRST_MS, EVERY_MS};
