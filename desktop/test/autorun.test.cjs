'use strict';
// Automatic start when the app opens. The gates are the real ones: startConnection and startProcesses (the same calls as
// the [연결 장치 시작] button), the real Supervisor with a fake spawn and the real consent lock guard with a fake powerMonitor.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {AutoRun,readPreferences,startConnection,startAutomatically,addChat,stopChatForLock,MAX_ATTEMPTS}=require('../src/autorun.cjs');
const {Supervisor}=require('../src/supervisor.cjs');
const {createConsentLockGuard}=require('../src/consent-lock-guard.cjs');
const {startChatSidecar}=require('../src/chat-sidecar.cjs');

function fakeChild(){const c=new EventEmitter();c.stdout=new EventEmitter();c.stderr=new EventEmitter();c.stdin=new EventEmitter();
 c.stdin.end=()=>setImmediate(()=>c.emit('close',0,null));c.kill=()=>c.emit('close',null,'SIGTERM');return c;}
// A small app: the same pieces main.cjs wires, minus Electron.
function app({saved='{}',connected=true,cliConfigured=false,screen='active',platform='darwin',bridge,ready=true}={}){
 const spawned=[],logs=[],writes=[];
 const supervisor=new Supervisor({binary:'/bundle/agent',home:'/user/data',spawn:(_b,args)=>{spawned.push(args.slice(2).join(' '));return fakeChild();}});
 const powerMonitor=Object.assign(new EventEmitter(),{getSystemIdleState:()=>state.screen});
 const state={connected,cliConfigured,screen,busy:false,quitting:false,ready};
 // onLock as in main.cjs: chat stops through stopChatForLock (the key revoke is out of scope here).
 const consentLock=createConsentLockGuard({powerMonitor,platform,onLock:async()=>{await stopChatForLock(supervisor,autorun);return true;}});
 const chatBridge=bridge||{start:async()=>({MYCRM_CHAT_BRIDGE_SOCKET:'/private/tmp/chat.sock',MYCRM_CHAT_BRIDGE_TOKEN:'A'.repeat(43)})};
 let prefs=readPreferences(saved);
 const connection=()=>({connected:state.connected,cliConfigured:state.cliConfigured});
 const deps={supervisor,consentLock,prefs:()=>prefs,connection,ready:()=>state.ready,startChat:()=>startChatSidecar(supervisor,chatBridge)};
 // Like main.cjs: taking and releasing the app lock reports a change, and a change nudges the automatic start.
 async function exclusively(fn){if(state.busy||state.quitting)throw new Error('busy');state.busy=true;autorun.nudge('change');
  try{return await fn();}finally{state.busy=false;autorun.nudge('change');}}
 const queue=[];
 const autorun=new AutoRun({wanted:()=>prefs.autoRun!==false,connected:()=>connection().connected,idle:()=>!state.busy&&!state.quitting,
  start:()=>exclusively(()=>startAutomatically(deps)),chatReady:()=>consentLock.canStart()===true,
  addChat:()=>exclusively(()=>addChat(deps)),remember:value=>{prefs.autoRun=value;writes.push(JSON.stringify(prefs));},
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
 // Screen lock and unlock through the real guard; the lock's chat stop is awaited.
 const lockScreen={lock:async()=>{state.screen='locked';powerMonitor.emit('lock-screen');await consentLock.whenSettled();},
  unlock:()=>{state.screen='active';powerMonitor.emit('unlock-screen');}};
 return {autorun,state,spawned,logs,writes,prefs:()=>prefs,settle,button,supervisor,screen:lockScreen};
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

test('a manual start that fails saves nothing and starts nothing',async()=>{
 const a=app({saved:'{"allowCli":false,"autoRun":false}',screen:'idle'});
 await assert.rejects(a.button.start(),/consent-lock-locked/);
 assert.deepEqual(a.writes,[]);assert.equal(a.prefs().autoRun,false);assert.deepEqual(a.spawned,[],'the button still refuses the whole list');
});

test('quitting the app stops everything without changing the preference',async()=>{
 const a=app();
 a.autorun.nudge('startup');await a.settle();
 await a.button.quit();
 assert.deepEqual(a.writes,[]);assert.equal(a.prefs().autoRun,undefined);
});

test('consent lock closed: viewer starts without input, chat is held and nothing else is logged',async()=>{
 const a=app({screen:'idle'});
 a.autorun.nudge('startup');await a.settle();
 assert.deepEqual(a.spawned,['serve']);
 assert.deepEqual(a.logs,['autorun:attempt-startup','autorun:started-without-chat']);
 assert.deepEqual(Object.keys(a.supervisor.snapshot()),['viewer'],'no chat entry: the status shows the viewer only');
 for(let i=0;i<MAX_ATTEMPTS+3;i++){a.autorun.nudge('change');a.autorun.nudge('timer');a.autorun.nudge('focus');await a.settle();}
 assert.deepEqual(a.spawned,['serve'],'chat never starts while the lock stays closed');
 assert.deepEqual(a.logs.slice(2),['autorun:chat-held'],'the hold is logged once');
});

test('consent lock closed with allowCli and a chosen CLI: viewer and jobs start, chat waits',async()=>{
 const a=app({saved:'{"allowCli":true}',cliConfigured:true,screen:'idle'});
 a.autorun.nudge('startup');await a.settle();
 assert.deepEqual(a.spawned,['serve','serve --jobs']);
});

test('held chat is added on window focus once the lock opens, without touching what runs',async()=>{
 const a=app({saved:'{"allowCli":true}',cliConfigured:true,screen:'idle'});
 a.autorun.nudge('startup');await a.settle();
 a.state.screen='active';
 a.autorun.nudge('change');await a.settle();
 assert.deepEqual(a.spawned,['serve','serve --jobs'],'a change notice does not add chat');
 a.autorun.nudge('focus');await a.settle();
 assert.deepEqual(a.spawned,['serve','serve --jobs','chat']);
 assert.equal(a.logs.at(-1),'autorun:chat-added');assert.equal(a.logs.at(-2),'autorun:attempt-focus');
 a.autorun.nudge('timer');a.autorun.nudge('focus');await a.settle();assert.equal(a.spawned.length,3,'done after one success');
});

test('held chat is added on a timer tick once the lock opens',async()=>{
 const a=app({screen:'idle'});
 a.autorun.nudge('startup');await a.settle();
 a.autorun.nudge('timer');await a.settle();assert.deepEqual(a.spawned,['serve']);
 a.state.screen='active';a.autorun.nudge('timer');await a.settle();
 assert.deepEqual(a.spawned,['serve','chat']);assert.deepEqual(a.logs.slice(-2),['autorun:attempt-timer','autorun:chat-added']);
});

test('chat is never started past a closed lock, even if the pre-check says ready',async()=>{
 const a=app({screen:'idle'});
 a.autorun.nudge('startup');await a.settle();
 a.autorun.chatReady=()=>true;          // the lock closes between the pre-check and the start
 for(let i=0;i<MAX_ATTEMPTS+2;i++){a.autorun.nudge('timer');await a.settle();}
 assert.deepEqual(a.spawned,['serve']);
 assert.equal(a.logs.filter(l=>l==='autorun:chat-held-consent-lock-locked').length,1);
 assert.ok(!a.logs.some(l=>l.includes('gave-up')),'a held chat does not use up the attempts');
 a.state.screen='active';a.autorun.nudge('focus');await a.settle();assert.deepEqual(a.spawned,['serve','chat']);
});

test('a stop cancels the held chat',async()=>{
 const a=app({screen:'idle'});
 a.autorun.nudge('startup');await a.settle();
 await a.button.stop();
 a.state.screen='active';a.autorun.nudge('focus');a.autorun.nudge('timer');await a.settle();
 assert.deepEqual(a.spawned,['serve']);assert.equal(a.prefs().autoRun,false);
 assert.equal(a.supervisor.snapshot().viewer.state,'stopped');
});

test('the button in the viewer-only state: refused while the lock is closed, adds only chat once it opens',async()=>{
 const a=app({screen:'idle'});
 a.autorun.nudge('startup');await a.settle();
 await assert.rejects(a.button.start(),/consent-lock-locked/,'the button keeps its rule');
 assert.equal(a.supervisor.snapshot().viewer.state,'running','the refused button leaves the viewer running');
 assert.equal(a.prefs().autoRun,undefined);
 a.state.screen='active';await a.button.start();
 assert.deepEqual(a.spawned,['serve','chat'],'no second viewer');assert.equal(a.prefs().autoRun,true);
 a.autorun.nudge('focus');await a.settle();assert.equal(a.spawned.length,2,'the manual start ends the held chat');
});

test('held chat that fails to start: counted, then it gives up',async()=>{
 const a=app({screen:'idle',bridge:{start:async()=>{throw new Error('bridge down');}}});
 a.autorun.nudge('startup');await a.settle();
 a.state.screen='active';
 for(let i=0;i<MAX_ATTEMPTS+3;i++){a.autorun.nudge('focus');await a.settle();}
 assert.equal(a.logs.filter(l=>l==='autorun:chat-failed-error').length,MAX_ATTEMPTS);
 assert.equal(a.logs.at(-1),'autorun:chat-gave-up');assert.deepEqual(a.spawned,['serve']);
});

test('platform without lock events: the button refuses, the automatic start runs the viewer and holds chat',async()=>{
 const a=app({platform:'linux'});
 await assert.rejects(a.button.start(),/consent-lock-unsupported/);
 a.autorun.nudge('startup');await a.settle();
 for(let i=0;i<MAX_ATTEMPTS+3;i++){a.autorun.nudge('timer');await a.settle();}
 assert.deepEqual(a.spawned,['serve']);assert.equal(a.logs.at(-1),'autorun:chat-held');
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

test('chat stopped by a screen lock comes back after the unlock, on focus or timer',async()=>{
 const a=app({saved:'{"allowCli":true}',cliConfigured:true});
 a.autorun.nudge('startup');await a.settle();
 assert.deepEqual(a.spawned,['serve','serve --jobs','chat']);
 await a.screen.lock();
 assert.equal(a.supervisor.snapshot().chat.state,'stopped');assert.equal(a.supervisor.snapshot().jobs.state,'running','the lock stops chat only');
 assert.equal(a.logs.at(-1),'autorun:chat-paused-lock');
 a.autorun.nudge('timer');a.autorun.nudge('focus');await a.settle();
 assert.equal(a.spawned.length,3,'no chat while locked');
 a.screen.unlock();a.autorun.nudge('change');await a.settle();
 assert.equal(a.spawned.length,3,'a change notice does not bring chat back');
 a.autorun.nudge('timer');await a.settle();
 assert.deepEqual(a.spawned,['serve','serve --jobs','chat','chat']);
 assert.equal(a.supervisor.snapshot().chat.state,'running');
 assert.deepEqual(a.writes,[],'the lock is not a stop: the preference is untouched');
});

test('chat started by hand also comes back after a lock',async()=>{
 const a=app({saved:'{"allowCli":false,"autoRun":false}'});
 a.autorun.nudge('startup');await a.settle();assert.deepEqual(a.spawned,[]);
 await a.button.start();await a.screen.lock();a.screen.unlock();
 a.autorun.nudge('focus');await a.settle();
 assert.deepEqual(a.spawned,['serve','chat','chat']);
});

test('after the user stops, a lock and unlock bring nothing back',async()=>{
 const a=app();
 a.autorun.nudge('startup');await a.settle();
 await a.button.stop();await a.screen.lock();a.screen.unlock();
 a.autorun.nudge('focus');a.autorun.nudge('timer');await a.settle();
 assert.deepEqual(a.spawned,['serve','chat']);assert.ok(!a.logs.includes('autorun:chat-paused-lock'));
});

test('a lock pause is ignored when the user stopped in this run or the preference is off',()=>{
 const logs=[];let wanted=true;
 const autorun=new AutoRun({wanted:()=>wanted,connected:()=>true,idle:()=>true,start:async()=>true,chatReady:()=>true,addChat:async()=>{},
  remember:()=>{throw new Error('disk full');},log:(c,e)=>logs.push(c+':'+e),defer:()=>{}});
 autorun.userStopped();autorun.chatPausedByLock();assert.equal(autorun.phase,'done','stopped by the user, even if the save failed');
 const other=new AutoRun({wanted:()=>wanted,connected:()=>true,idle:()=>true,start:async()=>true,chatReady:()=>true,addChat:async()=>{},
  remember:()=>{},log:()=>{},defer:()=>{}});
 other.phase='done';wanted=false;other.chatPausedByLock();assert.equal(other.phase,'done','autoRun false');
});

test('a lock while chat is only held changes nothing',async()=>{
 const a=app({screen:'idle'});
 a.autorun.nudge('startup');await a.settle();
 await a.screen.lock();a.screen.unlock();
 assert.ok(!a.logs.includes('autorun:chat-paused-lock'));
 a.autorun.nudge('focus');await a.settle();assert.deepEqual(a.spawned,['serve','chat']);
});

test('a disconnect and reconnect while chat is held starts over: viewer and jobs come back, chat stays held',async()=>{
 const a=app({saved:'{"allowCli":true}',cliConfigured:true,screen:'idle'});
 a.autorun.nudge('startup');await a.settle();
 assert.deepEqual(a.spawned,['serve','serve --jobs']);
 await a.button.disconnect();await a.settle();
 assert.equal(a.supervisor.snapshot().viewer.state,'stopped');
 await a.button.connect();await a.settle();
 assert.deepEqual(a.spawned,['serve','serve --jobs','serve','serve --jobs'],'the full decision runs again at once');
 assert.ok(a.logs.includes('autorun:reconnected'));
 assert.equal(a.logs.at(-1),'autorun:started-without-chat');
 a.state.screen='active';a.autorun.nudge('focus');await a.settle();
 assert.deepEqual(a.spawned.slice(4),['chat']);
});

test('a reconnect with the lock open starts the full list',async()=>{
 const a=app({screen:'idle'});
 a.autorun.nudge('startup');await a.settle();
 await a.button.disconnect();await a.settle();
 a.state.screen='active';await a.button.connect();await a.settle();
 assert.deepEqual(a.spawned,['serve','serve','chat']);assert.equal(a.logs.at(-1),'autorun:started');
});

test('a reconnect after the user stopped starts nothing',async()=>{
 const a=app({screen:'idle'});
 a.autorun.nudge('startup');await a.settle();
 await a.button.stop();await a.button.disconnect();await a.button.connect();await a.settle();
 a.autorun.nudge('timer');await a.settle();
 assert.deepEqual(a.spawned,['serve']);assert.ok(!a.logs.includes('autorun:reconnected'));
});

test('a reconnect after held chat gave up starts over too',async()=>{
 const a=app({screen:'idle',bridge:{start:async()=>{throw new Error('bridge down');}}});
 a.autorun.nudge('startup');await a.settle();
 a.state.screen='active';for(let i=0;i<MAX_ATTEMPTS;i++){a.autorun.nudge('focus');await a.settle();}
 assert.equal(a.logs.at(-1),'autorun:chat-gave-up');
 a.state.screen='idle';await a.button.disconnect();await a.button.connect();await a.settle();
 assert.deepEqual(a.spawned,['serve','serve']);assert.equal(a.logs.at(-1),'autorun:started-without-chat');
});
