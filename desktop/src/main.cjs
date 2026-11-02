'use strict';
const {app,BrowserWindow,Menu,Tray,nativeImage,ipcMain,shell,dialog} = require('electron');
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const {pathToFileURL} = require('node:url');
const {HOSTED,RELEASES,DASHBOARD,safeExternal,inAppAllowed,externalHttps,agentHome,checkUpdate} = require('./policy.cjs');
const {Supervisor,diagnosticLog} = require('./supervisor.cjs');
const {OutputTail,failureLine,hasLiveProcess} = require('./sidecar.cjs');
const handoff = require('./handoff.cjs');
let win,dash,tray,supervisor,log,prefs={},binary,home,settingsFile,quitting=false,ready=false;
let busy=false,trayLive=null; const commands=new Set();
// Login handoff: one pending login (verifier never leaves memory) and a deep link that arrived before the window existed.
let pendingLogin=null,queuedLink=handoff.findLink(process.argv);
const PAGE=pathToFileURL(path.join(__dirname,'index.html')).href;
// macOS delivers mycrm:// via open-url, also when the link itself launches the app — register before 'ready'.
app.on('will-finish-launching',()=>app.on('open-url',(event,url)=>{event.preventDefault();deepLink(url);}));
// SPIKE: MYCRM_PTY_SPIKE=1 runs the node-pty self-test only — no window, tray, single-instance lock or protocol registration.
if(process.env.MYCRM_PTY_SPIKE==='1') app.whenReady().then(ptySpikeSelfTest);
else if(!app.requestSingleInstanceLock()) app.quit();
else {
  // Windows (and Linux) hand the link to the running instance as an argument of the second launch.
  app.on('second-instance',(_event,argv)=>{const link=handoff.findLink(argv);if(link)deepLink(link);else showDashboard();});
  if(process.defaultApp&&process.argv.length>=2)app.setAsDefaultProtocolClient('mycrm',process.execPath,[path.resolve(process.argv[1])]);
  else app.setAsDefaultProtocolClient('mycrm');
  app.whenReady().then(initialize).catch(()=> {dialog.showErrorBox('MyCRM','앱을 시작하지 못했어요. 다시 설치하거나 지원팀에 문의해 주세요.');app.exit(1);});
}
// ---- SPIKE (node-pty packaging check, not product code) ----
// Spawns <cli> --version in a pty (argument array, no shell) and returns the first output line.
function ptyVersion(cli){
  return new Promise((resolve,reject)=>{
    if(typeof cli!=='string'||!path.isAbsolute(cli)||!fs.statSync(cli).isFile())throw new Error('cli-path');
    const pty=require('node-pty');
    const env={...process.env};delete env.ANTHROPIC_API_KEY;delete env.OPENAI_API_KEY;
    let out='',done=false;
    const term=pty.spawn(cli,['--version'],{name:'xterm-256color',cols:120,rows:30,cwd:os.homedir(),env});
    const finish=(err,code)=>{
      if(done)return;done=true;clearTimeout(timer);
      if(err)return reject(err);
      // Data can trail the exit event on ConPTY; give it a moment.
      setTimeout(()=>{
        const plain=out.replace(/\x1b\[[0-9;?]*[ -\/]*[@-~]/g,'').replace(/\x1b\][^\x07]*\x07/g,'');
        const firstLine=plain.split(/\r?\n/).map(l=>l.trim()).find(Boolean)||'';
        resolve({code,firstLine:Array.from(firstLine).slice(0,200).join(''),bytes:out.length});
      },300);
    };
    const timer=setTimeout(()=>{try{term.kill();}catch{}finish(new Error('pty-timeout'));},20000);
    term.onData(d=>{out+=d;if(out.length>8192)out=out.slice(-8192);});
    term.onExit(({exitCode})=>finish(null,exitCode));
  });
}
function spikeCli(){
  if(process.env.MYCRM_PTY_SPIKE_CLI)return process.env.MYCRM_PTY_SPIKE_CLI;
  try{return JSON.parse(fs.readFileSync(path.join(home,'config.json'),'utf8')).summary?.cli_path||null;}catch{return null;}
}
function claudeOnPath(){
  const names=process.platform==='win32'?['claude.exe','claude.cmd']:['claude'];
  return String(process.env.PATH||'').split(path.delimiter).filter(Boolean).some(dir=>names.some(n=>{try{return fs.statSync(path.join(dir,n)).isFile();}catch{return false;}}));
}
async function ptySpikeSelfTest(){
  const result={loaded:false,spawned:false,platform:process.platform,arch:process.arch,electron:process.versions.electron,napi:process.versions.napi,packaged:app.isPackaged,claudeOnPath:claudeOnPath()};
  try{require('node-pty');result.loaded=true;}catch(e){result.loadError=String(e&&e.message||e).slice(0,400);}
  const cli=process.env.MYCRM_PTY_SPIKE_CLI;
  if(result.loaded&&cli){
    try{const r=await ptyVersion(cli);result.spawned=true;result.exitCode=r.code;result.firstLine=r.firstLine;result.bytes=r.bytes;}
    catch(e){result.spawnError=String(e&&e.message||e).slice(0,400);}
  }
  const line=JSON.stringify(result);
  try{process.stdout.write(line+'\n');}catch{}
  if(process.env.MYCRM_PTY_SPIKE_OUT)try{fs.writeFileSync(process.env.MYCRM_PTY_SPIKE_OUT,line+'\n');}catch{}
  app.exit(result.loaded&&(!cli||result.spawned)?0:1);
}
// ---- end SPIKE ----
function preferences() {
  try {const p=JSON.parse(fs.readFileSync(settingsFile,'utf8'));return {allowCli:p.allowCli===true};} catch {return {allowCli:false};}
}
function savePreferences() {
  const tmp=settingsFile+'.tmp';fs.writeFileSync(tmp,JSON.stringify(prefs),{mode:0o600});fs.renameSync(tmp,settingsFile);
}
function connection() {
  try {
    const file=path.join(home,'config.json');
    if(fs.statSync(file).size>1024*1024) throw new Error('large');
    const c=JSON.parse(fs.readFileSync(file,'utf8'));
    return {connected:typeof c.source_instance_id==='string' && !!c.source_instance_id,cliConfigured:typeof c.summary?.cli_path==='string' && path.isAbsolute(c.summary.cli_path),expires:c.token_expires_at||null};
  } catch {return {connected:false,cliConfigured:false,expires:null};}
}
function snapshot() {return {version:app.getVersion(),ready,busy,allowCli:prefs.allowCli===true,autoStart:app.isPackaged&&app.getLoginItemSettings().openAtLogin,connection:connection(),processes:supervisor?.snapshot()||{}};}
function changed(){if(win&&!win.isDestroyed())win.webContents.send('status',snapshot());refreshTray();}
function trayMenu(live){return Menu.buildFromTemplate([{label:'대시보드 열기',click:showDashboard},{label:'연결 장치',click:show},{type:'separator'},{label:'연결 장치 중지',enabled:live,click:()=>exclusively(()=>supervisor.stopAll()).catch(()=>{})},{label:'종료',click:()=>app.quit()}]);}
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
  dash.loadURL(claim.url,claim.options).catch(()=>{});
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
  dash=new BrowserWindow({width:1200,height:800,minWidth:720,minHeight:520,title:'MyCRM',backgroundColor:'#ffffff',webPreferences:{partition:'persist:dashboard',nodeIntegration:false,contextIsolation:true,sandbox:true,webSecurity:true}});
  const wc=dash.webContents;
  wc.session.setPermissionRequestHandler((_wc,_p,callback)=>callback(false));
  wc.setWindowOpenHandler(({url})=>{if(handoff.isLoginNav(url,HOSTED))startLogin(handoff.wantsFresh(url));else if(inAppAllowed(url))wc.loadURL(url).catch(()=>{});else leave(url);return {action:'deny'};});
  wc.on('will-navigate',(e,url)=>guard(e,e.url||url));
  // Subframes (captcha, provider widgets) are not gated; only top-level navigation is.
  wc.on('will-redirect',(e,url,_inPlace,isMainFrame)=>{if(e.isMainFrame??isMainFrame)guard(e,e.url||url);});
  dash.on('close',event=>{if(!quitting){event.preventDefault();dash.hide();}});
  if(queuedLink){const link=queuedLink;queuedLink=null;deepLink(link);}else dash.loadURL(DASHBOARD).catch(()=>{});
}
async function external(url){if(!safeExternal(url))throw new Error('url');await shell.openExternal(url);}
function command(args,input) {
  return new Promise((resolve,reject)=> {
    const env={...process.env,PYTHONNOUSERSITE:'1',PYTHONDONTWRITEBYTECODE:'1'};
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
async function exclusively(fn) {
  if(busy||quitting)throw new Error('busy');busy=true;changed();
  try{return await fn();}finally{busy=false;changed();}
}
function register(name,fn) {
  ipcMain.handle(name,async(event,...args)=> {
    if(!win || event.sender!==win.webContents || event.senderFrame?.url!==PAGE)throw new Error('sender');
    try{return {ok:true,value:await fn(...args)};}catch(e){log('app','operation-failed');return {ok:false,error:e.message==='busy'?'다른 작업이 진행 중이에요. 잠시 뒤 다시 시도해 주세요.':'작업을 완료하지 못했어요. 연결 상태와 진단 로그를 확인해 주세요.'};}
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
  win.on('close',event=>{if(!quitting){event.preventDefault();win.hide();}});
  register('status',()=>snapshot());
  register('dashboard',()=>showDashboard());
  register('logs',()=>shell.openPath(path.join(userData,'logs')));
  register('connect',token=>exclusively(async()=>{
    if(!ready||typeof token!=='string'||token.length<16||token.length>1024||/[\r\n\x00]/.test(token))throw new Error('token');
    await supervisor.stopAll();
    const {code,detail}=await command(['connect','--server',HOSTED,'--token-stdin'],token);
    log('connect','completed',code);return {code,detail};
  }));
  register('choose-cli',()=>exclusively(async()=>{
    const result=await dialog.showOpenDialog(win,{title:'Claude CLI 실행 파일 선택',properties:['openFile']});
    if(result.canceled)return {canceled:true};
    const target=result.filePaths[0];
    if(!path.isAbsolute(target)||!fs.statSync(target).isFile())throw new Error('path');
    const {code,detail}=await command(['configure-cli','--path',target]);return {code,detail};
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
    if(!ready||!connection().connected)throw new Error('not-connected');
    if(prefs.allowCli&&!connection().cliConfigured)throw new Error('cli');
    supervisor.start('viewer',['serve']);
    if(prefs.allowCli)supervisor.start('jobs',['serve','--jobs'],{allowCli:true});
    return snapshot();
  }));
  register('stop',()=>exclusively(async()=>{await supervisor.stopAll();return snapshot();}));
  register('sync',()=>exclusively(async()=>{if(!ready||!connection().connected)throw new Error('not-connected');const {code,detail}=await command(['run-once']);log('sync','completed',code);return {code,detail};}));
  register('disconnect',()=>exclusively(async()=>{await supervisor.stopAll();const {code,detail}=await command(['disconnect']);log('disconnect','completed',code);return {code,detail};}));
  register('update',()=>checkUpdate(app.getVersion()));
  register('download',url=>external(url));
  // SPIKE: pty test button. Errors are returned as text so the spike can see the cause.
  register('pty:start',async()=>{try{return await ptyVersion(spikeCli());}catch(e){return {error:String(e&&e.message||e).slice(0,400)};}});
  app.on('activate',showDashboard);
  app.on('before-quit',event=> {
    if(quitting)return;event.preventDefault();quitting=true;changed();
    const pending=[...commands].map(child=>new Promise(resolve=>child.once('close',resolve)));
    Promise.all([supervisor.stopAll({closing:true}),...pending]).finally(()=>{tray?.destroy();app.quit();});
  });
  createDashboard();
  await win.loadFile(path.join(__dirname,'index.html'));
  const icon=nativeImage.createFromDataURL('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAIElEQVR42mNkYPj/n4ECwESJ5lEDRg0YNWDUgFEDBg0AADMSAh/0xSqxAAAAAElFTkSuQmCC');
  tray=new Tray(icon);tray.setToolTip('MyCRM');refreshTray();tray.on('double-click',showDashboard);tray.on('click',showDashboard);
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    {label:'MyCRM',submenu:[{label:'대시보드',accelerator:'CmdOrCtrl+1',click:showDashboard},{label:'연결 장치',accelerator:'CmdOrCtrl+2',click:show},{type:'separator'},{label:'종료',accelerator:process.platform==='darwin'?'Command+Q':'Alt+F4',click:()=>app.quit()}]},
    {role:'editMenu'},
    {label:'보기',submenu:[{label:'새로 고침',accelerator:'CmdOrCtrl+R',click:()=>dashNav('reload')},{label:'뒤로',accelerator:'CmdOrCtrl+[',click:()=>dashNav('back')},{label:'앞으로',accelerator:'CmdOrCtrl+]',click:()=>dashNav('forward')},{type:'separator'},{label:'브라우저에서 열기',click:openInBrowser}]}
  ]));
}
