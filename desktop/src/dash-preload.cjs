'use strict';
// Dashboard window preload (sandboxed, context-isolated). Opens window.mycrmDesktop with three parts:
//   update: get, onChange, download, install            (updater.cjs registerDashboardBridge)
//   pc:     get, sync, onChange                          "이 PC" line (dash-bridge.cjs, spec 2026-11-13 §1.1)
//   ai:     get, connect(provider), disconnect(provider), onChange   AI panel (spec §1.3)
// Main checks every call's sender. A change arrives as an empty signal and the state is read again through get(), so a
// page main refuses never sees it. Sandboxed preloads cannot require local files: the channel names repeat
// updater.cjs CHANNELS and desktop-contract.cjs DASH (a test keeps them equal).
const {contextBridge,ipcRenderer}=require('electron');
const UPDATE=Object.freeze({get:'update:get',download:'update:download',install:'update:install',changed:'update:changed'});
const DASH=Object.freeze({pcGet:'pc:get',pcSync:'pc:sync',pcChanged:'pc:changed',
  aiGet:'ai:get',aiConnect:'ai:connect',aiDisconnect:'ai:disconnect',aiChanged:'ai:changed'});
const PROVIDERS=Object.freeze(['claude','codex']);
function watch(channel,get){
  return callback=>{
    if(typeof callback!=='function')return()=>{};
    const listener=()=>{get().then(value=>{try{callback(value);}catch{}},()=>{});};
    ipcRenderer.on(channel,listener);
    return()=>{ipcRenderer.removeListener(channel,listener);};
  };
}
const provider=value=>{if(!PROVIDERS.includes(value))return Promise.reject(new Error('provider'));return null;};
const updateGet=()=>ipcRenderer.invoke(UPDATE.get);
const pcGet=()=>ipcRenderer.invoke(DASH.pcGet);
const aiGet=()=>ipcRenderer.invoke(DASH.aiGet);
contextBridge.exposeInMainWorld('mycrmDesktop',Object.freeze({
  update:Object.freeze({
    get:()=>updateGet(),
    onChange:watch(UPDATE.changed,updateGet),
    download:()=>ipcRenderer.invoke(UPDATE.download).then(()=>undefined),
    install:()=>ipcRenderer.invoke(UPDATE.install).then(()=>undefined),
  }),
  pc:Object.freeze({
    get:()=>pcGet(),
    sync:()=>ipcRenderer.invoke(DASH.pcSync),
    onChange:watch(DASH.pcChanged,pcGet),
  }),
  ai:Object.freeze({
    get:()=>aiGet(),
    connect:value=>provider(value)||ipcRenderer.invoke(DASH.aiConnect,value),
    disconnect:value=>provider(value)||ipcRenderer.invoke(DASH.aiDisconnect,value),
    onChange:watch(DASH.aiChanged,aiGet),
  }),
}));
