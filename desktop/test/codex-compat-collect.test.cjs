'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {choosePolicies} = require('../scripts/codex-compat-collect.cjs');
function policy(minApp, native = 'a'.repeat(64)) {
 const data = {schema:2,arch:'arm64',os:'darwin',min_app:minApp,config_sha256:'b'.repeat(64),versions:[{version:'0.167.0',native_sha256:native,host_sha256:'c'.repeat(64)}]};
 return JSON.stringify({key_id:'key',payload:Buffer.from(JSON.stringify(data)).toString('base64'),signature:'synthetic'});
}
test('identical configurations keep oldest supported app version',()=>{
 const name='darwin-arm64-'+'b'.repeat(64)+'.json';
 const result=choosePolicies([{name,data:policy('0.2.0')},{name,data:policy('0.1.2')}]);
 assert.equal(JSON.parse(Buffer.from(JSON.parse(result.get(name)).payload,'base64')).min_app,'0.1.2');
});
test('conflicting digest is omitted without blocking an unrelated valid source',()=>{
 const name='darwin-arm64-'+'b'.repeat(64)+'.json';
 const good=JSON.stringify({...JSON.parse(policy('0.1.2')),payload:Buffer.from(JSON.stringify({schema:2,arch:'x64',os:'darwin',min_app:'0.1.2',config_sha256:'e'.repeat(64),versions:[{version:'0.167.0',native_sha256:'a'.repeat(64),host_sha256:'c'.repeat(64)}]})).toString('base64')});
 const validName='darwin-x64-'+'e'.repeat(64)+'.json';
 const result=choosePolicies([{name,data:policy('0.2.0')},{name,data:policy('0.1.2','d'.repeat(64))},{name:validName,data:good}]);
 assert.equal(result.has(name),false);
 assert.equal(result.has(validName),true);
});
