'use strict';
const $=id=>document.getElementById(id);let latestDownload=null;
function say(text){$('message').textContent=text;}
function state(s){
  $('version').textContent='v'+s.version;$('connection').textContent=s.pc?.revoked?'해제됨':s.connection.connected?'연결됨':'연결 안 됨';
  $('expiry').textContent=s.connection.expires?'토큰 만료 '+s.connection.expires:'';
  $('allow-cli').checked=s.allowCli;$('auto-start').checked=s.autoStart;
  $('cli-state').textContent=s.connection.cliConfigured?' 실행 파일 지정됨':' 실행 파일을 지정해 주세요';
  const codexModels=s.connection.codexModels||[];
  $('codex-state').textContent=s.connection.codexCliConfigured
    ?(codexModels.length?'Codex CLI 경로와 모델 ID 저장됨':'Codex CLI 경로 저장됨, 모델 ID 설정 필요')
    :'Codex CLI 경로와 모델 ID 설정 필요';
  if(document.activeElement!==$('codex-models'))$('codex-models').value=codexModels.join(', ');
  $('codex-candidates').textContent=s.codexCandidates?.length
    ?'발견한 실행 파일 후보: '+s.codexCandidates.join(', ')
    :'PATH와 표준 위치에서 실행 파일을 찾지 못했어요. 파일 선택 창에서 직접 지정할 수 있어요.';
  const running=Object.values(s.processes).some(p=>p.state==='running');
  const problem=Object.values(s.processes).some(p=>['failed','authentication-required'].includes(p.state));
  $('runtime').textContent=problem?'조치 필요':running?'실행 중':'중지됨';
  const labels={running:'실행 중',stopped:'중지됨',failed:'실행 실패', 'authentication-required':'토큰을 다시 연결하세요',starting:'시작 중',stopping:'작업 종료를 기다리는 중', 'retry-wait':'잠시 뒤 재시도'};
  const names={viewer:'원문 뷰어',jobs:'대화 정리',chat:'AI 대화'};
  $('process-detail').textContent=Object.entries(s.processes).map(([name,p])=>(names[name]||name)+': '+(labels[p.state]||p.state)).join(' · ');
  for(const b of document.querySelectorAll('button'))b.disabled=s.busy;
  for(const id of ['allow-cli','auto-start','codex-models'])$(id).disabled=s.busy;
  if(!s.ready){$('start').disabled=true;$('sync').disabled=true;say('연결 장치 실행 파일이 없습니다. 공식 설치 패키지로 다시 설치해 주세요.');}
  const pc=s.pc||{};
  $('login').hidden=pc.session!=='none';
  $('pc-state').textContent=pc.revoked?'이 PC 연결이 해제됐어요 — 대화에서 다시 연결해 주세요.'
    :pc.session==='none'?'로그인이 필요해요. 로그인해야 대화에서 보낸 연결을 받고, 토큰도 자동으로 교체돼요.'
    :pc.registered?'대화에서 연결을 요청하면 이 PC가 받아요.':'';
  // Sync stays available without a device: the first sync connects this PC automatically.
  if(!s.connection.connected){$('start').disabled=true;$('disconnect').disabled=true;}
}
async function act(fn,success){try{const r=await fn();if(!r.ok){say(r.error);return;}if(r.value?.code!==undefined&&r.value.code!==0){say(r.value.detail?'작업이 완료되지 않았어요: '+r.value.detail:'작업이 완료되지 않았어요 (코드 '+r.value.code+'). 토큰·네트워크·Claude 로그인 상태를 확인해 주세요.');return;}if(success)say(success);await refresh();return r.value;}catch{say('앱과 통신하지 못했어요. 다시 시도해 주세요.');}}
async function refresh(){const r=await window.mycrm.status();if(r.ok)state(r.value);}
$('dashboard').onclick=()=>act(()=>window.mycrm.dashboard());
$('login').onclick=()=>act(()=>window.mycrm.login(),'브라우저에서 로그인을 마치면 앱으로 돌아와요.');
$('connect-form').onsubmit=event=>{event.preventDefault();const token=$('token').value;$('token').value='';act(()=>window.mycrm.connect(token),'이 PC를 연결했어요. 연결 장치가 꺼져 있으면 시작을 눌러 주세요.');};
$('allow-cli').onchange=()=>act(()=>window.mycrm.allowCli($('allow-cli').checked),'실행 설정을 저장했어요. 시작을 누르면 적용됩니다.');
$('auto-start').onchange=()=>act(()=>window.mycrm.autoStart($('auto-start').checked),'로그인 시 앱 실행 설정을 저장했어요.');
$('choose-cli').onclick=()=>act(()=>window.mycrm.chooseCli(),'Claude 실행 파일 설정을 확인했어요.');
$('configure-codex').onclick=()=>act(()=>window.mycrm.configureCodex({models:$('codex-models').value}),'Codex CLI 설정을 저장했어요.');
$('start').onclick=()=>act(()=>window.mycrm.start(),'연결 장치를 시작했어요.');
$('stop').onclick=()=>act(()=>window.mycrm.stop(),'연결 장치를 중지했어요.');
$('sync').onclick=()=>act(()=>window.mycrm.sync(),'동기화를 마쳤어요.');
$('disconnect').onclick=()=>act(()=>window.mycrm.disconnect(),'연결을 해제했어요. 기존 데이터는 보존됩니다.');
$('logs').onclick=()=>act(()=>window.mycrm.logs());
let updateCheckId=0,updateInFlight=false,lastAvailableVersion=null;
async function checkForUpdate(){
  if(updateInFlight)return;
  updateInFlight=true;
  const id=++updateCheckId;
  if(!lastAvailableVersion){$('update-state').textContent='업데이트를 확인하고 있어요.';$('download').hidden=true;latestDownload=null;}
  try {
    const response=await window.mycrm.update();
    if(id!==updateCheckId)return;
    if(!response.ok||!response.value)throw new Error('update-unavailable');
    const result=response.value;
    if(result.state==='available'){
      lastAvailableVersion=result.version;
      $('update-badge').textContent='새 버전 '+result.version;$('update-badge').hidden=false;
      latestDownload=result.url;$('download').hidden=false;
      $('update-state').textContent='새 버전 '+result.version+'을 받을 수 있어요. 앱을 종료한 뒤 설치하세요.';
    }else if(result.state==='not-published'){
      $('update-badge').hidden=true;
      lastAvailableVersion=null;latestDownload=null;$('download').hidden=true;
      $('update-state').textContent='아직 게시된 안정 버전이 없습니다.';
    }else if(result.state==='current'){
      $('update-badge').hidden=true;
      lastAvailableVersion=null;latestDownload=null;$('download').hidden=true;
      $('update-state').textContent='게시된 최신 안정 버전: '+result.version;
    }else throw new Error('update-invalid');
  }catch{
    if(id===updateCheckId)$('update-state').textContent=lastAvailableVersion
      ?'새 버전 '+lastAvailableVersion+'을 받을 수 있어요. 최신 상태를 다시 확인하지 못했어요.'
      :'업데이트를 확인하지 못했어요. 네트워크를 확인하고 다시 시도해 주세요.';
  }finally{
    updateInFlight=false;
  }
}
$('update').onclick=checkForUpdate;
$('download').onclick=()=>act(()=>window.mycrm.download(latestDownload));
window.mycrm.onStatus(state);refresh();checkForUpdate();
// The app may remain open for days. Retry periodically without interrupting work.
const updateTimer=setInterval(checkForUpdate,6*60*60*1000);
window.addEventListener('pagehide',()=>clearInterval(updateTimer),{once:true});
