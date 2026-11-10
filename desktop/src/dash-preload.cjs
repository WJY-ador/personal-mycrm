'use strict';
// Dashboard window preload (sandboxed, context-isolated). Opens window.mycrmDesktop.update with four calls and no
// arguments (onChange takes only the callback). Main checks every call's sender (updater.cjs registerDashboardBridge).
// A change arrives as an empty signal and the state is read again through get(), so a page main refuses never sees it.
// Sandboxed preloads cannot require local files: the channel names repeat updater.cjs CHANNELS.
const {contextBridge,ipcRenderer}=require('electron');
const get=()=>ipcRenderer.invoke('update:get');
contextBridge.exposeInMainWorld('mycrmDesktop',Object.freeze({update:Object.freeze({
  get:()=>get(),
  onChange:callback=>{
    if(typeof callback!=='function')return()=>{};
    const listener=()=>{get().then(value=>{try{callback(value);}catch{}},()=>{});};
    ipcRenderer.on('update:changed',listener);
    return()=>{ipcRenderer.removeListener('update:changed',listener);};
  },
  download:()=>ipcRenderer.invoke('update:download').then(()=>undefined),
  install:()=>ipcRenderer.invoke('update:install').then(()=>undefined),
})}));
