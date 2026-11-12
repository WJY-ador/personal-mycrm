// Tests for consent-approval.cjs (desktop-local native consent approval, unconnected).
// Synthetic only: mocked dialog, powerMonitor, safeStorage, app paths and window objects; the signing
// key is generated in-process by the key store under a fresh fs.mkdtemp userData and discarded.
// No Electron, no keychain, no account keys, no provider or server calls.
//
// FAKE, NOT A SECURITY IMPLEMENTATION: fakeSafeStorage XORs bytes with a fixed test constant.
//
// Run: node --test test/consent-approval.test.cjs   (from desktop/)
'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const fsSync=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const crypto=require('node:crypto');
const {EventEmitter}=require('node:events');
const approval=require('../src/consent-approval.cjs');
const {verifyConsent}=require('../src/consent-signature.cjs');

const PAGE='file:///Applications/MyCRM.app/Contents/Resources/app/src/index.html';
const NOW=1_800_000_000;
const CLAIMS=Object.freeze({user_id:'user_synthetic_1',device_id:'dev_synthetic_1',session_id:'inst_synthetic_1',
  provider:'claude',model:'claude-sonnet-5-5',nonce:'syntheticNonce_AAAAAAAAAAAAAAAA',expires_at:NOW+300});

const FAKE_XOR_BYTE=0x5a;
const fakeXor=buf=>Buffer.from(Buffer.from(buf).map(b=>b^FAKE_XOR_BYTE));
function fakeSafeStorage(available=()=>true){
  return {isEncryptionAvailable:()=>available(),encryptString:s=>fakeXor(Buffer.from(s,'utf8')),decryptString:b=>fakeXor(b).toString('utf8')};
}

async function fixture(t,over={}){
  const userData=await fs.mkdtemp(path.join(os.tmpdir(),'mycrm-consent-approval-'));
  t.after(()=>fs.rm(userData,{recursive:true,force:true}));
  const mainFrame={url:PAGE,parent:null};
  const webContents={mainFrame,getURL:()=>PAGE,isDevToolsOpened:()=>false};
  const win={webContents,isDestroyed:()=>false,isFocused:()=>true};
  const idle=over.idle||['active','active','active'];
  const calls={dialog:[],idle:[],challenge:0};
  const powerMonitor=over.powerMonitor!==undefined?over.powerMonitor:new EventEmitter();
  if(over.powerMonitor===undefined)powerMonitor.getSystemIdleState=threshold=>{
    calls.idle.push(threshold);const i=calls.idle.length-1;return idle[Math.min(i,idle.length-1)];};
  const dialog={showMessageBox:async(parent,options)=>{calls.dialog.push({parent,options});
    if(over.onDialog)return over.onDialog(parent,options);return {response:1,checkboxChecked:false};}};
  const challenge=over.challenge!==undefined?over.challenge:async()=>{calls.challenge++;return {...CLAIMS};};
  const api=approval.createConsentApproval({
    app:{getPath:name=>{assert.equal(name,'userData');return userData;}},
    dialog,powerMonitor,safeStorage:over.safeStorage||fakeSafeStorage(),
    trustedWindow:()=>win,allowedUrl:PAGE,challenge,now:()=>NOW,
  });
  const event={sender:webContents,senderFrame:mainFrame};
  const keyFile=path.join(userData,approval.KEY_FILE);
  return {api,win,webContents,mainFrame,event,calls,keyFile};
}

function assertNoSignature(result,code){
  assert.equal(result.ok,false);assert.equal(result.code,code);
  assert.equal('signature' in result,false);
}

test('unconnected: CONNECTED is false, preload and renderer expose nothing, main registers nothing',()=>{
  assert.equal(approval.CONNECTED,false);
  const src=name=>fsSync.readFileSync(path.join(__dirname,'..','src',name),'utf8');
  for(const name of ['preload.cjs','renderer.js','main.cjs']){
    assert.equal(src(name).includes(approval.CHANNEL),false,name);
    assert.equal(/consent-approval/.test(src(name)),false,name);
  }
  assert.equal(/require\(['"]electron['"]\)/.test(src('consent-approval.cjs')),false);
});

test('no server challenge source means UNSUPPORTED before any check or dialog',async t=>{
  const f=await fixture(t,{challenge:null});
  assertNoSignature(await f.api.approve(f.event,{...CLAIMS}),'UNSUPPORTED');
  assert.equal(f.calls.dialog.length,0);assert.equal(f.calls.idle.length,0);
  assert.equal(fsSync.existsSync(f.keyFile),false);
});

test('native approval explains the AI access in plain Korean without exposing internal identifiers',async t=>{
  const f=await fixture(t);
  const result=await f.api.approve(f.event,{...CLAIMS});
  assert.equal(result.ok,true);
  const {options}=f.calls.dialog[0];
  assert.equal(options.title,'MyCRM AI 대화 허용');
  assert.equal(options.message,'이 PC에서 Claude 대화를 허용할까요?');
  assert.match(options.detail,/^한 번 허용하면 다른 모델, 새 대화, 화면 잠금 해제, 앱 재시작 뒤에도 다시 묻지 않아요\./);
  assert.match(options.detail,/그만 쓰려면 연결 장치 창이나 웹의 연결 장치에서 허용을 해제하세요\.$/);
  assert.doesNotMatch(options.title+options.message+options.detail,/[「」·]/);
  assert.deepEqual(options.buttons,['취소','허용']);
  assert.equal(options.cancelId,0);assert.equal(options.defaultId,0);
  assert.match(options.detail,/대화에 필요한 MyCRM 기록을 조회/);
  assert.match(options.detail,/요청에 따라 기존 MyCRM 규칙으로 기록을 변경/);
  assert.match(options.detail,/대화 내용은 선택한 모델로 전송돼요/);
  assert.match(options.detail,/이 PC의 Claude CLI 기록에도 남을 수 있어요/);
  assert.match(options.detail,/이번에 고른 모델: claude-sonnet-5-5 \(허용은 모델과 상관없이 Claude 전체에 적용돼요\)/);
  assert.match(options.detail,/요청 만료 시각: 2027년 1월 15일 17:05 \(한국 시각\)/);
  assert.doesNotMatch(options.detail,/user_id|device_id|session_id|expires_at|synthetic|1800000300|nonce|token|private.?key/i);
});

test('provider display labels are friendly; the model line shows this chat\'s pick and the server default as 기본 모델',async t=>{
  const codex={...CLAIMS,provider:'codex',model:'gpt-5-codex'};
  const g=await fixture(t,{challenge:async()=>({...codex})});
  assert.equal((await g.api.approve(g.event,codex)).ok,true);
  assert.equal(g.calls.dialog[0].options.message,'이 PC에서 Codex 대화를 허용할까요?');
  assert.match(g.calls.dialog[0].options.detail,/이번에 고른 모델: gpt-5-codex \(허용은 모델과 상관없이 Codex 전체에 적용돼요\)/);
  const d={...CLAIMS,model:':default'};
  const h=await fixture(t,{challenge:async()=>({...d})});
  assert.equal((await h.api.approve(h.event,d)).ok,true);
  assert.match(h.calls.dialog[0].options.detail,/이번에 고른 모델: 기본 모델 /);
  assert.doesNotMatch(h.calls.dialog[0].options.detail,/:default/);
});

test('success only after explicit affirmative in the native dialog showing exact claims',async t=>{
  const f=await fixture(t);
  const result=await f.api.approve(f.event,{...CLAIMS});
  assert.equal(result.ok,true);
  assert.equal(f.calls.dialog.length,1);
  assert.equal(f.calls.dialog[0].parent,f.win);
  const {options}=f.calls.dialog[0];
  assert.equal(options.cancelId,0);assert.equal(options.defaultId,0);assert.equal(options.buttons[1],'허용');
  assert.ok(options.message.includes('Claude'));assert.ok(options.detail.includes('이번에 고른 모델: claude-sonnet-5-5'));
  assert.ok(options.detail.includes('2027년 1월 15일 17:05 (한국 시각)'));
  assert.ok(options.detail.includes('(한국 시각)'));
  assert.deepEqual(f.calls.idle,[1,1,1]); // before dialog, after dialog, before signing
  assert.equal(f.calls.challenge,2);
  assert.deepEqual({...result.claims},{...CLAIMS});
  const publicKey=crypto.createPublicKey({key:Buffer.from(result.publicKey,'base64'),type:'spki',format:'der'});
  assert.deepEqual(verifyConsent({...CLAIMS},result.signature,publicKey,{nowSeconds:NOW}),{ok:true});
  assert.equal(fsSync.existsSync(f.keyFile),true);
  const stored=await fs.readFile(f.keyFile,'utf8');
  assert.equal(stored.includes('PRIVATE KEY'),false);
});

test('sender: other webContents, other window, devtools, subframe, wrong URL, destroyed or unfocused window',async t=>{
  const cases=[
    f=>({event:{sender:{mainFrame:f.mainFrame},senderFrame:f.mainFrame}}),
    f=>({event:{sender:{...f.webContents},senderFrame:f.mainFrame}}),
    f=>{f.webContents.isDevToolsOpened=()=>true;return {};},
    f=>({event:{sender:f.webContents,senderFrame:{url:PAGE,parent:f.mainFrame}}}),
    f=>({event:{sender:f.webContents,senderFrame:null}}),
    f=>{f.mainFrame.url='https://evil.example/';return {};},
    f=>{f.mainFrame.url=PAGE+'?x=1';return {};},
    f=>{f.webContents.getURL=()=>'https://mycrm.example/';return {};},
    f=>{f.win.isDestroyed=()=>true;return {};},
    f=>{f.win.isFocused=()=>false;return {};},
  ];
  for(const [i,make] of cases.entries()){
    const f=await fixture(t);const {event=f.event}=make(f);
    assertNoSignature(await f.api.approve(event,{...CLAIMS}),'SENDER');
    assert.equal(f.calls.dialog.length,0,`case ${i}`);
    assert.equal(fsSync.existsSync(f.keyFile),false,`case ${i}`);
  }
});

test('trustedSender ignores Origin headers and labels: only object identity and exact URL count',()=>{
  const mainFrame={url:PAGE,parent:null};
  const wc={mainFrame,getURL:()=>PAGE,isDevToolsOpened:()=>false};
  const win={webContents:wc,isDestroyed:()=>false,isFocused:()=>true};
  assert.equal(approval.trustedSender({sender:wc,senderFrame:mainFrame},win,PAGE),true);
  const lookalike={url:PAGE,parent:null,origin:'file://'};
  assert.equal(approval.trustedSender({sender:wc,senderFrame:lookalike,headers:{Origin:'file://'}},win,PAGE),false);
  assert.equal(approval.trustedSender({sender:wc,senderFrame:mainFrame},win,''),false);
  assert.equal(approval.trustedSender({sender:wc,senderFrame:mainFrame},null,PAGE),false);
});

test('dialog cancel or close is DECLINED; throw or odd result is CANCELED; neither signs or creates a key',async t=>{
  // cancelId is 0, so both the 취소 button and closing the dialog arrive as response 0.
  for(const [onDialog,code] of [[()=>({response:0}),'DECLINED'],[()=>({response:0,checkboxChecked:false}),'DECLINED'],
    [()=>({response:'1'}),'CANCELED'],[()=>({response:'0'}),'CANCELED'],[()=>({response:2}),'CANCELED'],[()=>({}),'CANCELED'],
    [()=>null,'CANCELED'],[()=>{throw new Error('x');},'CANCELED']]){
    const f=await fixture(t,{onDialog});
    assertNoSignature(await f.api.approve(f.event,{...CLAIMS}),code);
    assert.equal(fsSync.existsSync(f.keyFile),false);
  }
});

test('abort while the dialog is open stays CANCELED even when the person pressed 취소',async t=>{
  const controller=new AbortController();
  const f=await fixture(t,{onDialog:()=>{controller.abort();return {response:0};}});
  assertNoSignature(await f.api.approve(f.event,{...CLAIMS},{signal:controller.signal}),'CANCELED');
});

test('J-F6: idle (no input for a second) is not a lock; the window opens and signs',async t=>{
  const f=await fixture(t,{idle:['idle','idle','idle']});
  const result=await f.api.approve(f.event,{...CLAIMS});
  assert.equal(result.ok,true);assert.equal(f.calls.dialog.length,1);
});

test('a lock state other than active or idle before the dialog fails closed without a dialog',async t=>{
  for(const state of ['locked','unknown','Active','',undefined]){
    const f=await fixture(t,{idle:[state]});
    assertNoSignature(await f.api.approve(f.event,{...CLAIMS}),'IDLE');
    assert.equal(f.calls.dialog.length,0);
  }
  for(const powerMonitor of [null,{},{getSystemIdleState:()=>{throw new Error('x');}}]){
    const f=await fixture(t,{powerMonitor});
    assertNoSignature(await f.api.approve(f.event,{...CLAIMS}),'IDLE');
    assert.equal(f.calls.dialog.length,0);
  }
});

test('locked after the dialog or before signing yields no signature',async t=>{
  const a=await fixture(t,{idle:['active','locked']});
  assertNoSignature(await a.api.approve(a.event,{...CLAIMS}),'IDLE');
  assert.equal(a.calls.dialog.length,1);assert.equal(fsSync.existsSync(a.keyFile),false);
  const b=await fixture(t,{idle:['active','active','unknown']});
  assertNoSignature(await b.api.approve(b.event,{...CLAIMS}),'IDLE');
});

test('a lock-screen event during the native dialog cancels approval even if immediately unlocked',async t=>{
 const powerMonitor=new EventEmitter();let locked=false;
 powerMonitor.getSystemIdleState=()=>locked?'locked':'active';
 const f=await fixture(t,{powerMonitor,onDialog:async()=>{
  locked=true;powerMonitor.emit('lock-screen');locked=false;
  return {response:1};
 }});
 assertNoSignature(await f.api.approve(f.event,{...CLAIMS}),'IDLE');
 assert.equal(f.calls.dialog.length,1);
 assert.equal(fsSync.existsSync(f.keyFile),false);
 f.api.dispose();
});

test('suspend during the native dialog cancels approval before resume',async t=>{
 const powerMonitor=new EventEmitter();let asleep=false;
 powerMonitor.getSystemIdleState=()=>asleep?'locked':'active';
 const f=await fixture(t,{powerMonitor,onDialog:async()=>{
  asleep=true;powerMonitor.emit('suspend');asleep=false;powerMonitor.emit('resume');
  return {response:1};
 }});
 assertNoSignature(await f.api.approve(f.event,{...CLAIMS}),'IDLE');
 assert.equal(f.calls.dialog.length,1);
 assert.equal(fsSync.existsSync(f.keyFile),false);
 f.api.dispose();
});

test('bridge abort during native dialog prevents a late allow from signing',async t=>{
  let resolveDialog;
  const controller=new AbortController();
  const f=await fixture(t,{onDialog:()=>new Promise(resolve=>{resolveDialog=resolve;})});
  const pending=f.api.approve(f.event,{...CLAIMS},{signal:controller.signal});
  while(!resolveDialog)await new Promise(resolve=>setImmediate(resolve));
  controller.abort();
  resolveDialog({response:1});
  assertNoSignature(await pending,'CANCELED');
  assert.equal(fsSync.existsSync(f.keyFile),false);
});

test('safeStorage unavailable before or after the dialog yields no signature',async t=>{
  const a=await fixture(t,{safeStorage:fakeSafeStorage(()=>false)});
  assertNoSignature(await a.api.approve(a.event,{...CLAIMS}),'KEY');
  assert.equal(a.calls.dialog.length,0);
  let n=0;const b=await fixture(t,{safeStorage:fakeSafeStorage(()=>++n===1)});
  assertNoSignature(await b.api.approve(b.event,{...CLAIMS}),'KEY');
  assert.equal(b.calls.dialog.length,1);assert.equal(fsSync.existsSync(b.keyFile),false);
  const c=await fixture(t,{safeStorage:{isEncryptionAvailable:()=>{throw new Error('x');}}});
  assertNoSignature(await c.api.approve(c.event,{...CLAIMS}),'KEY');
});

test('malformed claims, extra fields, getters and out-of-window expiry are refused before the dialog',async t=>{
  const getter={...CLAIMS};Object.defineProperty(getter,'model',{get:()=>'claude-sonnet-5-5',enumerable:true});
  for(const request of [null,'x',[],{...CLAIMS,extra:1},{...CLAIMS,provider:'Claude'},{...CLAIMS,user_id:'a\nb'},getter]){
    const f=await fixture(t);
    assertNoSignature(await f.api.approve(f.event,request),'CLAIMS');
    assert.equal(f.calls.dialog.length,0);
  }
  for(const expires_at of [NOW,NOW-1,NOW+approval.MAX_TTL_SECONDS+1]){
    const f=await fixture(t);
    assertNoSignature(await f.api.approve(f.event,{...CLAIMS,expires_at}),'EXPIRED');
    assert.equal(f.calls.dialog.length,0);
  }
});

test('changed claims: renderer claims differ from server challenge, or challenge changes during the dialog',async t=>{
  const a=await fixture(t,{challenge:async()=>({...CLAIMS,model:'other-model'})});
  assertNoSignature(await a.api.approve(a.event,{...CLAIMS}),'CLAIMS');
  assert.equal(a.calls.dialog.length,0);
  let n=0;
  const b=await fixture(t,{challenge:async()=>(++n===1?{...CLAIMS}:{...CLAIMS,device_id:'dev_synthetic_2'})});
  assertNoSignature(await b.api.approve(b.event,{...CLAIMS}),'CLAIMS');
  assert.equal(b.calls.dialog.length,1);assert.equal(fsSync.existsSync(b.keyFile),false);
  const c=await fixture(t,{challenge:async()=>{throw new Error('offline');}});
  assertNoSignature(await c.api.approve(c.event,{...CLAIMS}),'CLAIMS');
});

test('mutating the request during the dialog does not change what is signed',async t=>{
  const request={...CLAIMS};
  const f=await fixture(t,{onDialog:()=>{request.model='swapped-model';request.user_id='user_other';return {response:1};}});
  const result=await f.api.approve(f.event,request);
  assert.equal(result.ok,true);
  assert.deepEqual({...result.claims},{...CLAIMS});
  assert.ok(f.calls.dialog[0].options.detail.includes('이번에 고른 모델: '+CLAIMS.model));
  assert.doesNotMatch(f.calls.dialog[0].options.detail,/user_synthetic_1|user_id|device_id|session_id/);
});

test('one dialog at a time',async t=>{
  let release;const gate=new Promise(r=>{release=r;});
  const f=await fixture(t,{onDialog:()=>gate.then(()=>({response:0}))});
  const first=f.api.approve(f.event,{...CLAIMS});
  await new Promise(r=>setImmediate(r));
  assertNoSignature(await f.api.approve(f.event,{...CLAIMS}),'BUSY');
  release();
  assertNoSignature(await first,'DECLINED');
});
