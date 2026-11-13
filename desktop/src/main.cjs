'use strict';
// MyCRM app main process (spec 2026-11-13): one window, the hosted dashboard. No connection window: this PC connects by
// itself with the app's login session (connector.cjs), the dashboard's "이 PC" line and AI panel talk to the app through
// dash-bridge.cjs, the AI connection is the provider CLI's own login (ai-link.cjs), and failures become automatic error
// reports (error-report.cjs). The tray keeps: open the dashboard, sync now, stop or start, quit.
const {app,BrowserWindow,Menu,Tray,nativeImage,ipcMain,shell,dialog,net,session,Notification,powerMonitor,autoUpdater:nativeUpdater} = require('electron');
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {PACKAGE,HOSTED,DASHBOARD,inAppAllowed,externalHttps,agentHome,checkUpdate} = require('./policy.cjs');
const {Supervisor,diagnosticLog} = require('./supervisor.cjs');
const {OutputTail,failureLine,hasLiveProcess} = require('./sidecar.cjs');
const handoff = require('./handoff.cjs');
const grants = require('./grants.cjs');
const {Connector,ConnectError} = require('./connector.cjs');
const {AutoRun,readPreferences,startConnection,startAutomatically,restartChat,startProcesses:launchProcesses}=require('./autorun.cjs');
const {AutoSync}=require('./autosync.cjs');
const {createUpdater,inAppSupported,trustedSender,registerDashboardBridge,CHANNELS:UPDATE}=require('./updater.cjs');
const {DASH}=require('./desktop-contract.cjs');
const {registerDesktopBridge}=require('./dash-bridge.cjs');
const {createReporter}=require('./error-report.cjs');
const {classify,syncOutcome,message}=require('./failures.cjs');
const {createAiLink}=require('./ai-link.cjs');
const {createPcState}=require('./pc-state.cjs');
let dash,tray,supervisor,log,prefs={},binary,home,settingsFile,quitting=false,ready=false;
let busy=false,trayLive=null,connector=null,pollTimer=null,autorun=null,autosync=null,reporter=null,aiLink=null,pcState=null;
const commands=new Map();   // running sidecar commands: child -> first argument (ai-connect waits for a browser login)
// installing: an in-app update is quitting the app (set on 'before-quit-for-update'); the window's close no longer hides it.
let updater=null,installing=false;
function stopProcesses(options){return supervisor.stopAll(options);}
// Login handoff: one pending login (verifier never leaves memory) and a deep link that arrived before the window existed.
let pendingLogin=null,queuedLink=handoff.findLink(process.argv);
// macOS delivers mycrm:// via open-url, also when the link itself launches the app — register before 'ready'.
app.on('will-finish-launching',()=>app.on('open-url',(event,url)=>{event.preventDefault();deepLink(url);}));
if(!app.requestSingleInstanceLock()) app.quit();
else {
  // Windows (and Linux) hand the link to the running instance as an argument of the second launch.
  app.on('second-instance',(_event,argv)=>{const link=handoff.findLink(argv);if(link)deepLink(link);else showDashboard();});
  if(process.defaultApp&&process.argv.length>=2)app.setAsDefaultProtocolClient('mycrm',process.execPath,[path.resolve(process.argv[1])]);
  else app.setAsDefaultProtocolClient('mycrm');
  app.whenReady().then(initialize).catch(()=> {dialog.showErrorBox('MyCRM','앱을 시작하지 못했어요. 다시 설치하거나 지원팀에 문의해 주세요.');app.exit(1);});
}
function preferences() {
  try {return readPreferences(fs.readFileSync(settingsFile,'utf8'));} catch {return {allowCli:false};}
}
function savePreferences() {
  const tmp=settingsFile+'.tmp';fs.writeFileSync(tmp,JSON.stringify(prefs),{mode:0o600});fs.renameSync(tmp,settingsFile);
}
function connection() {
  try {
    const file=path.join(home,'config.json');
    if(fs.statSync(file).size>1024*1024) throw new Error('large');
    const c=JSON.parse(fs.readFileSync(file,'utf8'));
    return {connected:typeof c.source_instance_id==='string' && !!c.source_instance_id,cliConfigured:typeof c.summary?.cli_path==='string' && path.isAbsolute(c.summary.cli_path),
      expires:c.token_expires_at||null,deviceLabel:typeof c.device_label==='string'?c.device_label:''};
  } catch {return {connected:false,cliConfigured:false,expires:null,deviceLabel:''};}
}
// The dashboard hears an empty signal and reads the state again (dash-preload.cjs).
function signal(channel){if(dash&&!dash.isDestroyed())dash.webContents.send(channel);}
// Process states that end a process for good become an error report once per change (agent/chat, viewer, jobs).
const ENDED=new Set(['failed','authentication-required']);let lastStates={};
function watchProcesses(){
  const now=supervisor?.snapshot()||{},before=lastStates;
  lastStates=Object.fromEntries(Object.entries(now).map(([k,v])=>[k,v.state]));
  for(const [name,p] of Object.entries(now)){
    if(!ENDED.has(p.state)||before[name]===p.state)continue;
    if(['chat','viewer','jobs'].includes(name))reporter?.report('agent/'+name,p.state,{exit:p.code});
    if(name==='chat'&&p.state==='authentication-required')recoverChat();
  }
}
function changed(){refreshTray();autorun?.nudge('change');signal(DASH.pcChanged);watchProcesses();}
function trayMenu(live){return Menu.buildFromTemplate([{label:'대시보드 열기',click:showDashboard},{label:'지금 동기화',click:()=>{runSync().then(trayResult,()=>{});}},
  {type:'separator'},live?{label:'중지',click:()=>exclusively(userStop).catch(()=>{})}:{label:'시작',click:()=>exclusively(userStart).catch(()=>{})},
  {label:'종료',click:()=>app.quit()}]);}
function refreshTray(){if(!tray||tray.isDestroyed())return;const live=hasLiveProcess(supervisor?.snapshot());if(live===trayLive)return;trayLive=live;tray.setContextMenu(trayMenu(live));}
function showDashboard(){if(dash&&!dash.isDestroyed()){dash.show();dash.focus();}}
// Links that leave the hosted origin go to the system browser, https only.
function leave(url){if(externalHttps(url))shell.openExternal(url).catch(()=>{});}
// Order matters: a login start is taken over first; it is same-origin and would otherwise load in-app,
// then redirect to AuthKit outside the allow list and start a browser login that never comes back.
function guard(event,url){
  // A mycrm://connection?step=… link from an older web page used to open the connection window: it shows the dashboard.
  if(handoff.parseSetupLink(url)){event.preventDefault();raiseForLink(showDashboard);return;}
  if(handoff.isLoginNav(url,HOSTED)){event.preventDefault();startLogin(handoff.wantsFresh(url));return;}
  if(inAppAllowed(url))return;event.preventDefault();leave(url);
}
const NOTICES={
  waiting:['브라우저에서 로그인해 주세요','기본 브라우저에서 로그인을 마치면 이 창으로 돌아와요.','브라우저 다시 열기'],
  failed:['브라우저를 열지 못했어요','기본 브라우저를 확인한 뒤 다시 시도해 주세요.','다시 시도'],
  expired:['로그인 시간이 지났어요','로그인을 10분 안에 마치지 못했어요. 다시 로그인해 주세요.','다시 로그인'],
  none:['로그인을 이어 가지 못했어요','로그인을 시작한 뒤 앱이 다시 시작됐거나, 이미 처리한 응답이에요. 다시 로그인해 주세요.','다시 로그인'],
  mismatch:['다른 로그인 응답이에요','이 앱에서 시작한 로그인이 아니라서 사용하지 않았어요. 다시 로그인해 주세요.','다시 로그인'],
  invalid:['로그인 응답을 읽지 못했어요','주소 형식이 맞지 않아요. 다시 로그인해 주세요.','다시 로그인'],
};
// Fixed text only — never the link, code, state or verifier. The buttons are plain links the guard handles:
// /login starts a new handoff, / returns to the hosted start page.
function notice(kind){
  if(!dash||dash.isDestroyed())return;
  const [title,body,retry]=NOTICES[kind];
  const html='<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"><title>MyCRM</title>'
    +'<style>body{margin:0;font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#1f2328;background:#f6f7f9;display:grid;place-items:center;min-height:100vh}'
    +'main{max-width:420px;padding:32px;background:#fff;border:1px solid #e4e7eb;border-radius:12px;text-align:center}h1{font-size:20px;margin:0 0 8px}p{margin:0 0 20px;color:#57606a}'
    +'a{display:inline-block;margin:0 6px;padding:8px 14px;border-radius:8px;text-decoration:none;border:1px solid #d0d7de;color:#1f2328}a.primary{background:#1f6feb;border-color:#1f6feb;color:#fff}</style></head>'
    +`<body><main><h1>${title}</h1><p>${body}</p><a class="primary" href="${new URL('login',HOSTED).href}">${retry}</a><a href="${HOSTED}">처음 화면으로</a></main></body></html>`;
  dash.loadURL('data:text/html;charset=utf-8,'+encodeURIComponent(html)).catch(()=>{});
}
function startLogin(fresh=false){
  pendingLogin=handoff.begin();
  log?.('login','started');
  // HOSTED is the fixed production origin (or a loopback E2E server), so this is not routed through leave().
  shell.openExternal(handoff.loginUrl(HOSTED,pendingLogin.challenge,pendingLogin.state,fresh)).then(()=>notice('waiting'),()=>{pendingLogin=null;notice('failed');});
}
// R-J5: a deep link brings the window to the front at most once per 2 seconds (any web page can open mycrm://).
const linkRaise=handoff.focusLimiter();
function raiseForLink(showWindow){if(!linkRaise())return;showWindow();app.focus({steal:true});}
function deepLink(raw){
  if(!dash||dash.isDestroyed()){queuedLink=raw;return;}
  raiseForLink(showDashboard);
  if(handoff.parseSetupLink(raw))return;
  const parsed=handoff.parseCallback(raw),result=handoff.accept(pendingLogin,parsed);
  if(result!=='ok'){
    if(result==='expired')pendingLogin=null;
    log?.('login','rejected-'+result);notice({expired:'expired',format:'invalid',none:'none',state:'mismatch'}[result]);return;
  }
  const {verifier}=pendingLogin;pendingLogin=null; // one-shot: cleared before the claim is sent, whatever its outcome
  log?.('login','claim');
  const claim=handoff.claimRequest(HOSTED,parsed.code,verifier,parsed.state);
  // Spec §1.2: logging in connects this PC — no token, no device screen.
  dash.loadURL(claim.url,claim.options).then(()=>connector?.poll('login')).then(()=>autoDevice('login'),()=>{});
}
function history(wc){return wc.navigationHistory||{canGoBack:()=>wc.canGoBack(),canGoForward:()=>wc.canGoForward(),goBack:()=>wc.goBack(),goForward:()=>wc.goForward()};}
function dashNav(action){
  if(!dash||dash.isDestroyed())return;const wc=dash.webContents,h=history(wc);
  if(action==='reload')wc.reload();else if(action==='back'&&h.canGoBack())h.goBack();else if(action==='forward'&&h.canGoForward())h.goForward();
}
function openInBrowser(){
  const current=dash&&!dash.isDestroyed()?dash.webContents.getURL():'';
  let target=HOSTED;try{if(new URL(current).origin===new URL(HOSTED).origin)target=current;}catch{}
  leave(target);
}
function createDashboard(){
  dash=new BrowserWindow({width:1200,height:800,minWidth:720,minHeight:520,title:'MyCRM',backgroundColor:'#ffffff',webPreferences:{partition:'persist:dashboard',preload:path.join(__dirname,'dash-preload.cjs'),nodeIntegration:false,contextIsolation:true,sandbox:true,webSecurity:true}});
  const wc=dash.webContents;
  wc.session.setPermissionRequestHandler((_wc,_p,callback)=>callback(false));
  wc.setWindowOpenHandler(({url})=>{if(handoff.parseSetupLink(url))raiseForLink(showDashboard);else if(handoff.isLoginNav(url,HOSTED))startLogin(handoff.wantsFresh(url));else if(inAppAllowed(url))wc.loadURL(url).catch(()=>{});else leave(url);return {action:'deny'};});
  wc.on('will-navigate',(e,url)=>guard(e,e.url||url));
  // Subframes (captcha, provider widgets) are not gated; only top-level navigation is.
  wc.on('will-redirect',(e,url,_inPlace,isMainFrame)=>{if(e.isMainFrame??isMainFrame)guard(e,e.url||url);});
  dash.on('close',event=>{if(!quitting&&!installing){event.preventDefault();dash.hide();}});
  dash.on('focus',()=>{connector?.poll('focus').then(()=>autoDevice('timer'));autorun?.nudge('focus');});
  // A login callback that launched the app loads its claim (deepLink); anything else loads the dashboard.
  const link=queuedLink;queuedLink=null;
  if(link&&!handoff.parseSetupLink(link))deepLink(link);else dash.loadURL(DASHBOARD).catch(()=>{});
}
// timeoutMs: run-once 10 minutes, ai-connect 11 minutes (a browser login), others 45 seconds.
// The result keeps the last output line for the caller (ai-* answer with one JSON line); desktop.log keeps exit codes only.
function command(args,input,extraEnv={},timeoutMs=null) {
  return new Promise((resolve,reject)=> {
    const env={...process.env,PYTHONNOUSERSITE:'1',PYTHONDONTWRITEBYTECODE:'1',...extraEnv};
    delete env.MYCRM_JOBS_ALLOW_REAL_CLI;
    const child=spawn(binary,['--home',home,...args],{env,shell:false,windowsHide:true,stdio:['pipe','pipe','pipe']});
    commands.set(child,args[0]);let done=false;const output=new OutputTail();
    // The detail is shown only through fixed kinds and codes (failures.cjs); desktop.log keeps exit codes, never sidecar text.
    const finish=(err,code)=>{if(done)return;done=true;clearTimeout(timer);commands.delete(child);
      if(err){reject(new Error(err));return;}
      const text=output.text();resolve({code,detail:failureLine(code,text),last:failureLine(1,text)});};
    const timer=setTimeout(()=>{child.kill('SIGTERM');finish('command-timeout');},timeoutMs||(args[0]==='run-once'?600000:45000));
    child.stdout.on('data',chunk=>output.push(chunk));child.stderr.on('data',chunk=>output.push(chunk));child.stdin.on('error',()=>{});
    child.once('error',()=>finish('agent-unavailable'));child.once('close',code=>finish(null,code));
    child.stdin.end(input ? input+'\n' : '');
  });
}
// A provider login can wait for the browser for minutes; quitting or an update install does not wait for it.
function abortLogins(){for(const [child,name] of commands)if(name==='ai-connect'){try{child.kill('SIGTERM');}catch{}}}
// Requests for the PC connection run in the main process with the dashboard session (persist:dashboard): the same
// crm_session cookie as the dashboard window, plus X-MyCRM-Desktop. No Origin header is sent unless the caller adds it.
// Redirects are not followed. The body is read only as JSON and dropped by the caller after use; nothing here logs it.
const BODY_LIMIT=64*1024;
function request(method,url,body,extraHeaders={}){
  return new Promise(resolve=>{
    let done=false,timer=null;const finish=value=>{if(done)return;done=true;clearTimeout(timer);resolve(value);};
    let req;
    try{req=net.request({method,url,session:session.fromPartition('persist:dashboard'),useSessionCookies:true,redirect:'manual'});}
    catch{finish({status:0,body:null});return;}
    for(const [k,v] of Object.entries(grants.HEADERS))req.setHeader(k,v);
    for(const [k,v] of Object.entries(extraHeaders))req.setHeader(k,v);
    if(body!==undefined&&body!==null&&!extraHeaders['Content-Type']&&!extraHeaders['content-type'])req.setHeader('Content-Type','application/json');
    timer=setTimeout(()=>{req.abort();finish({status:0,body:null});},20000);
    req.on('redirect',status=>{req.abort();finish({status,body:null});});
    req.on('response',res=>{
      const chunks=[];let size=0;
      res.on('data',chunk=>{size+=chunk.length;if(size>BODY_LIMIT){req.abort();finish({status:0,body:null});return;}chunks.push(chunk);});
      res.on('end',()=>{let parsed=null;try{parsed=JSON.parse(Buffer.concat(chunks).toString('utf8'));}catch{}
        const ra=res.headers['retry-after'];finish({status:res.statusCode,body:parsed,retryAfter:Array.isArray(ra)?ra[0]:ra});});
      res.on('error',()=>finish({status:0,body:null}));
    });
    req.on('error',()=>finish({status:0,body:null}));
    req.end(body===undefined||body===null?undefined:JSON.stringify(body));
  });
}
// Chat starts with no approval channel to the app (spec §1.3): the agent checks the AI connection itself at its start.
async function startChatAgent(){supervisor.start('chat',['chat']);}
// One start for the tray and the automatic start (autorun.cjs). The caller holds the app lock.
const startDeps={get supervisor(){return supervisor;},prefs:()=>prefs,connection:()=>connection(),
  ready:()=>ready,startChat:()=>startChatAgent()};
function startProcesses(names){return launchProcesses(names,startDeps);}
// After an AI connection change: the running chat picks it up only on a fresh start. Retried while another task holds
// the app lock (a sync), at most for a minute.
async function chatAfterAiChange(){
  for(let attempt=0;attempt<12&&!quitting;attempt++){
    try{await exclusively(()=>restartChat(startDeps));return;}
    catch(e){if(e?.message!=='busy')throw e;await new Promise(resolve=>setTimeout(resolve,5000));}
  }
  // The agent still reads the local mark on every turn, so a disconnect holds without this restart.
  log('chat','restart-gave-up');
}
// The user's stop and start (tray). A stop is recorded first so the automatic start cannot bring it back in this run.
async function userStop(){autorun?.userStopped();await stopProcesses();}
async function userStart(){await startConnection(startDeps);autorun.manualStarted();}
// Puts an issued token into the sidecar through stdin. A device token replaces the connection, so running processes
// stop first and the ones that were running start again afterwards. The caller holds the app lock.
async function install(scope,token){
  const live=scope==='device'?Object.entries(supervisor.snapshot()).filter(([,p])=>hasLiveProcess({p})).map(([k])=>k):[];
  if(scope==='device')await stopProcesses();
  try{return await command(grants.sidecarArgs(scope,HOSTED),token);}
  catch{return {code:-1,detail:null};}
  finally{if(live.length&&connection().connected)await startProcesses(live).catch(()=>log('chat','restart-failed'));}
}
// The local device belongs to another account (M3): remove its token from the key store, keep data and HMAC key.
async function forgetLocal(){
  await stopProcesses();
  try{const {code}=await command(['disconnect','--local-only']);log('connect','forget-local',code);return {code};}
  catch{return {code:-1};}
}
// In-app update install, before quitAndInstall (plan 0.2.4). Takes the app lock and keeps it until the app quits or
// abort(): busy also holds the automatic start, connection delivery and the sync. The processes stop the way the
// token install does — not userStop, so the saved autoRun is unchanged and the reinstalled app starts them again.
// The window lets the updater close it only from 'before-quit-for-update' (initialize): on macOS Squirrel first fetches
// and checks the update, and a window closed before that would be gone if it fails. before-quit then runs the usual
// cleanup (it is not skipped, because quitting is not set here). abort() undoes this when the app did not quit.
async function prepareInstall(){
  if(busy||quitting||installing)throw new Error('busy');
  busy=true;changed();
  const live=Object.entries(supervisor.snapshot()).filter(([,p])=>hasLiveProcess({p})).map(([k])=>k);
  const restart=async()=>{if(live.length&&!quitting&&connection().connected)await startProcesses(live).catch(()=>log('update','restart-failed'));};
  const release=()=>{busy=false;changed();};
  try{
    await stopProcesses();
    abortLogins();
    await Promise.all([...commands.keys()].map(child=>new Promise(resolve=>child.once('close',resolve))));
  }catch(e){await restart();release();throw e;}
  if(quitting){release();throw new Error('closing');}
  return {quitting:()=>quitting,abort:async()=>{installing=false;await restart();release();}};
}
function notify({title,body}){try{if(Notification.isSupported())new Notification({title,body}).show();}catch{}}
function jsonStore(file){
  return {
    load:()=>{try{return fs.readFileSync(file,'utf8');}catch{return null;}},
    save:record=>{try{const tmp=file+'.tmp';fs.writeFileSync(tmp,JSON.stringify(record),{mode:0o600});fs.renameSync(tmp,file);}catch{log('app','store-failed');}},
  };
}
async function exclusively(fn) {
  if(busy||quitting)throw new Error('busy');busy=true;changed();
  try{return await fn();}finally{busy=false;changed();}
}
// The sync (button, tray, every hour). It connects this PC first when it has no usable device token, and a run halted on
// a refused token gets a fresh one with the login session once, then resumes (spec §1.2). The caller holds the app lock.
async function syncOnce(){
  if(!ready)throw new Error('agent-unavailable');
  if(connector.needsAuto())await connector.autoConnect();
  let {code,detail}=await command(grants.runOnceArgs());log('sync','completed',code);
  if(code===3&&/--resume auth/.test(detail||'')){
    await connector.autoConnect();
    ({code,detail}=await command(grants.runOnceArgs(true)));log('sync','resumed',code);
  }
  return {code,detail};
}
// One sync with its outcome recorded for the "이 PC" line and, when it is the app's to report, an error report.
// The agent reports its own halts and run failures (exit 1 and 3) with the device token; the app reports what the agent
// could not: a failed automatic connection, a missing or stuck sidecar, an exit by signal.
async function runSync(){
  let outcome,stage=null,exit;
  try{
    const r=await exclusively(()=>syncOnce());
    outcome=syncOutcome(r);exit=r.code;
    if(![0,1,3].includes(r.code))stage='sync/run-once';
  }catch(e){
    outcome=classify(e);
    if(outcome.kind!=='busy'&&outcome.kind!=='login'&&outcome.kind!=='disconnected')stage=e instanceof ConnectError?'sync/connect':'sync/run-once';
  }
  // desktop.log: the stage, the kind and its fixed code (failures.cjs), and the exit code.
  log('sync',outcome.kind==='ok'?'ok':'failed-'+outcome.kind+(outcome.code?'-'+outcome.code:''),exit);
  if(outcome.kind!=='busy')pcState.record(outcome);
  if(stage&&outcome.code)reporter.report(stage,outcome.code,{exit});
  return outcome;
}
function trayResult(outcome){if(outcome.kind!=='ok')notify({title:'동기화하지 못했어요',body:message(outcome)});}
// Automatic connection outside a sync (spec §1.2): at start, after a login and on the poll timer. A new token starts
// the processes the person did not stop.
async function autoDevice(reason){
  if(!ready||quitting||installing||!connector)return;
  try{
    const result=await connector.ensureDevice(reason);
    if(result==='issued'&&prefs.autoRun!==false)autorun.nudge('timer');
  }catch(e){
    const f=classify(e);log('connect','auto-failed-'+f.kind+(f.code?'-'+f.code:''));
    if((f.kind==='rejected'||f.kind==='unknown')&&f.code&&f.code!=='RATE-LIMIT')reporter.report('connect/auto',f.code);
  }
}
// The chat agent stopped because its token was refused twice: get a fresh token with the login session and start it
// again, at most once an hour.
let chatRecoverAt=0;
function recoverChat(){
  const now=Date.now();if(now<chatRecoverAt||prefs.autoRun===false||!ready)return;chatRecoverAt=now+60*60*1000;
  exclusively(async()=>{await connector.autoConnect();await startProcesses(['chat']);})
    .then(()=>log('chat','recovered'),e=>log('chat','recover-failed-'+classify(e).kind));
}
async function compatibleBinary() {
  if(!fs.existsSync(binary))return false;
  return new Promise(resolve=> {
    let output='',done=false;
    const child=spawn(binary,['--desktop-info'],{shell:false,windowsHide:true,stdio:['ignore','pipe','ignore']});
    const finish=value=>{if(done)return;done=true;clearTimeout(timer);resolve(value);};
    const timer=setTimeout(()=>{child.kill('SIGTERM');finish(false);},15000);
    child.stdout.on('data',chunk=>{output+=chunk.toString();if(output.length>4096){child.kill('SIGTERM');finish(false);}});
    child.once('error',()=>finish(false));
    child.once('close',code=>{try{const j=JSON.parse(output);finish(code===0&&j.protocol===1&&j.app_version===app.getVersion());}catch{finish(false);}});
  });
}
async function initialize(){
  app.setAppUserModelId('io.mycrm.desktop');
  const userData=app.getPath('userData');fs.mkdirSync(userData,{recursive:true,mode:0o700});
  settingsFile=path.join(userData,'desktop-preferences.json');prefs=preferences();home=agentHome();
  binary=app.isPackaged?path.join(process.resourcesPath,'agent',process.platform==='win32'?'mycrm-agent.exe':'mycrm-agent'):path.resolve(__dirname,'../../release/agent',process.platform==='win32'?'mycrm-agent.exe':'mycrm-agent');
  log=diagnosticLog(path.join(userData,'logs'));
  reporter=createReporter({request,hosted:HOSTED,version:app.getVersion(),platform:process.platform,log});
  ready=await compatibleBinary();
  if(!ready){log('app','agent-incompatible');reporter.report('app/command','agent-incompatible');}
  supervisor=new Supervisor({binary,home,log,changed});
  connector=new Connector({hosted:HOSTED,request,store:jsonStore(path.join(userData,'desktop-connection.json')),install,forgetLocal,
    exclusive:exclusively,canDeliver:()=>ready&&!busy&&!quitting,connection,notify,log,client:grants.clientInfo(os.hostname(),process.platform),changed});
  pcState=createPcState({store:jsonStore(path.join(userData,'desktop-sync.json')),connected:()=>connection().connected,
    syncing:()=>busy,blocked:()=>connector.blockReason(),version:app.getVersion(),changed:()=>signal(DASH.pcChanged)});
  aiLink=createAiLink({run:(args,{timeoutMs})=>ready?command(args,undefined,{},timeoutMs):Promise.reject(new Error('agent-unavailable')),
    restartChat:chatAfterAiChange,report:(stage,code)=>reporter.report(stage,code),log,changed:()=>signal(DASH.aiChanged)});
  // Opening the app starts the processes, unless the user stopped them last time.
  autorun=new AutoRun({wanted:()=>prefs.autoRun!==false,connected:()=>connection().connected,idle:()=>!busy&&!quitting,
    start:()=>exclusively(()=>startAutomatically(startDeps)),remember:value=>{prefs.autoRun=value;savePreferences();},log});
  // Automatic sync: 2 minutes after the app opens, then every 60 minutes. Skipped while the user stopped the processes or
  // another task holds the app; a PC without a device connects first (spec §1.2), one the server released waits.
  autosync=new AutoSync({wanted:()=>prefs.autoRun!==false,connected:()=>ready&&!connector.view().revoked,
    idle:()=>!busy&&!quitting&&!installing,
    run:async()=>{const o=await runSync();if(o.kind==='busy')throw new Error('busy');if(o.kind!=='ok')throw new Error('failed');},log});
  // Updates: updater.cjs is the only place that checks. The dashboard draws its state.
  updater=createUpdater({inApp:inAppSupported({isPackaged:app.isPackaged,platform:process.platform,pkg:PACKAGE}),current:app.getVersion(),
    load:()=>require('electron-updater').autoUpdater,checkRelease:checkUpdate,powerMonitor,prepare:prepareInstall,log});
  let updatePhase=null;
  updater.subscribe(value=>{
    if(dash&&!dash.isDestroyed())dash.webContents.send(UPDATE.changed);
    if(value?.phase==='error'&&updatePhase!=='error'&&value.reason)reporter.report('update/error',value.reason);
    updatePhase=value?.phase||null;
  });
  // Electron sends this right before it closes the windows for the install (macOS); electron-updater sends it before its
  // quit (Windows). Only an in-app build calls quitAndInstall.
  if(updater.state().inApp)nativeUpdater.on('before-quit-for-update',()=>{installing=true;});
  const trusted=event=>trustedSender(event,dash&&!dash.isDestroyed()?dash.webContents:null,inAppAllowed);
  registerDashboardBridge({ipcMain,updater,trusted});
  registerDesktopBridge({ipcMain,trusted,handlers:{
    pcView:()=>pcState.view(),sync:()=>runSync(),
    aiView:()=>aiLink.view(),aiRefresh:()=>aiLink.refresh(60*1000),
    aiConnect:provider=>aiLink.connect(provider),aiDisconnect:provider=>aiLink.disconnect(provider),
  }});
  app.on('activate',showDashboard);
  app.on('before-quit',event=> {
    if(quitting)return;event.preventDefault();quitting=true;clearInterval(pollTimer);autosync?.dispose();updater?.dispose();changed();
    abortLogins();
    const pending=[...commands.keys()].map(child=>new Promise(resolve=>child.once('close',resolve)));
    Promise.all([stopProcesses({closing:true}),...pending]).finally(()=>{tray?.destroy();app.quit();});
  });
  createDashboard();
  pollTimer=setInterval(()=>{connector.poll('timer').then(()=>autoDevice('timer'));autorun.nudge('timer');},grants.POLL_MS);
  connector.poll('timer').then(()=>autoDevice('startup'));
  if(ready)aiLink.refresh().catch(()=>{});
  const icon=nativeImage.createFromDataURL('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAIElEQVR42mNkYPj/n4ECwESJ5lEDRg0YNWDUgFEDBg0AADMSAh/0xSqxAAAAAElFTkSuQmCC');
  tray=new Tray(icon);tray.setToolTip('MyCRM');refreshTray();tray.on('double-click',showDashboard);tray.on('click',showDashboard);
  autorun.nudge('startup');
  autosync.start();
  updater.start();
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    {label:'MyCRM',submenu:[{label:'대시보드',accelerator:'CmdOrCtrl+1',click:showDashboard},{type:'separator'},{label:'종료',accelerator:process.platform==='darwin'?'Command+Q':'Alt+F4',click:()=>app.quit()}]},
    {role:'editMenu'},
    {label:'보기',submenu:[{label:'새로 고침',accelerator:'CmdOrCtrl+R',click:()=>dashNav('reload')},{label:'뒤로',accelerator:'CmdOrCtrl+[',click:()=>dashNav('back')},{label:'앞으로',accelerator:'CmdOrCtrl+]',click:()=>dashNav('forward')},{type:'separator'},{label:'브라우저에서 열기',click:openInBrowser}]}
  ]));
}
