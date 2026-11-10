'use strict';
// updater.cjs: the update state machine with a fake electron-updater (plan 2.4, contract 0.2.2 and 0.2.4).
const {test,after}=require('node:test');
const assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {createUpdater,inAppSupported,errorKind,CHECK_EVERY_MS,INSTALL_WAIT_MS}=require('../src/updater.cjs');

const flush=()=>new Promise(resolve=>setImmediate(resolve));
const KEYS=['inApp','phase','current','version','percent','reason'];
// The web band's parseState (server/ui/src/shared/desktopUpdate.ts) drops, without a word, any state that breaks one of
// these rules. Every state any test below sees is held to them (checked once all tests ran).
const BARE=/^\d+\.\d+\.\d+$/;
const newer=(a,b)=>{const x=a.split('.').map(Number),y=b.split('.').map(Number);for(let i=0;i<3;i++)if(x[i]!==y[i])return x[i]>y[i];return false;};
function contractProblem(s){
  if(!s||typeof s!=='object')return 'not an object';
  const keys=Object.keys(s).sort();if(keys.join()!==[...KEYS].sort().join())return 'keys '+keys.join();
  if(typeof s.inApp!=='boolean')return 'inApp';
  if(!['idle','checking','available','downloading','downloaded','error'].includes(s.phase))return 'phase';
  if(typeof s.current!=='string'||!BARE.test(s.current))return 'current '+s.current;
  if(s.version!==null&&(typeof s.version!=='string'||!BARE.test(s.version)))return 'version '+s.version;
  if(s.phase==='downloading'){if(!Number.isInteger(s.percent)||s.percent<0||s.percent>100)return 'percent '+s.percent;}
  else if(s.percent!==null)return 'percent outside downloading';
  if(s.phase==='error'){if(!['network','verify','install','unknown'].includes(s.reason))return 'reason '+s.reason;}
  else if(s.reason!==null)return 'reason outside error';
  if(!s.inApp&&!['idle','checking','available'].includes(s.phase))return 'phase without inApp '+s.phase;
  if(['available','downloading','downloaded'].includes(s.phase)&&!(s.version&&newer(s.version,s.current)))return 'version not above current';
  return null;
}
const violations=[];
after(()=>assert.deepEqual(violations,[],'states the web band would drop'));

function fakeUpdater(){
  const u=new EventEmitter();
  u.calls={check:0,download:0,quit:[]};
  u.check=()=>({isUpdateAvailable:true,updateInfo:{version:'0.2.0'}});
  u.download=()=>Promise.resolve(['/Users/someone/Library/Caches/mycrm-updater/pending/MyCRM-0.2.0.zip']);
  u.quit=()=>{};
  u.checkForUpdates=async()=>{u.calls.check++;return u.check();};
  u.downloadUpdate=()=>{u.calls.download++;return u.download();};
  u.quitAndInstall=(...args)=>{u.calls.quit.push(args);u.quit();};
  return u;
}
function fakeTimers(){
  const t={timeouts:[],intervals:[],cleared:[]};
  t.api={setTimeout:(fn,ms)=>{t.timeouts.push({fn,ms});return t.timeouts.length;},clearTimeout:id=>t.cleared.push(id),
    setInterval:(fn,ms)=>{t.intervals.push({fn,ms});return 'interval';},clearInterval:id=>t.cleared.push(id)};
  return t;
}
// A main-like install: prepare() resolves a session whose steps are recorded.
function fakeMain(order){
  const m={quitting:false,aborted:0};
  m.prepare=async()=>{order.push('prepare');if(m.prepareError)throw new Error(m.prepareError);
    return {quitting:()=>m.quitting,abort:async()=>{order.push('abort');m.aborted++;}};};
  return m;
}
function make({inApp=true,updater=fakeUpdater(),checkRelease,current='0.1.2',order=[],powerMonitor=null}={}){
  const timers=fakeTimers(),main=fakeMain(order),logs=[],seen=[];
  let loads=0;
  const up=createUpdater({inApp,current,load:()=>{loads++;return updater;},checkRelease:checkRelease||(async()=>{throw new Error('not used');}),
    powerMonitor,prepare:main.prepare,log:(c,e)=>logs.push(c+':'+e),timers:timers.api});
  up.subscribe(s=>{seen.push(s);const p=contractProblem(s);if(p)violations.push(p+' '+JSON.stringify(s));});
  return {up,u:updater,timers,main,logs,seen,order,loads:()=>loads};
}
async function toDownloaded(f){await f.up.check();await f.up.download();assert.equal(f.up.state().phase,'downloaded');}

test('in-app support: packaged Windows, or packaged macOS with the release marker; never dev runs or test-server builds',()=>{
  assert.equal(inAppSupported({isPackaged:true,platform:'win32',pkg:{}}),true);
  assert.equal(inAppSupported({isPackaged:true,platform:'darwin',pkg:{}}),false);
  assert.equal(inAppSupported({isPackaged:true,platform:'darwin',pkg:{mycrmMacUpdater:true}}),true);
  assert.equal(inAppSupported({isPackaged:true,platform:'darwin',pkg:{mycrmMacUpdater:'true'}}),false);
  assert.equal(inAppSupported({isPackaged:false,platform:'win32',pkg:{}}),false);
  assert.equal(inAppSupported({isPackaged:false,platform:'darwin',pkg:{mycrmMacUpdater:true}}),false);
  assert.equal(inAppSupported({isPackaged:true,platform:'win32',pkg:{mycrmDevHosted:'http://127.0.0.1:8800/'}}),false);
  assert.equal(inAppSupported({isPackaged:true,platform:'darwin',pkg:{mycrmMacUpdater:true,mycrmDevHosted:'http://127.0.0.1:8800/'}}),false);
  assert.equal(inAppSupported({isPackaged:true,platform:'linux',pkg:{mycrmMacUpdater:true}}),false);
});

test('a supported build sets the updater options: no automatic download or install, no prerelease or downgrade, no logger',()=>{
  const f=make();
  assert.equal(f.loads(),1);
  assert.equal(f.u.autoDownload,false);assert.equal(f.u.autoInstallOnAppQuit,false);
  assert.equal(f.u.allowPrerelease,false);assert.equal(f.u.allowDowngrade,false);
  assert.equal(f.u.logger,null);
  assert.deepEqual(f.up.state(),{inApp:true,phase:'idle',current:'0.1.2',version:null,percent:null,reason:null});
});

test('an unsupported build never loads electron-updater; a failed load falls back to announcing only',()=>{
  const off=make({inApp:false});
  assert.equal(off.loads(),0);assert.equal(off.up.state().inApp,false);
  const timers=fakeTimers(),logs=[];
  const broken=createUpdater({inApp:true,current:'0.1.2',load:()=>{throw new Error('Cannot find module /Applications/MyCRM.app/x');},
    checkRelease:async()=>({state:'current'}),prepare:async()=>{},log:(c,e)=>logs.push(c+':'+e),timers:timers.api});
  assert.equal(broken.state().inApp,false);assert.deepEqual(logs,['update:load-failed']);
});

test('check: idle → checking → available with the version without v; no new version → idle',async()=>{
  const f=make();f.u.check=()=>({isUpdateAvailable:true,updateInfo:{version:'v0.2.0'}});
  assert.equal(await f.up.check(),'ok');
  assert.deepEqual(f.seen.map(s=>s.phase),['checking','available']);
  assert.deepEqual(f.up.state(),{inApp:true,phase:'available',current:'0.1.2',version:'0.2.0',percent:null,reason:null});
  const g=make();g.u.check=()=>({isUpdateAvailable:false,updateInfo:{version:'0.1.2'}});
  await g.up.check();assert.deepEqual(g.seen.map(s=>s.phase),['checking','idle']);assert.equal(g.up.state().version,null);
});

test('checks never overlap: a second check while one runs shares it',async()=>{
  const f=make();let release;
  f.u.check=()=>new Promise(resolve=>{release=()=>resolve({isUpdateAvailable:true,updateInfo:{version:'0.2.0'}});});
  const a=f.up.check(),b=f.up.check();
  assert.equal(a,b);await flush();assert.equal(f.u.calls.check,1);
  release();await a;assert.equal(f.up.state().phase,'available');
  f.u.check=()=>({isUpdateAvailable:true,updateInfo:{version:'0.2.0'}});
  await f.up.check();assert.equal(f.u.calls.check,2);
});

test('a failed background check keeps the earlier state and never shows an error',async()=>{
  const f=make();await f.up.check();
  f.u.check=()=>{const e=new Error('getaddrinfo ENOTFOUND github.com');e.code='ENOTFOUND';throw e;};
  f.seen.length=0;
  assert.equal(await f.up.check(),'failed');
  assert.equal(f.up.state().phase,'available');assert.equal(f.up.state().version,'0.2.0');
  assert.deepEqual(f.seen,[],'a known version stays available while it is checked again (no blinking)');
  const g=make();g.u.check=()=>{throw new Error('offline');};
  await g.up.check();assert.deepEqual(g.seen.map(s=>s.phase),['checking','idle']);
  assert.ok(g.logs.includes('update:check-failed'));
});

test('the updater\'s own error event (also sent for a failed check) does not throw or change the state',async()=>{
  const f=make();
  f.u.check=()=>{const e=new Error('boom');f.u.emit('error',e,'stack /Users/x');throw e;};
  await f.up.check();assert.equal(f.up.state().phase,'idle');
});

test('download: progress rounded to whole numbers 0..100, sent only when they change, then downloaded',async()=>{
  const f=make();await f.up.check();let finish;
  f.u.download=()=>new Promise(resolve=>{finish=resolve;});
  const d=f.up.download();
  assert.equal(f.up.state().phase,'downloading');assert.equal(f.up.state().percent,0);
  f.seen.length=0;
  f.u.emit('download-progress',{percent:12.3,transferred:1,total:10});
  f.u.emit('download-progress',{percent:12.9});
  f.u.emit('download-progress',{percent:40.01});
  assert.deepEqual(f.seen.map(s=>s.percent),[12,13,40]);
  finish([]);await d;
  assert.deepEqual(f.up.state(),{inApp:true,phase:'downloaded',current:'0.1.2',version:'0.2.0',percent:null,reason:null});
  assert.equal(f.u.calls.download,1);
});

test('download errors become a kind only: verify, network, unknown — never the text or a path',async()=>{
  const cases=[[Object.assign(new Error('sha512 checksum mismatch, expected abc, got def'),{code:'ERR_CHECKSUM_MISMATCH'}),'verify'],
    [Object.assign(new Error('connect ECONNRESET'),{code:'ECONNRESET'}),'network'],
    [new Error('net::ERR_INTERNET_DISCONNECTED'),'network'],
    [Object.assign(new Error('HttpError: 404'),{statusCode:404}),'network'],
    [new Error('EACCES: permission denied, open \'/Users/someone/Library/Caches/x.zip\''),'unknown']];
  for(const [error,kind] of cases){
    const f=make();await f.up.check();f.u.download=()=>Promise.reject(error);
    await f.up.download();
    const s=f.up.state();
    assert.deepEqual(Object.keys(s).sort(),[...KEYS].sort());
    assert.equal(s.phase,'error');assert.equal(s.reason,kind);assert.equal(s.version,'0.2.0');
    assert.doesNotMatch(JSON.stringify(s),/Users|sha512|ECONN|net::|404/);
    assert.ok(f.logs.every(line=>/^update:[a-z-]+$/.test(line)),f.logs.join());
    assert.equal(errorKind(error),kind);
  }
});

test('retry from an error calls download again and reaches downloaded',async()=>{
  const f=make();await f.up.check();
  f.u.download=()=>Promise.reject(Object.assign(new Error('x'),{code:'ETIMEDOUT'}));
  await f.up.download();assert.equal(f.up.state().reason,'network');
  f.u.download=()=>Promise.resolve([]);
  await f.up.download();assert.equal(f.up.state().phase,'downloaded');assert.equal(f.u.calls.download,2);
});

test('background checks are skipped while downloading, after downloading and on an error',async()=>{
  const f=make();await f.up.check();let finish;
  f.u.download=()=>new Promise(resolve=>{finish=resolve;});
  const d=f.up.download();
  assert.equal(await f.up.check(),'skipped');
  finish([]);await d;
  assert.equal(await f.up.check(),'skipped');assert.equal(f.up.state().phase,'downloaded');
  const g=make();await g.up.check();g.u.download=()=>Promise.reject(new Error('x'));await g.up.download();
  assert.equal(await g.up.check(),'skipped');assert.equal(g.up.state().phase,'error');
  assert.equal(f.u.calls.check,1);
});

test('a check answer that arrives after the user started a download does not overwrite it',async()=>{
  const f=make();await f.up.check();let answer;
  f.u.check=()=>new Promise(resolve=>{answer=resolve;});
  const c=f.up.check();await flush();
  f.u.download=()=>new Promise(()=>{});f.up.download();
  answer({isUpdateAvailable:false,updateInfo:{version:'0.1.2'}});await c;
  assert.equal(f.up.state().phase,'downloading');
});

test('without in-app install: GitHub releases/latest announces a new version only (idle, checking, available)',async()=>{
  let calls=0;
  const f=make({inApp:false,checkRelease:async current=>{calls++;assert.equal(current,'0.1.2');return {state:'available',version:'v0.2.0',url:'https://github.com/WJY-ador/personal-mycrm/releases/tag/v0.2.0'};}});
  await f.up.check();
  assert.deepEqual(f.up.state(),{inApp:false,phase:'available',current:'0.1.2',version:'0.2.0',percent:null,reason:null});
  assert.doesNotMatch(JSON.stringify(f.up.state()),/github|https/);
  await f.up.download();await f.up.install();
  assert.equal(f.up.state().phase,'available');assert.deepEqual(f.order,[]);
  const g=make({inApp:false,checkRelease:async()=>({state:'current',version:'v0.1.2'})});
  await g.up.check();assert.equal(g.up.state().phase,'idle');
  const h=make({inApp:false,checkRelease:async()=>({state:'not-published'})});
  await h.up.check();assert.equal(h.up.state().phase,'idle');
  assert.equal(calls,1);
  assert.ok([...f.seen,...g.seen,...h.seen].every(s=>['idle','checking','available'].includes(s.phase)));
});

test('checks run at start, every 6 hours and on resume; dispose stops them',async()=>{
  const pm=new EventEmitter();
  const f=make({powerMonitor:pm});f.u.check=()=>({isUpdateAvailable:false,updateInfo:{version:'0.1.2'}});
  f.up.start();await flush();assert.equal(f.u.calls.check,1);
  f.up.start();await flush();assert.equal(f.u.calls.check,1,'start runs once');
  assert.equal(f.timers.intervals.length,1);assert.equal(f.timers.intervals[0].ms,CHECK_EVERY_MS);assert.equal(CHECK_EVERY_MS,6*60*60*1000);
  f.timers.intervals[0].fn();await flush();assert.equal(f.u.calls.check,2);
  pm.emit('resume');await flush();assert.equal(f.u.calls.check,3);
  f.up.dispose();assert.equal(pm.listenerCount('resume'),0);assert.ok(f.timers.cleared.includes('interval'));
});

test('install: main prepares first (lock, stop, wait), then quitAndInstall(silent, run after)',async()=>{
  const order=[];const f=make({order});await toDownloaded(f);
  f.u.quit=()=>{order.push('quitAndInstall');f.main.quitting=true;};
  const run=f.up.install();await flush();
  assert.deepEqual(order,['prepare','quitAndInstall']);
  assert.deepEqual(f.u.calls.quit,[[true,true]]);
  assert.equal(f.timers.timeouts.at(-1).ms,INSTALL_WAIT_MS);
  // The app is quitting: the wait running out changes nothing.
  f.timers.timeouts.at(-1).fn();await run;
  assert.equal(f.main.aborted,0);assert.equal(f.up.state().phase,'downloaded');
});

test('install: an error event during quitAndInstall (Windows) undoes the install and reports error install',async()=>{
  const order=[];const f=make({order});await toDownloaded(f);
  f.u.quit=()=>{f.u.emit('error',new Error('spawn /Users/x/installer.exe EACCES'));};
  await f.up.install();
  assert.deepEqual(order,['prepare','abort']);
  assert.deepEqual(f.up.state(),{inApp:true,phase:'error',current:'0.1.2',version:'0.2.0',percent:null,reason:'install'});
  assert.ok(f.logs.includes('update:install-failed'));
});

test('install: a late error event (macOS Squirrel refuses the update) undoes the install',async()=>{
  const order=[];const f=make({order});await toDownloaded(f);
  const run=f.up.install();await flush();
  assert.deepEqual(order,['prepare']);assert.equal(f.up.state().phase,'downloaded');
  f.u.emit('error',new Error('Code signature at URL file:///private/var/folders/x did not pass validation'));
  await run;
  assert.deepEqual(order,['prepare','abort']);assert.equal(f.up.state().reason,'install');
  assert.doesNotMatch(JSON.stringify(f.up.state()),/private|signature/);
});

test('install: the app not quitting within the wait undoes the install',async()=>{
  const order=[];const f=make({order});await toDownloaded(f);
  const run=f.up.install();await flush();
  f.timers.timeouts.at(-1).fn();await run;
  assert.deepEqual(order,['prepare','abort']);assert.equal(f.up.state().reason,'install');
});

test('install: quitAndInstall throwing undoes the install',async()=>{
  const order=[];const f=make({order});await toDownloaded(f);
  f.u.quit=()=>{throw new Error('No update filepath provided');};
  await f.up.install();
  assert.deepEqual(order,['prepare','abort']);assert.equal(f.up.state().reason,'install');
});

test('install: a busy app refuses before anything stops (error install); a quitting app is left alone',async()=>{
  const f=make();await toDownloaded(f);f.main.prepareError='busy';
  await f.up.install();
  assert.equal(f.u.calls.quit.length,0);assert.equal(f.up.state().reason,'install');
  const g=make();await toDownloaded(g);g.main.prepareError='closing';
  await g.up.install();
  assert.equal(g.u.calls.quit.length,0);assert.equal(g.up.state().phase,'downloaded');
});

test('install runs once at a time and only after a download',async()=>{
  const order=[];const f=make({order});
  await f.up.install();assert.deepEqual(order,[]);
  await f.up.check();await f.up.install();assert.deepEqual(order,[]);
  await f.up.download();
  const a=f.up.install();f.up.install();await flush();
  assert.deepEqual(order,['prepare']);assert.equal(f.u.calls.quit.length,1);
  assert.equal(await f.up.check(),'skipped');await f.up.download();assert.equal(f.u.calls.download,1);
  f.u.emit('error',new Error('x'));await a;
  // After the undo the retry path is download() again (contract: error → 다시 시도 → download()).
  await f.up.download();assert.equal(f.up.state().phase,'downloaded');
});

test('the state never carries more than the contract fields',async()=>{
  const f=make();await f.up.check();await f.up.download();
  for(const s of f.seen){assert.deepEqual(Object.keys(s).sort(),[...KEYS].sort());assert.ok(Object.isFrozen(s));}
});

test('contract shape: the web band accepts every state, GitHub tags and electron-updater versions alike',async()=>{
  // Without in-app install: GitHub tag_name is vX.Y.Z; the state carries X.Y.Z. A tag not above current is no update.
  const gh=make({inApp:false,checkRelease:async()=>({state:'available',version:'v0.2.0'})});
  await gh.up.check();assert.equal(gh.up.state().version,'0.2.0');assert.equal(contractProblem(gh.up.state()),null);
  const same=make({inApp:false,checkRelease:async()=>({state:'available',version:'v0.1.2'})});
  await same.up.check();assert.equal(same.up.state().phase,'idle');
  const pre=make({inApp:false,checkRelease:async()=>({state:'available',version:'v0.2.0-beta.1'})});
  await pre.up.check();assert.equal(pre.up.state().phase,'idle');
  // electron-updater: a v-prefixed, equal, older or prerelease version never becomes 'available'.
  for(const [version,phase] of [['v0.2.0','available'],['0.1.2','idle'],['0.1.1','idle'],['0.2.0-beta.1','idle']]){
    const f=make();f.u.check=()=>({isUpdateAvailable:true,updateInfo:{version}});
    await f.up.check();assert.equal(f.up.state().phase,phase,version);assert.equal(contractProblem(f.up.state()),null);
  }
  // Fractional, negative and over-100 progress stay whole numbers in 0..100.
  const p=make();await p.up.check();let finish;p.u.download=()=>new Promise(resolve=>{finish=resolve;});
  const d=p.up.download();
  for(const percent of [-3,0.4,49.5,99.6,100.2,NaN,'x'])p.u.emit('download-progress',{percent});
  assert.deepEqual(p.seen.filter(s=>s.phase==='downloading').map(s=>s.percent),[0,50,100]);
  finish([]);await d;assert.equal(p.up.state().percent,null);
  // A failed install (0.2.4 undo) reports reason install; the other failures report their kind.
  const i=make();await i.up.check();await i.up.download();i.u.quit=()=>i.u.emit('error',new Error('x'));
  await i.up.install();assert.equal(i.up.state().reason,'install');assert.equal(contractProblem(i.up.state()),null);
  // Every key is present in every phase, unused ones as null.
  for(const s of [...gh.seen,...p.seen,...i.seen])assert.equal(contractProblem(s),null,JSON.stringify(s));
});
