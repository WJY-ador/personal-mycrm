const {test}=require('node:test');const assert=require('node:assert/strict');const {EventEmitter}=require('node:events');
const {Supervisor}=require('../src/supervisor.cjs');
function fake(){const c=new EventEmitter();c.stdout=new EventEmitter();c.stderr=new EventEmitter();c.stdin=new EventEmitter();c.stdin.end=input=>{c.input=input;setImmediate(()=>c.emit('close',0,null));};c.kill=()=>c.emit('close',null,'SIGTERM');return c;}
function setup(options={}){const calls=[];const s=new Supervisor({binary:'/bundle/agent',home:'/user/data',spawn:(...a)=>{const c=fake();calls.push({args:a,child:c});return c;},restartDelay:10,stopGrace:100,...options});return {s,calls};}
const delay=ms=>new Promise(r=>setTimeout(r,ms));
test('single child per role, no shell and CLI consent isolated to intended jobs process',async()=>{
 const {s,calls}=setup();s.start('viewer',['serve']);s.start('viewer',['serve']);assert.equal(calls.length,1);assert.equal(calls[0].args[2].shell,false);assert.equal(calls[0].args[2].env.MYCRM_JOBS_ALLOW_REAL_CLI,undefined);
 s.start('jobs',['serve','--jobs'],{allowCli:true});assert.equal(calls[1].args[2].env.MYCRM_JOBS_ALLOW_REAL_CLI,'1');assert.deepEqual(calls[1].args[1],['--home','/user/data','serve','--jobs']);await s.stopAll();
});
test('manual stop cancels restart backoff and sends graceful control without restarting',async()=>{
 const {s,calls}=setup();s.start('jobs',['serve','--jobs']);calls[0].child.emit('close',null,'SIGABRT');assert.equal(s.snapshot().jobs.state,'retry-wait');await s.stop('jobs');await delay(25);assert.equal(calls.length,1);
 s.start('jobs',['serve','--jobs']);const c=calls.at(-1).child;await s.stop('jobs');assert.equal(c.input,'{"command":"stop"}\n');assert.equal(s.snapshot().jobs.state,'stopped');
});
test('authentication/config errors never enter automatic restart loop',async()=>{
 for(const code of [0,1,3]){const {s,calls}=setup();s.start('jobs',['serve','--jobs']);calls[0].child.emit('close',code,null);await delay(25);assert.equal(calls.length,1);assert.equal(s.snapshot().jobs.state,code===3?'authentication-required':code===1?'failed':'stopped');}
});
test('unexpected crashes have bounded recovery and app shutdown prevents new children',async()=>{
 const {s,calls}=setup({restartDelay:1});s.start('viewer',['serve']);
 for(let i=0;i<4;i++){calls.at(-1).child.emit('close',null,'SIGABRT');await delay(8);}
 assert.equal(calls.length,4);await s.stopAll({closing:true});assert.throws(()=>s.start('viewer',['serve']),/closing/);
});
