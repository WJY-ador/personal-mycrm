'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { verifyPolicy } = require('../src/codex-compat-policy.cjs');
const keys = crypto.generateKeyPairSync('ed25519');
const now = 1780000000;
const base = {schema:2,revision:2,issued_at:now-1,expires_at:now+3600,os:'darwin',arch:'arm64',min_app:'0.1.2',source_sha:'a'.repeat(40),config_sha256:'b'.repeat(64),versions:[{version:'0.166.0',native_sha256:'c'.repeat(64),host_sha256:'e'.repeat(64)},{version:'0.167.0',native_sha256:'d'.repeat(64),host_sha256:'f'.repeat(64)}]};
function envelope(payload=base, key=keys.privateKey){
 const data=Buffer.from(JSON.stringify(payload));
 return JSON.stringify({key_id:'test-1',payload:data.toString('base64'),signature:crypto.sign(null,data,key).toString('base64')});
}
function opts(overrides={}){ return {keys:{'test-1':keys.publicKey},now,os:'darwin',arch:'arm64',appVersion:'0.1.2',configSha256:'b'.repeat(64),floor:{revision:0,digest:null},...overrides}; }
test('valid signed policy provides versions and durable rollback checkpoint',()=>{
 const x=verifyPolicy(envelope(),opts());
 assert.deepEqual(x.versions,base.versions); assert.equal(x.checkpoint.revision,2); assert.match(x.checkpoint.digest,/^[0-9a-f]{64}$/);
});
test('rejects forged signatures, unknown keys and incorrect platform',()=>{
 assert.throws(()=>verifyPolicy(envelope(base,crypto.generateKeyPairSync('ed25519').privateKey),opts()));
 assert.throws(()=>verifyPolicy(envelope(),opts({keys:{}})));
 assert.throws(()=>verifyPolicy(envelope(),opts({arch:'x64'})));
 assert.throws(()=>verifyPolicy(envelope(),opts({configSha256:'f'.repeat(64)})));
});
test('rejects expired, future, prolonged, app-incompatible and malformed policies',()=>{
 for(const patch of [{expires_at:now},{issued_at:now+1},{expires_at:now+91*86400},{min_app:'0.2.0'},{versions:['0.167.0;evil']},{versions:['0.167.0','0.167.0']},{extra:true}]){
  assert.throws(()=>verifyPolicy(envelope({...base,...patch}),opts()));
 }
});
test('rejects rollback and same revision equivocation',()=>{
 assert.throws(()=>verifyPolicy(envelope(),opts({floor:{revision:3,digest:'a'.repeat(64)}})));
 assert.throws(()=>verifyPolicy(envelope(),opts({floor:{revision:2,digest:'a'.repeat(64)}})));
 const x=verifyPolicy(envelope(),opts());
 assert.deepEqual(verifyPolicy(envelope(),opts({floor:x.checkpoint})),x);
});
test('rejects missing rollback state, huge payload and unexpected envelope fields',()=>{
 assert.throws(()=>verifyPolicy(envelope(),opts({floor:null})));
 assert.throws(()=>verifyPolicy('x'.repeat(20000),opts()));
 const v=JSON.parse(envelope());v.extra=1;assert.throws(()=>verifyPolicy(JSON.stringify(v),opts()));
});

test('a signed empty version list revokes every CLI version',()=>{
 const result=verifyPolicy(envelope({...base,versions:[]}),opts());
 assert.deepEqual(result.versions,[]);
});

test('durable policy checkpoint rejects rollback after reopening state',()=>{
 const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
 const {acceptPolicy}=require('../src/codex-compat-policy.cjs');
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'mycrm-policy-test-'));
 try{
  const first=acceptPolicy(envelope(),opts(),dir);
  assert.deepEqual(first.versions,base.versions);
  assert.throws(()=>acceptPolicy(envelope({...base,revision:1}),opts(),dir));
  assert.deepEqual(acceptPolicy(envelope(),opts(),dir).versions,base.versions);
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});

test('durable policy checkpoint fails closed on malformed state after initialization',()=>{
 const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
 const {acceptPolicy}=require('../src/codex-compat-policy.cjs');
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'mycrm-policy-test-'));
 try{
  acceptPolicy(envelope(),opts(),dir);
  fs.writeFileSync(path.join(dir,'policy-checkpoint.json'),'not json');
  assert.throws(()=>acceptPolicy(envelope({...base,revision:3}),opts(),dir));
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});

test('concurrent checkpoint access fails closed',()=>{
 const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
 const {acceptPolicy}=require('../src/codex-compat-policy.cjs');
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'mycrm-policy-test-'));
 try{
  fs.mkdirSync(path.join(dir,'.policy-checkpoint.lock'));
  assert.throws(()=>acceptPolicy(envelope(),opts(),dir));
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});

test('checkpoint file symlink fails closed',()=>{
 const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
 const {acceptPolicy}=require('../src/codex-compat-policy.cjs');
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'mycrm-policy-test-'));
 try{
  fs.writeFileSync(path.join(dir,'other'),JSON.stringify({revision:0,digest:null}));
  fs.symlinkSync(path.join(dir,'other'),path.join(dir,'policy-checkpoint.json'));
  assert.throws(()=>acceptPolicy(envelope(),opts(),dir));
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});
