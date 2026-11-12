// Desktop-local native consent approval: trusted sender -> strict claims -> server challenge match ->
// active session -> native dialog -> explicit affirmative -> active session -> safeStorage key -> sign.
//
// The hosted renderer and preload do not expose an approval IPC endpoint. The desktop main process
// invokes this only through the private supervised-agent bridge after fetching the server challenge.
// Claims from renderer input are never trusted. This approval signs the challenge, but does not
// consume a grant, dispatch work or enable a provider.
//
// The module never imports Electron (dialog, powerMonitor, safeStorage, app are injected), never logs,
// and never returns key material or puts the signature anywhere but the return value.
'use strict';
const path=require('node:path');
const {DOMAIN,FIELDS,encodeConsent,signConsent}=require('./consent-signature.cjs');
const {loadOrCreateKeyPair}=require('./consent-key-store.cjs');

const CONNECTED=false; // no renderer-facing IPC channel; main calls the module through the private bridge
const CHANNEL='consent-approve'; // reserved; main invokes the module directly, never exposed to renderer
const KEY_FILE='consent-signing-key.json';
const MAX_TTL_SECONDS=600;
const APPROVE=1,CANCEL=0;
const CODES=Object.freeze({UNSUPPORTED:'UNSUPPORTED',BUSY:'BUSY',SENDER:'SENDER',CLAIMS:'CLAIMS',EXPIRED:'EXPIRED',
  IDLE:'IDLE',DECLINED:'DECLINED',CANCELED:'CANCELED',KEY:'KEY'});
const LOCK_EVENT_PLATFORMS=new Set(['darwin','win32']);

const refuse=code=>Object.freeze({ok:false,code});

// The sender must be the top frame of the one trusted app window, showing exactly the allowed app URL.
// Other windows, devtools, subframes, destroyed or unfocused windows and any other URL are refused.
// Origin headers and renderer-supplied labels play no part.
function trustedSender(event,win,allowedUrl){
  try{
    if(typeof allowedUrl!=='string'||!allowedUrl)return false;
    if(!win||typeof win.isDestroyed!=='function'||win.isDestroyed())return false;
    if(typeof win.isFocused!=='function'||win.isFocused()!==true)return false;
    const wc=win.webContents;
    if(!wc||!event||event.sender!==wc)return false;
    if(typeof wc.isDevToolsOpened!=='function'||wc.isDevToolsOpened()!==false)return false;
    const frame=event.senderFrame;
    if(!frame||!wc.mainFrame||frame!==wc.mainFrame)return false;
    if(frame.parent!==null)return false;
    if(frame.url!==allowedUrl)return false;
    if(typeof wc.getURL!=='function'||wc.getURL()!==allowedUrl)return false;
    return true;
  }catch{return false;}
}

// The screen is not locked: 'active' or 'idle'. 'idle' only means no input for the threshold (1 second), which is the
// normal state while a person reads the chat or waits for the window (J-F6: it used to count as locked).
// 'locked', 'unknown', a missing API, a throw or an unsupported platform fail closed.
function sessionActive(powerMonitor,platform=process.platform){
  try{
    if(!LOCK_EVENT_PLATFORMS.has(platform)||!powerMonitor||typeof powerMonitor.getSystemIdleState!=='function')return false;
    const state=powerMonitor.getSystemIdleState(1);
    return state==='active'||state==='idle';
  }catch{return false;}
}

function encryptionAvailable(safeStorage){
  try{return !!safeStorage&&typeof safeStorage.isEncryptionAvailable==='function'&&safeStorage.isEncryptionAvailable()===true;}
  catch{return false;}
}

// Strict copy: the bytes are encoded once (own data properties only, exact field set, per-field
// patterns) and the claims used afterwards are rebuilt from those bytes, so getters, extra fields
// or later mutation of the request cannot change what is shown or signed.
function strictClaims(request){
  let bytes;
  try{bytes=encodeConsent(request);}catch{return null;}
  const tuple=JSON.parse(bytes.subarray(Buffer.byteLength(DOMAIN+'\n')).toString('utf8'));
  const claims=Object.freeze(Object.fromEntries(FIELDS.map((name,i)=>[name,tuple[i]])));
  return {bytes,claims};
}

function sameBytes(a,b){return Buffer.isBuffer(a)&&Buffer.isBuffer(b)&&a.length===b.length&&a.equals(b);}

async function challengeMatches(challenge,claims,bytes){
  try{
    const server=strictClaims(await challenge(claims));
    return !!server&&sameBytes(server.bytes,bytes);
  }catch{return false;}
}

function kst(seconds){
  const d=new Date((seconds+9*3600)*1000);   // 한국 시각을 UTC 필드로 읽는다(PC 시간대와 무관)
  const p=n=>String(n).padStart(2,'0');
  return `${d.getUTCFullYear()}년 ${d.getUTCMonth()+1}월 ${d.getUTCDate()}일 ${p(d.getUTCHours())}:${p(d.getUTCMinutes())} (한국 시각)`;
}

function providerLabel(provider){
  if(provider==='claude')return 'Claude';
  if(provider==='codex')return 'Codex';
  return 'AI 서비스';
}

// The server signs a request without a chosen model as ':default' (webchat CONSENT_DEFAULT_MODEL).
const DEFAULT_MODEL=':default';
function modelLabel(model){return model===DEFAULT_MODEL?'기본 모델':model;}

// J JD1, JD2: one allow covers this PC and this AI service (any model, any new chat) and stands through screen unlocks
// and app restarts until the person releases it. The window says that scope; the model line is only this chat's pick.
function dialogOptions(c){
  const name=providerLabel(c.provider);
  return {
    type:'question',buttons:['취소','허용'],defaultId:CANCEL,cancelId:CANCEL,noLink:true,
    title:'MyCRM AI 대화 허용',message:`이 PC에서 ${name} 대화를 허용할까요?`,
    detail:[
      '한 번 허용하면 다른 모델, 새 대화, 화면 잠금 해제, 앱 재시작 뒤에도 다시 묻지 않아요.',
      'AI는 대화에 필요한 MyCRM 기록을 조회해요.',
      '요청에 따라 기존 MyCRM 규칙으로 기록을 변경할 수 있어요.',
      '변경은 MyCRM의 기존 권한과 규칙을 따라요.',
      '대화 내용은 선택한 모델로 전송돼요.',
      `이 PC의 ${name} CLI 기록에도 남을 수 있어요.`,'',
      `이번에 고른 모델: ${modelLabel(c.model)} (허용은 모델과 상관없이 ${name} 전체에 적용돼요)`,
      `요청 만료 시각: ${kst(c.expires_at)}`,'',
      '그만 쓰려면 연결 장치 창이나 웹의 연결 장치에서 허용을 해제하세요.',
    ].join('\n'),
  };
}

function createConsentApproval(options){
  const {app,dialog,powerMonitor,safeStorage,trustedWindow,allowedUrl,challenge}=options||{};
  const platform=options?.platform||process.platform;
  const loadKeyPair=typeof options?.loadKeyPair==='function'?options.loadKeyPair:loadOrCreateKeyPair;
  const now=typeof options?.now==='function'?options.now:()=>Math.floor(Date.now()/1000);
  const lockSignalsSupported=LOCK_EVENT_PLATFORMS.has(platform)&&powerMonitor
    &&typeof powerMonitor.on==='function'&&typeof powerMonitor.removeListener==='function'
  let pending=false;
  let lockEpoch=0;
  const onLock=()=>{lockEpoch++;};
  if(lockSignalsSupported){
    powerMonitor.on('lock-screen',onLock);
    powerMonitor.on('suspend',onLock);
  }
  function activeAt(epoch){
    return lockSignalsSupported&&lockEpoch===epoch&&sessionActive(powerMonitor,platform);
  }

  function inWindow(claims){
    let t;try{t=now();}catch{return false;}
    return Number.isSafeInteger(t)&&claims.expires_at>t&&claims.expires_at<=t+MAX_TTL_SECONDS;
  }
  function keyFile(){
    const dir=app?.getPath?.('userData');
    if(typeof dir!=='string'||!path.isAbsolute(dir))throw new Error('path');
    return path.join(dir,KEY_FILE);
  }

  async function approve(event,request,{signal}={}){
    if(signal?.aborted)return refuse(CODES.CANCELED);
    if(typeof challenge!=='function')return refuse(CODES.UNSUPPORTED);
    if(pending)return refuse(CODES.BUSY);
    pending=true;
    try{
      const approvalEpoch=lockEpoch;
      const win=typeof trustedWindow==='function'?trustedWindow():null;
      const trusted=()=>trustedSender(event,win,allowedUrl);
      if(!trusted())return refuse(CODES.SENDER);
      const strict=strictClaims(request);
      if(!strict)return refuse(CODES.CLAIMS);
      const {bytes,claims}=strict;
      if(!inWindow(claims))return refuse(CODES.EXPIRED);
      if(!await challengeMatches(challenge,claims,bytes))return refuse(CODES.CLAIMS);
      if(signal?.aborted)return refuse(CODES.CANCELED);
      if(!encryptionAvailable(safeStorage))return refuse(CODES.KEY);
      if(!activeAt(approvalEpoch))return refuse(CODES.IDLE);
      if(!trusted())return refuse(CODES.SENDER);

      let result;
      try{result=await dialog.showMessageBox(win,dialogOptions(claims));}catch{return refuse(CODES.CANCELED);}
      if(signal?.aborted)return refuse(CODES.CANCELED);
      // DECLINED: the person pressed 취소 or closed the dialog (cancelId maps both to CANCEL).
      // CANCELED: anything else that is not an explicit 허용 (dialog failure, abort, malformed result).
      if(result&&typeof result==='object'&&result.response===CANCEL)return refuse(CODES.DECLINED);
      if(!result||typeof result!=='object'||result.response!==APPROVE)return refuse(CODES.CANCELED);

      // Everything is checked again: the dialog may have stayed open while the screen locked,
      // the window changed or the server challenge moved on.
      if(!activeAt(approvalEpoch))return refuse(CODES.IDLE);
      if(!trusted())return refuse(CODES.SENDER);
      if(!inWindow(claims))return refuse(CODES.EXPIRED);
      if(!await challengeMatches(challenge,claims,bytes))return refuse(CODES.CLAIMS);
      if(signal?.aborted)return refuse(CODES.CANCELED);

      let pair;
      try{pair=await loadKeyPair({safeStorage,filePath:keyFile()});}catch{return refuse(CODES.KEY);}
      if(signal?.aborted)return refuse(CODES.CANCELED);
      if(!activeAt(approvalEpoch))return refuse(CODES.IDLE);
      let signature,t;
      try{t=now();signature=signConsent(claims,pair.privateKey,{nowSeconds:t});}catch{return refuse(CODES.EXPIRED);}
      const publicKey=pair.publicKey.export({type:'spki',format:'der'}).toString('base64');
      return Object.freeze({ok:true,claims,signature,publicKey});
    }finally{pending=false;}
  }
  return Object.freeze({approve,dispose:()=>{
    if(lockSignalsSupported){
      powerMonitor.removeListener('lock-screen',onLock);
      powerMonitor.removeListener('suspend',onLock);
    }
  }});
}

module.exports=Object.freeze({CONNECTED,CHANNEL,KEY_FILE,MAX_TTL_SECONDS,CODES,trustedSender,sessionActive,createConsentApproval});
