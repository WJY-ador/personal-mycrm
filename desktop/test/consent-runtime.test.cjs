'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const {EventEmitter}=require('node:events');
const {createConsentRuntime}=require('../src/consent-runtime.cjs');
const {encodeConsent,verifyConsent}=require('../src/consent-signature.cjs');

const NOW=Math.floor(Date.now()/1000);
function keyPair(){return crypto.generateKeyPairSync('ed25519');}
function fixture({dialogResult=1,locked=false,requestOverride,onDialog}={}){
 const pair=keyPair(),calls=[],url='file:///mycrm/index.html';
 let keyLoads=0;
 const claims={user_id:'u_synthetic_1',device_id:'dev_synthetic_1',session_id:'request_test_1',provider:'claude',
  model:'claude/opus+latest',nonce:'AAAAAAAAAAAAAAAAAAAAAA',expires_at:NOW+60};
 const win={isDestroyed:()=>false,isFocused:()=>true,webContents:{
  isDevToolsOpened:()=>false,mainFrame:{parent:null,url},getURL:()=>url,
 }};
 const request=async(path,body,authorization)=>{
  calls.push({path,body,authorization});
  if(requestOverride)return requestOverride(path,body,authorization,calls,claims,pair);
  if(path.endsWith('/keys/begin'))return {status:200,body:{key_id:'ck_synthetic_1',claims:{...claims,session_id:'ck_synthetic_1',provider:'mycrm-key',model:'bind'}}};
  if(path.endsWith('/keys/activate'))return {status:200,body:{key_id:body.key_id,state:'active',rotated:true}};
  if(path.endsWith('/keys/revoke'))return {status:200,body:{revoked:1}};
  if(path.endsWith('/challenges/issue'))return {status:200,body:{challenge_id:'cc_synthetic_1',claims}};
  if(path.endsWith('/challenges/verify')){
   const verified=verifyConsent(claims,body.signature,pair.publicKey,{nowSeconds:NOW});
   return verified.ok?{status:200,body:{state:'verified',grant_id:'cg_synthetic_1'}}:{status:409,body:{code:'CONSENT_REQUIRED'}};
  }
  return {status:404,body:null};
 };
 let lockedState=locked;
 const powerMonitor=new EventEmitter();powerMonitor.getSystemIdleState=()=>lockedState?'locked':'active';
 const runtime=createConsentRuntime({request,getInstallationId:async()=>'di_'+'a'.repeat(24),safeStorage:{isEncryptionAvailable:()=>true},
  keyFile:'/synthetic/key',loadKey:async()=>{keyLoads++;return pair;},app:{getPath:()=>'/synthetic'},dialog:{showMessageBox:async(_w,options)=>{
   assert.match(options.detail,/claude\/opus\+latest/);return onDialog?onDialog():{response:dialogResult};
  }},powerMonitor,trustedWindow:()=>win,allowedUrl:url,
  focusWindow:async()=>true,now:()=>NOW});
 return {runtime,pair,calls,claims,powerMonitor,setLocked(value){lockedState=value;},get keyLoads(){return keyLoads;}};
}

test('supervised request bootstraps OS key, shows native approval, signs server claims and verifies once',async()=>{
 const f=fixture();
 assert.equal(await f.runtime.handle({request_id:'request_test_1',device_bearer:'Bearer synthetic-device-token'}),true);
 assert.deepEqual(f.calls.map(x=>x.path),[
  '/api/chat/consent/keys/begin','/api/chat/consent/keys/activate',
  '/api/chat/consent/challenges/issue','/api/chat/consent/challenges/verify',
 ]);
 assert(f.calls.every(x=>x.authorization==='Bearer synthetic-device-token'));
 assert.equal(verifyConsent(f.claims,f.calls.at(-1).body.signature,f.pair.publicKey,{nowSeconds:NOW}).ok,true);
});

test('screen lock revokes the active server key, then the same protected key can be approved again',async()=>{
 let currentClaims;
 const f=fixture({requestOverride:async(path,body,_auth,_calls,claims,pair)=>{
  if(path.endsWith('/keys/begin'))return {status:200,body:{key_id:'ck_synthetic_1',claims:{...claims,session_id:'ck_synthetic_1',provider:'mycrm-key',model:'bind'}}};
  if(path.endsWith('/keys/activate'))return {status:200,body:{key_id:body.key_id,state:'active',rotated:true}};
  if(path.endsWith('/keys/revoke'))return {status:200,body:{revoked:1}};
  if(path.endsWith('/challenges/issue')){
   currentClaims={...claims,session_id:body.request_id};return {status:200,body:{challenge_id:'cc_synthetic_1',claims:currentClaims}};
  }
  if(path.endsWith('/challenges/verify')){
   const verified=verifyConsent(currentClaims,body.signature,pair.publicKey,{nowSeconds:NOW});
   return verified.ok?{status:200,body:{state:'verified',grant_id:'cg_synthetic_1'}}:{status:409,body:{code:'CONSENT_REQUIRED'}};
  }
  return {status:404,body:null};
 }});
 assert.equal(await f.runtime.handle({request_id:'request_test_1',device_bearer:'Bearer synthetic-device-token'}),true);
 f.setLocked(true);f.powerMonitor.emit('lock-screen');
 assert.equal(await f.runtime.invalidateOnLock(),true);
 assert.deepEqual(f.calls.at(-1),{path:'/api/chat/consent/keys/revoke',body:{installation_id:'di_'+'a'.repeat(24)},authorization:'Bearer synthetic-device-token'});
 assert.equal(await f.runtime.handle({request_id:'request_test_2',device_bearer:'Bearer synthetic-device-token'}),false);
 f.setLocked(false);f.powerMonitor.emit('unlock-screen');
 assert.equal(await f.runtime.handle({request_id:'request_test_2',device_bearer:'Bearer synthetic-device-token'}),true);
 assert.equal(f.keyLoads,4,'each approval reloads the same OS-protected private key for registration and signing');
 assert.equal(f.calls.filter(x=>x.path.endsWith('/keys/activate')).length,2);
});

test('suspend during a pending native approval revokes the server key and cannot verify a late allow',async()=>{
 let resolveDialog;
 const f=fixture({onDialog:()=>new Promise(resolve=>{resolveDialog=resolve;})});
 const controller=new AbortController();
 const pending=f.runtime.handle({request_id:'request_test_1',device_bearer:'Bearer synthetic-device-token'},controller.signal);
 while(!resolveDialog)await new Promise(resolve=>setImmediate(resolve));
 f.setLocked(true);f.powerMonitor.emit('suspend');controller.abort();
 const revoke=f.runtime.invalidateOnLock();
 resolveDialog({response:1});
 assert.equal(await pending,false);
 assert.equal(await revoke,true);
 assert.equal(f.calls.some(x=>x.path.endsWith('/challenges/verify')),false);
 assert.equal(f.calls.at(-1).path,'/api/chat/consent/keys/revoke');
});

test('cancel, locked session, malformed notification, and server binding mismatch fail closed',async()=>{
 const canceled=fixture({dialogResult:0});
 assert.equal(await canceled.runtime.handle({request_id:'request_test_1',device_bearer:'Bearer synthetic-device-token'}),false);
 assert.equal(canceled.calls.some(x=>x.path.endsWith('/verify')),false);
 const locked=fixture({locked:true});
 assert.equal(await locked.runtime.handle({request_id:'request_test_1',device_bearer:'Bearer synthetic-device-token'}),false);
 assert.equal(locked.calls.some(x=>x.path.endsWith('/verify')),false);
 const invalid=fixture();
 assert.equal(await invalid.runtime.handle({request_id:'bad id',device_bearer:'Bearer synthetic-device-token'}),false);
 assert.equal(invalid.calls.length,0);
 const mismatch=fixture({requestOverride:async(path,body,_auth,_calls,claims)=>{
  if(path.endsWith('/keys/begin'))return {status:200,body:{key_id:'ck_synthetic_1',claims:{...claims,session_id:'ck_synthetic_1',provider:'mycrm-key',model:'bind'}}};
  if(path.endsWith('/keys/activate'))return {status:200,body:{state:'active'}};
  if(path.endsWith('/challenges/issue'))return {status:200,body:{claims:{...claims,session_id:'other_request'}}};
  return {status:500,body:null};
 }});
 assert.equal(await mismatch.runtime.handle({request_id:'request_test_1',device_bearer:'Bearer synthetic-device-token'}),false);
});

test('stop abort while native dialog is open cannot submit challenge verification',async()=>{
 let resolveDialog;
 const pair=keyPair(),calls=[],url='file:///mycrm/index.html';
 const claims={user_id:'u_synthetic_1',device_id:'dev_synthetic_1',session_id:'request_test_1',provider:'claude',model:'claude/opus+latest',nonce:'AAAAAAAAAAAAAAAAAAAAAA',expires_at:NOW+60};
 const win={isDestroyed:()=>false,isFocused:()=>true,webContents:{isDevToolsOpened:()=>false,mainFrame:{parent:null,url},getURL:()=>url}};
 const request=async(path,body)=>{
  calls.push(path);
  if(path.endsWith('/keys/begin'))return {status:200,body:{key_id:'ck_synthetic_1',claims:{...claims,session_id:'ck_synthetic_1',provider:'mycrm-key',model:'bind'}}};
  if(path.endsWith('/keys/activate'))return {status:200,body:{state:'active'}};
  if(path.endsWith('/challenges/issue'))return {status:200,body:{claims}};
  if(path.endsWith('/challenges/verify'))return {status:200,body:{state:'verified',grant_id:'cg_synthetic_1'}};
  return {status:404,body:null};
 };
 const runtime=createConsentRuntime({request,getInstallationId:async()=>'di_'+'a'.repeat(24),safeStorage:{isEncryptionAvailable:()=>true},
  keyFile:'/synthetic/key',loadKey:async()=>pair,app:{getPath:()=>'/synthetic'},dialog:{showMessageBox:()=>new Promise(resolve=>{resolveDialog=resolve;})},
  powerMonitor:Object.assign(new EventEmitter(),{getSystemIdleState:()=> 'active'}),trustedWindow:()=>win,allowedUrl:url,focusWindow:async()=>true,now:()=>NOW});
 const controller=new AbortController();
 const pending=runtime.handle({request_id:'request_test_1',device_bearer:'Bearer synthetic-device-token'},controller.signal);
 while(!resolveDialog)await new Promise(resolve=>setImmediate(resolve));
 controller.abort(); // UDS client disconnects when supervised child stops
 resolveDialog({response:1});
 assert.equal(await pending,false);
 assert.equal(calls.some(path=>path.endsWith('/verify')),false);
});
