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
 assert.deepEqual(await f.runtime.handle({request_id:'request_test_1',device_bearer:'Bearer synthetic-device-token'}),{ok:true});
 f.setLocked(true);f.powerMonitor.emit('lock-screen');
 assert.equal(await f.runtime.invalidateOnLock(),true);
 assert.deepEqual(f.calls.at(-1),{path:'/api/chat/consent/keys/revoke',body:{installation_id:'di_'+'a'.repeat(24)},authorization:'Bearer synthetic-device-token'});
 assert.deepEqual(await f.runtime.handle({request_id:'request_test_2',device_bearer:'Bearer synthetic-device-token'}),{ok:false,reason:'failed'});
 f.setLocked(false);f.powerMonitor.emit('unlock-screen');
 assert.deepEqual(await f.runtime.handle({request_id:'request_test_2',device_bearer:'Bearer synthetic-device-token'}),{ok:true});
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
 assert.deepEqual(await pending,{ok:false,reason:'failed'});
 assert.equal(await revoke,true);
 assert.equal(f.calls.some(x=>x.path.endsWith('/challenges/verify')),false);
 assert.equal(f.calls.at(-1).path,'/api/chat/consent/keys/revoke');
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

// R5: stored-token revoke. The fake agent stands in for `chat-consent-revoke`: it hands the device token back over
// the bridge (revokeWith) and exits 0 on an ok reply, 1 otherwise, or 3 when the PC has no device token.
const INSTALL='di_'+'a'.repeat(24);
function storedFixture({agent='token',installation=INSTALL,...rest}={}){
 const holder={runs:0};
 const f=fixture({...rest,runtimeOptions:{
  getRevokeInstallationId:async()=>installation,
  runRevokeAgent:async()=>{
   holder.runs++;
   const mode=Array.isArray(agent)?agent[Math.min(holder.runs,agent.length)-1]:agent;
   if(mode==='none')return 3;
   if(mode==='fail')return 1;
   if(mode==='crash')throw new Error('agent-unavailable');
   const reply=await holder.runtime.revokeWith({device_bearer:'Bearer synthetic-stored-token'});
   return reply.ok===true?0:1;
  },
 }});
 holder.runtime=f.runtime;
 return Object.assign(f,{holder});
}

test('R5: a new runtime revokes on lock through the stored device token, without an approval in this run',async()=>{
 const f=storedFixture();
 assert.equal(await f.runtime.invalidateOnLock(),true);
 assert.equal(f.holder.runs,1);
 assert.deepEqual(f.calls,[{path:'/api/chat/consent/keys/revoke',body:{installation_id:INSTALL},authorization:'Bearer synthetic-stored-token'}]);
});

test('R5: app start sends one revoke, a second call reuses it, and an approval still follows',async()=>{
 const f=storedFixture();
 const first=f.runtime.revokeAtStart(),second=f.runtime.revokeAtStart();
 assert.equal(first,second);
 assert.equal(await first,'revoked');
 assert.equal(f.holder.runs,1);
 assert.deepEqual(f.calls.map(x=>x.path),['/api/chat/consent/keys/revoke']);
 assert.deepEqual(await f.runtime.handle({request_id:'request_test_1',device_bearer:'Bearer synthetic-device-token'}),{ok:true});
 assert.equal(f.calls.filter(x=>x.path.endsWith('/keys/revoke')).length,1);
});

test('R5: an approval waits for the start revoke, so the revoke cannot land after the new key',async()=>{
 let release;
 const gate=new Promise(resolve=>{release=resolve;});
 const f=storedFixture({requestOverride:async(path,body,auth,calls,claims,pair)=>{
  if(path.endsWith('/keys/revoke')){await gate;return {status:200,body:{revoked:1}};}
  if(path.endsWith('/keys/begin'))return {status:200,body:{key_id:'ck_synthetic_1',claims:{...claims,session_id:'ck_synthetic_1',provider:'mycrm-key',model:'bind'}}};
  if(path.endsWith('/keys/activate'))return {status:200,body:{key_id:body.key_id,state:'active',rotated:true}};
  if(path.endsWith('/challenges/issue'))return {status:200,body:{challenge_id:'cc_synthetic_1',claims}};
  if(path.endsWith('/challenges/verify'))return {status:200,body:{state:'verified',grant_id:'cg_synthetic_1'}};
  return {status:404,body:null};
 }});
 const start=f.runtime.revokeAtStart();
 const approval=f.runtime.handle({request_id:'request_test_1',device_bearer:'Bearer synthetic-device-token'});
 await new Promise(resolve=>setImmediate(resolve));
 assert.deepEqual(f.calls.map(x=>x.path),['/api/chat/consent/keys/revoke']);
 release();
 assert.equal(await start,'revoked');
 assert.deepEqual(await approval,{ok:true});
 assert.equal(f.calls[1].path,'/api/chat/consent/keys/begin');
});

test('R5: a failed start revoke resolves failed, never rejects, and the approval still runs',async()=>{
 for(const [label,options] of [
  ['server refuses',{requestOverride:async(path,body,auth,calls,claims)=>path.endsWith('/keys/revoke')?{status:503,body:{code:'X'}}
   :path.endsWith('/keys/begin')?{status:200,body:{key_id:'ck_synthetic_1',claims:{...claims,session_id:'ck_synthetic_1',provider:'mycrm-key',model:'bind'}}}
   :path.endsWith('/keys/activate')?{status:200,body:{key_id:body.key_id,state:'active',rotated:true}}
   :path.endsWith('/challenges/issue')?{status:200,body:{challenge_id:'cc_synthetic_1',claims}}
   :{status:200,body:{state:'verified',grant_id:'cg_synthetic_1'}}}],
  ['agent unavailable',{agent:'crash'}],
  ['bad installation id',{installation:'not-an-id'}],
 ]){
  const f=storedFixture(options);
  assert.equal(await f.runtime.revokeAtStart(),'failed',label);
  assert.deepEqual(await f.runtime.handle({request_id:'request_test_1',device_bearer:'Bearer synthetic-device-token'}),{ok:true},label);
 }
});

test('R5: no device token or no installation id means nothing to revoke; a failed stored revoke keeps the lock closed',async()=>{
 const none=storedFixture({agent:'none'});
 assert.equal(await none.runtime.invalidateOnLock(),true);
 assert.equal(none.calls.length,0);
 const unregistered=storedFixture({installation:null});
 assert.equal(await unregistered.runtime.invalidateOnLock(),true);
 assert.equal(unregistered.holder.runs,0);
 const failed=storedFixture({requestOverride:async()=>({status:401,body:{code:'NO-SESSION'}})});
 assert.equal(await failed.runtime.invalidateOnLock(),false);
 const crashed=storedFixture({agent:'crash'});
 assert.equal(await crashed.runtime.invalidateOnLock(),false);
 // Older wiring without the stored path fails closed instead of the old silent true.
 assert.equal(await fixture().runtime.invalidateOnLock(),false);
});

test('R5: revokeWith answers only while a stored revoke waits for it',async()=>{
 const f=storedFixture();
 assert.deepEqual(await f.runtime.revokeWith({device_bearer:'Bearer synthetic-stored-token'}),{ok:false,reason:'failed'});
 assert.equal(f.calls.length,0);
});

test('R5: an approval in this run still revokes with its own token on lock, not the stored path',async()=>{
 const f=storedFixture();
 assert.deepEqual(await f.runtime.handle({request_id:'request_test_1',device_bearer:'Bearer synthetic-device-token'}),{ok:true});
 assert.equal(await f.runtime.invalidateOnLock(),true);
 assert.equal(f.holder.runs,0);
 assert.deepEqual(f.calls.at(-1),{path:'/api/chat/consent/keys/revoke',body:{installation_id:INSTALL},authorization:'Bearer synthetic-device-token'});
});

const APPROVE={request_id:'request_test_1',device_bearer:'Bearer synthetic-device-token'};
// Server answers keys/revoke from a list per call (true = {revoked:1}, false = 503); other paths as the default fixture.
function revokeSequence(answers){
 let n=0;
 return async(path,body,auth,calls,claims,pair)=>{
  if(path.endsWith('/keys/revoke'))return answers[Math.min(n++,answers.length-1)]?{status:200,body:{revoked:1}}:{status:503,body:{code:'X'}};
  if(path.endsWith('/keys/begin'))return {status:200,body:{key_id:'ck_synthetic_1',claims:{...claims,session_id:'ck_synthetic_1',provider:'mycrm-key',model:'bind'}}};
  if(path.endsWith('/keys/activate'))return {status:200,body:{key_id:body.key_id,state:'active',rotated:true}};
  if(path.endsWith('/challenges/issue'))return {status:200,body:{challenge_id:'cc_synthetic_1',claims}};
  if(path.endsWith('/challenges/verify'))return {status:200,body:{state:'verified',grant_id:'cg_synthetic_1'}};
  return {status:404,body:null};
 };
}

test('R5 rule 1: a failed lock revoke counts as done after a confirmed revoke with no approval since',async()=>{
 const revoked=storedFixture({requestOverride:revokeSequence([true,false])});
 assert.equal(await revoked.runtime.revokeAtStart(),'revoked');
 assert.equal(await revoked.runtime.invalidateOnLock(),true);
 assert.equal(revoked.holder.runs,2);
 const none=storedFixture({agent:['none','fail']});
 assert.equal(await none.runtime.revokeAtStart(),'none');
 assert.equal(await none.runtime.invalidateOnLock(),true);
});

test('R5 rule 1: without a confirmed revoke, or after an approval attempt, a failed lock revoke stays closed',async()=>{
 const neverConfirmed=storedFixture({agent:'fail'});
 assert.equal(await neverConfirmed.runtime.revokeAtStart(),'failed');
 assert.equal(await neverConfirmed.runtime.invalidateOnLock(),false);
 // start confirmed, then an approval (lastAuthorization), then the lock revoke fails: fail-closed
 const approved=storedFixture({requestOverride:revokeSequence([true,false])});
 assert.equal(await approved.runtime.revokeAtStart(),'revoked');
 assert.deepEqual(await approved.runtime.handle(APPROVE),{ok:true});
 assert.equal(await approved.runtime.invalidateOnLock(),false);
 // an approval attempt that never reached the server still clears the confirmation
 const sequence=revokeSequence([true,false]);
 const attempted=storedFixture({requestOverride:async(path,...rest)=>path.endsWith('/keys/begin')?{status:500,body:null}
  :sequence(path,...rest)});
 assert.equal(await attempted.runtime.revokeAtStart(),'revoked');
 assert.deepEqual(await attempted.runtime.handle(APPROVE),{ok:false,reason:'failed'});
 assert.equal(await attempted.runtime.invalidateOnLock(),false);
});

test('R5 rule 1: a lock revoke confirmed with the approval token counts for the next lock',async()=>{
 const f=storedFixture({requestOverride:revokeSequence([true,true,false])});
 assert.equal(await f.runtime.revokeAtStart(),'revoked');
 assert.deepEqual(await f.runtime.handle(APPROVE),{ok:true});
 assert.equal(await f.runtime.invalidateOnLock(),true);   // bound revoke with the approval token, confirmed
 assert.equal(await f.runtime.invalidateOnLock(),true);   // stored revoke fails; nothing was attempted since
});

test('R5 rule 2: the chat sidecar gate retries an unconfirmed start revoke once per start and stops asking once confirmed',async()=>{
 const f=storedFixture({agent:['fail','fail','token']});
 assert.equal(await f.runtime.revokeAtStart(),'failed');
 assert.equal(await f.runtime.ensureStartRevoked(),false);
 assert.equal(f.holder.runs,2);
 assert.equal(await f.runtime.ensureStartRevoked(),true);
 assert.equal(f.holder.runs,3);
 assert.equal(await f.runtime.ensureStartRevoked(),true);
 assert.equal(f.holder.runs,3);
 const confirmed=storedFixture({agent:'none'});
 confirmed.runtime.revokeAtStart();
 assert.equal(await confirmed.runtime.ensureStartRevoked(),true);   // waits for the start revoke, no second run
 assert.equal(confirmed.holder.runs,1);
 const noStart=storedFixture();
 assert.equal(await noStart.runtime.ensureStartRevoked(),true);
 assert.equal(noStart.holder.runs,1);
});
