'use strict';
// AI connection in the app (spec 2026-11-13 §1.3, contract ai:get) and the "이 PC" line (§1.1, contract pc:get),
// with a fake sidecar run().
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {createAiLink,parseLinks,STATES,CONNECT_TIMEOUT_MS}=require('../src/ai-link.cjs');
const {createPcState,parseLast}=require('../src/pc-state.cjs');

const line=links=>({code:0,last:JSON.stringify({ai:links})});
const L=(state,code=null)=>({state,code});

test('only provider names, state words and well-formed codes survive the sidecar line',()=>{
  assert.deepEqual(parseLinks('{"ai":{"claude":{"state":"linked","code":null},"codex":{"state":"missing","code":"untrusted-cli"}}}'),
    {claude:L('linked'),codex:L('missing','untrusted-cli')});
  assert.deepEqual(parseLinks('{"ai":{"claude":{"state":"signed_out","code":"/Users/x","email":"x@example.invalid"},"codex":{"state":"weird"}}}'),
    {claude:L('signed_out')});
  for(const raw of ['','not json','{"ai":[]}','{"ai":{"claude":"linked"}}',null])assert.equal(parseLinks(raw),null);
  assert.deepEqual([...STATES],['linked','signed_out','off','missing']);
});

function link(answers){
  const runs=[],reports=[],logs=[],crossed=[];let notices=0,changes=0,clock=0;
  const ai=createAiLink({run:async(args,{timeoutMs})=>{runs.push([args,timeoutMs]);const a=answers.shift();if(a instanceof Error)throw a;return a;},
    notifyChat:()=>{notices++;},linkedChanged:(p,v)=>crossed.push([p,v]),report:(...a)=>reports.push(a),log:(...a)=>logs.push(a),
    changed:()=>{changes++;},now:()=>clock});
  const states=()=>Object.fromEntries(ai.view().providers.map(p=>[p.provider,p.state]));
  return {ai,runs,reports,logs,crossed,states,notices:()=>notices,changes:()=>changes,tick:ms=>{clock+=ms;}};
}

test('ai:get shape: checking before the first check, then the sidecar states with their codes',async()=>{
  const h=link([line({claude:L('signed_out','unsupported-auth'),codex:L('missing')})]);
  assert.deepEqual(h.ai.view(),{providers:[{provider:'claude',state:'checking',code:null},{provider:'codex',state:'checking',code:null}]});
  await h.ai.refresh();
  assert.deepEqual(h.ai.view(),{providers:[{provider:'claude',state:'signed_out',code:'unsupported-auth'},{provider:'codex',state:'missing',code:null}]});
  assert.deepEqual(h.runs[0][0],['ai-status']);
  assert.equal(h.notices(),0,'the first check after start tells chat nothing (it checked at its own start)');
});

test('refresh reuses a young check; a failed sidecar is reported and shows missing with a code',async()=>{
  const h=link([line({claude:L('linked'),codex:L('off')}),new Error('agent-unavailable')]);
  await h.ai.refresh();
  await h.ai.refresh(60000);assert.equal(h.runs.length,1,'reused');
  h.tick(60000);await h.ai.refresh(60000);
  assert.deepEqual(h.ai.view().providers,[{provider:'claude',state:'missing',code:'status-unavailable'},{provider:'codex',state:'off',code:'status-unavailable'}]);
  assert.deepEqual(h.reports,[['ai/status','unavailable']]);
  assert.equal(h.notices(),0,'a failed check tells chat nothing');
});

test('a login or logout made outside the app is told to chat and to main (jobs) when it crosses linked',async()=>{
  const h=link([line({claude:L('signed_out'),codex:L('missing')}),line({claude:L('linked'),codex:L('missing')}),
    line({claude:L('linked'),codex:L('missing')}),line({claude:L('signed_out'),codex:L('missing')})]);
  await h.ai.refresh();await h.ai.refresh();
  assert.equal(h.notices(),1);assert.deepEqual(h.crossed,[['claude',true]]);
  await h.ai.refresh();assert.equal(h.notices(),1,'no change');
  await h.ai.refresh();assert.equal(h.notices(),2);assert.deepEqual(h.crossed,[['claude',true],['claude',false]]);
});

test('connect shows linking, runs the provider login through the sidecar, then tells chat',async()=>{
  let release;const pending=new Promise(r=>{release=r;});
  const h=link([pending]);
  const done=h.ai.connect('claude');
  assert.deepEqual(h.ai.view().providers[0],{provider:'claude',state:'linking',code:null});
  await assert.rejects(h.ai.connect('codex'),/busy/,'one login at a time');
  await assert.rejects(h.ai.connect('gemini'),/input/);
  release(line({claude:L('linked')}));await done;
  assert.deepEqual(h.runs[0],[['ai-connect','--provider','claude'],CONNECT_TIMEOUT_MS]);
  assert.equal(h.states().claude,'linked');
  assert.equal(h.notices(),1);assert.deepEqual(h.crossed,[['claude',true]]);assert.deepEqual(h.reports,[]);
});

test('a login that did not finish is reported with its code; a failed sidecar too',async()=>{
  const h=link([line({claude:L('signed_out','login-unfinished')})]);
  await h.ai.connect('claude');
  assert.deepEqual(h.reports,[['ai/connect','login-unfinished']]);
  const g=link([{code:1,last:'설정 오류: /Users/someone'}]);
  await g.ai.connect('claude');
  assert.deepEqual(g.ai.view().providers[0],{provider:'claude',state:'missing',code:'connect-unavailable'});
  assert.deepEqual(g.reports,[['ai/connect','unavailable']]);
});

test('disconnect sets the local mark and tells chat; a failed sidecar changes nothing',async()=>{
  const h=link([line({claude:L('linked'),codex:L('missing')}),line({claude:L('off')}),new Error('x')]);
  await h.ai.refresh();
  await h.ai.disconnect('claude');
  assert.deepEqual(h.runs[1][0],['ai-disconnect','--provider','claude']);
  assert.equal(h.states().claude,'off');assert.equal(h.notices(),1);
  assert.deepEqual(h.crossed,[['claude',true],['claude',false]]);
  await h.ai.disconnect('codex');
  assert.equal(h.states().codex,'missing');assert.deepEqual(h.reports,[['ai/connect','disconnect-unavailable']]);
});

test('a chat notice that throws is logged, not thrown',async()=>{
  const ai=createAiLink({run:async()=>line({claude:L('linked')}),notifyChat:()=>{throw new Error('closed');},log:()=>{},changed:()=>{}});
  await ai.connect('claude');
  assert.equal(ai.linked('claude'),true);
});

test('pc:get shape: state from the live values and the last sync kept across a restart',()=>{
  let saved=null,changes=0,live={signedIn:true,deviceId:'is_'+'a'.repeat(24),syncing:false,login:false,stopped:false,blocked:false};
  const store={load:()=>saved,save:r=>{saved=JSON.stringify(r);}};
  const pc=createPcState({store,live:()=>live,version:'0.1.7',now:()=>Date.parse('2026-11-13T00:00:00.123Z'),changed:()=>{changes++;}});
  assert.deepEqual(pc.view(),{signed_in:true,device_id:'is_'+'a'.repeat(24),state:'ok',last_sync_at:null,last_result:null,last_code:null,app_version:'0.1.7'});
  pc.record({kind:'rejected',code:'halt-policy',detail:'/Users/someone'});
  assert.deepEqual(pc.view(),{signed_in:true,device_id:'is_'+'a'.repeat(24),state:'failed',last_sync_at:'2026-11-13T00:00:00Z',
    last_result:'failed',last_code:'halt-policy',app_version:'0.1.7'});
  assert.equal(changes,1);assert.ok(!saved.includes('someone'));
  pc.record({kind:'login',code:null});assert.equal(pc.view().last_code,'login');
  pc.record({kind:'unknown',code:'/x y'});assert.equal(pc.view().last_code,'unknown');
  pc.record({kind:'ok'});assert.deepEqual([pc.view().state,pc.view().last_result,pc.view().last_code],['ok','ok',null]);
  for(const [patch,state] of [[{syncing:true,login:true},'syncing'],[{login:true,stopped:true},'login'],[{stopped:true,blocked:true},'stopped'],[{blocked:true},'failed']]){
    live={...live,syncing:false,login:false,stopped:false,blocked:false,...patch};assert.equal(pc.view().state,state,JSON.stringify(patch));
  }
  live={signedIn:false,deviceId:'../x'};assert.deepEqual([pc.view().signed_in,pc.view().device_id],[false,null]);
  const again=createPcState({store,live:()=>({}),version:'0.1.7'});
  assert.equal(again.view().last_result,'ok');
  assert.equal(parseLast('{"at":"x","result":"ok"}'),null);
  assert.equal(parseLast('{"at":"2026-11-13T00:00:00Z","result":"weird"}'),null);
});
