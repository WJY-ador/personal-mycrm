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
const refusal=code=>Object.freeze({ok:false,reason:code==='DECLINED'?'declined':code==='IDLE'?'locked':'failed'});

function createConsentRuntime(options={}){
 const {request,getInstallationId,safeStorage,keyFile,app,dialog,powerMonitor,trustedWindow,allowedUrl,focusWindow}=options;
 const platform=options.platform||process.platform;
 const lockSupported=(platform==='darwin'||platform==='win32')&&powerMonitor&&typeof powerMonitor.on==='function'
  &&typeof powerMonitor.getSystemIdleState==='function';
 const now=typeof options.now==='function'?options.now:()=>Math.floor(Date.now()/1000);
 const loadKey=options.loadKey||loadOrCreateKeyPair;
 let pending=false,currentClaims=null,activeTask=null,lastAuthorization=null,epoch=0;
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
  lastAuthorization={installation_id,authorization};
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
  const task=run(input,signal,requestEpoch);activeTask=task;
  try{const result=await task;return result&&result.ok===true?OK:result&&REASONS.includes(result.reason)?result:FAIL;}
  catch{return FAIL;}
  finally{pending=false;if(activeTask===task)activeTask=null;currentClaims=null;}
 }
 async function invalidateOnLock(){
  epoch++;currentClaims=null;
  const task=activeTask;
  const revoke=async auth=>{
   if(!auth)return true;
   const result=await post('/api/chat/consent/keys/revoke',{installation_id:auth.installation_id},auth.authorization);
   return !!result&&Number.isSafeInteger(result.revoked)&&result.revoked>=0;
  };
  const initial=lastAuthorization;
  let revoked=false;
  try{revoked=await revoke(initial);}catch{revoked=false;}
  if(task)try{await task;}catch{}
  const auth=lastAuthorization;
  if(!auth)return revoked||!initial;
  // The approval flow may have been inside key activation when lock arrived.
  // Revoke again after it settles so that such a late activation cannot survive.
  if(task&& (auth===initial||!revoked)){
   try{revoked=await revoke(auth);}catch{revoked=false;}
  }
  if(!revoked)return false;
  lastAuthorization=null;
  return true;
 }
 return Object.freeze({handle,invalidateOnLock,dispose:()=>approval.dispose()});
}

module.exports=Object.freeze({createConsentRuntime,REASONS});
