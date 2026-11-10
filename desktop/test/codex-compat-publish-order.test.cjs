'use strict';
const test=require('node:test'), assert=require('node:assert/strict');
const {publishDecision}=require('../scripts/codex-compat-publish-order.cjs');
function doc(revision, value='x') {return JSON.stringify({key_id:'k',payload:Buffer.from(JSON.stringify({revision,value})).toString('base64'),signature:'s'});}
test('older rerun cannot replace newer policy',()=>{
 assert.equal(publishDecision(doc(10),doc(11)),false);
 assert.equal(publishDecision(doc(12),doc(11)),true);
});
test('same revision is idempotent but differing data is rejected',()=>{
 assert.equal(publishDecision(doc(11),doc(11)),false);
 assert.throws(()=>publishDecision(doc(11,'other'),doc(11)));
 assert.throws(()=>publishDecision(doc(11),'invalid'));
});
