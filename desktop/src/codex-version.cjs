'use strict';
const unavailable=()=>({status:'unavailable',installed_version:null,supported_versions:[],recommended_action:'check_installation'});
const ver=/^(?:0|[1-9]\d{0,5})\.(?:0|[1-9]\d{0,5})\.(?:0|[1-9]\d{0,5})(?:-[0-9A-Za-z.-]{1,40})?$/;
const actions={supported:'none',too_old:'update_codex',unverified_newer:'update_mycrm',unverified_version:'update_mycrm',unavailable:'check_installation',policy_unavailable:'retry',policy_unverified:'update_mycrm',policy_expired:'update_mycrm',setup_required:'start_login'};
function validate(value){
 if(!value||typeof value!=='object'||Array.isArray(value)||!Object.hasOwn(actions,value.status)||actions[value.status]!==value.recommended_action)return unavailable();
 if(value.installed_version!==null&&(typeof value.installed_version!=='string'||!ver.test(value.installed_version)))return unavailable();
 if(!Array.isArray(value.supported_versions)||value.supported_versions.length>50||value.supported_versions.some(v=>typeof v!=='string'||!ver.test(v)))return unavailable();
 if(value.status==='unavailable'&&value.installed_version!==null)return unavailable();
 if(!['unavailable','policy_unavailable','policy_unverified','policy_expired','setup_required'].includes(value.status)&&value.installed_version===null)return unavailable();
 if(value.status==='supported'&&!value.supported_versions.includes(value.installed_version))return unavailable();
 return {status:value.status,installed_version:value.installed_version,supported_versions:value.supported_versions,recommended_action:value.recommended_action};
}
function checkCodexVersion({spawn,binary,home,timeoutMs=15000}){
 return new Promise(resolve=>{
  let child,done=false,output='';let timer;
  const finish=value=>{if(done)return;done=true;clearTimeout(timer);resolve(value);};
  try{child=spawn(binary,['--home',home,'codex-version-status'],{shell:false,windowsHide:true,stdio:['ignore','pipe','ignore']});}catch{return finish(unavailable());}
  timer=setTimeout(()=>{child.kill('SIGTERM');finish(unavailable());},timeoutMs);
  child.stdout.on('data',chunk=>{output+=chunk.toString('utf8');if(Buffer.byteLength(output)>4096){child.kill('SIGTERM');finish(unavailable());}});
  child.once('error',()=>finish(unavailable()));
  child.once('close',code=>{if(code!==0)return finish(unavailable());try{finish(validate(JSON.parse(output)));}catch{finish(unavailable());}});
 });
}
module.exports={checkCodexVersion,validate};
