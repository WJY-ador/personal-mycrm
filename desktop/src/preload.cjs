'use strict';
const {contextBridge,ipcRenderer}=require('electron');
const call=channel=>(...args)=>ipcRenderer.invoke(channel,...args);
contextBridge.exposeInMainWorld('mycrm',Object.freeze({
  status:call('status'),dashboard:call('dashboard'),login:call('login'),logs:call('logs'),connect:call('connect'),
  chooseCli:call('choose-cli'),configureCodex:call('configure-codex'),allowCli:call('allow-cli'),autoStart:call('auto-start'),
  start:call('start'),stop:call('stop'),sync:call('sync'),disconnect:call('disconnect'),
  updateState:call('update-state'),checkUpdate:call('update'),downloadUpdate:call('update-download'),installUpdate:call('update-install'),openReleases:call('releases'),
  onUpdate:callback=>{const listener=(_e,value)=>callback(value);ipcRenderer.on('update-changed',listener);return()=>ipcRenderer.removeListener('update-changed',listener);},
  onStatus:callback=>{const listener=(_e,value)=>callback(value);ipcRenderer.on('status',listener);return()=>ipcRenderer.removeListener('status',listener);}
}));
