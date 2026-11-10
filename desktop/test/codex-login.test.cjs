'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {PassThrough}=require('node:stream');
const {createCodexLogin}=require('../src/codex-login.cjs');

function child(){const c=new EventEmitter();c.stdin=new PassThrough();c.stdout=new PassThrough();c.kill=()=>true;return c;}

test('login remains unavailable unless explicitly enabled',()=>{
  let spawned=false;const login=createCodexLogin({spawn:()=>{spawned=true;},binary:'/agent',home:'/private'});
  assert.deepEqual(login.start(),{status:'unavailable'});assert.equal(spawned,false);
});

test('reports fixed status only and cancellation goes to the private child',async()=>{
  const c=child(),states=[];let sent='';c.stdin.on('data',v=>{sent+=v.toString();});
  const login=createCodexLogin({enabled:true,spawn:()=>c,binary:'/agent',home:'/private',onChange:s=>states.push(s)});
  assert.deepEqual(login.start(),{status:'starting'});
  c.stdout.write('{"status":"waiting"}\n');
  assert.equal(login.view().status,'waiting');login.cancel();
  assert.equal(sent,'cancel\n');
  c.stdout.write('{"status":"cancelled"}\n');c.emit('close',0);
  assert.equal(login.view().status,'cancelled');assert.deepEqual(states,['starting','waiting','cancelled']);
});

test('rejects and does not expose unexpected child output',()=>{
  const c=child(),states=[];const login=createCodexLogin({enabled:true,spawn:()=>c,binary:'/agent',home:'/private',onChange:s=>states.push(s)});
  login.start();c.stdout.write('{"status":"waiting","url":"https://example.invalid/private"}\n');
  c.stdout.write('{"status":"completed"}\n');
  assert.equal(login.view().status,'error');assert.equal(JSON.stringify(states).includes('https://'),false);
});

test('closing rejects if child does not confirm exit',async()=>{
  const c=child();let killed=false;c.kill=()=>{killed=true;};
  const login=createCodexLogin({enabled:true,spawn:()=>c,binary:'/agent',home:'/private',closeTimeoutMs:10});
  login.start();await assert.rejects(login.close(),/login-stop-unconfirmed/);
  assert.equal(killed,false);assert.equal(login.view().status,'error');
});
