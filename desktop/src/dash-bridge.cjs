'use strict';
// Dashboard page ↔ app IPC for "이 PC" and the AI panel (desktop-contract.cjs DASH). The page is remote content: every
// call is checked with trusted(event) (updater.trustedSender: the dashboard window's top frame on the hosted origin),
// takes no argument except a provider name from the fixed list, and answers with enums, times and short codes only.
// No Electron here: ipcMain and the handlers are injected.
const {DASH, PROVIDERS} = require('./desktop-contract.cjs');

// handlers: pcView() · sync() -> {kind, code} · aiView() · aiRefresh() · aiConnect(p) · aiDisconnect(p)
function registerDesktopBridge({ipcMain, trusted, handlers}) {
  const none = fn => (event, ...args) => { if (args.length || !trusted(event)) throw new Error('sender'); return fn(); };
  const provider = fn => (event, ...args) => {
    if (args.length !== 1 || !PROVIDERS.includes(args[0]) || !trusted(event)) throw new Error('sender');
    return fn(args[0]);
  };
  ipcMain.handle(DASH.pcGet, none(() => handlers.pcView()));
  ipcMain.handle(DASH.pcSync, none(() => handlers.sync()));
  // ai:get answers the last known state and starts a fresh check in the background (the page hears ai:changed).
  ipcMain.handle(DASH.aiGet, none(() => { Promise.resolve().then(handlers.aiRefresh).catch(() => {}); return handlers.aiView(); }));
  ipcMain.handle(DASH.aiConnect, provider(p => handlers.aiConnect(p)));
  ipcMain.handle(DASH.aiDisconnect, provider(p => handlers.aiDisconnect(p)));
}

module.exports = Object.freeze({registerDesktopBridge});
