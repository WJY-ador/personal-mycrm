'use strict';
// AI connection in the app (spec 2026-11-13 §1.3) and the "이 PC" line (§1.1), with a fake sidecar run().
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {createAiLink,parseStates,STATES,CONNECT_TIMEOUT_MS}=require('../src/ai-link.cjs');
const {createPcState,parseLast}=require('../src/pc-state.cjs');

test('only provider names and state words survive the sidecar line',()=>{
  assert.deepEqual(parseStates('{"ai":{"claude":"ready","codex":"missing"}}'),{claude:'ready',codex:'missing'});
  assert.deepEqual(parseStates('{"ai":{"claude":"ready","email":"x@example.invalid","codex":"weird"}}'),{claude:'ready'});
  for(const line of ['','not json','{"ai":[]}','{"ai":{"claude":"logged in"}}',null])assert.equal(parseStates(line),null);
  assert.deepEqual([...STATES],['ready','signed-out','missing','off','unsupported','error']);
});

function link(answers){
  const runs=[],reports=[],logs=[];let restarts=0,changes=0,clock=0;
  const ai=createAiLink({run:async(args,{timeoutMs})=>{runs.push([args,timeoutMs]);const a=answers.shift();if(a instanceof Error)throw a;return a;},
    restartChat:async()=>{restarts++;},report:(...a)=>reports.push(a),log:(...a)=>logs.push(a),changed:()=>{changes++;},now:()=>clock});
  return {ai,runs,reports,logs,restarts:()=>restarts,changes:()=>changes,tick:ms=>{clock+=ms;}};
}

test('refresh reads ai-status; a failed sidecar marks every provider as error and is reported',async()=>{
  const h=link([{code:0,last:'{"ai":{"claude":"signed-out","codex":"missing"}}'},new Error('agent-unavailable')]);
  assert.deepEqual((await h.ai.refresh()).providers,{claude:'signed-out',codex:'missing'});
  assert.deepEqual(h.runs[0][0],['ai-status']);
  assert.deepEqual((await h.ai.refresh(60000)).providers,{claude:'signed-out',codex:'missing'},'a young check is reused');
  assert.equal(h.runs.length,1);
  h.tick(60000);
  assert.deepEqual((await h.ai.refresh(60000)).providers,{claude:'error',codex:'error'});
  assert.deepEqual(h.reports,[['ai/status','unavailable']]);
});

test('connect runs the provider login through the sidecar, then restarts chat when ready',async()=>{
  const h=link([{code:0,last:'{"ai":{"claude":"ready"}}'}]);
  const view=await h.ai.connect('claude');
  assert.deepEqual(h.runs,[[['ai-connect','--provider','claude'],CONNECT_TIMEOUT_MS]]);
  assert.equal(view.providers.claude,'ready');assert.equal(view.connecting,null);
  assert.equal(h.restarts(),1);assert.deepEqual(h.reports,[]);
});

test('connect: one login at a time, unknown providers refused, a failed login reported and chat untouched',async()=>{
  let release;const pending=new Promise(r=>{release=r;});
  const h=link([pending]);
  const first=h.ai.connect('claude');
  assert.equal(h.ai.view().connecting,'claude');
  await assert.rejects(h.ai.connect('codex'),/busy/);
  await assert.rejects(h.ai.connect('gemini'),/input/);
  release({code:0,last:'{"ai":{"claude":"error"}}'});
  assert.equal((await first).providers.claude,'error');
  assert.equal(h.restarts(),0);assert.deepEqual(h.reports,[['ai/connect','error']]);
  const g=link([{code:1,last:'설정 오류: /Users/someone'}]);
  assert.equal((await g.ai.connect('claude')).providers.claude,'error');
  assert.deepEqual(g.reports,[['ai/connect','unavailable']]);
});

test('disconnect sets the local mark and restarts chat; signed-out stays signed-out (no login started)',async()=>{
  const h=link([{code:0,last:'{"ai":{"claude":"off"}}'},{code:0,last:'{"ai":{"claude":"signed-out"}}'}]);
  assert.equal((await h.ai.disconnect('claude')).providers.claude,'off');
  assert.deepEqual(h.runs[0][0],['ai-disconnect','--provider','claude']);
  assert.equal(h.restarts(),1);
  assert.equal((await h.ai.connect('claude')).providers.claude,'signed-out');
  assert.equal(h.restarts(),1,'not ready: no restart');
});

test('a chat restart that fails is logged, not thrown',async()=>{
  const ai=createAiLink({run:async()=>({code:0,last:'{"ai":{"claude":"ready"}}'}),restartChat:async()=>{throw new Error('busy');},
    log:()=>{},changed:()=>{}});
  assert.equal((await ai.connect('claude')).providers.claude,'ready');
});

test('the "이 PC" line keeps the last sync (time, kind, code) across a restart and drops anything else',()=>{
  let saved=null,changes=0;const store={load:()=>saved,save:r=>{saved=JSON.stringify(r);}};
  const pc=createPcState({store,connected:()=>true,syncing:()=>false,version:'0.1.7',now:()=>Date.parse('2026-11-13T00:00:00Z'),changed:()=>{changes++;}});
  assert.deepEqual(pc.view(),{version:'0.1.7',connected:true,syncing:false,lastSync:null});
  pc.record({kind:'rejected',code:'halt-policy',detail:'/Users/someone'});
  assert.deepEqual(pc.view().lastSync,{at:'2026-11-13T00:00:00.000Z',kind:'rejected',code:'halt-policy'});
  assert.equal(changes,1);assert.ok(!saved.includes('someone'));
  const again=createPcState({store,connected:()=>false,syncing:()=>true,version:'0.1.7'});
  assert.deepEqual(again.view(),{version:'0.1.7',connected:false,syncing:true,lastSync:{at:'2026-11-13T00:00:00.000Z',kind:'rejected',code:'halt-policy'}});
  assert.equal(parseLast('{"at":"x","kind":"ok"}'),null);
  assert.equal(parseLast('{"at":"2026-11-13T00:00:00Z","kind":"weird"}'),null);
  assert.deepEqual(parseLast('{"at":"2026-11-13T00:00:00Z","kind":"ok","code":"a b"}'),{at:'2026-11-13T00:00:00Z',kind:'ok',code:null});
});
