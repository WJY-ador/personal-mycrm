'use strict';
const {contextBridge,ipcRenderer}=require('electron');
const call=channel=>(...args)=>ipcRenderer.invoke(channel,...args);
contextBridge.exposeInMainWorld('mycrm',Object.freeze({
  status:call('status'),dashboard:call('dashboard'),logs:call('logs'),connect:call('connect'),
  chooseCli:call('choose-cli'),allowCli:call('allow-cli'),autoStart:call('auto-start'),
  start:call('start'),stop:call('stop'),sync:call('sync'),disconnect:call('disconnect'),
  update:call('update'),download:call('download'),
  onStatus:callback=>{const listener=(_e,value)=>callback(value);ipcRenderer.on('status',listener);return()=>ipcRenderer.removeListener('status',listener);}
}));
