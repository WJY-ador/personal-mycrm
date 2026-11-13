'use strict';
// Automatic error report from the app (spec 2026-11-13 §1.4) and the failure kinds the person reads (failures.cjs).
// The body carries fixed fields only: no error text, path, URL, token or record content reaches it or desktop.log.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {createReporter,buildReport,STAGES,REPEAT_MS}=require('../src/error-report.cjs');
const {classify,syncOutcome,message}=require('../src/failures.cjs');
const {ConnectError}=require('../src/connector.cjs');
const {ERROR_REPORT_PATH}=require('../src/desktop-contract.cjs');

const HOSTED='https://crm.example.invalid/';
const NOW=Date.parse('2026-11-13T02:03:04.567Z');

test('the report body follows the contract; unknown stages are dropped and malformed codes become unknown',()=>{
  const env={version:'0.1.7',platform:'darwin',now:()=>NOW};
  assert.deepEqual(buildReport('sync/run-once','command-timeout',{},env),{source:'app',stage:'sync/run-once',
    code:'command-timeout',app_version:'0.1.7',os:'mac',occurred_at:'2026-11-13T02:03:04Z',count:1});
  assert.equal(buildReport('update/error','network',{},{...env,platform:'win32'}).os,'win');
  assert.equal(buildReport('update/error','network',{},{...env,platform:'linux'}).os,'other');
  assert.equal(buildReport('sync/connect','DEVICE-LIMIT',{source:'agent'},env).source,'agent');
  assert.equal(buildReport('sync/connect','x',{source:'web'},env),null);
  for(const code of ['/Users/someone/x','has space','x'.repeat(49),null,'a.b','https://x.example']){
    assert.equal(buildReport('sync/run-once',code,{},env).code,'unknown',String(code));
  }
  assert.equal(buildReport('other','x',{},env),null);
  const STAGE=/^[a-z][a-z0-9-]{0,23}(\/[a-z0-9-]{1,32}){0,2}$/;
  for(const stage of STAGES)assert.match(stage,STAGE);
  assert.ok(Buffer.byteLength(JSON.stringify(buildReport('agent/chat','authentication-required',{},env)))<=2048);
});

function reporter(...statuses){
  const sent=[],logs=[];let clock=NOW;
  const r=createReporter({request:async(method,url,body,headers)=>{sent.push({method,url,body,headers});
    const status=statuses[Math.min(sent.length-1,statuses.length-1)];
    if(status instanceof Error)throw status;return {status,body:{accepted:true,state:'created',secret:'server text'}};},
    hosted:HOSTED,version:'0.1.7',platform:'darwin',log:(...a)=>logs.push(a),now:()=>clock});
  return {r,sent,logs,tick:ms=>{clock+=ms;}};
}

test('a report is one POST to /desktop/error-reports with the session origin; repeats in one run are spaced',async()=>{
  const h=reporter(200);
  assert.equal(await h.r.report('connect/auto','DEVICE-LIMIT'),true);
  assert.equal(h.sent[0].method,'POST');assert.equal(h.sent[0].url,'https://crm.example.invalid/desktop/error-reports');
  assert.equal(ERROR_REPORT_PATH,'/desktop/error-reports');
  assert.equal(h.sent[0].headers.Origin,'https://crm.example.invalid');
  assert.equal(await h.r.report('connect/auto','DEVICE-LIMIT'),false,'spaced');
  assert.equal(await h.r.report('connect/auto','FAILED'),true,'another code');
  h.tick(REPEAT_MS);assert.equal(await h.r.report('connect/auto','DEVICE-LIMIT'),true);
  assert.equal(h.sent.length,3);
  assert.deepEqual(h.logs,[['report','sent',200],['report','sent',200],['report','sent',200]]);
});

test('a network failure or 5xx is sent once more; 4xx and 429 are not; nothing is reported about a report',async()=>{
  for(const [statuses,ok,tries] of [[[new Error('/Users/someone/token-abc'),200],true,2],[[503,503],false,2],
    [[401],false,1],[[403],false,1],[[429],false,1],[[400],false,1]]){
    const h=reporter(...statuses);
    assert.equal(await h.r.report('update/error','network'),ok,JSON.stringify(statuses));
    assert.equal(h.sent.length,tries,JSON.stringify(statuses));
    assert.ok(!JSON.stringify(h.logs).includes('someone'));
  }
  const h=reporter(200);
  assert.equal(await h.r.report('not/a-stage','x'),false);
  assert.equal(h.sent.length,0);assert.deepEqual(h.logs,[['report','invalid']]);
});

test('failure kinds: lock, disconnected, login, refused with its code, unknown — never the error text',()=>{
  assert.deepEqual(classify(new Error('busy')),{kind:'busy',code:null});
  assert.deepEqual(classify(new ConnectError('login')),{kind:'login',code:null});
  assert.deepEqual(classify(new ConnectError('revoked')),{kind:'disconnected',code:null});
  assert.deepEqual(classify(new ConnectError('limit')),{kind:'rejected',code:'DEVICE-LIMIT'});
  assert.deepEqual(classify(new ConnectError('name')),{kind:'rejected',code:'NAME-REQUIRED'});
  assert.deepEqual(classify(new ConnectError('failed','RATE-LIMIT')),{kind:'rejected',code:'RATE-LIMIT'});
  assert.deepEqual(classify(new ConnectError('failed','bad code /x')),{kind:'rejected',code:'FAILED'});
  assert.deepEqual(classify(new Error('command-timeout')),{kind:'unknown',code:'command-timeout'});
  assert.deepEqual(classify(new Error('/Users/someone/secret')),{kind:'unknown',code:'error'});
  assert.deepEqual(classify(null),{kind:'unknown',code:'error'});
});

test('run-once outcome: halts by their fixed word, other exits by number',()=>{
  assert.deepEqual(syncOutcome({code:0}),{kind:'ok',code:null});
  assert.deepEqual(syncOutcome({code:3,detail:'… `run-once --resume policy` 로 다시 시작하세요.'}),{kind:'rejected',code:'halt-policy'});
  assert.deepEqual(syncOutcome({code:3,detail:'--resume /etc/passwd'}),{kind:'rejected',code:'halt'});
  assert.deepEqual(syncOutcome({code:1,detail:'실행 멈춤: /Users/someone'}),{kind:'unknown',code:'exit-1'});
  assert.deepEqual(syncOutcome({code:-1}),{kind:'unknown',code:'exit-signal'});
  assert.deepEqual(syncOutcome({code:null}),{kind:'unknown',code:'exit'});
});

test('the notification text is fixed per kind and shows the code for refused and unknown',()=>{
  assert.equal(message({kind:'busy'}),'다른 작업이 진행 중이에요. 잠시 뒤 다시 시도해 주세요.');
  assert.match(message({kind:'login'}),/로그인이 필요해요/);
  assert.match(message({kind:'disconnected'}),/연결이 끊겼어요/);
  assert.equal(message({kind:'rejected',code:'halt-policy'}),'서버가 요청을 거절했어요(코드 halt-policy).');
  assert.equal(message({kind:'unknown',code:'/Users/x'}),'알 수 없는 이유로 완료하지 못했어요(코드 없음).');
  assert.equal(message({kind:'other'}),'알 수 없는 이유로 완료하지 못했어요(코드 없음).');
});
