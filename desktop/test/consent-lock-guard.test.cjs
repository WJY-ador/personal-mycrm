'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {createConsentLockGuard}=require('../src/consent-lock-guard.cjs');

function monitor(state='active'){
 const e=new EventEmitter();e.getSystemIdleState=()=>state;return e;
}

test('lock and suspend immediately invalidate and stop; unlock/resume only restores availability after revoke succeeds',async()=>{
 const pm=monitor(),calls=[];
 const guard=createConsentLockGuard({powerMonitor:pm,platform:'darwin',onLock:async()=>{calls.push('invalidate');return true;}});
 assert.equal(guard.canStart(),true);
 pm.emit('lock-screen');
 assert.equal(guard.canStart(),false);
 await guard.whenSettled();
 pm.emit('unlock-screen');
 assert.equal(guard.canStart(),true);
 pm.emit('suspend');
 assert.equal(guard.canStart(),false);
 await guard.whenSettled();
 pm.emit('resume');
 assert.equal(guard.canStart(),true);
 assert.deepEqual(calls,['invalidate','invalidate']);
 guard.dispose();
});

test('unknown lock state, failed revoke and unsupported platforms remain unavailable',async()=>{
 const pm=monitor('unknown');
 const unknown=createConsentLockGuard({powerMonitor:pm,platform:'win32',onLock:async()=>false});
 assert.equal(unknown.canStart(),false);
 pm.getSystemIdleState=()=> 'active';
 pm.emit('lock-screen');await unknown.whenSettled();pm.emit('unlock-screen');
 assert.equal(unknown.canStart(),false,'a failed server key revoke must keep provider work blocked');
 unknown.dispose();
 const linux=createConsentLockGuard({powerMonitor:monitor(),platform:'linux',onLock:()=>true});
 assert.equal(linux.supported,false);
 assert.equal(linux.canStart(),false);
 linux.dispose();
});

test('missing lock signal API fails closed',()=>{
 const guard=createConsentLockGuard({powerMonitor:{getSystemIdleState:()=> 'active'},platform:'darwin',onLock:()=>true});
 assert.equal(guard.supported,false);
 assert.equal(guard.canStart(),false);
 guard.dispose();
});

test('unlock retries an unconfirmed server revoke before chat may start',async()=>{
 const pm=monitor();let attempts=0;
 const guard=createConsentLockGuard({powerMonitor:pm,platform:'win32',onLock:async()=>++attempts>1});
 pm.emit('suspend');await guard.whenSettled();
 pm.emit('resume');await guard.whenSettled();
 assert.equal(attempts,2);
 assert.equal(guard.canStart(),true);
 guard.dispose();
});

test('lock and suspend arriving together share one invalidation operation',async()=>{
 const pm=monitor();let calls=0,finish;
 const guard=createConsentLockGuard({powerMonitor:pm,platform:'darwin',onLock:()=>{calls++;return new Promise(resolve=>{finish=resolve;});}});
 pm.emit('lock-screen');pm.emit('suspend');
 assert.equal(calls,1);
 finish(true);await guard.whenSettled();
 pm.emit('unlock-screen');assert.equal(guard.canStart(),true);
 guard.dispose();
});
