'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {issuePolicy, checkEvidence} = require('../scripts/codex-compat-issuer.cjs');
const {verifyPolicy} = require('../src/codex-compat-policy.cjs');
const pair = crypto.generateKeyPairSync('ed25519');
const now = 1780000000;
const payload = {schema:2,revision:4,issued_at:now,expires_at:now+3600,os:'darwin',arch:'arm64',min_app:'0.1.2',source_sha:'a'.repeat(40),config_sha256:'b'.repeat(64),versions:[{version:'0.166.0',native_sha256:'c'.repeat(64),host_sha256:'e'.repeat(64)},{version:'0.167.0',native_sha256:'c'.repeat(64),host_sha256:'e'.repeat(64)}]};
const probes=['find','read','write','decide','fileprobe','filecat','view','shell','patch','web','mcp','goal','node','resume','revoke'];
const sha='a'.repeat(40), digest='b'.repeat(64);
function evidence(version,arch='arm64') {return {source_sha:sha,version,os:'darwin',arch,package_sha256:digest,node_sha256:digest,native_sha256:'c'.repeat(64),host_sha256:'e'.repeat(64),archive_sha256:digest,config_sha256:digest,probes};}
test('evidence must cover exact signed versions, platform, source and all probes', () => {
 const receipts=[evidence('0.166.0'),evidence('0.167.0')];
 assert.doesNotThrow(()=>checkEvidence(payload,receipts,sha));
 assert.doesNotThrow(()=>checkEvidence({...payload,versions:[]},[],sha));
 for(const forged of [[evidence('0.166.0')],[evidence('0.166.0'),{...evidence('0.167.0'),source_sha:'c'.repeat(40)}],
                      [evidence('0.166.0'),{...evidence('0.167.0'),probes:['read']}],
                      [evidence('0.166.0'),evidence('0.167.0','x86_64')],
                      [evidence('0.166.0'),{...evidence('0.167.0'),package_sha256:'broken'}],
                      [evidence('0.166.0'),{...evidence('0.167.0'),native_sha256:'d'.repeat(64)}],
                      [evidence('0.166.0'),{...evidence('0.167.0'),config_sha256:'d'.repeat(64)}]]) {
  assert.throws(()=>checkEvidence(payload,forged,sha));
 }
});
test('issues a policy independently verified by the app', () => {
 const raw = issuePolicy(payload, {privateKey:pair.privateKey,keyId:'prod-1',now});
 const result=verifyPolicy(raw, {keys:{'prod-1':pair.publicKey},now,os:'darwin',arch:'arm64',appVersion:'0.1.2',configSha256:'b'.repeat(64),floor:{revision:0,digest:null}});
 assert.deepEqual(result.versions,payload.versions);
 assert.equal(JSON.parse(raw).key_id,'prod-1');
});
test('rejects invalid, expired and overlong policies', () => {
 for(const patch of [{expires_at:now},{issued_at:now+1},{expires_at:now+91*86400},{versions:['latest']},{extra:true}]) {
  assert.throws(()=>issuePolicy({...payload,...patch},{privateKey:pair.privateKey,keyId:'prod-1',now}));
 }
});
test('requires an Ed25519 private key and valid key identifier', () => {
 assert.throws(()=>issuePolicy(payload,{privateKey:pair.publicKey,keyId:'prod-1',now}));
 assert.throws(()=>issuePolicy(payload,{privateKey:crypto.generateKeyPairSync('rsa',{modulusLength:2048}).privateKey,keyId:'prod-1',now}));
 assert.throws(()=>issuePolicy(payload,{privateKey:pair.privateKey,keyId:'bad/id',now}));
});

test('issuer CLI prints a signed envelope without exposing key material', () => {
 const {spawnSync}=require('node:child_process');
 const fs=require('node:fs'), os=require('node:os'), path=require('node:path');
 const head=spawnSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).stdout.trim();
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'mycrm-evidence-'));
 for(const {version} of payload.versions) {
  const folder=path.join(dir,`codex-probe-arm64-${version}`); fs.mkdirSync(folder);
  fs.writeFileSync(path.join(folder,'compat-receipt.json'),JSON.stringify({...evidence(version),source_sha:head}));
 }
 const key=pair.privateKey.export({format:'pem',type:'pkcs8'}).toString();
 try { const child=spawnSync(process.execPath,[require.resolve('../scripts/codex-compat-issuer.cjs')],{
  input:JSON.stringify({...payload,source_sha:head,issued_at:Math.floor(Date.now()/1000)-1,expires_at:Math.floor(Date.now()/1000)+3600}),
  env:{...process.env,MYCRM_COMPAT_SIGNING_KEY:key,MYCRM_COMPAT_KEY_ID:'test-1',
       MYCRM_COMPAT_EVIDENCE_DIR:dir,GITHUB_ACTIONS:'true',GITHUB_REPOSITORY:'WJY-ador/personal-mycrm',
       GITHUB_REF:'refs/heads/main',GITHUB_EVENT_NAME:'workflow_dispatch',GITHUB_SHA:head},encoding:'utf8'
 });
 assert.equal(child.status,0); assert.equal(child.stderr,'');
 assert.equal(child.stdout.includes('PRIVATE KEY'),false);
 const nowReal=Math.floor(Date.now()/1000);
 const result=verifyPolicy(child.stdout.trim(),{keys:{'test-1':pair.publicKey},now:nowReal,os:'darwin',arch:'arm64',appVersion:'0.1.2',configSha256:'b'.repeat(64),floor:{revision:0,digest:null}});
 assert.deepEqual(result.versions,payload.versions);
 } finally {fs.rmSync(dir,{recursive:true,force:true});}
});
test('issuer CLI refuses invalid keys without printing input or secrets', () => {
 const {spawnSync}=require('node:child_process');
 const secret='synthetic-secret-do-not-print';
 const child=spawnSync(process.execPath,[require.resolve('../scripts/codex-compat-issuer.cjs')],{
  input:JSON.stringify(payload),env:{...process.env,MYCRM_COMPAT_SIGNING_KEY:secret,MYCRM_COMPAT_KEY_ID:'test-1'},encoding:'utf8'
 });
 assert.notEqual(child.status,0);
 assert.equal((child.stdout+child.stderr).includes(secret),false);
});
test('issuer CLI refuses signing without trusted CI evidence', () => {
 const {spawnSync}=require('node:child_process');
 const key=pair.privateKey.export({format:'pem',type:'pkcs8'}).toString();
 const child=spawnSync(process.execPath,[require.resolve('../scripts/codex-compat-issuer.cjs')],{
  input:JSON.stringify(payload), env:{...process.env,MYCRM_COMPAT_SIGNING_KEY:key,
    MYCRM_COMPAT_KEY_ID:'test-1',GITHUB_ACTIONS:'false'},encoding:'utf8'
 });
 assert.notEqual(child.status,0); assert.equal(child.stdout,'');
 assert.equal(child.stderr.includes('PRIVATE KEY'),false);
});
