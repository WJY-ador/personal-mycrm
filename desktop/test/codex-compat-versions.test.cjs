'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {selectCandidates}=require('../scripts/codex-compat-versions.cjs');
const policy=(versions)=>JSON.stringify({payload:Buffer.from(JSON.stringify({versions:versions.map(version=>({version}))})).toString('base64')});
test('reprobes previous verified versions even when absent from newest releases',()=>{
 assert.deepEqual(selectCandidates(['0.170.0','0.171.0'],[policy(['0.167.0','0.168.0'])]),['0.167.0','0.168.0','0.170.0','0.171.0']);
});
test('deduplicates and orders mixed candidate sources',()=>{
 assert.deepEqual(selectCandidates(['0.170.0','0.169.0'],[policy(['0.170.0','0.168.0'])]),['0.168.0','0.169.0','0.170.0']);
});
test('rejects malformed or unbounded candidate policies without silently dropping versions',()=>{
 assert.throws(()=>selectCandidates(['0.170.0'],['bad']));
 assert.throws(()=>selectCandidates(['0.170.0'],[policy(Array.from({length:10},(_,i)=>`0.${i}.0`))]));
 assert.throws(()=>selectCandidates(['0.170.0'],[policy(['0.1.0;echo'])]));
});
