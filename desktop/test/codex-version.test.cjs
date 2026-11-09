'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {PassThrough}=require('node:stream');
const {checkCodexVersion}=require('../src/codex-version.cjs');
function fakeChild(){const c=new EventEmitter();c.stdout=new PassThrough();c.kill=()=>{};return c;}
const good={status:'unverified_newer',installed_version:'0.167.0',supported_versions:['0.166.0'],recommended_action:'update_mycrm'};
test('runs agent diagnostic with selected app home and returns validated version status',async()=>{
 const child=fakeChild();let args;
 const promise=checkCodexVersion({spawn:(...x)=>{args=x;return child;},binary:'/app/agent',home:'/app/data'});
 child.stdout.end(JSON.stringify(good));child.emit('close',0);
 assert.deepEqual(await promise,good);assert.deepEqual(args[1],['--home','/app/data','codex-version-status']);assert.equal(args[2].shell,false);
});
test('malformed, unbounded and nonzero diagnostics return a fixed unavailable result',async()=>{
 for(const [text,code] of [[JSON.stringify({...good,installed_version:'secret data'}),0],['x'.repeat(5000),0],['private error',1]]){
  const child=fakeChild();const promise=checkCodexVersion({spawn:()=>child,binary:'/app/agent',home:'/app/data'});
  child.stdout.write(text);child.emit('close',code);
  assert.deepEqual(await promise,{status:'unavailable',installed_version:null,supported_versions:[],recommended_action:'check_installation'});
 }
});
test('pre-release version remains visible and marked unverified',async()=>{
 const child=fakeChild();const promise=checkCodexVersion({spawn:()=>child,binary:'/app/agent',home:'/app/data'});
 const expected={status:'unverified_version',installed_version:'0.166.0-beta.1',supported_versions:['0.166.0'],recommended_action:'update_mycrm'};
 child.stdout.end(JSON.stringify(expected));child.emit('close',0);assert.deepEqual(await promise,expected);
});
