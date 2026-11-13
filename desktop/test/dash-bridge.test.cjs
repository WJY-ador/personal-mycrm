'use strict';
// The dashboard bridge: main's sender check (updater.cjs) and the dashboard preload (dash-preload.cjs). Plan 2.4, 3.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {trustedSender,registerDashboardBridge,CHANNELS}=require('../src/updater.cjs');
const {registerDesktopBridge}=require('../src/dash-bridge.cjs');
const {DASH,PROVIDERS}=require('../src/desktop-contract.cjs');
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
    invoke:(...args)=>{invoked.push(args);return Promise.resolve(args[0]===CHANNELS.get?{phase:'available',version:'0.2.0'}:args[0]===DASH.pcGet?{connected:true}:'ignored');},
    on:(channel,fn)=>listeners.set(channel,fn),removeListener:(channel,fn)=>{if(listeners.get(channel)===fn)listeners.delete(channel);},
  };
  const electron={contextBridge:{exposeInMainWorld:(key,value)=>{name=key;exposed=value;}},ipcRenderer};
  vm.runInNewContext(src('dash-preload.cjs'),{require:m=>{assert.equal(m,'electron');return electron;}});
  return {api:exposed,name,invoked,listeners};
}

test('the dashboard preload opens window.mycrmDesktop.update with get, onChange, download and install only',async()=>{
  const p=loadPreload();
  assert.equal(p.name,'mycrmDesktop');
  assert.deepEqual(Object.keys(p.api),['update','pc','ai']);
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

test('the preload\'s pc and ai calls: no argument except a provider name from the fixed list',async()=>{
  const p=loadPreload();
  assert.deepEqual(Object.keys(p.api.pc).sort(),['get','onChange','sync']);
  assert.deepEqual(Object.keys(p.api.ai).sort(),['connect','disconnect','get','onChange']);
  assert.ok(Object.isFrozen(p.api.pc)&&Object.isFrozen(p.api.ai));
  assert.deepEqual(await p.api.pc.get('x'),{connected:true});
  await p.api.pc.sync({force:true});await p.api.ai.get();
  await p.api.ai.connect('claude');await p.api.ai.disconnect('codex');
  await assert.rejects(p.api.ai.connect('../../evil'),/provider/);
  await assert.rejects(p.api.ai.disconnect({provider:'claude'}),/provider/);
  assert.deepEqual(p.invoked,[[DASH.pcGet],[DASH.pcSync],[DASH.aiGet],[DASH.aiConnect,'claude'],[DASH.aiDisconnect,'codex']]);
  const seen=[];p.api.pc.onChange(v=>seen.push(v));p.listeners.get(DASH.pcChanged)({},{secret:'/Users/x'});
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(seen,[{connected:true}]);
});

test('main wires the bridges: dashboard preload, sandbox and isolation kept, sender check, empty change signals',()=>{
  const main=src('main.cjs');
  const dashPrefs=/dash=new BrowserWindow\(\{[^\n]*webPreferences:\{([^}]*)\}/.exec(main)?.[1]||'';
  assert.match(dashPrefs,/preload:path\.join\(__dirname,'dash-preload\.cjs'\)/);
  assert.match(dashPrefs,/contextIsolation:true/);assert.match(dashPrefs,/sandbox:true/);assert.match(dashPrefs,/nodeIntegration:false/);
  assert.match(main,/const trusted=event=>trustedSender\(event,dash&&!dash\.isDestroyed\(\)\?dash\.webContents:null,inAppAllowed\);/);
  assert.match(main,/registerDashboardBridge\(\{ipcMain,updater,trusted\}\);/);
  assert.match(main,/registerDesktopBridge\(\{ipcMain,trusted,handlers:\{/);
  assert.match(main,/dash\.webContents\.send\(UPDATE\.changed\);/,'the dashboard gets a signal without the state');
  assert.match(main,/function signal\(channel\)\{if\(dash&&!dash\.isDestroyed\(\)\)dash\.webContents\.send\(channel\);\}/);
  // One window (spec 2026-11-13 §1.1): no other BrowserWindow, no ipcMain handler outside the two bridges.
  assert.equal((main.match(/new BrowserWindow\(/g)||[]).length,1);
  assert.doesNotMatch(main,/ipcMain\.handle\(|register\('/);
  // The preload's channel names repeat updater.cjs and desktop-contract.cjs (a sandboxed preload cannot require them).
  const preload=src('dash-preload.cjs');
  for(const channel of [...Object.values(CHANNELS),...Object.values(DASH)])assert.ok(preload.includes(`'${channel}'`),channel);
  const repeated=/const DASH=Object\.freeze\((\{[\s\S]*?\})\);/.exec(preload)[1];
  assert.deepEqual(JSON.parse(JSON.stringify(vm.runInNewContext('('+repeated+')'))),{...DASH});
  assert.ok(preload.includes(`const PROVIDERS=Object.freeze(${JSON.stringify(PROVIDERS).replace(/"/g,"'")});`));
});

function desktopBridge(){
  const handlers=new Map(),calls=[];
  registerDesktopBridge({ipcMain:{handle:(name,fn)=>handlers.set(name,fn)},trusted:e=>trustedSender(e,dash,inAppAllowed),handlers:{
    pcView:()=>({connected:true}),sync:()=>{calls.push('sync');return {kind:'ok',code:null};},
    aiView:()=>({providers:{claude:'ready'}}),aiRefresh:()=>{calls.push('refresh');return Promise.reject(new Error('x'));},
    aiConnect:p=>{calls.push('connect '+p);return {};},aiDisconnect:p=>{calls.push('disconnect '+p);return {};},
  }});
  return {handlers,calls};
}

test('the desktop bridge registers the contract channels and answers trusted calls',async()=>{
  const b=desktopBridge(),good=event(dash,top(page));
  assert.deepEqual([...b.handlers.keys()].sort(),[DASH.aiConnect,DASH.aiDisconnect,DASH.aiGet,DASH.pcGet,DASH.pcSync].sort());
  assert.deepEqual(await b.handlers.get(DASH.pcGet)(good),{connected:true});
  assert.deepEqual(await b.handlers.get(DASH.pcSync)(good),{kind:'ok',code:null});
  assert.deepEqual(await b.handlers.get(DASH.aiGet)(good),{providers:{claude:'ready'}});
  await b.handlers.get(DASH.aiConnect)(good,'claude');await b.handlers.get(DASH.aiDisconnect)(good,'codex');
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(b.calls.sort(),['connect claude','disconnect codex','refresh','sync'],'a failing background check does not escape');
});

test('the desktop bridge refuses other senders, extra arguments and unknown providers',()=>{
  const b=desktopBridge(),good=event(dash,top(page));
  for(const name of [DASH.pcGet,DASH.pcSync,DASH.aiGet]){
    const fn=b.handlers.get(name);
    assert.throws(()=>fn(event(other,top(page))),/sender/,name);
    assert.throws(()=>fn(event(dash,sub(page))),/sender/,name);
    assert.throws(()=>fn(good,'x'),/sender/,name);
  }
  for(const name of [DASH.aiConnect,DASH.aiDisconnect]){
    const fn=b.handlers.get(name);
    assert.throws(()=>fn(good),/sender/,name);
    assert.throws(()=>fn(good,'claude','x'),/sender/,name);
    assert.throws(()=>fn(good,'gemini'),/sender/,name);
    assert.throws(()=>fn(event(dash,top('https://evil.example/app')),'claude'),/sender/,name);
  }
  assert.deepEqual(b.calls,[]);
});

test('electron-updater is required in main.cjs only',()=>{
  for(const name of fs.readdirSync(path.join(__dirname,'..','src'))){
    const text=src(name);const uses=/require\(['"]electron-updater['"]\)/.test(text);
    assert.equal(uses,name==='main.cjs',name);
  }
});

test('the window lets an install quit it; the install path never uses userStop or changes autoRun',()=>{
  const main=src('main.cjs');
  assert.match(main,/dash\.on\('close',event=>\{if\(!quitting&&!installing\)/);
  assert.match(main,/nativeUpdater\.on\('before-quit-for-update',\(\)=>\{installing=true;\}\)/);
  assert.equal((main.match(/installing=true/g)||[]).length,1,'the windows close only for the updater\'s own quit');
  const prepare=/async function prepareInstall\(\)\{[\s\S]*?\n\}/.exec(main)?.[0]||'';
  assert.ok(prepare,'prepareInstall exists');
  assert.doesNotMatch(prepare,/userStop|autorun|savePreferences|prefs\.|quitting=true/);
  assert.match(prepare,/await stopProcesses\(\);/);
  assert.match(prepare,/abortLogins\(\);\n    await Promise\.all\(\[\.\.\.commands\.keys\(\)\]/,'ends a provider login and waits for running commands');
  // before-quit keeps its own cleanup; the install does not set quitting, so that cleanup still runs.
  assert.match(main,/Promise\.all\(\[stopProcesses\(\{closing:true\}\),\.\.\.pending\]\)\.finally\(\(\)=>\{tray\?\.destroy\(\);app\.quit\(\);\}\);/);
});
