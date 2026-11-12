'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const {EventEmitter}=require('node:events');
const {createConsentRuntime}=require('../src/consent-runtime.cjs');
const {encodeConsent,verifyConsent}=require('../src/consent-signature.cjs');

const NOW=Math.floor(Date.now()/1000);
function keyPair(){return crypto.generateKeyPairSync('ed25519');}
function fixture({dialogResult=1,locked=false,requestOverride,onDialog,runtimeOptions={}}={}){
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
  focusWindow:async()=>true,now:()=>NOW,...runtimeOptions});
 return {runtime,pair,calls,claims,powerMonitor,setLocked(value){lockedState=value;},get keyLoads(){return keyLoads;}};
}

test('supervised request bootstraps OS key, shows native approval, signs server claims and verifies once',async()=>{
 const f=fixture();
 assert.deepEqual(await f.runtime.handle({request_id:'request_test_1',device_bearer:'Bearer synthetic-device-token'}),{ok:true});
 assert.deepEqual(f.calls.map(x=>x.path),[
  '/api/chat/consent/keys/begin','/api/chat/consent/keys/activate',
  '/api/chat/consent/challenges/issue','/api/chat/consent/challenges/verify',
 ]);
 assert(f.calls.every(x=>x.authorization==='Bearer synthetic-device-token'));
 assert.equal(verifyConsent(f.claims,f.calls.at(-1).body.signature,f.pair.publicKey,{nowSeconds:NOW}).ok,true);
});

test('JD2: a screen lock sends nothing to the server; while locked no window opens, after unlock approval works',async()=>{
 const f=fixture();
 assert.deepEqual(await f.runtime.handle({request_id:'request_test_1',device_bearer:'Bearer synthetic-device-token'}),{ok:true});
 const before=f.calls.length;
 f.setLocked(true);f.powerMonitor.emit('lock-screen');f.runtime.cancel();
 assert.equal(f.calls.length,before,'no keys/revoke on lock');
 assert.deepEqual(await f.runtime.handle({request_id:'request_test_2',device_bearer:'Bearer synthetic-device-token'}),{ok:false,reason:'failed'});
 assert.equal(f.calls.length,before,'a locked screen opens no window and calls nothing');
 f.setLocked(false);f.powerMonitor.emit('unlock-screen');
 assert.deepEqual(await f.runtime.handle({request_id:'request_test_1',device_bearer:'Bearer synthetic-device-token'}),{ok:true});
 assert.equal(f.calls.some(x=>x.path.endsWith('/keys/revoke')),false);
 assert.equal(typeof f.runtime.invalidateOnLock,'undefined');
 assert.equal(typeof f.runtime.revokeAtStart,'undefined');
 assert.equal(typeof f.runtime.ensureStartRevoked,'undefined');
});

test('suspend during a pending native approval cancels it: a late allow cannot verify, nothing is revoked',async()=>{
 let resolveDialog;
 const f=fixture({onDialog:()=>new Promise(resolve=>{resolveDialog=resolve;})});
 const pending=f.runtime.handle({request_id:'request_test_1',device_bearer:'Bearer synthetic-device-token'});
 while(!resolveDialog)await new Promise(resolve=>setImmediate(resolve));
 f.powerMonitor.emit('suspend');f.runtime.cancel();
 resolveDialog({response:1});
 assert.notEqual((await pending).ok,true);
 assert.equal(f.calls.some(x=>x.path.endsWith('/challenges/verify')),false);
 assert.equal(f.calls.some(x=>x.path.endsWith('/keys/revoke')),false);
});

test('J-F6: no input for a second (idle) is not a lock; locked and unknown still refuse',async()=>{
 for(const [state,ok] of [['idle',true],['active',true],['locked',false],['unknown',false]]){
  const f=fixture();f.powerMonitor.getSystemIdleState=()=>state;
  const result=await f.runtime.handle({request_id:'request_test_1',device_bearer:'Bearer synthetic-device-token'});
  assert.equal(result.ok,ok,state);
 }
 const unsupported=fixture({runtimeOptions:{platform:'linux'}});
 assert.deepEqual(await unsupported.runtime.handle({request_id:'request_test_1',device_bearer:'Bearer synthetic-device-token'}),{ok:false,reason:'failed'});
 assert.equal(unsupported.calls.length,0);
});

test('cancel, locked session, malformed notification, and server binding mismatch fail closed',async()=>{
 const canceled=fixture({dialogResult:0});
 assert.deepEqual(await canceled.runtime.handle({request_id:'request_test_1',device_bearer:'Bearer synthetic-device-token'}),{ok:false,reason:'declined'});
 assert.equal(canceled.calls.some(x=>x.path.endsWith('/verify')),false);
 const locked=fixture({locked:true});
 assert.deepEqual(await locked.runtime.handle({request_id:'request_test_1',device_bearer:'Bearer synthetic-device-token'}),{ok:false,reason:'failed'});
 assert.equal(locked.calls.some(x=>x.path.endsWith('/verify')),false);
 const invalid=fixture();
 assert.deepEqual(await invalid.runtime.handle({request_id:'bad id',device_bearer:'Bearer synthetic-device-token'}),{ok:false,reason:'failed'});
 assert.equal(invalid.calls.length,0);
 const mismatch=fixture({requestOverride:async(path,body,_auth,_calls,claims)=>{
  if(path.endsWith('/keys/begin'))return {status:200,body:{key_id:'ck_synthetic_1',claims:{...claims,session_id:'ck_synthetic_1',provider:'mycrm-key',model:'bind'}}};
  if(path.endsWith('/keys/activate'))return {status:200,body:{state:'active'}};
  if(path.endsWith('/challenges/issue'))return {status:200,body:{claims:{...claims,session_id:'other_request'}}};
  return {status:500,body:null};
 }});
 assert.deepEqual(await mismatch.runtime.handle({request_id:'request_test_1',device_bearer:'Bearer synthetic-device-token'}),{ok:false,reason:'failed'});
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
 assert.deepEqual(await pending,{ok:false,reason:'failed'});
 assert.equal(calls.some(path=>path.endsWith('/verify')),false);
});

test('refusal reasons: 취소 or close is declined, lock during the dialog is locked, dialog failure is failed',async()=>{
 const req={request_id:'request_test_1',device_bearer:'Bearer synthetic-device-token'};
 const declined=fixture({dialogResult:0});
 assert.deepEqual(await declined.runtime.handle(req),{ok:false,reason:'declined'});
 assert.equal(declined.calls.some(x=>x.path.endsWith('/verify')),false);
 let locking;
 locking=fixture({onDialog:()=>{locking.powerMonitor.emit('lock-screen');return {response:1};}});
 assert.deepEqual(await locking.runtime.handle(req),{ok:false,reason:'locked'});
 assert.equal(locking.calls.some(x=>x.path.endsWith('/verify')),false);
 const thrown=fixture({onDialog:()=>{throw new Error('synthetic dialog failure');}});
 assert.deepEqual(await thrown.runtime.handle(req),{ok:false,reason:'failed'});
 const odd=fixture({dialogResult:2});
 assert.deepEqual(await odd.runtime.handle(req),{ok:false,reason:'failed'});
 const serverDown=fixture({requestOverride:async()=>{throw new Error('synthetic network failure');}});
 assert.deepEqual(await serverDown.runtime.handle(req),{ok:false,reason:'failed'});
 const verifyRefused=fixture({requestOverride:async(path,body,_a,_c,claims)=>{
  if(path.endsWith('/keys/begin'))return {status:200,body:{key_id:'ck_synthetic_1',claims:{...claims,session_id:'ck_synthetic_1',provider:'mycrm-key',model:'bind'}}};
  if(path.endsWith('/keys/activate'))return {status:200,body:{state:'active'}};
  if(path.endsWith('/challenges/issue'))return {status:200,body:{claims}};
  return {status:409,body:{code:'CONSENT_REQUIRED'}};
 }});
 assert.deepEqual(await verifyRefused.runtime.handle(req),{ok:false,reason:'failed'});
});

test('a second request while one is pending is failed, never declined',async()=>{
 let resolveDialog;
 const f=fixture({onDialog:()=>new Promise(resolve=>{resolveDialog=resolve;})});
 const req={request_id:'request_test_1',device_bearer:'Bearer synthetic-device-token'};
 const first=f.runtime.handle(req);
 while(!resolveDialog)await new Promise(resolve=>setImmediate(resolve));
 assert.deepEqual(await f.runtime.handle(req),{ok:false,reason:'failed'});
 resolveDialog({response:0});
 assert.deepEqual(await first,{ok:false,reason:'declined'});
});
