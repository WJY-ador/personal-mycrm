'use strict';
// Automatic start when the app opens. The gates are the real ones: startConnection and startProcesses (the same calls as
// the tray's start), the real Supervisor with a fake spawn. Chat starts as main.cjs starts it: no consent bridge
// (spec 2026-11-13 §1.3), and a screen lock neither holds nor stops it.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {AutoRun,readPreferences,startConnection,startAutomatically,MAX_ATTEMPTS}=require('../src/autorun.cjs');
const {Supervisor}=require('../src/supervisor.cjs');

function fakeChild(){const c=new EventEmitter();c.stdout=new EventEmitter();c.stderr=new EventEmitter();c.stdin=new EventEmitter();
 c.stdin.end=()=>setImmediate(()=>c.emit('close',0,null));c.kill=()=>c.emit('close',null,'SIGTERM');return c;}
// A small app: the same pieces main.cjs wires, minus Electron.
function app({saved='{}',connected=true,cliConfigured=false,chatFails=null,ready=true}={}){
 const spawned=[],logs=[],writes=[];
 const supervisor=new Supervisor({binary:'/bundle/agent',home:'/user/data',spawn:(_b,args)=>{spawned.push(args.slice(2).join(' '));return fakeChild();}});
 const state={connected,cliConfigured,busy:false,quitting:false,ready};
 // main.cjs startChatAgent: supervisor.start('chat',['chat']). chatFails makes it throw like a failed spawn setup.
 const startChat=async()=>{if(chatFails)throw new Error(chatFails);supervisor.start('chat',['chat']);};
 let prefs=readPreferences(saved);
 const connection=()=>({connected:state.connected,cliConfigured:state.cliConfigured});
 const deps={supervisor,prefs:()=>prefs,connection,ready:()=>state.ready,startChat};
 // Like main.cjs: taking and releasing the app lock reports a change, and a change nudges the automatic start.
 async function exclusively(fn){if(state.busy||state.quitting)throw new Error('busy');state.busy=true;autorun.nudge('change');
  try{return await fn();}finally{state.busy=false;autorun.nudge('change');}}
 const queue=[];
 const autorun=new AutoRun({wanted:()=>prefs.autoRun!==false,connected:()=>connection().connected,idle:()=>!state.busy&&!state.quitting,
  start:()=>exclusively(()=>startAutomatically(deps)),remember:value=>{prefs.autoRun=value;writes.push(JSON.stringify(prefs));},
  log:(component,event)=>logs.push(component+':'+event),defer:fn=>queue.push(fn)});
 // Runs deferred checks until none are left (a check may queue another one).
 async function settle(){while(queue.length){queue.shift()();await new Promise(r=>setImmediate(r));}}
 // The handlers main.cjs gives the tray (start, stop) and its quit.
 const button={
  start:()=>exclusively(async()=>{await startConnection(deps);autorun.manualStarted();}),
  stop:()=>exclusively(async()=>{autorun.userStopped();await supervisor.stopAll();}),
  quit:async()=>{state.quitting=true;await supervisor.stopAll({closing:true});},
 };
 return {autorun,state,spawned,logs,writes,prefs:()=>prefs,settle,button,supervisor,deps};
}

test('no saved preference and a connected PC: starts once on open, through the same start as the button',async()=>{
 const a=app();
 a.autorun.nudge('startup');await a.settle();
 assert.deepEqual(a.spawned,['serve','chat']);
 assert.deepEqual(a.logs,['autorun:attempt-startup','autorun:started']);
 a.autorun.nudge('timer');a.autorun.nudge('focus');a.autorun.nudge('change');await a.settle();
 assert.equal(a.spawned.length,2,'one automatic start per run');
 assert.deepEqual(a.writes,[],'the automatic start does not rewrite the preference');
});

test('preference file: missing or unreadable means start automatically, allowCli stays off',()=>{
 assert.deepEqual(readPreferences('{"allowCli":true}'),{allowCli:true});
 assert.deepEqual(readPreferences('not json'),{allowCli:false});
 assert.deepEqual(readPreferences('{"allowCli":false,"autoRun":false}'),{allowCli:false,autoRun:false});
 assert.deepEqual(readPreferences('{"autoRun":"no"}'),{allowCli:false},'a non-boolean value counts as absent');
});

test('autoRun false: nothing starts, now or later in this run',async()=>{
 const a=app({saved:'{"allowCli":false,"autoRun":false}'});
 a.autorun.nudge('startup');await a.settle();a.autorun.nudge('timer');a.autorun.nudge('focus');await a.settle();
 assert.deepEqual(a.spawned,[]);assert.deepEqual(a.logs,['autorun:off']);
});

test('not connected: nothing starts until this PC is connected, then exactly once',async()=>{
 const a=app({connected:false});
 a.autorun.nudge('startup');await a.settle();a.autorun.nudge('timer');await a.settle();
 assert.deepEqual(a.spawned,[]);assert.deepEqual(a.logs,['autorun:waiting-connection'],'the waiting line is written once');
 a.state.connected=true;               // first connection or login recovery during this run, reported through changed()
 a.autorun.nudge('change');await a.settle();
 assert.deepEqual(a.spawned,['serve','chat']);
 a.state.connected=false;a.autorun.nudge('change');await a.settle();a.state.connected=true;a.autorun.nudge('change');await a.settle();
 assert.equal(a.spawned.length,2);
});

test('the user stops: false is saved and nothing starts again in this run',async()=>{
 const a=app();
 a.autorun.nudge('startup');await a.settle();
 await a.button.stop();
 assert.equal(a.prefs().autoRun,false);assert.deepEqual(JSON.parse(a.writes.at(-1)),{allowCli:false,autoRun:false});
 a.autorun.nudge('timer');a.autorun.nudge('focus');await a.settle();
 assert.equal(a.spawned.length,2);
 assert.equal(a.supervisor.snapshot().viewer.state,'stopped');
});

test('a stop before the automatic start keeps the device off',async()=>{
 const a=app({connected:false});
 a.autorun.nudge('startup');await a.settle();
 await a.button.stop();a.state.connected=true;a.autorun.nudge('change');a.autorun.nudge('timer');await a.settle();
 assert.deepEqual(a.spawned,[]);assert.equal(a.prefs().autoRun,false);
});

test('a stop whose save fails still keeps the device off in this run',async()=>{
 const a=app({connected:false});
 a.autorun.remember=()=>{throw new Error('disk full');};
 await a.button.stop();
 a.state.connected=true;a.autorun.nudge('change');a.autorun.nudge('timer');await a.settle();
 assert.deepEqual(a.spawned,[]);assert.ok(a.logs.includes('autorun:save-failed'));
});

test('a manual start that succeeds saves true, also after an earlier stop',async()=>{
 const a=app({saved:'{"allowCli":false,"autoRun":false}'});
 await a.button.start();
 assert.equal(a.prefs().autoRun,true);assert.deepEqual(a.spawned,['serve','chat']);
});

test('quitting the app stops everything without changing the preference',async()=>{
 const a=app();
 a.autorun.nudge('startup');await a.settle();
 await a.button.quit();
 assert.deepEqual(a.writes,[]);assert.equal(a.prefs().autoRun,undefined);
});

test('allowCli on without a chosen CLI: refused like the button (cli), no jobs and no subscription CLI',async()=>{
 const a=app({saved:'{"allowCli":true}',cliConfigured:false});
 await assert.rejects(a.button.start(),/^Error: cli$/);
 a.autorun.nudge('startup');await a.settle();
 assert.deepEqual(a.spawned,[]);assert.ok(a.logs.includes('autorun:failed-cli'));
});

test('allowCli off: the automatic start never starts jobs, even with a CLI chosen',async()=>{
 const a=app({saved:'{"allowCli":false}',cliConfigured:true});
 a.autorun.nudge('startup');await a.settle();
 assert.deepEqual(a.spawned,['serve','chat']);
});

test('allowCli on with a chosen CLI: jobs start with the CLI consent, as with the button',async()=>{
 const a=app({saved:'{"allowCli":true}',cliConfigured:true});
 a.autorun.nudge('startup');await a.settle();
 assert.deepEqual(a.spawned,['serve','serve --jobs','chat']);
});

test('the sidecar binary does not match the app: refused like the button',async()=>{
 const a=app({ready:false});
 a.autorun.nudge('startup');await a.settle();
 assert.deepEqual(a.spawned,[]);assert.ok(a.logs.includes('autorun:failed-not-connected'));
});

test('partial failure: the viewer runs, the chat failure is logged as a fixed kind and nothing escapes',async()=>{
 const secret='/Users/someone/Library/token-abc';
 const a=app({chatFails:secret});
 a.autorun.nudge('startup');await a.settle();
 assert.deepEqual(a.spawned,['serve']);
 assert.equal(a.supervisor.snapshot().viewer.state,'running');
 assert.deepEqual(a.logs,['autorun:attempt-startup','autorun:failed-error']);
 assert.ok(a.logs.every(l=>!l.includes('someone')&&!l.includes('token')),'no error text in the log');
 // A later try does not start a second viewer.
 a.autorun.nudge('timer');await a.settle();assert.deepEqual(a.spawned,['serve']);
});

test('a throwing check or a failing save never escapes',async()=>{
 const logs=[];const queue=[];
 const autorun=new AutoRun({wanted:()=>{throw new Error('x');},connected:()=>true,idle:()=>true,start:async()=>{},
  remember:()=>{throw new Error('disk full');},log:(c,e)=>logs.push(c+':'+e),defer:fn=>queue.push(fn)});
 autorun.nudge('startup');queue.shift()();await new Promise(r=>setImmediate(r));
 assert.deepEqual(logs,['autorun:check-error']);
 autorun.userStopped();assert.equal(logs.at(-1),'autorun:save-failed');
});

test('busy app: the start waits without using an attempt and runs when the lock is free',async()=>{
 const a=app();
 a.state.busy=true;a.autorun.nudge('startup');await a.settle();
 assert.deepEqual(a.spawned,[]);assert.deepEqual(a.logs,[]);
 a.state.busy=false;a.autorun.nudge('change');await a.settle();
 assert.deepEqual(a.spawned,['serve','chat']);
});

test('quitting app: no automatic start',async()=>{
 const a=app();
 await a.button.quit();a.autorun.nudge('startup');await a.settle();
 assert.deepEqual(a.spawned,[]);
});

test('a refused start does not loop on change notices',async()=>{
 const a=app({chatFails:'chat'});
 let runs=0;const start=a.autorun.start;a.autorun.start=()=>{runs++;return start();};
 a.autorun.nudge('startup');await a.settle();
 for(let i=0;i<20;i++){a.autorun.nudge('change');await a.settle();}
 assert.equal(runs,1);
});

test('a manual start that fails saves nothing',async()=>{
 const a=app({saved:'{"allowCli":true,"autoRun":false}',cliConfigured:false});
 await assert.rejects(a.button.start(),/^Error: cli$/);
 assert.deepEqual(a.writes,[]);assert.equal(a.prefs().autoRun,false);assert.deepEqual(a.spawned,[]);
});

test('chat starts with the viewer at once, whatever the screen state (no consent window to wait for)',async()=>{
 const a=app();
 a.autorun.nudge('startup');await a.settle();
 assert.deepEqual(a.spawned,['serve','chat']);
 assert.deepEqual(a.logs,['autorun:attempt-startup','autorun:started']);
 const b=app();await b.button.start();assert.deepEqual(b.spawned,['serve','chat']);
});

test('a chat start failure is counted and gives up after the attempts, without a second viewer',async()=>{
 const a=app({chatFails:'chat down'});
 a.autorun.nudge('startup');await a.settle();
 for(let i=0;i<MAX_ATTEMPTS+3;i++){a.autorun.nudge('focus');await a.settle();}
 assert.equal(a.logs.filter(l=>l==='autorun:failed-error').length,MAX_ATTEMPTS);
 assert.equal(a.logs.at(-1),'autorun:gave-up');assert.deepEqual(a.spawned,['serve']);
});

test('main: chat starts without a bridge, hears an AI change through its control line, jobs follow the Claude link',()=>{
 const main=require('node:fs').readFileSync(require('node:path').join(__dirname,'..','src','main.cjs'),'utf8');
 assert.match(main,/async function startChatAgent\(\)\{supervisor\.start\('chat',\['chat'\]\);\}/);
 assert.match(main,/notifyChat:\(\)=>supervisor\.send\('chat',\{command:'ai-refresh'\}\)/);
 assert.match(main,/prefs:\(\)=>\(\{\.\.\.prefs,allowCli:aiLink\?\.linked\('claude'\)===true\}\)/);
 assert.match(main,/linkedChanged:\(provider,isLinked\)=>\{if\(provider==='claude'\)jobsFollowClaude\(isLinked\);\}/);
 assert.doesNotMatch(main,/consent|Consent|BRIDGE|restartChat/,'no consent runtime, bridge or chat restart');
});

test('preference file keeps openAtLogin once it is set',()=>{
 assert.deepEqual(readPreferences('{"openAtLogin":false}'),{allowCli:false,openAtLogin:false});
 assert.deepEqual(readPreferences('{"openAtLogin":"yes"}'),{allowCli:false});
});
