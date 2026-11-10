'use strict';
// The dashboard bridge: main's sender check (updater.cjs) and the dashboard preload (dash-preload.cjs). Plan 2.4, 3.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {trustedSender,registerDashboardBridge,CHANNELS}=require('../src/updater.cjs');
const {inAppAllowed,HOSTED}=require('../src/policy.cjs');
const src=name=>fs.readFileSync(path.join(__dirname,'..','src',name),'utf8');

const dash={id:'dashboard'},other={id:'connection-window'};
const page=new URL('app',HOSTED).href;
const top=url=>({url,parent:null});
const sub=url=>({url,parent:top(page)});
const event=(sender,frame)=>({sender,senderFrame:frame});

test('only the dashboard window\'s top-level frame on the hosted origin is trusted',()=>{
  const ok=(e,contents=dash)=>trustedSender(e,contents,inAppAllowed);
  assert.equal(ok(event(dash,top(page))),true);
  assert.equal(ok(event(dash,top(new URL('settings?x=1',HOSTED).href))),true);
  assert.equal(ok(event(other,top(page))),false,'another window');
  assert.equal(ok(event(dash,sub(page))),false,'a subframe, even on the hosted origin');
  assert.equal(ok(event(dash,top('data:text/html;charset=utf-8,%3Ch1%3E'))),false,'notice() page');
  assert.equal(ok(event(dash,top('https://evil.example/app'))),false,'another origin');
  assert.equal(ok(event(dash,top('about:blank'))),false);
  assert.equal(ok(event(dash,null)),false,'no sender frame');
  assert.equal(ok(event(dash,top(page)),null),false,'the dashboard window is gone');
  const u=new URL(page);u.username='a';u.password='b';
  assert.equal(ok(event(dash,top(u.href))),false,'credentials in the URL');
  assert.equal(trustedSender({get sender(){throw new Error('destroyed');}},dash,inAppAllowed),false);
});

function bridge(){
  const handlers=new Map(),calls=[];
  const state=Object.freeze({inApp:true,phase:'downloaded',current:'0.1.2',version:'0.2.0',percent:null,reason:null});
  const updater={state:()=>state,download:()=>{calls.push('download');return new Promise(()=>{});},install:()=>{calls.push('install');return new Promise(()=>{});}};
  registerDashboardBridge({ipcMain:{handle:(name,fn)=>handlers.set(name,fn)},updater,trusted:e=>trustedSender(e,dash,inAppAllowed)});
  return {handlers,calls,state};
}

test('the bridge registers get, download and install; download and install answer at once',async()=>{
  const b=bridge();
  assert.deepEqual([...b.handlers.keys()].sort(),[CHANNELS.download,CHANNELS.get,CHANNELS.install].sort());
  const good=event(dash,top(page));
  assert.equal(await b.handlers.get(CHANNELS.get)(good),b.state);
  assert.equal(await b.handlers.get(CHANNELS.download)(good),undefined);
  assert.equal(await b.handlers.get(CHANNELS.install)(good),undefined);
  assert.deepEqual(b.calls,['download','install']);
});

test('the bridge refuses other senders and any argument',()=>{
  const b=bridge();
  for(const name of [CHANNELS.get,CHANNELS.download,CHANNELS.install]){
    const fn=b.handlers.get(name);
    assert.throws(()=>fn(event(dash,top('data:text/html,x'))),/sender/,name);
    assert.throws(()=>fn(event(other,top(page))),/sender/,name);
    assert.throws(()=>fn(event(dash,sub(page))),/sender/,name);
    assert.throws(()=>fn(event(dash,top(page)),'https://github.com/x/releases/download/evil.exe'),/sender/,name);
    assert.throws(()=>fn(event(dash,top(page)),undefined),/sender/,name);
  }
  assert.deepEqual(b.calls,[]);
});

function loadPreload(){
  const invoked=[],listeners=new Map();let exposed=null,name=null;
  const ipcRenderer={
    invoke:(...args)=>{invoked.push(args);return Promise.resolve(args[0]===CHANNELS.get?{phase:'available',version:'0.2.0'}:'ignored');},
    on:(channel,fn)=>listeners.set(channel,fn),removeListener:(channel,fn)=>{if(listeners.get(channel)===fn)listeners.delete(channel);},
  };
  const electron={contextBridge:{exposeInMainWorld:(key,value)=>{name=key;exposed=value;}},ipcRenderer};
  vm.runInNewContext(src('dash-preload.cjs'),{require:m=>{assert.equal(m,'electron');return electron;}});
  return {api:exposed,name,invoked,listeners};
}

test('the dashboard preload opens window.mycrmDesktop.update with get, onChange, download and install only',async()=>{
  const p=loadPreload();
  assert.equal(p.name,'mycrmDesktop');
  assert.deepEqual(Object.keys(p.api),['update']);
  assert.deepEqual(Object.keys(p.api.update).sort(),['download','get','install','onChange']);
  assert.ok(Object.isFrozen(p.api)&&Object.isFrozen(p.api.update));
  assert.deepEqual(await p.api.update.get('ignored'),{phase:'available',version:'0.2.0'});
  assert.equal(await p.api.update.download('https://evil.example/x.exe'),undefined);
  assert.equal(await p.api.update.install({path:'/tmp/x'}),undefined);
  assert.deepEqual(p.invoked,[[CHANNELS.get],[CHANNELS.download],[CHANNELS.install]],'no argument reaches main');
});

test('onChange reads the state again through get on each signal and unsubscribes',async()=>{
  const p=loadPreload();const seen=[];
  const off=p.api.update.onChange(s=>seen.push(s));
  const signal=p.listeners.get(CHANNELS.changed);
  signal({sender:'main'},{phase:'error',secret:'/Users/x'});   // a payload, if any, is ignored
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(seen,[{phase:'available',version:'0.2.0'}]);
  assert.deepEqual(p.invoked,[[CHANNELS.get]]);
  off();assert.equal(p.listeners.has(CHANNELS.changed),false);
  assert.equal(typeof p.api.update.onChange('not a function'),'function');
  assert.equal(p.listeners.has(CHANNELS.changed),false);
});

test('main wires the bridge: dashboard preload, sandbox and isolation kept, sender check, empty change signal',()=>{
  const main=src('main.cjs');
  const dashPrefs=/dash=new BrowserWindow\(\{[^\n]*webPreferences:\{([^}]*)\}/.exec(main)?.[1]||'';
  assert.match(dashPrefs,/preload:path\.join\(__dirname,'dash-preload\.cjs'\)/);
  assert.match(dashPrefs,/contextIsolation:true/);assert.match(dashPrefs,/sandbox:true/);assert.match(dashPrefs,/nodeIntegration:false/);
  assert.match(main,/registerDashboardBridge\(\{ipcMain,updater,trusted:event=>trustedSender\(event,dash&&!dash\.isDestroyed\(\)\?dash\.webContents:null,inAppAllowed\)\}\)/);
  assert.match(main,/dash\.webContents\.send\(UPDATE\.changed\);/,'the dashboard gets a signal without the state');
  // The preload's channel names repeat updater.cjs (a sandboxed preload cannot require it).
  const preload=src('dash-preload.cjs');
  for(const channel of Object.values(CHANNELS))assert.ok(preload.includes(`'${channel}'`),channel);
});

test('electron-updater is required in main.cjs only',()=>{
  for(const name of fs.readdirSync(path.join(__dirname,'..','src'))){
    const text=src(name);const uses=/require\(['"]electron-updater['"]\)/.test(text);
    assert.equal(uses,name==='main.cjs',name);
  }
});

test('the windows let an install quit them; the install path never uses userStop or changes autoRun',()=>{
  const main=src('main.cjs');
  assert.match(main,/dash\.on\('close',event=>\{if\(!quitting&&!installing\)/);
  assert.match(main,/win\.on\('close',event=>\{if\(!quitting&&!installing\)/);
  assert.match(main,/nativeUpdater\.on\('before-quit-for-update',\(\)=>\{installing=true;\}\)/);
  assert.equal((main.match(/installing=true/g)||[]).length,1,'the windows close only for the updater\'s own quit');
  const prepare=/async function prepareInstall\(\)\{[\s\S]*?\n\}/.exec(main)?.[0]||'';
  assert.ok(prepare,'prepareInstall exists');
  assert.doesNotMatch(prepare,/userStop|autorun|savePreferences|prefs\.|quitting=true/);
  assert.match(prepare,/await stopProcesses\(\);/);
  assert.match(prepare,/commands\]/,'waits for running commands');
  // before-quit keeps its own cleanup; the install does not set quitting, so that cleanup still runs.
  assert.match(main,/consentLock\?\.dispose\(\);consentRuntime\?\.dispose\(\);await consentBridge\?\.close\(\);tray\?\.destroy\(\);app\.quit\(\);/);
});
