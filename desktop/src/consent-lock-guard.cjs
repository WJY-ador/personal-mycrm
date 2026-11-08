'use strict';

// Electron exposes lock/unlock notifications on macOS and Windows. Linux does not
// expose equivalent lock-screen events, so provider-capable chat stays unavailable.
const SUPPORTED_PLATFORMS=new Set(['darwin','win32']);

function createConsentLockGuard({powerMonitor,platform=process.platform,onLock}={}){
 const supported=SUPPORTED_PLATFORMS.has(platform)&&!!powerMonitor
  &&typeof powerMonitor.on==='function'&&typeof powerMonitor.removeListener==='function'
  &&typeof powerMonitor.getSystemIdleState==='function'&&typeof onLock==='function';
 let disposed=false,locked=true,lockObserved=false,revokeReady=true;
 let pending=Promise.resolve(),invalidationFlight=null;
 function state(){try{return powerMonitor.getSystemIdleState(1);}catch{return 'unknown';}}
 if(supported)locked=state()!=='active';
 function invalidate(){
  if(invalidationFlight)return invalidationFlight;
  revokeReady=false;
  let task;
  try{task=Promise.resolve(onLock()).then(value=>{revokeReady=value===true;return revokeReady;},()=>false);}
  catch{task=Promise.resolve(false);}
  invalidationFlight=task.finally(()=>{if(invalidationFlight===wrapped)invalidationFlight=null;});
  const wrapped=invalidationFlight;
  pending=wrapped;
  return wrapped;
 }
 function enterLock(){
  if(disposed||!supported||lockObserved)return;
  locked=true;lockObserved=true;invalidate();
 }
 function leaveLock(){
  if(disposed||!supported||state()!=='active')return;
  locked=false;lockObserved=false;
  if(!revokeReady)invalidate();
 }
 if(supported){
  powerMonitor.on('lock-screen',enterLock);
  powerMonitor.on('suspend',enterLock);
  powerMonitor.on('unlock-screen',leaveLock);
  powerMonitor.on('resume',leaveLock);
 }
 function canStart(){
  return status()==='ready';
 }
 function status(){
  if(disposed||!supported)return 'unsupported';
  if(!revokeReady)return 'revoke-unconfirmed';
  if(!lockObserved){locked=state()!=='active';}
  return !locked&&state()==='active'?'ready':'locked';
 }
 return Object.freeze({supported,canStart,status,whenSettled:()=>pending,
  dispose(){if(disposed)return;disposed=true;if(supported){
   powerMonitor.removeListener('lock-screen',enterLock);powerMonitor.removeListener('suspend',enterLock);
   powerMonitor.removeListener('unlock-screen',leaveLock);powerMonitor.removeListener('resume',leaveLock);
  }}});
}

module.exports=Object.freeze({SUPPORTED_PLATFORMS,createConsentLockGuard});
