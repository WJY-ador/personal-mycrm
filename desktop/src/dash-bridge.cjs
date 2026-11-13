'use strict';
// Dashboard page ↔ app IPC for "이 PC" and the AI panel (desktop-contract.cjs DASH). The page is remote content: every
// call is checked with trusted(event) (updater.trustedSender: the dashboard window's top frame on the hosted origin),
// takes no argument except a provider name from the fixed list, and answers with enums, times and short codes only.
// No Electron here: ipcMain and the handlers are injected.
const {DASH, PROVIDERS} = require('./desktop-contract.cjs');

// handlers: pcView() · sync() · aiView() · aiRefresh() · aiConnect(p) · aiDisconnect(p)
// pc:sync, ai:connect and ai:disconnect answer undefined at once; the work runs on and its result reaches the page as a
// state change (pc:changed, ai:changed). A failure inside never reaches the page.
function registerDesktopBridge({ipcMain, trusted, handlers}) {
  const none = fn => (event, ...args) => { if (args.length || !trusted(event)) throw new Error('sender'); return fn(); };
  const provider = fn => (event, ...args) => {
    if (args.length !== 1 || !PROVIDERS.includes(args[0]) || !trusted(event)) throw new Error('sender');
    return fn(args[0]);
  };
  ipcMain.handle(DASH.pcGet, none(() => handlers.pcView()));
  const later = fn => { Promise.resolve().then(fn).catch(() => {}); return undefined; };
  ipcMain.handle(DASH.pcSync, none(() => later(handlers.sync)));
  // ai:get answers the last known state and starts a fresh check in the background (the page hears ai:changed).
  ipcMain.handle(DASH.aiGet, none(() => { later(handlers.aiRefresh); return handlers.aiView(); }));
  ipcMain.handle(DASH.aiConnect, provider(p => later(() => handlers.aiConnect(p))));
  ipcMain.handle(DASH.aiDisconnect, provider(p => later(() => handlers.aiDisconnect(p))));
}

module.exports = Object.freeze({registerDesktopBridge});
