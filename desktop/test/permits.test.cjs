'use strict';
// J JD3: this PC's standing allows, listed and released by the person from the connection window.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {createPermits,PERMITS_PATH,PERMIT_REVOKE_PATH}=require('../src/permits.cjs');

const HOSTED='https://mycrm.example/';
const ME='di_'+'a'.repeat(24),OTHER='di_'+'b'.repeat(24);
function setup({answer,usable=true,installation=ME}={}){
 const calls=[],logs=[];let cancels=0;
 const listed={status:200,body:{permits:[{device_id:'d1',installation_id:ME,provider:'claude',created_at:'x'},
  {device_id:'d2',installation_id:OTHER,provider:'codex',created_at:'x'},{installation_id:ME,provider:'other'},null]}};
 const request=async(method,url,body,headers)=>{calls.push({method,url,body,headers});
  return answer?answer(method,url,body):method==='GET'?listed:{status:200,body:{revoked:1}};};
 const p=createPermits({request,hosted:HOSTED,installationId:()=>installation,usable:()=>usable,cancel:()=>{cancels++;},log:(...a)=>logs.push(a.join(':'))});
 return {p,calls,logs,get cancels(){return cancels;}};
}

test('the list keeps only this installation and the known AI services; only names leave',async()=>{
 const f=setup();
 assert.deepEqual(await f.p.state(),{known:true,providers:['claude']});
 assert.deepEqual(f.calls,[{method:'GET',url:HOSTED.replace(/\/$/,'')+PERMITS_PATH,body:null,headers:undefined}]);
});

test('no login, no installation, not connected or a bad answer: unknown, nothing claimed',async()=>{
 assert.deepEqual(await setup({usable:false}).p.state(),{known:false,providers:[]});
 assert.deepEqual(await setup({installation:null}).p.state(),{known:false,providers:[]});
 assert.deepEqual(await setup({installation:'di_bad'}).p.state(),{known:false,providers:[]});
 for(const answer of [()=>({status:401,body:{code:'NO-SESSION'}}),()=>({status:200,body:{permits:'x'}}),()=>{throw new Error('net');}])
  assert.deepEqual(await setup({answer}).p.state(),{known:false,providers:[]});
});

test('release posts this installation and one provider with Origin and no device token, cancels an open window',async()=>{
 const f=setup();
 assert.deepEqual(await f.p.release('claude'),{known:true,providers:['claude']});
 const post=f.calls[0];
 assert.equal(post.method,'POST');assert.equal(post.url,'https://mycrm.example'+PERMIT_REVOKE_PATH);
 assert.deepEqual(post.body,{installation_id:ME,provider:'claude'});
 assert.deepEqual(post.headers,{'Origin':'https://mycrm.example','Content-Type':'application/json'});
 assert.ok(!Object.keys(post.headers).some(k=>k.toLowerCase()==='authorization'));
 assert.equal(f.cancels,1);assert.deepEqual(f.logs,['consent:permit-revoked']);
});

test('release refuses unknown services and reports failure kinds without server text',async()=>{
 await assert.rejects(setup().p.release('gpt'),/^Error: input$/);
 await assert.rejects(setup({usable:false}).p.release('claude'),/permit-failed/);
 await assert.rejects(setup({answer:()=>({status:401,body:{code:'NO-SESSION'}})}).p.release('codex'),/^Error: login$/);
 for(const answer of [()=>({status:404,body:{code:'NOT-FOUND',message:'secret text'}}),()=>({status:200,body:{revoked:'1'}}),()=>{throw new Error('secret');}]){
  const f=setup({answer});
  await assert.rejects(f.p.release('codex'),/^Error: permit-failed$/);
  assert.ok(f.logs.every(l=>!l.includes('secret')));
 }
});

function windowWith(permits){
 const nodes=new Map();
 const element=id=>{if(!nodes.has(id))nodes.set(id,{id,textContent:'',value:'',hidden:false,disabled:false,checked:false,className:'',open:false});return nodes.get(id);};
 const released=[];let focus;
 const mycrm={status:async()=>({ok:false}),onStatus:()=>{},updateState:async()=>({ok:false}),onUpdate:()=>{},
  permits:async()=>permits,releasePermit:async name=>{released.push(name);return {ok:true,value:{known:true,providers:[]}};}};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../src/renderer.js'),'utf8'),{window:{mycrm,addEventListener:(e,fn)=>{if(e==='focus')focus=fn;}},
  document:{getElementById:element,querySelectorAll:()=>[],activeElement:null},console,setInterval:()=>1,clearInterval:()=>{}});
 return {el:element,released,focus:()=>focus()};
}
const tick=()=>new Promise(r=>setImmediate(r));

test('the window shows a release button per allowed service and hides the rest',async()=>{
 const w=windowWith({ok:true,value:{known:true,providers:['claude','codex']}});await tick();
 assert.equal(w.el('release-claude').hidden,false);assert.equal(w.el('release-codex').hidden,false);
 assert.equal(w.el('permit-badge').textContent,'허용 2개');assert.match(w.el('permit-state').textContent,/Claude, Codex/);
 await w.el('release-claude').onclick();await tick();
 assert.deepEqual(w.released,['claude']);assert.equal(w.el('release-claude').hidden,true);
});

test('unknown state hides every button and points to the web devices screen',async()=>{
 const w=windowWith({ok:true,value:{known:false,providers:[]}});await tick();
 assert.equal(w.el('release-claude').hidden,true);assert.equal(w.el('release-codex').hidden,true);
 assert.equal(w.el('permit-badge').textContent,'확인 못 함');assert.match(w.el('permit-state').textContent,/연결 장치/);
 const none=windowWith({ok:true,value:{known:true,providers:[]}});await tick();
 assert.equal(none.el('permit-badge').textContent,'허용 없음');
});

test('main wires the permits module under the app lock with the bridge and runtime cancel',()=>{
 const main=fs.readFileSync(path.join(__dirname,'../src/main.cjs'),'utf8');
 assert.match(main,/register\('permit-revoke',provider=>exclusively\(\(\)=>permits\.release\(provider\)\)\)/);
 assert.match(main,/cancel:\(\)=>\{consentBridge\?\.abortPending\(\);consentRuntime\?\.cancel\(\);\}/);
 const preload=fs.readFileSync(path.join(__dirname,'../src/preload.cjs'),'utf8');
 assert.match(preload,/permits:call\('permits'\),releasePermit:call\('permit-revoke'\)/);
});
