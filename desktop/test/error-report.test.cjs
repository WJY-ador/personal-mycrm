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

test('the report body has the fixed fields; stage and code come from fixed forms only',()=>{
  const env={version:'0.1.7',platform:'darwin',now:()=>NOW};
  assert.deepEqual(buildReport('sync/run-once','command-timeout',{exit:-1,status:503},env),{source:'desktop',stage:'sync/run-once',
    code:'command-timeout',app_version:'0.1.7',os:'mac',occurred_at:'2026-11-13T02:03:04Z',http_status:503,exit_code:-1});
  assert.equal(buildReport('update/error','network',{},{...env,platform:'win32'}).os,'win');
  assert.equal(buildReport('ai/status','unavailable',{exit:'x',status:1e6},env).exit_code,undefined);
  for(const [stage,code] of [['other','x'],['sync/run-once','/Users/someone/x'],['sync/run-once','has space'],
    ['sync/run-once','x'.repeat(41)],['sync/run-once',null],['sync/run-once','https://x.example']]){
    assert.equal(buildReport(stage,code,{},env),null,stage+' '+code);
  }
  assert.ok(STAGES.includes('connect/auto')&&STAGES.includes('ai/connect')&&STAGES.includes('agent/chat'));
});

function reporter(status=202){
  const sent=[],logs=[];let clock=NOW;
  const r=createReporter({request:async(method,url,body,headers)=>{sent.push({method,url,body,headers});
    if(status instanceof Error)throw status;return {status,body:{secret:'server text'}};},
    hosted:HOSTED,version:'0.1.7',platform:'darwin',log:(...a)=>logs.push(a),now:()=>clock});
  return {r,sent,logs,tick:ms=>{clock+=ms;}};
}

test('a report is one POST with the session origin; the same stage and code is spaced, others are not',async()=>{
  const h=reporter();
  assert.equal(await h.r.report('connect/auto','DEVICE-LIMIT'),true);
  assert.equal(h.sent[0].method,'POST');assert.equal(h.sent[0].url,new URL(ERROR_REPORT_PATH,HOSTED).href);
  assert.equal(h.sent[0].headers.Origin,'https://crm.example.invalid');
  assert.equal(await h.r.report('connect/auto','DEVICE-LIMIT'),false,'spaced');
  assert.equal(await h.r.report('connect/auto','FAILED'),true,'another code');
  h.tick(REPEAT_MS);assert.equal(await h.r.report('connect/auto','DEVICE-LIMIT'),true);
  assert.equal(h.sent.length,3);
  assert.deepEqual(h.logs,[['report','sent',202],['report','sent',202],['report','sent',202]]);
});

test('no session, a refusal or a network failure drops the report silently and never retries',async()=>{
  for(const status of [401,500,new Error('/Users/someone/token-abc')]){
    const h=reporter(status);
    assert.equal(await h.r.report('update/error','network'),false);
    assert.equal(await h.r.report('update/error','network'),false);
    assert.equal(h.sent.length,1,'no retry');
    assert.ok(!JSON.stringify(h.logs).includes('someone'));
  }
  const h=reporter();
  assert.equal(await h.r.report('sync/run-once','/Users/someone/file.jsonl'),false);
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
