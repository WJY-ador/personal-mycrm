'use strict';
const {app,BrowserWindow,Menu,Tray,nativeImage,ipcMain,shell,dialog} = require('electron');
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {HOSTED,RELEASES,safeExternal,agentHome,checkUpdate} = require('./policy.cjs');
const {Supervisor,diagnosticLog} = require('./supervisor.cjs');
const {OutputTail,failureLine,hasLiveProcess} = require('./sidecar.cjs');
let win,tray,supervisor,log,prefs={},binary,home,settingsFile,quitting=false,ready=false;
let busy=false,trayLive=null; const commands=new Set();
const PAGE=pathToFileURL(path.join(__dirname,'index.html')).href;
if(!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance',()=>show());
  app.whenReady().then(initialize).catch(()=> {dialog.showErrorBox('MyCRM','앱을 시작하지 못했어요. 다시 설치하거나 지원팀에 문의해 주세요.');app.exit(1);});
}
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
function trayMenu(live){return Menu.buildFromTemplate([{label:'MyCRM 열기',click:show},{label:'대시보드 열기',click:()=>external(HOSTED).catch(()=>{})},{type:'separator'},{label:'연결 장치 중지',enabled:live,click:()=>exclusively(()=>supervisor.stopAll()).catch(()=>{})},{label:'종료',click:()=>app.quit()}]);}
function refreshTray(){if(!tray||tray.isDestroyed())return;const live=hasLiveProcess(supervisor?.snapshot());if(live===trayLive)return;trayLive=live;tray.setContextMenu(trayMenu(live));}
function show(){if(win){win.show();win.focus();}}
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
  win=new BrowserWindow({width:660,height:790,minWidth:520,minHeight:600,title:'MyCRM',backgroundColor:'#f6f7f9',webPreferences:{preload:path.join(__dirname,'preload.cjs'),nodeIntegration:false,contextIsolation:true,sandbox:true,webSecurity:true}});
  win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  win.webContents.on('will-navigate',e=>e.preventDefault());
  win.webContents.session.setPermissionRequestHandler((_wc,_p,callback)=>callback(false));
  win.on('close',event=>{if(!quitting){event.preventDefault();win.hide();}});
  register('status',()=>snapshot());
  register('dashboard',()=>external(HOSTED));
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
  app.on('activate',show);
  app.on('before-quit',event=> {
    if(quitting)return;event.preventDefault();quitting=true;changed();
    const pending=[...commands].map(child=>new Promise(resolve=>child.once('close',resolve)));
    Promise.all([supervisor.stopAll({closing:true}),...pending]).finally(()=>{tray?.destroy();app.quit();});
  });
  await win.loadFile(path.join(__dirname,'index.html'));
  const icon=nativeImage.createFromDataURL('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAIElEQVR42mNkYPj/n4ECwESJ5lEDRg0YNWDUgFEDBg0AADMSAh/0xSqxAAAAAElFTkSuQmCC');
  tray=new Tray(icon);tray.setToolTip('MyCRM');refreshTray();tray.on('double-click',show);tray.on('click',show);
  Menu.setApplicationMenu(Menu.buildFromTemplate([{label:'MyCRM',submenu:[{label:'MyCRM 열기',click:show},{label:'종료',accelerator:process.platform==='darwin'?'Command+Q':'Alt+F4',click:()=>app.quit()}]},{role:'editMenu'}]));
}
