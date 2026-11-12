'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {createConsentLockGuard}=require('../src/consent-lock-guard.cjs');

function monitor(){return Object.assign(new EventEmitter(),{getSystemIdleState:()=>'active'});}

test('JD2: lock and suspend only call onLock (cancel the window in flight); unlock and resume do nothing',()=>{
 const pm=monitor();let locks=0;
 const guard=createConsentLockGuard({powerMonitor:pm,platform:'darwin',onLock:()=>{locks++;}});
 assert.equal(guard.supported,true);
 pm.emit('lock-screen');pm.emit('suspend');assert.equal(locks,2);
 pm.emit('unlock-screen');pm.emit('resume');assert.equal(locks,2);
 assert.equal(typeof guard.canStart,'undefined','the guard no longer gates the chat start');
 guard.dispose();pm.emit('lock-screen');assert.equal(locks,2);
 assert.equal(pm.listenerCount('lock-screen'),0);assert.equal(pm.listenerCount('suspend'),0);
});

test('J-F6: an idle screen (no input for a second) never calls onLock',()=>{
 const pm=monitor();pm.getSystemIdleState=()=>'idle';let locks=0;
 createConsentLockGuard({powerMonitor:pm,platform:'darwin',onLock:()=>{locks++;}});
 assert.equal(locks,0);
});

test('a throwing onLock does not escape; unsupported platforms or a missing API subscribe nothing',()=>{
 const pm=monitor();
 createConsentLockGuard({powerMonitor:pm,platform:'win32',onLock:()=>{throw new Error('x');}});
 assert.doesNotThrow(()=>pm.emit('lock-screen'));
 const linux=monitor();
 assert.equal(createConsentLockGuard({powerMonitor:linux,platform:'linux',onLock:()=>{}}).supported,false);
 assert.equal(linux.listenerCount('lock-screen'),0);
 assert.equal(createConsentLockGuard({powerMonitor:{},platform:'darwin',onLock:()=>{}}).supported,false);
});
