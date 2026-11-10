'use strict';
const test=require('node:test'), assert=require('node:assert/strict');
const {selectVerifiedVersions}=require('../scripts/codex-compat-evidence-select.cjs');
test('a failing new CLI does not block a verified prior CLI',()=>{
 assert.deepEqual(selectVerifiedVersions(['0.166.0','0.168.0'], (arch,v)=>v==='0.166.0'),['0.166.0']);
});
test('a version must pass for both Mac architectures and empty evidence fails closed',()=>{
 assert.throws(()=>selectVerifiedVersions(['0.166.0'], (arch)=>arch==='arm64'));
 assert.throws(()=>selectVerifiedVersions(['latest'],()=>true));
});
