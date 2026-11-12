'use strict';
// Automatic start when the app opens. The gates are the real ones: startConnection and startProcesses (the same calls as
// the [연결 장치 시작] button), the real Supervisor with a fake spawn, and the real consent lock guard wired as main.cjs
// wires it (J JD2: a lock only cancels the consent window in flight; it never holds or stops chat).
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {AutoRun,readPreferences,startConnection,startAutomatically,restartChat,MAX_ATTEMPTS}=require('../src/autorun.cjs');
const {Supervisor}=require('../src/supervisor.cjs');
const {createConsentLockGuard}=require('../src/consent-lock-guard.cjs');
const {startChatSidecar}=require('../src/chat-sidecar.cjs');

function fakeChild(){const c=new EventEmitter();c.stdout=new EventEmitter();c.stderr=new EventEmitter();c.stdin=new EventEmitter();
 c.stdin.end=()=>setImmediate(()=>c.emit('close',0,null));c.kill=()=>c.emit('close',null,'SIGTERM');return c;}
// A small app: the same pieces main.cjs wires, minus Electron.
function app({saved='{}',connected=true,cliConfigured=false,screen='active',platform='darwin',bridge,ready=true}={}){
 const spawned=[],logs=[],writes=[],cancels=[];
 const supervisor=new Supervisor({binary:'/bundle/agent',home:'/user/data',spawn:(_b,args)=>{spawned.push(args.slice(2).join(' '));return fakeChild();}});
 const powerMonitor=Object.assign(new EventEmitter(),{getSystemIdleState:()=>state.screen});
 const state={connected,cliConfigured,screen,busy:false,quitting:false,ready};
 // onLock as in main.cjs: abort the bridge's pending approvals and cancel the runtime's approval in flight.
 const consentLock=createConsentLockGuard({powerMonitor,platform,onLock:()=>{cancels.push('lock');}});
 const chatBridge=bridge||{start:async()=>({MYCRM_CHAT_BRIDGE_SOCKET:'/private/tmp/chat.sock',MYCRM_CHAT_BRIDGE_TOKEN:'A'.repeat(43)})};
 let prefs=readPreferences(saved);
 const connection=()=>({connected:state.connected,cliConfigured:state.cliConfigured});
 const deps={supervisor,prefs:()=>prefs,connection,ready:()=>state.ready,startChat:()=>startChatSidecar(supervisor,chatBridge)};
 // Like main.cjs: taking and releasing the app lock reports a change, and a change nudges the automatic start.
 async function exclusively(fn){if(state.busy||state.quitting)throw new Error('busy');state.busy=true;autorun.nudge('change');
  try{return await fn();}finally{state.busy=false;autorun.nudge('change');}}
 const queue=[];
 const autorun=new AutoRun({wanted:()=>prefs.autoRun!==false,connected:()=>connection().connected,idle:()=>!state.busy&&!state.quitting,
  start:()=>exclusively(()=>startAutomatically(deps)),remember:value=>{prefs.autoRun=value;writes.push(JSON.stringify(prefs));},
  log:(component,event)=>logs.push(component+':'+event),defer:fn=>queue.push(fn)});
 // Runs deferred checks until none are left (a check may queue another one).
 async function settle(){while(queue.length){queue.shift()();await new Promise(r=>setImmediate(r));}}
 // The handlers main.cjs registers for the window buttons and the tray.
 const button={
  start:()=>exclusively(async()=>{await startConnection(deps);autorun.manualStarted();}),
  stop:()=>exclusively(async()=>{autorun.userStopped();await supervisor.stopAll();}),
  quit:async()=>{state.quitting=true;await supervisor.stopAll({closing:true});},
  // [연결 해제] stops every process and drops the device; a pasted token or sync connects again.
  disconnect:()=>exclusively(async()=>{await supervisor.stopAll();state.connected=false;}),
  connect:()=>exclusively(async()=>{state.connected=true;}),
 };
 const lockScreen={lock:()=>{state.screen='locked';powerMonitor.emit('lock-screen');},
  unlock:()=>{state.screen='active';powerMonitor.emit('unlock-screen');}};
 return {autorun,state,spawned,logs,writes,cancels,prefs:()=>prefs,settle,button,supervisor,screen:lockScreen,consentLock,deps};
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
 const a=app({bridge:{start:async()=>{throw new Error(secret);}}});
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
 const a=app({bridge:{start:async()=>{throw new Error('bridge');}}});
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

test('J-F6: an idle screen (no input for a second) starts chat at once with the viewer, no 30-second hold',async()=>{
 const a=app({screen:'idle'});
 a.autorun.nudge('startup');await a.settle();
 assert.deepEqual(a.spawned,['serve','chat']);
 assert.deepEqual(a.logs,['autorun:attempt-startup','autorun:started']);
});

test('JD2: a locked screen or a platform without lock events does not hold the chat start (the button too)',async()=>{
 for(const options of [{screen:'locked'},{screen:'unknown'},{platform:'linux'}]){
  const a=app(options);
  a.autorun.nudge('startup');await a.settle();
  assert.deepEqual(a.spawned,['serve','chat'],JSON.stringify(options));
  const b=app(options);await b.button.start();assert.deepEqual(b.spawned,['serve','chat']);
 }
});

test('JD2: a screen lock and unlock leave chat running and only cancel the consent window in flight',async()=>{
 const a=app({saved:'{"allowCli":true}',cliConfigured:true});
 a.autorun.nudge('startup');await a.settle();
 assert.deepEqual(a.spawned,['serve','serve --jobs','chat']);
 a.screen.lock();await a.settle();
 assert.deepEqual(a.cancels,['lock']);
 assert.equal(a.supervisor.snapshot().chat.state,'running');
 a.screen.unlock();a.autorun.nudge('focus');a.autorun.nudge('timer');await a.settle();
 assert.deepEqual(a.spawned,['serve','serve --jobs','chat'],'nothing restarts');
 assert.deepEqual(a.writes,[]);
});

test('a chat start failure is counted and gives up after the attempts, without a second viewer',async()=>{
 const a=app({bridge:{start:async()=>{throw new Error('bridge down');}}});
 a.autorun.nudge('startup');await a.settle();
 for(let i=0;i<MAX_ATTEMPTS+3;i++){a.autorun.nudge('focus');await a.settle();}
 assert.equal(a.logs.filter(l=>l==='autorun:failed-error').length,MAX_ATTEMPTS);
 assert.equal(a.logs.at(-1),'autorun:gave-up');assert.deepEqual(a.spawned,['serve']);
});

test('J-F1: a CLI chosen after start restarts chat once so the web sees the new AI service; the viewer is untouched',async()=>{
 const a=app();
 a.autorun.nudge('startup');await a.settle();
 assert.deepEqual(a.spawned,['serve','chat']);
 assert.equal(await restartChat(a.deps),true);
 assert.deepEqual(a.spawned,['serve','chat','chat']);
 assert.equal(a.supervisor.snapshot().chat.state,'running');assert.equal(a.supervisor.snapshot().viewer.state,'running');
});

test('J-F1: no restart when chat never started, the user stopped the device, or the PC is not connected',async()=>{
 const never=app({saved:'{"autoRun":false}'});
 assert.equal(await restartChat(never.deps),false);assert.deepEqual(never.spawned,[]);
 const stopped=app();stopped.autorun.nudge('startup');await stopped.settle();await stopped.button.stop();
 assert.equal(await restartChat(stopped.deps),false);assert.deepEqual(stopped.spawned,['serve','chat']);
 const gone=app();gone.autorun.nudge('startup');await gone.settle();gone.state.connected=false;
 assert.equal(await restartChat(gone.deps),false);assert.deepEqual(gone.spawned,['serve','chat']);
});

test('main restarts chat only after a successful CLI choice',()=>{
 const main=require('node:fs').readFileSync(require('node:path').join(__dirname,'..','src','main.cjs'),'utf8');
 assert.match(main,/if\(result\?\.code===0\)await restartChat\(startDeps\)/);
 assert.equal((main.match(/return chatAfterProviderChange\(\{code,detail\}\);/g)||[]).length,2);
});
