'use strict';
const $=id=>document.getElementById(id);let latestDownload=null;
function say(text){$('message').textContent=text;}
function state(s){
  $('version').textContent='v'+s.version;$('connection').textContent=s.connection.connected?'연결됨':'연결 안 됨';
  $('expiry').textContent=s.connection.expires?'토큰 만료 '+s.connection.expires:'';
  $('allow-cli').checked=s.allowCli;$('auto-start').checked=s.autoStart;
  $('cli-state').textContent=s.connection.cliConfigured?' 실행 파일 지정됨':' 실행 파일을 지정해 주세요';
  const running=Object.values(s.processes).some(p=>p.state==='running');
  const problem=Object.values(s.processes).some(p=>['failed','authentication-required'].includes(p.state));
  $('runtime').textContent=problem?'조치 필요':running?'실행 중':'중지됨';
  const labels={running:'실행 중',stopped:'중지됨',failed:'실행 실패', 'authentication-required':'토큰을 다시 연결하세요',starting:'시작 중',stopping:'작업 종료를 기다리는 중', 'retry-wait':'잠시 뒤 재시도'};
  $('process-detail').textContent=Object.entries(s.processes).map(([name,p])=>(name==='jobs'?'대화 정리':'원문 뷰어')+': '+(labels[p.state]||p.state)).join(' · ');
  for(const b of document.querySelectorAll('button'))b.disabled=s.busy;
  for(const id of ['allow-cli','auto-start'])$(id).disabled=s.busy;
  if(!s.ready){$('start').disabled=true;$('sync').disabled=true;say('연결 장치 실행 파일이 없습니다. 공식 설치 패키지로 다시 설치해 주세요.');}
  if(!s.connection.connected){$('start').disabled=true;$('sync').disabled=true;$('disconnect').disabled=true;}
}
async function act(fn,success){try{const r=await fn();if(!r.ok){say(r.error);return;}if(r.value?.code!==undefined&&r.value.code!==0){say('작업이 완료되지 않았어요 (코드 '+r.value.code+'). 토큰·네트워크·Claude 로그인 상태를 확인해 주세요.');return;}if(success)say(success);await refresh();return r.value;}catch{say('앱과 통신하지 못했어요. 다시 시도해 주세요.');}}
async function refresh(){const r=await window.mycrm.status();if(r.ok)state(r.value);}
$('dashboard').onclick=()=>act(()=>window.mycrm.dashboard());
$('connect-form').onsubmit=event=>{event.preventDefault();const token=$('token').value;$('token').value='';act(()=>window.mycrm.connect(token),'이 PC를 연결했어요. 시작을 눌러 실행하세요.');};
$('allow-cli').onchange=()=>act(()=>window.mycrm.allowCli($('allow-cli').checked),'실행 설정을 저장했어요. 시작을 누르면 적용됩니다.');
$('auto-start').onchange=()=>act(()=>window.mycrm.autoStart($('auto-start').checked),'로그인 시 앱 실행 설정을 저장했어요.');
$('choose-cli').onclick=()=>act(()=>window.mycrm.chooseCli(),'Claude 실행 파일 설정을 확인했어요.');
$('start').onclick=()=>act(()=>window.mycrm.start(),'연결 장치를 시작했어요.');
$('stop').onclick=()=>act(()=>window.mycrm.stop(),'연결 장치를 중지했어요.');
$('sync').onclick=()=>act(()=>window.mycrm.sync(),'동기화를 마쳤어요.');
$('disconnect').onclick=()=>act(()=>window.mycrm.disconnect(),'연결을 해제했어요. 기존 데이터는 보존됩니다.');
$('logs').onclick=()=>act(()=>window.mycrm.logs());
$('update').onclick=async()=>{const result=await act(()=>window.mycrm.update());if(!result)return;latestDownload=result.url;$('download').hidden=false;$('update-state').textContent=result.state==='available'?'새 버전 '+result.version+'을 받을 수 있어요. 연결 장치를 중지하고 앱을 종료한 뒤 설치하세요.':result.state==='not-published'?'아직 게시된 안정 버전이 없습니다.':'최신 안정 버전을 사용하고 있어요.';};
$('download').onclick=()=>act(()=>window.mycrm.download(latestDownload));
window.mycrm.onStatus(state);refresh();
