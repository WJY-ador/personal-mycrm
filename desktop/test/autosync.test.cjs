'use strict';
// Automatic sync (spec 2026-11-13 §5): 2 minutes after the app opens, then every 60 minutes; skipped while the user
// stopped the device, this PC is not connected, or another command holds the app. Fake timers drive the clock.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {AutoSync,FIRST_MS,EVERY_MS}=require('../src/autosync.cjs');

const MIN=60*1000;
function fakeTimers(){
 let now=0,seq=0;const queue=new Map();
 const flush=()=>new Promise(r=>setImmediate(r));
 return {
  setTimeout:(fn,ms)=>{const id=++seq;queue.set(id,{at:now+ms,fn});return id;},
  clearTimeout:id=>{queue.delete(id);},
  pending:()=>queue.size,
  now:()=>now,
  async advance(ms){
   const end=now+ms;
   for(;;){
    const next=[...queue.entries()].sort((a,b)=>a[1].at-b[1].at||a[0]-b[0])[0];
    if(!next||next[1].at>end)break;
    queue.delete(next[0]);now=next[1].at;next[1].fn();await flush();await flush();
   }
   now=end;await flush();
  },
 };
}
// The gates main.cjs wires: wanted (not stopped by the user), connected, idle (no other command holds the app).
function rig({run}={}){
 const timers=fakeTimers(),logs=[],runs=[];
 const state={wanted:true,connected:true,busy:false};
 const sync=new AutoSync({wanted:()=>state.wanted,connected:()=>state.connected,idle:()=>!state.busy,
  run:run||(async()=>{runs.push(timers.now()/MIN);}),log:(component,event)=>logs.push(component+':'+event),timers});
 return {timers,logs,runs,state,sync};
}

test('first sync 2 minutes after start, then every 60 minutes',async()=>{
 const r=rig();r.sync.start();
 assert.equal(FIRST_MS,2*MIN);assert.equal(EVERY_MS,60*MIN);
 await r.timers.advance(2*MIN-1);assert.deepEqual(r.runs,[]);
 await r.timers.advance(1);assert.deepEqual(r.runs,[2]);
 await r.timers.advance(59*MIN);assert.deepEqual(r.runs,[2],'not before the hour');
 await r.timers.advance(1*MIN);assert.deepEqual(r.runs,[2,62]);
 await r.timers.advance(120*MIN);assert.deepEqual(r.runs,[2,62,122,182]);
 assert.deepEqual(r.logs.slice(0,2),['sync:auto','sync:auto']);
 r.sync.start();assert.equal(r.timers.pending(),1,'start twice keeps one timer');
});

test('skips while stopped, not connected or busy, and waits for the next period',async()=>{
 const r=rig();r.sync.start();
 r.state.wanted=false;await r.timers.advance(2*MIN);
 r.state.wanted=true;await r.timers.advance(30*MIN);
 assert.deepEqual(r.runs,[],'a skipped tick is not retried early');
 r.state.connected=false;await r.timers.advance(30*MIN);
 r.state.connected=true;r.state.busy=true;await r.timers.advance(60*MIN);
 r.state.busy=false;await r.timers.advance(60*MIN);
 assert.deepEqual(r.runs,[182]);
 assert.deepEqual(r.logs,['sync:auto-skipped-stopped','sync:auto-skipped-not-connected','sync:auto-skipped-busy','sync:auto']);
});

test('a failed run is tried again on the next period; a lock taken meanwhile counts as busy',async()=>{
 const outcomes=['fail','busy','ok'];const seen=[];
 const r=rig({run:async()=>{const o=outcomes.shift();seen.push(o);if(o==='fail')throw new Error('agent-unavailable');if(o==='busy')throw new Error('busy');}});
 r.sync.start();await r.timers.advance(122*MIN);
 assert.deepEqual(seen,['fail','busy','ok']);
 assert.deepEqual(r.logs,['sync:auto','sync:auto-failed','sync:auto','sync:auto-skipped-busy','sync:auto']);
});

test('a run still in flight makes the next tick skip',async()=>{
 let release;const r=rig({run:()=>new Promise(res=>{release=res;})});
 r.sync.start();await r.timers.advance(2*MIN);
 await r.timers.advance(60*MIN);
 assert.deepEqual(r.logs,['sync:auto','sync:auto-skipped-busy']);
 release();await new Promise(r=>setImmediate(r));await r.timers.advance(60*MIN);
 assert.deepEqual(r.logs,['sync:auto','sync:auto-skipped-busy','sync:auto']);
});

test('a gate that throws counts as busy; dispose stops the schedule',async()=>{
 const r=rig();r.sync.idle=()=>{throw new Error('x');};
 assert.equal(await r.sync.tick(),'busy');
 r.sync.idle=()=>true;r.sync.start();r.sync.dispose();
 assert.equal(r.timers.pending(),0);
 await r.timers.advance(300*MIN);assert.deepEqual(r.runs,[]);
 assert.equal(await r.sync.tick(),'disposed');
});

test('main wires the automatic sync to the button sync, never connects by itself, stops it on quit',()=>{
 const main=fs.readFileSync(path.join(__dirname,'..','src','main.cjs'),'utf8');
 assert.match(main,/register\('sync',\(\)=>exclusively\(\(\)=>syncOnce\(\)\)\);/);
 assert.match(main,/run:\(\)=>exclusively\(\(\)=>syncOnce\(\{auto:true\}\)\)/);
 assert.match(main,/wanted:\(\)=>prefs\.autoRun!==false,connected:\(\)=>ready&&connection\(\)\.connected&&!connector\.needsAuto\(\)/);
 assert.match(main,/idle:\(\)=>!busy&&!quitting&&!installing/);
 assert.match(main,/if\(connector\.needsAuto\(\)\)\{if\(auto\)throw new Error\('not-connected'\);/);
 assert.match(main,/if\(!auto&&code===3&&/);
 assert.match(main,/log\('sync','completed',code\)/);
 assert.match(main,/autosync\.start\(\);/);
 assert.match(main,/clearInterval\(pollTimer\);autosync\?\.dispose\(\);/);
});
