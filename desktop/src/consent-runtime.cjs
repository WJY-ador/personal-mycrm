'use strict';

const {createConsentApproval}=require('./consent-approval.cjs');
const {loadOrCreateKeyPair}=require('./consent-key-store.cjs');
const {encodeConsent,signConsent}=require('./consent-signature.cjs');

const INSTALLATION=/^di_[0-9a-f]{24}$/;
const REQUEST_ID=/^[A-Za-z0-9_-]{1,64}$/;
const BEARER=/^Bearer [A-Za-z0-9._~+/-]{16,500}$/;
const SIGNATURE=/^[A-Za-z0-9_-]{86}$/;
// The only refusal reasons the bridge reports to the agent (and the agent to the server).
// declined = the person said no; locked = screen lock/idle; failed = every other failure.
const REASONS=Object.freeze(['declined','locked','failed']);
const OK=Object.freeze({ok:true});
const FAIL=Object.freeze({ok:false,reason:'failed'});
// chat-consent-revoke exit code: this PC has no device token (agent/cli.py EXIT_HALT). 0 = sent and answered ok.
const REVOKE_NONE_EXIT=3;
const refusal=code=>Object.freeze({ok:false,reason:code==='DECLINED'?'declined':code==='IDLE'?'locked':'failed'});

function createConsentRuntime(options={}){
 const {request,getInstallationId,safeStorage,keyFile,app,dialog,powerMonitor,trustedWindow,allowedUrl,focusWindow}=options;
 const platform=options.platform||process.platform;
 const lockSupported=(platform==='darwin'||platform==='win32')&&powerMonitor&&typeof powerMonitor.on==='function'
  &&typeof powerMonitor.getSystemIdleState==='function';
 const now=typeof options.now==='function'?options.now:()=>Math.floor(Date.now()/1000);
 const loadKey=options.loadKey||loadOrCreateKeyPair;
 // Stored-token revoke (app start, and a lock with no approval in this run). The device token lives only in the
 // agent's key store, so main runs the agent once (runRevokeAgent -> exit code); the agent hands the token back over
 // the private bridge (revokeWith) and main calls keys/revoke with the dashboard session. getRevokeInstallationId
 // reads the saved installation id only: no busy check, no registration.
 const {getRevokeInstallationId,runRevokeAgent}=options;
 let pending=false,currentClaims=null,activeTask=null,lastAuthorization=null,epoch=0;
 let revokeSlot=null,storedFlight=null,startup=null;
 // clean: the server confirmed this installation's revoke in this run ('revoked' count or 'none') and no approval
 // attempt (lastAuthorization) was made after it. authGen counts approval attempts, so a revoke that raced one
 // does not count. startConfirmed: a stored revoke reached 'revoked' or 'none' in this run (the chat sidecar gate).
 let clean=false,authGen=0,startConfirmed=false;
 const confirmedAt=gen=>{if(authGen===gen)clean=true;};
 const screenActive=()=>{try{return !!lockSupported&&powerMonitor.getSystemIdleState(1)==='active';}catch{return false;}};
 const approval=createConsentApproval({app,dialog,powerMonitor,safeStorage,trustedWindow,allowedUrl,now,loadKeyPair:loadKey,
  platform,
  challenge:async claims=>{
   try{return currentClaims&&encodeConsent(claims).equals(encodeConsent(currentClaims))?currentClaims:null;}catch{return null;}
  }});

 async function post(path,body,authorization){
  try{
   const r=await request(path,body,authorization);
   if(!r||r.status!==200||!r.body||typeof r.body!=='object'||Array.isArray(r.body))return null;
   return r.body;
  }catch{return null;}
 }
 async function run(input,signal,requestEpoch){
  const current=()=>!signal?.aborted&&requestEpoch===epoch&&screenActive();
  if(!current())return FAIL;
  let installation_id;
  try{installation_id=await getInstallationId();}catch{return FAIL;}
  if(!current()||typeof installation_id!=='string'||!INSTALLATION.test(installation_id))return FAIL;
  const authorization=input.device_bearer;
  lastAuthorization={installation_id,authorization};authGen++;clean=false;
  try{
   const pair=await loadKey({safeStorage,filePath:keyFile});
   if(!current())return FAIL;
   const spki=pair.publicKey.export({type:'spki',format:'der'}).toString('base64url');
   const begun=await post('/api/chat/consent/keys/begin',{installation_id,spki},authorization);
   if(!current()||!begun||!begun.claims||typeof begun.key_id!=='string')return FAIL;
   const bind=begun.claims;
   const pop=signConsent(bind,pair.privateKey,{nowSeconds:now()});
   const rotate=signConsent({...bind,model:'rotate'},pair.privateKey,{nowSeconds:now()});
   if(!SIGNATURE.test(pop)||!SIGNATURE.test(rotate))return FAIL;
   const activated=await post('/api/chat/consent/keys/activate',
    {installation_id,key_id:begun.key_id,pop_signature:pop,rotate_signature:rotate},authorization);
   if(!current()||!activated||activated.state!=='active')return FAIL;

   const issued=await post('/api/chat/consent/challenges/issue',{installation_id,request_id:input.request_id},authorization);
   if(!current()||!issued||!issued.claims)return FAIL;
   const claims=issued.claims;
   try{encodeConsent(claims);}catch{return FAIL;}
   if(claims.session_id!==input.request_id||claims.expires_at<=now())return FAIL;
   currentClaims=claims;

   const win=trustedWindow();
   if(!win||typeof focusWindow!=='function')return FAIL;
   await focusWindow(win);
   if(!current())return FAIL;
   const frame=win.webContents?.mainFrame;
   if(!frame)return FAIL;
   const event={sender:win.webContents,senderFrame:frame};
   const signed=await approval.approve(event,claims,{signal});
   if(signed&&signed.ok===false)return refusal(signed.code);
   if(!current()||!signed||signed.ok!==true||!SIGNATURE.test(signed.signature))return FAIL;
   if(!encodeConsent(signed.claims).equals(encodeConsent(claims)))return FAIL;
   const verified=await post('/api/chat/consent/challenges/verify',
    {installation_id,nonce:claims.nonce,signature:signed.signature},authorization);
   return current()&&!!verified&&verified.state==='verified'&&typeof verified.grant_id==='string'?OK:FAIL;
  }catch{return FAIL;}
  finally{currentClaims=null;}
 }
 async function handle(input,signal){
  if(pending||signal?.aborted||!screenActive()||!input||typeof input!=='object'||!REQUEST_ID.test(input.request_id||'')||!BEARER.test(input.device_bearer||''))return FAIL;
  pending=true;currentClaims=null;
  const requestEpoch=epoch;
  // The start revoke must not land after this approval's new key. Its result does not gate the approval.
  if(startup)try{await startup;}catch{}
  const task=run(input,signal,requestEpoch);activeTask=task;
  try{const result=await task;return result&&result.ok===true?OK:result&&REASONS.includes(result.reason)?result:FAIL;}
  catch{return FAIL;}
  finally{pending=false;if(activeTask===task)activeTask=null;currentClaims=null;}
 }
 // Server-confirmed only: keys/revoke answered 200 with a non-negative integer count.
 async function revokeBound(installation_id,authorization){
  const result=await post('/api/chat/consent/keys/revoke',{installation_id},authorization);
  return !!result&&Number.isSafeInteger(result.revoked)&&result.revoked>=0;
 }
 // The bridge's revoke request. Accepted only while revokeStored() waits for it; the installation id is main's own.
 async function revokeWith(input){
  const slot=revokeSlot;
  if(!slot||!input||typeof input!=='object'||typeof input.device_bearer!=='string'||!BEARER.test(input.device_bearer))return FAIL;
  let ok=false;
  try{ok=await revokeBound(slot.installation_id,input.device_bearer);}catch{ok=false;}
  if(ok&&revokeSlot===slot)slot.confirmed=true;
  return ok?OK:FAIL;
 }
 // 'revoked': the server confirmed. 'none': this PC holds no installation id or no device token, so no key of this
 // installation can be used from here. 'failed': anything else. One flight at a time.
 function revokeStored(){
  if(storedFlight)return storedFlight;
  const gen=authGen;
  const flight=(async()=>{
   if(typeof getRevokeInstallationId!=='function'||typeof runRevokeAgent!=='function')return 'failed';
   let installation_id;
   try{installation_id=await getRevokeInstallationId();}catch{return 'failed';}
   if(installation_id===null||installation_id===undefined)return 'none';
   if(typeof installation_id!=='string'||!INSTALLATION.test(installation_id))return 'failed';
   const slot={installation_id,confirmed:false};
   revokeSlot=slot;
   try{
    const code=await runRevokeAgent();
    if(code===REVOKE_NONE_EXIT)return 'none';
    return code===0&&slot.confirmed?'revoked':'failed';
   }catch{return 'failed';}
   finally{if(revokeSlot===slot)revokeSlot=null;}
  })().then(outcome=>{
   if(outcome==='revoked'||outcome==='none'){startConfirmed=true;confirmedAt(gen);}
   return outcome;
  });
  storedFlight=flight;
  flight.finally(()=>{if(storedFlight===flight)storedFlight=null;}).catch(()=>{});
  return flight;
 }
 // App start: once per runtime. Never rejects; the caller only logs the outcome.
 function revokeAtStart(){
  if(!startup)startup=revokeStored().catch(()=>'failed');
  return startup;
 }
 // Right before the chat sidecar starts: true once a stored revoke was confirmed in this run. Otherwise one more
 // stored revoke; its outcome decides this start only, and the next start asks again until one is confirmed.
 async function ensureStartRevoked(){
  if(startup)try{await startup;}catch{}
  if(startConfirmed)return true;
  let outcome;
  try{outcome=await revokeStored();}catch{outcome='failed';}
  return outcome==='revoked'||outcome==='none';
 }
 async function invalidateOnLock(){
  epoch++;currentClaims=null;
  const task=activeTask;
  const revoke=async auth=>{
   if(!auth){const outcome=await revokeStored();return outcome==='revoked'||outcome==='none';}
   const gen=authGen;
   const ok=await revokeBound(auth.installation_id,auth.authorization);
   if(ok)confirmedAt(gen);
   return ok;
  };
  const initial=lastAuthorization;
  let revoked=false;
  try{revoked=await revoke(initial);}catch{revoked=false;}
  if(task)try{await task;}catch{}
  const auth=lastAuthorization;
  // A failed revoke is still safe when this run already confirmed one and no approval was attempted since.
  if(!auth)return revoked||clean;
  // The approval flow may have been inside key activation when lock arrived.
  // Revoke again after it settles so that such a late activation cannot survive.
  if(task&& (auth===initial||!revoked)){
   try{revoked=await revoke(auth);}catch{revoked=false;}
  }
  if(!revoked)return false;
  lastAuthorization=null;
  return true;
 }
 return Object.freeze({handle,invalidateOnLock,revokeWith,revokeAtStart,ensureStartRevoked,dispose:()=>approval.dispose()});
}

module.exports=Object.freeze({createConsentRuntime,REASONS,REVOKE_NONE_EXIT});
