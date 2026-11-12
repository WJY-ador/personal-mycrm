'use strict';

// Screen lock for the consent window only (J JD2). A lock or sleep cancels the approval in flight (onLock) and the
// runtime will not open a new consent window while the screen is locked (consent-approval sessionActive). The lock no
// longer stops the chat sidecar, holds its start or revokes anything on the server: a standing allow survives a lock.
// Electron exposes lock notifications on macOS and Windows. Elsewhere no consent window opens (fail closed).
const SUPPORTED_PLATFORMS=new Set(['darwin','win32']);

function createConsentLockGuard({powerMonitor,platform=process.platform,onLock}={}){
 const supported=SUPPORTED_PLATFORMS.has(platform)&&!!powerMonitor
  &&typeof powerMonitor.on==='function'&&typeof powerMonitor.removeListener==='function'
  &&typeof onLock==='function';
 let disposed=false;
 function enterLock(){
  if(disposed)return;
  try{onLock();}catch{}
 }
 if(supported){
  powerMonitor.on('lock-screen',enterLock);
  powerMonitor.on('suspend',enterLock);
 }
 return Object.freeze({supported,
  dispose(){if(disposed)return;disposed=true;if(supported){
   powerMonitor.removeListener('lock-screen',enterLock);powerMonitor.removeListener('suspend',enterLock);
  }}});
}

module.exports=Object.freeze({SUPPORTED_PLATFORMS,createConsentLockGuard});
