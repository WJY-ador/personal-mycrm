'use strict';
const {app,BrowserWindow,Menu,Tray,nativeImage,ipcMain,shell,dialog,net,session,Notification,safeStorage,powerMonitor,autoUpdater:nativeUpdater} = require('electron');
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {PACKAGE,HOSTED,RELEASES,DASHBOARD,safeExternal,inAppAllowed,externalHttps,agentHome,checkUpdate} = require('./policy.cjs');
const {Supervisor,diagnosticLog} = require('./supervisor.cjs');
const {OutputTail,failureLine,hasLiveProcess} = require('./sidecar.cjs');
const handoff = require('./handoff.cjs');
const grants = require('./grants.cjs');
const {Connector} = require('./connector.cjs');
const {ConsentBridge}=require('./consent-bridge.cjs');
const {createConsentRuntime,REVOKE_NONE_EXIT}=require('./consent-runtime.cjs');
const {createConsentLockGuard}=require('./consent-lock-guard.cjs');
const {startChatSidecar}=require('./chat-sidecar.cjs');
const {findCliCandidates,parseModelIds}=require('./cli-discovery.cjs');
const {AutoRun,readPreferences,startConnection,startAutomatically,addChat,stopChatForLock,startProcesses:launchProcesses}=require('./autorun.cjs');
const {createUpdater,inAppSupported,trustedSender,registerDashboardBridge,CHANNELS:UPDATE}=require('./updater.cjs');
let win,dash,tray,supervisor,log,prefs={},binary,home,settingsFile,quitting=false,ready=false;
let busy=false,trayLive=null,connector=null,pollTimer=null,consentBridge=null,consentRuntime=null,consentLock=null,autorun=null; const commands=new Set();
// installing: an in-app update is quitting the app (set on 'before-quit-for-update'); the windows' close no longer hides them.
let updater=null,installing=false;
function stopProcesses(options){consentBridge?.abortPending();return supervisor.stopAll(options);}
// Login handoff: one pending login (verifier never leaves memory) and a deep link that arrived before the window existed.
let pendingLogin=null,queuedLink=handoff.findLink(process.argv);
const PAGE=pathToFileURL(path.join(__dirname,'index.html')).href;
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
      codexCliConfigured:typeof c.summary?.codex_cli_path==='string'&&path.isAbsolute(c.summary.codex_cli_path),
      codexModels:Array.isArray(c.summary?.codex_models)?c.summary.codex_models.filter(x=>typeof x==='string'):[],expires:c.token_expires_at||null,
      deviceLabel:typeof c.device_label==='string'?c.device_label:''};
  } catch {return {connected:false,cliConfigured:false,codexCliConfigured:false,codexModels:[],expires:null,deviceLabel:''};}
}
function snapshot() {
  const {connected,cliConfigured,codexCliConfigured,codexModels,expires}=connection();
  const codexCandidates=findCliCandidates('codex',{platform:process.platform,home:os.homedir(),pathValue:process.env.PATH||''});
  return {version:app.getVersion(),ready,busy,allowCli:prefs.allowCli===true,autoStart:app.isPackaged&&app.getLoginItemSettings().openAtLogin,
    connection:{connected,cliConfigured,codexCliConfigured,codexModels,expires},codexCandidates,
    pc:connector?.view()||{session:'unknown',revoked:false,registered:false},processes:supervisor?.snapshot()||{}};
}
function changed(){if(win&&!win.isDestroyed())win.webContents.send('status',snapshot());refreshTray();autorun?.nudge('change');}
function trayMenu(live){return Menu.buildFromTemplate([{label:'대시보드 열기',click:showDashboard},{label:'연결 장치',click:show},{type:'separator'},{label:'연결 장치 중지',enabled:live,click:()=>exclusively(userStop).catch(()=>{})},{label:'종료',click:()=>app.quit()}]);}
function refreshTray(){if(!tray||tray.isDestroyed())return;const live=hasLiveProcess(supervisor?.snapshot());if(live===trayLive)return;trayLive=live;tray.setContextMenu(trayMenu(live));}
function show(){if(win){win.show();win.focus();}}
function showDashboard(){if(dash&&!dash.isDestroyed()){dash.show();dash.focus();}}
// Links that leave the hosted origin go to the system browser, https only.
function leave(url){if(externalHttps(url))shell.openExternal(url).catch(()=>{});}
// Order matters: a login start is taken over first; it is same-origin and would otherwise load in-app,
// then redirect to AuthKit outside the allow list and start a browser login that never comes back.
function guard(event,url){
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
function deepLink(raw){
  if(!dash||dash.isDestroyed()){queuedLink=raw;return;}
  showDashboard();app.focus({steal:true});
  const parsed=handoff.parseCallback(raw),result=handoff.accept(pendingLogin,parsed);
  if(result!=='ok'){
    if(result==='expired')pendingLogin=null;
    log?.('login','rejected-'+result);notice({expired:'expired',format:'invalid',none:'none',state:'mismatch'}[result]);return;
  }
  const {verifier}=pendingLogin;pendingLogin=null; // one-shot: cleared before the claim is sent, whatever its outcome
  log?.('login','claim');
  const claim=handoff.claimRequest(HOSTED,parsed.code,verifier,parsed.state);
  dash.loadURL(claim.url,claim.options).then(()=>connector?.poll('login'),()=>{});
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
  wc.setWindowOpenHandler(({url})=>{if(handoff.isLoginNav(url,HOSTED))startLogin(handoff.wantsFresh(url));else if(inAppAllowed(url))wc.loadURL(url).catch(()=>{});else leave(url);return {action:'deny'};});
  wc.on('will-navigate',(e,url)=>guard(e,e.url||url));
  // Subframes (captcha, provider widgets) are not gated; only top-level navigation is.
  wc.on('will-redirect',(e,url,_inPlace,isMainFrame)=>{if(e.isMainFrame??isMainFrame)guard(e,e.url||url);});
  dash.on('close',event=>{if(!quitting&&!installing){event.preventDefault();dash.hide();}});
  dash.on('focus',()=>{connector?.poll('focus');autorun?.nudge('focus');});
  if(queuedLink){const link=queuedLink;queuedLink=null;deepLink(link);}else dash.loadURL(DASHBOARD).catch(()=>{});
}
async function external(url){if(!safeExternal(url))throw new Error('url');await shell.openExternal(url);}
function command(args,input,extraEnv={}) {
  return new Promise((resolve,reject)=> {
    const env={...process.env,PYTHONNOUSERSITE:'1',PYTHONDONTWRITEBYTECODE:'1',...extraEnv};
    delete env.MYCRM_JOBS_ALLOW_REAL_CLI;
    const child=spawn(binary,['--home',home,...args],{env,shell:false,windowsHide:true,stdio:['pipe','pipe','pipe']});
    commands.add(child);let done=false;const output=new OutputTail();
    // The detail is returned to the window only; desktop.log keeps exit codes, never sidecar text.
    const finish=(err,code)=>{if(done)return;done=true;clearTimeout(timer);commands.delete(child);err?reject(new Error(err)):resolve({code,detail:failureLine(code,output.text())});};
    const timer=setTimeout(()=>{child.kill('SIGTERM');finish('command-timeout');},args[0]==='run-once'?600000:45000);
    child.stdout.on('data',chunk=>output.push(chunk));child.stderr.on('data',chunk=>output.push(chunk));child.stdin.on('error',()=>{});
    child.once('error',()=>finish('agent-unavailable'));child.once('close',code=>finish(null,code));
    child.stdin.end(input ? input+'\n' : '');
  });
}
// Requests for the PC connection run in the main process with the dashboard session (persist:dashboard): the same
// crm_session cookie as the dashboard window, plus X-MyCRM-Desktop. No Origin header is sent. Redirects are not
// followed. The body is read only as JSON and dropped by the caller after use; nothing here logs it.
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
const CONSENT_PATHS=new Set(['/api/chat/consent/keys/begin','/api/chat/consent/keys/activate',
  '/api/chat/consent/keys/revoke','/api/chat/consent/challenges/issue','/api/chat/consent/challenges/verify']);
function consentRequest(pathname,body,authorization){
  if(!CONSENT_PATHS.has(pathname)||typeof authorization!=='string')return Promise.resolve({status:0,body:null});
  const origin=new URL(HOSTED).origin;
  return request('POST',new URL(pathname,HOSTED).href,body,{
    'Origin':origin,'Authorization':authorization,'Content-Type':'application/json',
  });
}
// Stored-token consent revoke (R5): runs the agent once with the bridge capability in its env (never argv). The agent
// sends its device token back over the bridge and the runtime calls keys/revoke. Windows has no bridge, so no consent
// key can be made from this installation there: nothing to revoke.
async function runConsentRevokeAgent(){
  if(process.platform==='win32')return REVOKE_NONE_EXIT;
  if(!ready||quitting||!consentBridge)return -1;
  const env=await consentBridge.start();
  const {code}=await command(['chat-consent-revoke'],null,env);
  return code;
}
async function startChatAgent(){
  if(!consentBridge)throw new Error('bridge');
  // R5: chat runs only after this run confirmed the stored revoke; otherwise one more try, then this start is refused.
  if(!consentRuntime||!await consentRuntime.ensureStartRevoked()){
    log('consent','chat-start-revoke-unconfirmed');throw new Error('consent-start-revoke-unconfirmed');
  }
  await startChatSidecar(supervisor,consentBridge);
}
// One start for the button and the automatic start (autorun.cjs). The caller holds the app lock.
const startDeps={get supervisor(){return supervisor;},get consentLock(){return consentLock;},prefs:()=>prefs,connection:()=>connection(),
  ready:()=>ready,startChat:()=>startChatAgent()};
function startProcesses(names){return launchProcesses(names,startDeps);}
// The user's stop (window or tray). Recorded first so the automatic start cannot bring it back in this run.
async function userStop(){autorun?.userStopped();await stopProcesses();}
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
// abort(): busy also holds the automatic start, connection delivery and every button. The processes stop the way the
// token install does — not userStop, so the saved autoRun is unchanged and the reinstalled app starts them again.
// The windows let the updater close them only from 'before-quit-for-update' (initialize): on macOS Squirrel first fetches
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
    await Promise.all([...commands].map(child=>new Promise(resolve=>child.once('close',resolve))));
  }catch(e){await restart();release();throw e;}
  if(quitting){release();throw new Error('closing');}
  return {quitting:()=>quitting,abort:async()=>{installing=false;await restart();release();}};
}
function notify({title,body}){try{if(Notification.isSupported())new Notification({title,body}).show();}catch{}}
function connectionStore(file){
  return {
    load:()=>{try{return fs.readFileSync(file,'utf8');}catch{return null;}},
    save:record=>{try{const tmp=file+'.tmp';fs.writeFileSync(tmp,JSON.stringify(record),{mode:0o600});fs.renameSync(tmp,file);}catch{log('connect','store-failed');}},
  };
}
async function exclusively(fn) {
  if(busy||quitting)throw new Error('busy');busy=true;changed();
  try{return await fn();}finally{busy=false;changed();}
}
// Fixed text per failure kind; never the error's own text (it could carry server or sidecar content).
const FAILURES={
  busy:'다른 작업이 진행 중이에요. 잠시 뒤 다시 시도해 주세요.',
  login:'로그인이 필요해요. 이 창의 [로그인]을 눌러 브라우저에서 로그인한 뒤 다시 시도해 주세요.',
  revoked:'이 PC 연결이 해제됐어요 — 대화에서 다시 연결해 주세요.',
  limit:'연결된 PC가 이미 5대예요. 쓰지 않는 PC를 대화나 웹에서 해제한 뒤 다시 시도해 주세요.',
  name:'웹에서 표시 이름을 먼저 정한 뒤 다시 시도해 주세요.',
  failed:'이 PC를 자동으로 연결하지 못했어요. 잠시 뒤 다시 시도하거나 진단 로그를 확인해 주세요.',
  'consent-lock-unsupported':'이 운영체제에서는 화면 잠금 상태를 확인할 수 없어 AI 대화를 사용할 수 없어요.',
  'consent-lock-locked':'화면 잠금을 풀고 PC를 다시 시작해 주세요.',
  'consent-lock-revoke-unconfirmed':'화면 잠금 뒤 PC 승인을 폐기했는지 확인하지 못해 대화를 막았어요. 연결을 확인한 뒤 다시 시도해 주세요.',
  'consent-start-revoke-unconfirmed':'지난 실행의 PC 승인을 폐기했는지 확인하지 못해 대화를 시작하지 않았어요. 로그인과 연결을 확인한 뒤 다시 시도해 주세요.',
  default:'작업을 완료하지 못했어요. 연결 상태와 진단 로그를 확인해 주세요.',
};
function register(name,fn) {
  ipcMain.handle(name,async(event,...args)=> {
    if(!win || event.sender!==win.webContents || event.senderFrame?.url!==PAGE)throw new Error('sender');
    try{return {ok:true,value:await fn(...args)};}catch(e){log('app','operation-failed');return {ok:false,error:FAILURES[e.message]||FAILURES.default};}
  });
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
  ready=await compatibleBinary();supervisor=new Supervisor({binary,home,log,changed});
  win=new BrowserWindow({width:660,height:790,minWidth:520,minHeight:600,title:'MyCRM 연결 장치',show:false,backgroundColor:'#f6f7f9',webPreferences:{preload:path.join(__dirname,'preload.cjs'),nodeIntegration:false,contextIsolation:true,sandbox:true,webSecurity:true}});
  win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  win.webContents.on('will-navigate',e=>e.preventDefault());
  win.webContents.session.setPermissionRequestHandler((_wc,_p,callback)=>callback(false));
  win.on('close',event=>{if(!quitting&&!installing){event.preventDefault();win.hide();}});
  connector=new Connector({hosted:HOSTED,request,store:connectionStore(path.join(userData,'desktop-connection.json')),install,forgetLocal,
    exclusive:exclusively,canDeliver:()=>ready&&!busy&&!quitting,connection,notify,log,client:grants.clientInfo(os.hostname(),process.platform),changed});
  consentBridge=new ConsentBridge({directory:path.join(userData,'chat-ipc'),handler:async(input,signal)=>consentRuntime?await consentRuntime.handle(input,signal):{ok:false,reason:'failed'},
    revokeHandler:async input=>consentRuntime?await consentRuntime.revokeWith(input):{ok:false,reason:'failed'}});
  consentRuntime=createConsentRuntime({
    request:consentRequest,
    getInstallationId:async()=>{
      if(!connector||busy||quitting||!connection().connected||connector.view().revoked)return null;
      try{return await connector.installation();}catch{return null;}
    },
    safeStorage,keyFile:path.join(userData,'consent-signing-key.json'),app,dialog,powerMonitor,
    getRevokeInstallationId:async()=>connector?.record?.installationId||null,
    runRevokeAgent:runConsentRevokeAgent,
    trustedWindow:()=>win,allowedUrl:PAGE,
    focusWindow:async target=>{
      if(quitting||!target||target.isDestroyed())return false;
      target.show();target.focus();app.focus({steal:true});
      await new Promise(resolve=>setTimeout(resolve,100));
      return target.isFocused()===true;
    },
  });
  // R5: a restart must not keep the previous run's consent alive. Revoke this installation's server consent key once
  // at start. A failure is logged only; it does not hold the app or the lock guard. An approval waits for this to end.
  consentRuntime.revokeAtStart().then(outcome=>log('consent','start-revoke-'+outcome));
  consentLock=createConsentLockGuard({powerMonitor,platform:process.platform,onLock:async()=>{
    consentBridge?.abortPending();
    const stopped=supervisor?stopChatForLock(supervisor,autorun):Promise.resolve();
    const revoked=consentRuntime?.invalidateOnLock()||Promise.resolve(false);
    const results=await Promise.allSettled([stopped,revoked]);
    return results[0].status==='fulfilled'&&results[1].status==='fulfilled'&&results[1].value===true;
  }});
  // Opening the app starts the connection device the way [연결 장치 시작] does, unless the user stopped it last time.
  // While the consent lock is closed it starts without chat and adds chat on a later focus or timer tick.
  autorun=new AutoRun({wanted:()=>prefs.autoRun!==false,connected:()=>connection().connected,idle:()=>!busy&&!quitting,
    start:()=>exclusively(()=>startAutomatically(startDeps)),chatReady:()=>consentLock?.canStart()===true,
    addChat:()=>exclusively(()=>addChat(startDeps)),remember:value=>{prefs.autoRun=value;savePreferences();},log});
  register('status',()=>snapshot());
  // M4: the browser opens only from this button (or the dashboard's own login link), never from a failed request.
  register('login',()=>{startLogin();});
  register('dashboard',()=>showDashboard());
  register('logs',()=>shell.openPath(path.join(userData,'logs')));
  register('connect',token=>exclusively(async()=>{
    if(!ready||typeof token!=='string'||token.length<16||token.length>1024||/[\r\n\x00]/.test(token))throw new Error('token');
    await stopProcesses();
    const {code,detail}=await command(['connect','--server',HOSTED,'--token-stdin'],token);
    log('connect','completed',code);if(code===0)connector.manualConnected();return {code,detail};
  }));
  register('choose-cli',()=>exclusively(async()=>{
    const result=await dialog.showOpenDialog(win,{title:'Claude CLI 실행 파일 선택',properties:['openFile']});
    if(result.canceled)return {canceled:true};
    const target=result.filePaths[0];
    if(!path.isAbsolute(target)||!fs.statSync(target).isFile())throw new Error('path');
    const {code,detail}=await command(['configure-cli','--path',target]);return {code,detail};
  }));
  register('configure-codex',value=>exclusively(async()=>{
    if(!value||typeof value!=='object'||Array.isArray(value))throw new Error('input');
    const models=parseModelIds(value.models);
    const candidates=findCliCandidates('codex',{platform:process.platform,home:os.homedir(),pathValue:process.env.PATH||''});
    const result=await dialog.showOpenDialog(win,{title:'Codex CLI 실행 파일 선택',
      ...(candidates[0]?{defaultPath:candidates[0]}:{}),properties:['openFile']});
    if(result.canceled)return {canceled:true};
    const target=path.resolve(result.filePaths[0]);
    if(!path.isAbsolute(target)||!fs.statSync(target).isFile())throw new Error('path');
    const args=['configure-codex','--path',target];
    for(const model of models)args.push('--model',model);
    const {code,detail}=await command(args);return {code,detail};
  }));
  register('allow-cli',value=>exclusively(async()=>{
    if(typeof value!=='boolean')throw new Error('input');
    await supervisor.stop('jobs');prefs.allowCli=value;savePreferences();return snapshot();
  }));
  register('auto-start',value=>exclusively(async()=>{
    if(typeof value!=='boolean'||!app.isPackaged)throw new Error('input');
    app.setLoginItemSettings({openAtLogin:value});return snapshot();
  }));
  register('start',()=>exclusively(async()=>{
    await startConnection(startDeps);autorun.manualStarted();
    return snapshot();
  }));
  register('stop',()=>exclusively(async()=>{await userStop();return snapshot();}));
  // Turning collection on is the moment this PC gets a device automatically (no device yet, or one left from another
  // account). A run halted on auth asks for a fresh token for the same device once, then resumes.
  register('sync',()=>exclusively(async()=>{
    if(!ready)throw new Error('not-connected');
    if(connector.needsAuto())await connector.autoConnect();
    let {code,detail}=await command(grants.runOnceArgs());log('sync','completed',code);
    if(code===3&&/--resume auth/.test(detail||'')){
      await connector.autoConnect();
      ({code,detail}=await command(grants.runOnceArgs(true)));log('sync','resumed',code);
    }
    return {code,detail};
  }));
  // A disconnect made here is a release: automatic connection does not bring this PC back; a conversation does.
  register('disconnect',()=>exclusively(async()=>{await stopProcesses();const {code,detail}=await command(['disconnect']);log('disconnect','completed',code);if(code===0)connector.released();return {code,detail};}));
  // Updates: updater.cjs is the only place that checks. The connection window and the dashboard draw its state.
  updater=createUpdater({inApp:inAppSupported({isPackaged:app.isPackaged,platform:process.platform,pkg:PACKAGE}),current:app.getVersion(),
    load:()=>require('electron-updater').autoUpdater,checkRelease:checkUpdate,powerMonitor,prepare:prepareInstall,log});
  updater.subscribe(value=>{
    if(win&&!win.isDestroyed())win.webContents.send('update-changed',value);
    if(dash&&!dash.isDestroyed())dash.webContents.send(UPDATE.changed);
  });
  // Electron sends this right before it closes the windows for the install (macOS); electron-updater sends it before its
  // quit (Windows). Only an in-app build calls quitAndInstall.
  if(updater.state().inApp)nativeUpdater.on('before-quit-for-update',()=>{installing=true;});
  registerDashboardBridge({ipcMain,updater,trusted:event=>trustedSender(event,dash&&!dash.isDestroyed()?dash.webContents:null,inAppAllowed)});
  register('update-state',()=>updater.state());
  register('update',async()=>({checked:await updater.check()}));
  register('update-download',()=>{updater.download().catch(()=>{});});
  register('update-install',()=>{updater.install().catch(()=>{});});
  register('releases',()=>external(RELEASES));
  app.on('activate',showDashboard);
  app.on('before-quit',event=> {
    if(quitting)return;event.preventDefault();quitting=true;clearInterval(pollTimer);updater?.dispose();changed();
    const pending=[...commands].map(child=>new Promise(resolve=>child.once('close',resolve)));
    Promise.all([stopProcesses({closing:true}),...pending]).finally(async()=>{consentLock?.dispose();consentRuntime?.dispose();await consentBridge?.close();tray?.destroy();app.quit();});
  });
  createDashboard();
  win.on('focus',()=>{connector.poll('focus');autorun.nudge('focus');});
  pollTimer=setInterval(()=>{connector.poll('timer');autorun.nudge('timer');},grants.POLL_MS);
  connector.poll('timer');
  await win.loadFile(path.join(__dirname,'index.html'));
  const icon=nativeImage.createFromDataURL('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAIElEQVR42mNkYPj/n4ECwESJ5lEDRg0YNWDUgFEDBg0AADMSAh/0xSqxAAAAAElFTkSuQmCC');
  tray=new Tray(icon);tray.setToolTip('MyCRM');refreshTray();tray.on('double-click',showDashboard);tray.on('click',showDashboard);
  autorun.nudge('startup');
  updater.start();
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    {label:'MyCRM',submenu:[{label:'대시보드',accelerator:'CmdOrCtrl+1',click:showDashboard},{label:'연결 장치',accelerator:'CmdOrCtrl+2',click:show},{type:'separator'},{label:'종료',accelerator:process.platform==='darwin'?'Command+Q':'Alt+F4',click:()=>app.quit()}]},
    {role:'editMenu'},
    {label:'보기',submenu:[{label:'새로 고침',accelerator:'CmdOrCtrl+R',click:()=>dashNav('reload')},{label:'뒤로',accelerator:'CmdOrCtrl+[',click:()=>dashNav('back')},{label:'앞으로',accelerator:'CmdOrCtrl+]',click:()=>dashNav('forward')},{type:'separator'},{label:'브라우저에서 열기',click:openInBrowser}]}
  ]));
}
